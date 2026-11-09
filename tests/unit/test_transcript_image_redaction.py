"""Inline image records use byte signatures before ordinary storage masking."""
from copy import deepcopy

import pytest

from memory_core import redact
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_transcript_append import redact_message_for_storage


@pytest.mark.parametrize("block", [
    {"type": "image", "data": "iVBORw0KGgo=\n", "mimeType": "image/JPEG"},
    {"type": "base64", "data": "iVBORw0KGgo=\n", "mediaType": " image/GIF ", "media_type": "image/jpeg"},
])
def test_valid_inline_record_canonicalizes_mime_and_bytes_without_redacting_image_payload(block):
    before = deepcopy(block)
    message = {"role": "toolResult", "content": [block]}
    actual = redact_message_for_storage(message, redact.LoggingConfig(("iVBOR",)))
    expected = {**block, "data": "iVBORw0KGgo="}
    for key in ("mimeType", "mediaType", "media_type"):
        if key in expected:
            expected[key] = "image/png"
    assert actual["content"] == [expected]
    assert block == before


def test_nested_inline_data_url_is_canonicalized_and_persisted_through_the_catalog(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    key = "agent:main:dm:session-1"
    catalog.upsert_session(key, {"sessionId": "session-1", "updatedAt": 1000})
    message = {"role": "user", "content": [{"type": "image_url", "image_url": {
        "url": "DATA:image/jpeg;base64,iVBORw0KGgo=\n",
    }}]}
    appended = catalog.append_message("session-1", message, session_key=key, now_ms=1000)
    assert appended["message"]["content"][0]["image_url"]["url"] == "data:image/png;base64,iVBORw0KGgo="
    reopened = MemorySessionCatalog(catalog.path).read_transcript("session-1")
    assert reopened.events[-1]["message"] == appended["message"]


def test_canonical_image_keeps_identity_while_malformed_bytes_follow_regular_redaction():
    message = {"role": "toolResult", "content": [{"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"}]}
    assert redact_message_for_storage(message) is message
    malformed = {"role": "toolResult", "content": [{"type": "image", "data": "fixture-secret", "mimeType": "image/png"}]}
    assert redact_message_for_storage(malformed, redact.LoggingConfig(("fixture-secret",)))["content"][0]["data"] == "***"
