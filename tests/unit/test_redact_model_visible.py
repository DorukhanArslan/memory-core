"""Offline checks of ``redact_model_visible_secrets`` and the replay-input normalizer.

The values compared with the real TS live in tests/integration/test_redact_oracle.py and
test_openclaw_compaction_checkpoint_oracle.py; these pin the documented behaviour without it.
"""

from __future__ import annotations

from memory_core import compaction_replay as cr
from memory_core import redact

LONG = "a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuVwXyZ"


def test_sensitive_key_masks_the_whole_value():
    assert redact.redact_model_visible_secrets({"password": "pw", "name": "pw"}) == {
        "password": "***",
        "name": "pw",
    }


def test_env_lines_survive_under_a_plain_key_but_not_under_a_secret_key():
    text = f"API_KEY={LONG}\nPATH=/usr/bin"
    assert redact.redact_model_visible_secrets({"stdout": text}) == {"stdout": text}
    assert redact.redact_model_visible_secrets({"token": text})["token"] != text


def test_vendor_tokens_are_masked_anywhere():
    out = redact.redact_model_visible_secrets(["x sk-" + LONG[:30], {"note": "ghp_" + LONG}])
    assert LONG[:30] not in out[0] and "…" in out[0]
    assert "…" in out[1]["note"]


def test_numbers_under_secret_keys_and_code_paths():
    assert redact.redact_model_visible_secrets({"secret": 5, "count": 5}) == {
        "secret": "***",
        "count": 5,
    }
    assert redact.redact_model_visible_secrets({"code": "x", "error": {"code": "y"}}) == {
        "code": "x",
        "error": {"code": "y"},
    }
    assert redact.redact_model_visible_secrets({"a": {"code": "x"}}) == {"a": {"code": "***"}}


def test_the_input_is_not_mutated():
    value = {"password": LONG, "l": [{"token": LONG}]}
    redact.redact_model_visible_secrets(value)
    assert value == {"password": LONG, "l": [{"token": LONG}]}


def test_normalize_from_response_rewrites_arguments_with_unsafe_integers_quoted():
    item = {"type": "function_call", "id": "fc", "arguments": '{ "a": 9007199254740993 }'}
    assert cr.normalize_assistant_replay_input([item])[0] == {
        "type": "function_call",
        "arguments": '{ "a": 9007199254740993 }',
    }
    assert cr.normalize_assistant_replay_input([item], True)[0]["arguments"] == (
        '{"a":"9007199254740993"}'
    )
    bad = {"type": "function_call", "arguments": "nope"}
    assert cr.normalize_assistant_replay_input([bad], True)[0]["arguments"] == "nope"
