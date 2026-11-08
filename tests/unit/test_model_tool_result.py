"""Live model-result owners preserve policy provenance without raw-input caches."""
from __future__ import annotations

import json

import pytest

import memory_core.model_tool_result as owner
from memory_core import redact, secret_registry


@pytest.fixture(autouse=True)
def clean_policy():
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)
    yield
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)


def test_full_result_strips_image_data_before_deep_redaction_and_retains_all_other_fields(monkeypatch):
    source = {
        "content": [{"type": "text", "text": "Authorization: Bearer fixture-secret-value", "custom": 7},
                    {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png", "custom": "keep"}],
        "details": {"token": "fixture-secret", "nested": {"apiKey": 7}},
        "extra": {"preserve": [False, None]},
    }
    seen = []
    original = owner.redact_model_visible_secrets

    def capture(value, **options):
        seen.append(value)
        assert "data" not in value["content"][1]
        return original(value, **options)

    monkeypatch.setattr(owner, "redact_model_visible_secrets", capture)
    actual = owner.sanitize_tool_result(source)

    assert actual == {
        "content": [{"type": "text", "text": "Authorization: Bearer fixtur…alue", "custom": 7},
                    {"type": "image", "bytes": 5, "mimeType": "image/png", "custom": "keep", "omitted": True}],
        "details": {"token": "***", "nested": {"apiKey": "***"}},
        "extra": {"preserve": [False, None]},
    }
    assert len(seen) == 1
    assert source["content"][1]["data"] == "aGVsbG8="
    assert source["details"]["token"] == "fixture-secret"


@pytest.mark.parametrize("data,expected", [("", 0), (" aG\x00VsbG8= \n", 5), ("😀=", 1), ("====", 1)])
def test_image_size_uses_original_estimator_without_allocating_decoded_data(data, expected):
    actual = owner.sanitize_tool_result({"content": [{"type": "image", "data": data, "bytes": 999}]})
    assert actual == {"content": [{"type": "image", "bytes": expected, "omitted": True}]}


def test_nonstring_image_payload_is_omitted_and_only_numeric_existing_size_is_retained():
    actual = owner.sanitize_tool_result({"content": [
        {"type": "image", "data": {"private": "payload"}, "bytes": 7},
        {"type": "image", "bytes": True},
    ]})
    assert actual == {"content": [
        {"type": "image", "bytes": 7, "omitted": True}, {"type": "image", "omitted": True},
    ]}


def test_text_is_redacted_before_utf16_truncation_with_no_split_surrogate():
    text = "a" * 7999 + "😀" + " token=abcdefghijklmnopqrstuvwxyz"
    actual = owner.sanitize_tool_result({"content": [{"type": "text", "text": text}]})
    assert actual["content"][0]["text"] == "a" * 7999 + "\n…(truncated)…"
    actual["content"][0]["text"].encode("utf-8")


def test_prepared_result_reuse_rechecks_mutated_output_and_updated_registry():
    source = {"content": [{"type": "text", "text": "ordinary"}], "details": {"note": "opaque-credential"}}
    first = owner.sanitize_tool_result(source)
    assert owner.sanitize_tool_result(first) is first
    first["details"]["token"] = "second-secret"
    first["content"].append({"type": "text", "text": "Authorization: Bearer appended-secret-value"})
    changed = owner.sanitize_tool_result(first)
    assert changed is not first
    assert changed["details"]["token"] == "***"
    assert "appended-secret-value" not in json.dumps(changed)
    assert "token" not in source["details"]

    secret_registry.register_secret_value_for_redaction("opaque-credential")
    newest = owner.sanitize_tool_result(changed)
    assert newest is not changed
    assert newest["details"]["note"] == "***"


def test_original_input_is_reprocessed_without_retaining_credentials_in_a_global_cache():
    source = {"details": {"note": "ordinary"}}
    prepared = owner.sanitize_tool_result(source)
    prepared["details"]["note"] = "Authorization: Bearer consumer-secret-value"
    assert owner.sanitize_tool_result(source) == {"details": {"note": "ordinary"}}
    assert not any(item is source for item, _kind, _properties in prepared._sanitized_snapshot)


def test_args_diagnostic_policy_and_result_model_policy_have_distinct_actual_walkers():
    shared = {"token": "fixture-secret"}
    value = {"first": shared, "second": shared, "source": "api_key=fixture-value"}
    args = owner.sanitize_tool_args(value)
    result = owner.sanitize_tool_result(value)
    assert args == {"first": {"token": "***"}, "second": "[Circular]", "source": "api_key=***"}
    assert result == {"first": {"token": "***"}, "second": {"token": "***"}, "source": "api_key=fixture-value"}


def test_actual_session_event_preparation_retains_live_provenance_and_avoids_double_redaction():
    config = redact.LoggingConfig((r"foo|\*",))
    text = {"type": "text", "text": "foo", "custom": "preserved"}
    image = {"type": "image", "data": "aGVsbG8="}
    event = {"type": "message_end", "message": {
        "role": "toolResult", "toolCallId": "call-1", "content": [text, image], "timestamp": 1,
    }}

    assert owner.prepare_session_tool_result(event, logging_config=config) is True
    prepared = event["message"]["content"][0]
    assert prepared == {"type": "text", "text": "***", "custom": "preserved"}
    assert prepared is not text and text["text"] == "foo"
    assert event["message"]["content"][1] is image
    assert owner.is_prepared_model_visible_tool_text(prepared, "***", config)
    assert owner.prepare_session_tool_result(event, logging_config=config) is False
    assert event["message"]["content"][0] is prepared
    assert owner.prepare_model_visible_tool_text_block(json.loads(json.dumps(prepared)), config)["text"] == "*********"


def test_prepared_text_marker_cannot_be_forged_and_invalidates_on_text_or_policy_change():
    config = redact.LoggingConfig((r"foo|\*",))
    forged = {"type": "text", "text": "***", "_admitted_text": "***"}
    assert not owner.is_prepared_model_visible_tool_text(forged, "***", config)
    first = owner.prepare_model_visible_tool_text_block({"type": "text", "text": "foo"}, config)
    copied = owner.copy_prepared_model_visible_tool_text(first, {"type": "text", "text": "***", "copied": True})
    assert owner.is_prepared_model_visible_tool_text(copied, "***", config)
    assert json.loads(json.dumps(copied)) == {"type": "text", "text": "***", "copied": True}

    copied["text"] = "foo"
    assert not owner.is_prepared_model_visible_tool_text(copied, "foo", config)
    assert not owner.is_prepared_model_visible_tool_text(first, "***", redact.LoggingConfig(("other",)))
    assert not owner.is_prepared_model_visible_tool_text(first, "***", redact.mark_full_context_tool_payload_redaction(config))
    secret_registry.register_secret_value_for_redaction("unrelated-registry-update")
    assert not owner.is_prepared_model_visible_tool_text(first, "***", config)


@pytest.mark.parametrize("value", [None, False, 0, 1.5])
def test_primitive_results_and_unrelated_events_keep_their_actual_value(value):
    assert owner.sanitize_tool_result(value) is value
    event = {"type": "message_update", "message": {"role": "toolResult", "content": []}}
    assert owner.prepare_session_tool_result(event) is False
