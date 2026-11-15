"""Labelled callback frames and source registration; no memory engine runs."""
import sqlite3
import sys

from equivalence.forget_index_fence_sdk import _OriginalObserver, _code_identity, _original_bindings


def test_original_replanner_registration_comes_from_actual_workspace_forget_code():
    from memory_core.consolidation.forget import _forget_workspace_memory

    bindings = _original_bindings()
    actual = [code for code in _forget_workspace_memory.__code__.co_consts
              if getattr(code, "co_name", None) == "current_index_plan"]
    assert len(actual) == 1
    entry = bindings[actual[0]]
    assert entry["replanCallback"] is True
    assert entry["name"] == "_forget_workspace_memory.<locals>.current_index_plan"
    assert entry["code"] == _code_identity(actual[0])


def _labelled_replan(db=None):
    return {"sameDatabase": str(id(db)), "actualReturn": 7}


def _labelled_purge(store, db, replan):
    return replan(db)


def _observer(store):
    codes = {_labelled_purge.__code__: {"name": "purge_memory_index", "receiver": "store",
                "code": _code_identity(_labelled_purge.__code__)},
        _labelled_replan.__code__: {"name": "labelled.current_index_plan", "receiver": None,
                "replanCallback": True, "code": _code_identity(_labelled_replan.__code__)}}
    observer = _OriginalObserver(codes)
    observer.bind_owner(store, "labelled-store")
    return observer


def test_replanner_proof_retains_exact_parent_callback_and_live_transaction():
    store = object()
    observer = _observer(store)
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN")
        previous = sys.getprofile()
        try:
            sys.setprofile(observer.profile)
            with observer.call_scope("selected", "forget"):
                returned = _labelled_purge(store, db, _labelled_replan)
        finally:
            sys.setprofile(previous)
        assert returned == {"sameDatabase": str(id(db)), "actualReturn": 7}
        parent, callback = [row for row in observer.events if row["event"] == "original-call"]
        proof = callback["replanParent"]
        assert proof == {"parentFrameObjectId": parent["frameObjectId"],
            "parentCallSequence": parent["sequence"], "parentCode": parent["code"],
            "replanObjectId": str(id(_labelled_replan)), "replanCodeIsCallback": True,
            "databaseObjectId": str(id(db)), "parentDatabaseObjectId": str(id(db)),
            "parentStoreObjectId": str(id(store)), "inTransaction": True}
        assert observer.failures == []


def test_unqualified_callback_records_observer_failure_without_replacing_actual_return():
    observer = _observer(object())
    with sqlite3.connect(":memory:") as db:
        previous = sys.getprofile()
        try:
            sys.setprofile(observer.profile)
            with observer.call_scope("selected", "forget"):
                returned = _labelled_replan(db)
        finally:
            sys.setprofile(previous)
        assert returned == {"sameDatabase": str(id(db)), "actualReturn": 7}
        assert observer.failures[0]["phase"] == "original-replan-parent"
        assert observer.events[-1]["returned"] == returned
