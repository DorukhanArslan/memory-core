"""Actual SQLite preparation rejects a secret-registry revision that became stale."""
from contextlib import contextmanager
from dataclasses import asdict
import json
import sys

import pytest

from memory_core import secret_registry
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_corpus import MemoryCoreSessionCorpus, SessionCorpusFile
from memory_core.session_entry import build_session_entry
from memory_core.tools.common import MemoryToolError


SECRET = "worker-fixture-credential"
KEY = "agent:main:dm:worker-fixture"


@pytest.fixture(autouse=True)
def clean_registry():
    secret_registry.reset_secret_redaction_registry()
    yield
    secret_registry.reset_secret_redaction_registry()


def _catalog(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session(KEY, {"sessionId": "worker-fixture", "updatedAt": 1000})
    catalog.append_message(
        "worker-fixture", {"role": "user", "content": f"Remember {SECRET}", "timestamp": 1000},
        session_key=KEY, event_id="user-1", now_ms=1000,
    )
    corpus = MemoryCoreSessionCorpus(tmp_path, catalog=catalog)
    return catalog, corpus, corpus.discover_files()[0]


@contextmanager
def _after_actual_preparation(callback):
    """Observe the genuine return, without replacing its code or returned entry.

    The coupled native fixture registers at its real worker reply before the
    unchanged parent handler accepts it. This is the same causal cut in the
    synchronous SDK: the builder returned, its corpus owner has not accepted it.
    """
    previous = sys.getprofile()
    prepared = []

    def profile(frame, event, value):
        if event == "return" and frame.f_code is build_session_entry.__code__:
            prepared.append(asdict(value))
            callback(len(prepared))

    try:
        sys.setprofile(profile)
        yield prepared
    finally:
        sys.setprofile(previous)


def test_one_real_registry_change_retries_and_returns_only_current_redaction(tmp_path):
    catalog, corpus, file = _catalog(tmp_path)
    before = catalog.read_transcript("worker-fixture")

    def register_once(ordinal):
        if ordinal == 1:
            secret_registry.register_secret_value_for_redaction(SECRET)

    with _after_actual_preparation(register_once) as prepared:
        actual = corpus.read_index_entry(file)

    assert len(prepared) == 2
    assert prepared[0]["content"] == f"User: Remember {SECRET}"
    assert prepared[1]["content"] == actual.content == "User: Remember worker…tial"
    assert catalog.read_transcript("worker-fixture") == before
    assert actual.hash != prepared[0]["hash"]


def test_two_real_registry_changes_hit_original_bounded_retry_diagnostic(tmp_path):
    catalog, corpus, file = _catalog(tmp_path)
    before = catalog.read_transcript("worker-fixture")

    def register_each(ordinal):
        secret_registry.register_secret_value_for_redaction(SECRET if ordinal == 1 else "another-worker-credential")

    with _after_actual_preparation(register_each) as prepared:
        with pytest.raises(MemoryToolError, match="^Session transcript redaction changed during preparation; retry the operation\\.$"):
            corpus.read_index_entry(file)

    assert len(prepared) == 2
    assert catalog.read_transcript("worker-fixture") == before


def test_duplicate_membership_does_not_invalidate_an_admitted_snapshot(tmp_path):
    _catalogue, corpus, file = _catalog(tmp_path)
    secret_registry.register_secret_value_for_redaction(SECRET)
    before = secret_registry.get_secret_redaction_registry_revision()
    with _after_actual_preparation(lambda _ordinal: secret_registry.register_secret_value_for_redaction(SECRET)) as prepared:
        actual = corpus.read_index_entry(file)
    assert len(prepared) == 1 and actual.content == "User: Remember worker…tial"
    assert secret_registry.get_secret_redaction_registry_revision() == before


def test_retry_rereads_actual_committed_source_instead_of_reusing_first_snapshot(tmp_path):
    catalog, corpus, file = _catalog(tmp_path)

    def changed_after_first(ordinal):
        if ordinal == 1:
            secret_registry.register_secret_value_for_redaction(SECRET)
            catalog.append_message(
                "worker-fixture", {"role": "assistant", "content": "New committed response", "timestamp": 1001},
                session_key=KEY, event_id="assistant-1", now_ms=1001,
            )

    with _after_actual_preparation(changed_after_first) as prepared:
        actual = corpus.read_index_entry(file)
    assert len(prepared) == 2
    assert actual.content == "User: Remember worker…tial\nAssistant: New committed response"
    assert actual.line_map == [2, 3]


@pytest.mark.parametrize("callback_kind", ["transcript-observer", "host-redactor"])
def test_sqlite_callbacks_keep_live_policy_and_run_once_per_original_message(tmp_path, callback_kind):
    catalog, _corpus, file = _catalog(tmp_path)
    catalog.append_message("worker-fixture", {"role": "assistant", "content": f"Again {SECRET}", "timestamp": 1001},
                           session_key=KEY, event_id="assistant-1", now_ms=1001)
    calls = []

    def observer(message, observed_at):
        calls.append((message, observed_at))
        if len(calls) == 2:
            secret_registry.register_secret_value_for_redaction(SECRET)

    def redact(text):
        calls.append(text)
        if len(calls) == 1:
            secret_registry.register_secret_value_for_redaction(SECRET)
        return text

    corpus = MemoryCoreSessionCorpus(tmp_path, catalog=catalog,
                                    redact_text=redact if callback_kind == "host-redactor" else None)
    with _after_actual_preparation(lambda _ordinal: None) as prepared:
        actual = corpus.read_index_entry(file, on_transcript_message=observer if callback_kind == "transcript-observer" else None)
    assert len(calls) == 2 and len(prepared) == 1
    assert actual.content == f"User: Remember {SECRET}\nAssistant: Again worker…tial"


def test_plain_file_preparation_keeps_native_in_process_acceptance(tmp_path):
    filename = tmp_path / "recorded.jsonl"
    filename.write_text(json.dumps({"type": "message", "message": {"role": "user", "content": SECRET}}))
    file = SessionCorpusFile("sessions/main/recorded.jsonl", filename)
    corpus = MemoryCoreSessionCorpus(tmp_path)
    with _after_actual_preparation(lambda _ordinal: secret_registry.register_secret_value_for_redaction(SECRET)) as prepared:
        actual = corpus.read_index_entry(file)
    assert len(prepared) == 1 and actual.content == f"User: {SECRET}"
