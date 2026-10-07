"""Offline checks of the exact-secret registry, ``logging.redactPatterns`` and the redaction policies.

The expected values were produced by the real TypeScript (``tests/integration/
test_redact_policies_oracle.py`` compares the two on about 175 scenarios and 2,500 generated ones);
these tests pin the rules without Node.
"""

from __future__ import annotations

import pytest

from memory_core import redact, secret_registry
from memory_core.redact_user_patterns import compile_redact_pattern, parse_redact_pattern_source

LONG = "a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuVwXyZ"


@pytest.fixture(autouse=True)
def _clean_state():
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)
    yield
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)


def test_registry_registers_encoded_and_json_forms_raw_last():
    secret_registry.register_secret_value_for_redaction("a b\"c\\d é 😀 secret")
    snapshot = secret_registry.capture_secret_redaction_registry_snapshot()
    assert snapshot.values == (
        "a%20b%22c%5Cd%20%C3%A9%20%F0%9F%98%80%20secret",
        'a b\\"c\\\\d é 😀 secret',
        'a b"c\\d é 😀 secret',
    )
    assert secret_registry.get_secret_redaction_registry_revision() == 4  # reset + 3 forms


def test_registry_ignores_short_values_and_counts_utf16_units():
    secret_registry.register_secret_value_for_redaction("abcde")
    secret_registry.register_secret_value_for_redaction("😀😀")  # 4 units
    assert not secret_registry.has_registered_secret_values_for_redaction()
    secret_registry.register_secret_value_for_redaction("😀😀😀")  # 6 units
    assert secret_registry.is_secret_value_registered_for_redaction("😀😀😀")


def test_registry_masks_exact_values_before_the_patterns():
    secret_registry.register_secret_value_for_redaction("my secret value!")
    secret_registry.register_secret_value_for_redaction("a b\"c\\d é 😀 secret")
    text = 'x my secret value! y a b"c\\d é 😀 secret z'
    assert redact.redact_sensitive_text(text) == 'x *** y a b"c\\…cret z'
    assert redact.redact_sensitive_text(text, mode="off") == 'x *** y a b"c\\…cret z'
    assert secret_registry.redact_registered_secret_values(
        text, lambda value, index: f"<{len(redact.to_units(value))}@{index}>"
    ) == "x <16@2> y <19@21> z"


def test_registry_longest_value_wins_at_a_position_and_leftmost_start():
    secret_registry.register_secret_value_for_redaction("secret")
    secret_registry.register_secret_value_for_redaction("secret-longer")
    redactor = secret_registry.create_secret_value_redactor(["secret", "secret-longer"])
    assert redactor("secret-longer secret", lambda value, index: f"[{value}]") == "[secret-longer] [secret]"


def test_registry_is_bounded_oldest_first_and_reregistering_does_not_invalidate():
    for index in range(520):
        secret_registry.register_secret_value_for_redaction(f"secret-{index:04d}")
    values = secret_registry.capture_secret_redaction_registry_snapshot().values
    assert len(values) == 512 and values[0] == "secret-0008" and values[-1] == "secret-0519"
    revision = secret_registry.get_secret_redaction_registry_revision()
    secret_registry.register_secret_value_for_redaction("secret-0008")
    assert secret_registry.get_secret_redaction_registry_revision() == revision
    assert secret_registry.capture_secret_redaction_registry_snapshot().values[-1] == "secret-0008"


def test_registry_rejects_a_lone_surrogate_like_encode_uri_component():
    with pytest.raises(ValueError):
        secret_registry.register_secret_value_for_redaction("a\ud800bcdefgh")
    assert not secret_registry.has_registered_secret_values_for_redaction()


def test_snapshot_redactor_ignores_later_registrations():
    secret_registry.register_secret_value_for_redaction("first-registered-secret")
    snapshot = redact.capture_sensitive_text_redaction_snapshot()
    secret_registry.register_secret_value_for_redaction("later-registered-secret")
    redactor = redact.create_sensitive_text_redactor(snapshot)
    text = "first-registered-secret later-registered-secret"
    assert redactor(text) == "first-…cret later-registered-secret"
    assert redact.redact_sensitive_text(text) == "first-…cret later-…cret"


def test_user_patterns_replace_the_defaults_in_redact_sensitive_text():
    text = "CUST-12345678 FOObar token=abcdefghijklmnopqrstuvwxyz"
    patterns = ["CUST-\\d+", "/foo(bar)/i"]
    assert redact.redact_sensitive_text(text, patterns=patterns) == (
        "*** FOO*** token=abcdefghijklmnopqrstuvwxyz"
    )
    # An empty list means the defaults; the structural protections run either way.
    assert redact.redact_sensitive_text(text, patterns=[]) == redact.redact_sensitive_text(text)
    assert redact.redact_sensitive_text("?access_token=" + LONG, patterns=["zzz"]) == "?access_token=a1B2c3…wXyZ"


def test_user_patterns_merge_with_the_defaults_in_the_tool_payload_policy():
    config = redact.LoggingConfig(("CUST-\\d+", "/foo(bar)/i"))
    text = "CUST-12345678 FOObar token=abcdefghijklmnopqrstuvwxyz"
    assert redact.redact_tool_payload_text(text, logging_config=config) == (
        "*** FOO*** token=abcdef…wxyz"
    )
    redact.configure_logging_redaction(config)
    assert redact.redact_tool_payload_text(text) == "*** FOO*** token=abcdef…wxyz"
    assert redact.redact_sensitive_text(text, config="host") == "*** FOO*** token=abcdefghijklmnopqrstuvwxyz"
    assert redact.redact_sensitive_text(text) != redact.redact_sensitive_text(text, config="host")


def test_pattern_parsing_and_classification():
    assert parse_redact_pattern_source("abc") == ("abc", "gi")
    assert parse_redact_pattern_source("/abc/m") == ("abc", "mg")
    assert parse_redact_pattern_source("/abc/gi") == ("abc", "gi")
    assert parse_redact_pattern_source("  /abc/") == ("  /abc/", "gi")
    assert compile_redact_pattern("   ") is None
    assert compile_redact_pattern("(a+)+b").reason == "unsafe-nested-repetition"
    assert compile_redact_pattern("([").reason == "invalid-regex"
    assert compile_redact_pattern("/a/gg").reason == "invalid-regex"
    assert compile_redact_pattern("/\\p{L}/u").reason == "unsupported-syntax"
    assert compile_redact_pattern("  CUST-\\d+ ").reason is None


def test_blank_unsafe_and_invalid_entries_are_skipped_the_rest_apply():
    patterns = ["", "  ", "(a+)+b", "([", "CUST-\\d+"]
    assert redact.redact_sensitive_text("CUST-1 aaab", patterns=patterns) == "*** aaab"


def test_empty_matches_advance_one_position_like_javascript():
    assert redact.redact_sensitive_text("ab", patterns=["x*"]) == "***a***b***"


def test_programmatic_matcher_with_replacement_and_astral_offsets():
    def exec_(text):
        import re

        for found in re.finditer(r"CUST-([0-9]+)", text):
            yield redact.RedactMatch(
                found.group(0), (found.group(1),), found.start(), "<c>" if len(found.group(1)) > 3 else None
            )

    matcher = redact.RedactMatcher("cust", exec_)
    out = redact.redact_sensitive_text("😀 CUST-1234 CUST-12", patterns=[matcher])
    assert out == "😀 CUST-<c> CUST-***"


def test_full_context_runs_patterns_over_the_whole_text():
    # The secret straddles the 16,384-unit chunk boundary: chunked matching misses it.
    big = " " * 16_380 + "sk-" + "a" * 30 + " " + " " * 40_000
    plain = redact.redact_tool_payload_text(big)
    full = redact.redact_tool_payload_text(big, logging_config=redact.mark_full_context_tool_payload_redaction())
    assert "…" not in plain and "…" in full


def test_model_visible_policy_keeps_assignments_but_masks_registered_values():
    secret_registry.register_secret_value_for_redaction(LONG)
    value = {"note": f"see {LONG}", "token": "x"}
    assert redact.redact_model_visible_secrets(value) == {"note": "see a1B2c3…wXyZ", "token": "***"}
    assert redact.redact_model_visible_secrets(f"plain {LONG}") == "plain a1B2c3…wXyZ"


def test_transcript_pagination_tokens_skip_the_field_name_mask():
    token = "abcdefghijklmnopqrstuvwxyz0123"
    assert redact.redact_transcript_structured_field_value("next_page_token", token) == token
    assert redact.redact_transcript_structured_field_value("token", token) != token


def test_defaults_are_unchanged_without_registry_or_config():
    text = f"Authorization: Bearer {LONG} token={LONG}"
    assert redact.redact_sensitive_text(text) == redact.redact_tool_payload_text(text)
    assert redact.redact_model_visible_secrets({"a": "plain"}) == {"a": "plain"}
