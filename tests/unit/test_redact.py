"""Offline checks of ``memory_core.redact``; the oracle comparison is
``tests/integration/test_redact_oracle.py``."""

import pytest

from memory_core import redact
from memory_core.session_entry import build_session_entry

LONG = "abcdefghijklmnopqrstuvwxyz0123456789"


def test_masks_keep_six_and_four_for_eighteen_units_or_more():
    assert redact.mask_token("a" * 17) == "***"
    assert redact.mask_token("abcdef" + "x" * 8 + "wxyz") == "abcdef…wxyz"
    assert redact.mask_token("***") == "***"


def test_mask_counts_utf16_units_and_never_splits_a_pair():
    # 9 astral characters are 18 units: masked with the pair-safe 6/4 slices.
    assert redact.mask_token("\U0001f600" * 9) == "\U0001f600" * 3 + "…" + "\U0001f600" * 2
    assert redact.mask_token("\U0001f600" * 8) == "***"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("token=" + LONG, "token=abcdef…6789"),
        ('OPENAI_API_KEY="' + LONG + '"', 'OPENAI_API_KEY="abcdef…6789"'),
        ("password=short", "password=***"),
        ("MY_TOKEN=$MY_TOKEN", "MY_TOKEN=$MY_TOKEN"),
        ("Authorization: Bearer " + LONG, "Authorization: Bearer abcdef…6789"),
        ("sk-abcdefghijklmnop12345", "sk-abc…2345"),
        ("see https://user:" + LONG + "@h.example/x", "see https://user:abcdef…6789@h.example/x"),
        ("plain text without secrets", "plain text without secrets"),
        ("", ""),
    ],
)
def test_known_outputs(text, expected):
    assert redact.redact_sensitive_text(text) == expected


def test_pem_block_keeps_only_the_delimiters():
    pem = "-----BEGIN PRIVATE KEY-----\nAAAA\nBBBB\n-----END PRIVATE KEY-----"
    assert redact.redact_sensitive_text("k\n" + pem) == (
        "k\n-----BEGIN PRIVATE KEY-----\n…redacted…\n-----END PRIVATE KEY-----"
    )


def test_base64_data_url_payloads_are_not_vendor_tokens():
    token = "AKIAIOSFODNN7EXAMPLE"
    assert redact.redact_sensitive_text("data:a/b;base64," + token) == "data:a/b;base64," + token
    assert redact.redact_sensitive_text("x-" + token) == "x-AKIAIO…MPLE"


def test_decode_uri_component_matches_javascript():
    assert redact.js_decode_uri_component("%74oken%2D") == "token-"
    assert redact.js_decode_uri_component("%E2%80%8B") == chr(0x200B)
    for bad in ("%", "%2", "%ZZ", "%E2%80", "%C0%80", "%ED%A0%80", "%F8%80%80%80%80"):
        with pytest.raises(ValueError):
            redact.js_decode_uri_component(bad)


def test_utf16_views_round_trip():
    high, low = chr(0xD83D), chr(0xDE00)
    assert redact.to_units("a\U0001f600") == "a" + high + low
    assert redact.from_units("a" + high + low + high) == "a\U0001f600" + high


def test_session_entry_redacts_by_default_and_extends_with_the_host_hook():
    events = [{"type": "message", "message": {"role": "user", "content": "token=" + LONG + " Friday"}}]
    default = build_session_entry(events)
    assert default.content == "User: token=abcdef…6789 Friday"
    extended = build_session_entry(events, redact_text=lambda text: text.replace("Friday", "[day]"))
    assert extended.content == "User: token=abcdef…6789 [day]"
    raw = build_session_entry(events, apply_default_redaction=False)
    assert raw.content == "User: token=" + LONG + " Friday"
