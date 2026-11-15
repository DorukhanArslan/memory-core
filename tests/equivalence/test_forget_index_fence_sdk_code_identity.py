"""Pure code-identity ownership tests; labelled bodies and SDK engines never run."""
import gc
from types import FunctionType, SimpleNamespace
import weakref

import pytest

from equivalence.forget_index_fence_sdk import _OriginalObserver, _encode
from equivalence.forget_index_fence_sdk_clock import CodeIdentityMap, OwnedSourceWriteClock


def _labelled_method(self, argument=None):
    raise AssertionError("A labelled stand-in body must never execute")


def _equal_code_pair():
    original = _labelled_method.__code__.replace()
    equivalent = original.replace()
    assert equivalent is not original and equivalent == original
    return original, equivalent


def test_equal_but_distinct_code_requires_its_own_explicit_registration():
    original, equivalent = _equal_code_pair()
    first, second, missing = object(), object(), object()
    ownership = CodeIdentityMap([(original, first)])

    assert ownership[original] is first
    assert ownership.get(equivalent, missing) is missing
    assert equivalent not in ownership
    with pytest.raises(KeyError):
        ownership[equivalent]
    assert len(ownership) == 1

    ownership[equivalent] = second
    assert len(ownership) == 2
    assert ownership[original] is first and ownership[equivalent] is second
    assert any(code is original for code in ownership)
    assert any(code is equivalent for code in ownership)


def test_missing_lookup_does_not_hide_later_registration_update_or_deletion():
    original, equivalent = _equal_code_pair()
    ownership = CodeIdentityMap()
    assert ownership.get(original) is None and len(ownership) == 0
    initial, replacement, second = object(), object(), object()
    ownership.update([(original, initial), (equivalent, second)])
    ownership.update([(original, replacement)])
    assert len(ownership) == 2
    assert ownership[original] is replacement and ownership[equivalent] is second

    del ownership[original]
    assert len(ownership) == 1 and ownership.get(original) is None
    assert ownership[equivalent] is second
    with pytest.raises(KeyError):
        del ownership[original]
    ownership[original] = initial
    assert ownership[original] is initial


def test_registered_code_has_a_strong_reference_until_its_entry_is_deleted():
    code = _labelled_method.__code__.replace()
    reference = weakref.ref(code)
    ownership = CodeIdentityMap([(code, {"label": "strong original ownership"})])
    del code
    gc.collect()
    assert reference() is not None
    ownership.clear()
    gc.collect()
    assert reference() is None


def test_forged_numeric_id_slot_does_not_bypass_exact_object_guard():
    original, other = _equal_code_pair()
    ownership = CodeIdentityMap()
    # Deliberately corrupt a labelled unit-only slot: numeric equality alone
    # must never authenticate another code object.
    ownership._entries[id(original)] = (other, {"forged": True})
    missing = object()
    assert ownership.get(original, missing) is missing
    assert original not in ownership
    with pytest.raises(KeyError):
        ownership[original]
    with pytest.raises(KeyError):
        del ownership[original]
    assert len(ownership) == 1


def _specification(name):
    return {"name": name, "receiver": "self", "code": {"labelledUnitSource": name}}


def test_observer_rechecks_live_code_receiver_and_scope_for_each_frame():
    original, equivalent = _equal_code_pair()
    first = FunctionType(original, globals(), "labelled_first")
    second = FunctionType(equivalent, globals(), "labelled_second")
    owner, stranger = object(), object()
    observer = _OriginalObserver([(first.__code__, _specification("first"))])
    observer.bind_owner(owner, "labelled-owner")
    first_frame = SimpleNamespace(f_code=first.__code__, f_locals={"self": owner})
    second_frame = SimpleNamespace(f_code=second.__code__, f_locals={"self": owner})

    observer.profile(first_frame, "call", None)
    assert observer.events == []  # Registered code alone supplies no scope.
    with observer.call_scope("first-call", "sync"):
        observer.profile(second_frame, "call", None)
        assert observer.events == []  # Structural code equality supplies no ownership.
        observer.profile(first_frame, "call", None)
        observer.profile(first_frame, "return", 7)
        first_frame.f_locals["self"] = stranger
        observer.profile(first_frame, "call", None)
        assert len(observer.events) == 2

    observer.codes[second.__code__] = _specification("late-second")
    with observer.call_scope("second-call", "search"):
        observer.profile(second_frame, "call", None)
        observer.profile(second_frame, "return", False)
    observer.profile(second_frame, "call", None)
    assert len(observer.events) == 4
    calls = [row for row in observer.events if row["event"] == "original-call"]
    assert [(row["name"], row["callLabel"], row["callKind"]) for row in calls] == [
        ("first", "first-call", "sync"), ("late-second", "second-call", "search")]
    assert all(row["receiverObjectId"] == str(id(owner)) and row["exactReceiver"] for row in calls)
    assert observer.events[-1]["returned"] is False
    assert observer.local.stack == ()


def test_source_clock_honors_late_registration_and_removal_without_running_source(tmp_path):
    original, equivalent = _equal_code_pair()
    clock = OwnedSourceWriteClock(root=tmp_path, actor="labelled-actor", policy={}, owners=[],
        scope=lambda: {"kind": "labelled-read", "label": "actual-scope"},
        encode=_encode, full_stat=lambda value: value)
    frame = SimpleNamespace(f_code=original, f_locals={"path": "memory/labelled.md"}, f_back=None)
    other_frame = SimpleNamespace(f_code=equivalent, f_locals=frame.f_locals, f_back=None)
    returned = SimpleNamespace(source="memory", path="memory/labelled.md", content="retained raw value")
    clock.profile(frame, "return", returned)
    assert clock.source_reads == []

    source = {"role": "source-read", "code": {"labelledSource": "late registered"}}
    clock.owners[original] = source
    clock.profile(other_frame, "return", returned)
    assert clock.source_reads == []
    clock.profile(frame, "return", returned)
    assert len(clock.source_reads) == 1
    receipt = clock.source_reads[0]
    assert receipt["sourceCode"] == source["code"]
    assert receipt["returned"]["attributes"]["content"] == "retained raw value"

    del clock.owners[original]
    clock.profile(frame, "return", returned)
    assert len(clock.source_reads) == 1
    assert clock.receipts == [] and clock.original_io == [] and clock.failures == []
