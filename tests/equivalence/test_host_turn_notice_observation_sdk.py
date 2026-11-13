"""Forwarding/closure-only tests; no real SDK or Native host is executed."""
import itertools
from concurrent.futures import ThreadPoolExecutor
import linecache
from types import SimpleNamespace

import pytest

from equivalence.host_turn_barrier_sdk import _NoticeObservations


class Owner:
    def __init__(self):
        self._automatic_rebuild_notice = {"sequence": 0, "warning": ""}
        self._local = SimpleNamespace(automatic_repair_notice=None)


def _observer(owner):
    counter = itertools.count(1)
    return _NoticeObservations(owner,
        lambda: {"sequence": next(counter), "atNs": "1"},
        lambda: {"turnLabel": "actual", "toolCallId": "actual:search"})


def _capture(status):
    notice = status["custom"]["automaticRebuildNotice"]
    sequence = notice["sequence"]

    def read():
        return notice["warning"] if notice["sequence"] != sequence else None

    return read


def test_observed_capture_retains_exact_closure_cells_without_eager_read():
    owner = Owner()
    observer = _observer(owner)
    actual_captures = []
    status = {"custom": {"automaticRebuildNotice": owner._automatic_rebuild_notice}}

    def original(status):
        actual_captures.append(status)
        return _capture(status)

    reader = observer._capture_wrapper(original)(status)

    assert actual_captures == [status]
    assert not [call for call in observer.data["calls"] if call["method"] == "notice-reader"]
    captured = observer.data["captures"][0]
    assert captured["capturedSequence"] == 0 and captured["noticeIsOwnerObject"] is True
    assert captured["originalReaderRef"] != captured["observedReaderRef"]
    assert captured["closureCellRefs"]["notice"] == captured["noticeRef"]
    sequence_ref = next(row for row in observer.data["references"]
                        if row["ref"] == captured["closureCellRefs"]["sequence"])
    assert type(sequence_ref["primitiveValue"]) is int and sequence_ref["primitiveValue"] == 0
    assert reader() is None
    warning = "original warning " + str(id(owner))
    owner._automatic_rebuild_notice.update(sequence=1, warning=warning)
    assert reader() is warning
    calls = [call for call in observer.data["calls"] if call["method"] == "notice-reader"]
    assert [call["originalInvocations"] for call in calls] == [1, 1]
    assert [call["returnPrimitive"] for call in calls] == [None, warning]


def test_reader_calls_original_once_and_preserves_exact_error_identity():
    owner = Owner()
    observer = _observer(owner)
    failure = RuntimeError("original failure")

    class Notice(dict):
        def __getitem__(self, key):
            if key == "warning":
                raise failure
            return super().__getitem__(key)

    notice = Notice(sequence=0, warning="never returned")
    reader = observer._capture_wrapper(_capture)({"custom": {"automaticRebuildNotice": notice}})
    notice["sequence"] = 1
    with pytest.raises(RuntimeError) as raised:
        reader()
    assert raised.value is failure
    call = observer.data["calls"][-1]
    assert call["method"] == "notice-reader" and call["originalInvocations"] == 1
    assert observer._objects[id(failure)][1]["ref"] == call["errorRef"]


def test_store_forwarder_preserves_original_receiver_args_return_and_exception():
    owner = Owner()
    observer = _observer(owner)
    expected, argument, option = object(), object(), object()
    invocations = []
    failure = RuntimeError("original method failure")

    def method(self, *args, **kwargs):
        invocations.append((self, args, kwargs))
        if kwargs.get("fail"):
            raise failure
        return expected

    original = method.__get__(owner, Owner)
    observed = observer._method_wrapper("custom", original)
    assert observed(argument, option=option) is expected
    with pytest.raises(RuntimeError) as raised:
        observed(argument, option=option, fail=True)
    assert raised.value is failure
    assert invocations == [(owner, (argument,), {"option": option}),
                           (owner, (argument,), {"option": option, "fail": True})]
    assert all(call["originalInvocations"] == 1 and call["originalReceiverIsExactOwner"]
               for call in observer.data["calls"])


def test_original_status_retains_live_nested_identity_instead_of_returning_copy():
    owner = Owner()
    observer = _observer(owner)
    status = {"custom": {"automaticRebuildNotice": owner._automatic_rebuild_notice}}
    def original():
        return status

    result = observer._method_wrapper("status", original)()

    assert result is status
    proof = observer.data["calls"][0]["statusReturn"]
    assert proof["noticeIsOwnerObject"] is True
    assert proof["noticeRef"] == observer.notice()["noticeRef"]
    owner._automatic_rebuild_notice["sequence"] = 4
    assert proof["noticeScalar"]["sequence"] == 0
    assert result["custom"]["automaticRebuildNotice"]["sequence"] == 4


def test_restore_exact_preexisting_and_inherited_descriptors():
    class InheritedOwner(Owner):
        def inherited(self):
            return "original"

    owner = InheritedOwner()
    def own_descriptor():
        return "own"
    owner.own = own_descriptor
    observer = _observer(owner)
    module = SimpleNamespace(_capture_rebuild_notice=_capture)
    for target, name in ((owner, "inherited"), (owner, "own"), (module, "_capture_rebuild_notice")):
        original = getattr(target, name)
        observer._replace(target, name, lambda: "observer", original)

    observer.restore()

    assert "inherited" not in vars(owner)
    assert owner.inherited() == "original"
    assert owner.own is own_descriptor
    assert module._capture_rebuild_notice is _capture
    assert all(row["restoredExactOwnDescriptor"] for row in observer.data["restoration"])


def test_reference_bookkeeping_preserves_concurrent_shared_and_distinct_identities_without_locks():
    observer = _observer(Owner())
    shared, distinct = object(), [object() for _ in range(64)]

    def record(value):
        return observer.reference(shared, "shared"), observer.reference(value, "distinct")

    with ThreadPoolExecutor(max_workers=8) as workers:
        returned = list(workers.map(record, distinct))

    assert len({shared_ref for shared_ref, _ in returned}) == 1
    assert len({distinct_ref for _, distinct_ref in returned}) == len(distinct)
    assert len({row["ref"] for row in observer.data["references"]}) == len(observer.data["references"])


@pytest.mark.parametrize("method", ["status", "_record_rebuild_request"])
def test_event_caller_stack_never_looks_up_source_files(method, monkeypatch):
    owner = Owner()
    observer = _observer(owner)
    calls = []
    status = {"custom": {"automaticRebuildNotice": owner._automatic_rebuild_notice}}

    def original():
        calls.append(True)
        return status if method == "status" else None

    def forbid_source_lookup(*args, **kwargs):
        raise AssertionError("Per-event source I/O is forbidden")

    for name in ("checkcache", "getline", "getlines", "updatecache"):
        monkeypatch.setattr(linecache, name, forbid_source_lookup)

    result = observer._method_wrapper(method, original)()

    assert result is (status if method == "status" else None)
    assert calls == [True]
    frames = observer.data["events"][0]["callerStack"]
    assert frames and all(set(frame) == {"path", "line", "name", "qualname"} for frame in frames)
    assert any(frame["name"] == "test_event_caller_stack_never_looks_up_source_files" for frame in frames)
