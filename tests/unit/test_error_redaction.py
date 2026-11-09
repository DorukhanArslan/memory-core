"""Actual memory-tool diagnostics use the native shared-error redaction policy."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

import pytest

from memory_core import redact, secret_registry
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.supplements import RegisteredMemoryCorpusSupplement, StaticMemoryCorpusSupplement
from memory_core.tools.common import format_error_message
from memory_core.tools.memory_get import execute_memory_get_tool
from memory_core.tools.memory_search import execute_memory_search_tool


@pytest.fixture(autouse=True)
def clean_redaction_state():
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)
    yield
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)


def test_assembled_cause_diagnostic_masks_registered_surface_forms_without_mutating_errors():
    # Synthetic credentials only. Registration owns raw, URI and JSON surfaces.
    credential = 'demo key"\\suffix!'
    surfaces = [credential, quote(credential, safe="~()*!.'-"), json.dumps(credential)[1:-1]]
    secret_registry.register_secret_value_for_redaction(credential)
    inner = RuntimeError("transport " + surfaces[1])
    inner.code = "ECONNRESET"
    outer = RuntimeError("request " + surfaces[0] + " serialized " + surfaces[2])
    outer.__cause__ = inner

    result = format_error_message(outer)

    assert result == "request *** serialized demo k…fix! | transport demo%2…fix! | ECONNRESET"
    assert all(surface not in result for surface in surfaces)
    assert str(outer) == "request " + surfaces[0] + " serialized " + surfaces[2]
    assert str(inner) == "transport " + surfaces[1]
    assert outer.__cause__ is inner


def test_diagnostic_uses_current_host_pattern_config_and_registry_even_when_patterns_change():
    secret_registry.register_secret_value_for_redaction("hidden-credential")
    text = "CUST-1234 hidden-credential token=abcdefghijklmnopqrstuvwxyz"
    redact.configure_logging_redaction(redact.LoggingConfig(("([", "(a+)+b", "CUST-\\d+")))
    assert format_error_message(text) == "*** *** token=abcdefghijklmnopqrstuvwxyz"

    redact.configure_logging_redaction(None)
    assert format_error_message(text) == "CUST-1234 *** token=abcdef…wxyz"
    secret_registry.reset_secret_redaction_registry()
    assert format_error_message(text) == "CUST-1234 hidden-credential token=abcdef…wxyz"


def test_embedded_cause_message_is_not_repeated_but_its_code_remains():
    inner = RuntimeError("transport failed")
    inner.code = "ECONNRESET"
    outer = RuntimeError("request failed: transport failed (ECONNRESET)")
    outer.__cause__ = inner

    assert format_error_message(outer) == "request failed: transport failed (ECONNRESET) | ECONNRESET"


def test_memory_get_redacts_actual_file_read_failure(tmp_path: Path, monkeypatch):
    filename = tmp_path / "MEMORY.md"
    filename.write_text("Readable content.\n", encoding="utf-8")
    credential = "demo-reader-credential"
    secret_registry.register_secret_value_for_redaction(credential)
    failure = PermissionError("reader refused " + credential)
    target = filename.stat()
    read = os.read
    attempts = []

    def denied(descriptor, size):
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == (target.st_dev, target.st_ino):
            attempts.append(descriptor)
            raise failure
        return read(descriptor, size)

    # Exercise the admitted descriptor's real read boundary, including the IO
    # bridge and public error formatter. The reader never reopens the pathname.
    monkeypatch.setattr(os, "read", denied)
    result = execute_memory_get_tool(MemoryConfig(workspace_dir=tmp_path), {"path": "MEMORY.md"})

    assert len(attempts) == 1
    assert result == {
        "path": "MEMORY.md", "text": "", "status": "error", "code": "MEMORY_READ_FAILED",
        "error": "reader refused demo-r…tial",
    }
    assert str(failure) == "reader refused " + credential


@pytest.mark.parametrize("tool", ["get", "search"])
def test_registered_corpus_failure_is_redacted_before_public_tool_serialization(tmp_path: Path, tool: str):
    secret_registry.register_secret_value_for_redaction("demo-supplement-credential")
    redact.configure_logging_redaction(redact.LoggingConfig(("CUST-\\d+",)))
    failure = RuntimeError("provider CUST-1234 demo-supplement-credential")
    calls = []

    def failed(**options):
        calls.append(options)
        raise failure

    supplement = RegisteredMemoryCorpusSupplement(
        "wiki-demo", StaticMemoryCorpusSupplement([]), reader=failed, searcher=failed,
    )
    config = MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False))
    if tool == "get":
        result = execute_memory_get_tool(
            config, {"path": "topic", "corpus": "wiki"}, supplements=[supplement],
        )
    else:
        store = SQLiteMemoryStore(config, None)
        result = execute_memory_search_tool(
            config, store, {"query": "topic", "corpus": "wiki"}, supplements=[supplement],
        )

    assert len(calls) == 1
    serialized = json.dumps(result)
    assert "demo-supplement-credential" not in serialized
    assert "CUST-1234" not in serialized
    assert result["error"] == "provider *** demo-s…tial"
    assert result["corpora"] == [{
        "corpus": "wiki", "outcome": "unavailable", "error": "provider *** demo-s…tial",
    }]
    assert str(failure) == "provider CUST-1234 demo-supplement-credential"
