"""Observer regressions only: no index owner, public engine or host execution."""
from dataclasses import replace
import json
import sqlite3
import threading

from equivalence.query_sync_boundaries_sdk import (
    _observed_arguments, _sdk_tool_context_codes, _SdkToolContexts,
)
from memory_core.tools.memory_search import MemorySearchToolContext


def test_actual_callable_sqlite_connection_is_observed_without_invocation_or_mutation():
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE actual(value TEXT)")
        db.execute("INSERT INTO actual VALUES ('retained')")
        assert callable(db) and not hasattr(db, "__qualname__")
        before = db.total_changes

        observed = _observed_arguments({"0": db, "force": True})

        assert observed["0"] == {"className": "Connection", "module": "sqlite3",
            "objectId": str(id(db)), "sqliteConnection": True, "callable": True}
        assert observed["force"] is True
        json.dumps(observed)
        assert db.total_changes == before
        assert db.execute("SELECT * FROM actual").fetchall() == [("retained",)]
        assert db.in_transaction
    finally:
        db.close()


def test_real_worker_thread_resolves_original_sdk_source_context_and_exact_store():
    # These are the loaded original SDK code objects and a genuine SDK context;
    # only the observer mapping runs. No original engine function is invoked.
    public_code, worker_codes = _sdk_tool_context_codes()
    context, other_context = MemorySearchToolContext(), MemorySearchToolContext()
    store, other_store = object(), object()
    observer = _SdkToolContexts(public_code, worker_codes, {id(store): "owner-1"})
    public = observer.public_entry(public_code, context, store, "duringSync")
    results = []

    def worker():
        worker_code = next(code for code in worker_codes if code.co_name == "search_memory_worker")
        rejected = [observer.worker_entry(worker_code, other_context, store),
                    observer.worker_entry(worker_code, replace(context), store),
                    observer.worker_entry(worker_code, context, other_store),
                    observer.worker_entry(worker.__code__, context, store),
                    observer.worker_entry(worker_code, None, store)]
        results.append((threading.get_ident(), observer.worker_entry(worker_code, context, store), rejected))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    assert len(results) == 1 and results[0][0] != threading.get_ident()
    assert results[0][1] is public
    assert results[0][2] == [None] * 5
    assert public["label"] == "duringSync" and public["ownerId"] == "owner-1"
    assert public["context"] is context and public["store"] is store


def test_source_context_registration_needs_actual_original_public_code_and_owned_store():
    public_code, worker_codes = _sdk_tool_context_codes()
    context, store = MemorySearchToolContext(), object()
    observer = _SdkToolContexts(public_code, worker_codes, {id(store): "owner-1"})
    worker_code = next(iter(worker_codes))

    assert observer.worker_entry(worker_code, context, store) is None
    assert observer.public_entry(test_source_context_registration_needs_actual_original_public_code_and_owned_store.__code__,
                                 context, store, "unrelated") is None
    assert observer.public_entry(public_code, context, object(), "unowned") is None
    assert observer.public_entry(public_code, None, store, "missing-context") is None
    assert observer.public_entry(public_code, context, store, None) is None
    assert observer.worker_entry(worker_code, context, store) is None
