"""Host policy reaches the same full-context text owner as an explicit policy."""
import pytest

from memory_core import redact, secret_registry


@pytest.fixture(autouse=True)
def clean_policy():
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)
    yield
    redact.configure_logging_redaction(None)
    secret_registry.reset_secret_redaction_registry()


@pytest.mark.parametrize("owner", [redact.redact_tool_payload_text, redact.redact_model_visible_tool_payload_text])
def test_default_host_full_context_masks_a_custom_match_crossing_a_regex_chunk(owner):
    # Native bounded regex chunks stop at 16384 units once total length exceeds
    # 32768; the genuine full-context host mark deliberately bypasses them.
    text = " " * 16380 + "CUST-1234567890" + " " * 20000
    config = redact.mark_full_context_tool_payload_redaction(redact.LoggingConfig(("CUST-[0-9]+",)))
    redact.configure_logging_redaction(config)
    assert owner(text) == " " * 16380 + "***" + " " * 20000
    assert owner(text) == owner(text, logging_config=config)
    # An explicit unmarked policy still selects the bounded native path.
    assert owner(text, logging_config=redact.LoggingConfig(("CUST-[0-9]+",))) == text
