"""Configured Unicode regexes retain native UTF-16 hint boundaries."""
import pytest

from memory_core import redact, secret_registry


@pytest.fixture(autouse=True)
def clean_policy():
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)
    yield
    redact.configure_logging_redaction(None)
    secret_registry.reset_secret_redaction_registry()


@pytest.mark.parametrize("pattern,text,expected", [
    ("/(prefix:)(𐐀+)/gu", "prefix:" + "𐐀" * 8, "prefix:***"),
    ("/(prefix:)(𐐀+)/gu", "prefix:" + "𐐀" * 9, "prefix:" + "𐐀" * 3 + "…" + "𐐀" * 2),
    ("/(prefix:)(𐐀+)/gu", "prefix:" + "𐐀" * 22, "prefix:" + "𐐀" * 3 + "…" + "𐐀" * 2),
    ("/(prefix:)(a𐐀+b)/gu", "prefix:a" + "𐐀" * 8 + "b", "prefix:a" + "𐐀" * 2 + "…𐐀b"),
    (r"/(prefix:)(\ud800+)/gu", "prefix:" + "\ud800" * 22, "prefix:" + "\ud800" * 6 + "…" + "\ud800" * 4),
    ("/(prefix:)((?:𐐀)+)/g", "prefix:" + "𐐀" * 22, "prefix:" + "𐐀" * 3 + "…" + "𐐀" * 2),
])
@pytest.mark.parametrize("owner", [redact.redact_tool_payload_text, redact.redact_model_visible_tool_payload_text])
def test_public_configured_redaction_uses_unit_lengths_and_surrogate_safe_hints(pattern, text, expected, owner):
    # Expectations are actual pinned Node24.16 redactor outputs. The non-u and
    # lone-surrogate cases exercise the already-unit input path as well.
    assert owner(text, logging_config=redact.LoggingConfig((pattern,))) == expected
