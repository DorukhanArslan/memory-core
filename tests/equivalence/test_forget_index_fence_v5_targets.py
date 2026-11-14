"""Labelled completion-capture receivers; no memory engine is constructed."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from equivalence.forget_index_fence_sdk import _OriginalObserver, _SdkActor, _full_stat


def _version(path):
    info = path.lstat()
    return {"path": str(path), "exists": True, "version": {"device": str(info.st_dev),
        "inode": str(info.st_ino), "size": info.st_size, "mtimeNs": str(info.st_mtime_ns),
        "ctimeNs": str(info.st_ctime_ns)}}


class _LabelledCaptureReceiver:
    def __init__(self, owned):
        self.owned, self.calls = owned, []

    def capture_versions(self, paths):
        self.calls.append(list(paths))
        if any(Path(path) != self.owned for path in paths):
            raise ValueError("Labelled receiver owns only its declared source")
        return [_version(Path(path)) if Path(path).exists() else
            {"path": str(path), "exists": False, "version": None} for path in paths]


def _actor(path, receipts, io=()):
    actor = _SdkActor.__new__(_SdkActor)
    actor.actor = "labelled-actor"
    actor.owner = SimpleNamespace(memory_watcher=_LabelledCaptureReceiver(path))
    actor.observer = _OriginalObserver({})
    actor.source_clock = SimpleNamespace(receipts=receipts, original_io=list(io))
    return actor


def _receipt(path, *, sequence=1):
    return {"sequence": sequence, "atNs": str(sequence), "callKey": "promotion:seed", "committed": True,
        "absolutePath": str(path), "committedState": {"stat": _full_stat(path.lstat())}}


def test_completion_capture_retains_successful_write_even_when_original_call_rejected(tmp_path):
    path = tmp_path / "MEMORY.md"
    path.write_text("actual source version")
    receipt = _receipt(path)
    actor = _actor(path, [receipt])
    call = {"kind": "promotion", "label": "seed", "error": {"message": "actual labelled original rejection"}}
    original_error = deepcopy(call["error"])
    actor._capture_watch_targets(call)
    capture = call["watchTargetCapture"]
    assert capture["versions"] == [_version(path)]
    assert capture["mutations"][0]["receipt"] == receipt
    assert capture["mutations"][0]["capture"] == [_version(path)]
    assert call["error"] == original_error and actor.observer.failures == []
    assert actor.owner.memory_watcher.calls == [[str(path)]]


def test_overwritten_completion_target_fails_closed_without_borrowing_later_version(tmp_path):
    path = tmp_path / "MEMORY.md"
    path.write_text("earlier committed version")
    old = _receipt(path)
    path.write_text("later version physically replaced the first")
    actor = _actor(path, [old])
    call = {"kind": "promotion", "label": "seed", "returned": {"actualOriginal": 7}}
    actor._capture_watch_targets(call)
    assert call["watchTargetCapture"]["versions"] == []
    assert call["watchTargetCapture"]["mutations"][0]["receipt"] == old
    assert actor.observer.failures[0]["phase"] == "watch-target-version"
    assert call["returned"] == {"actualOriginal": 7}


def test_actual_successful_delete_captures_absence_and_keeps_original_receipt(tmp_path):
    path = tmp_path / "MEMORY.md"
    path.write_text("real bytes before deletion")
    path.unlink()
    actual_io = {"sequence": 7, "atNs": "17", "syscall": "unlink", "arguments": [str(path)],
        "returned": None, "scope": {"kind": "forget", "label": "selected"},
        "ownerArguments": {"path": str(path), "content": None, "expected_content": "real bytes before deletion"}}
    actor = _actor(path, [], [actual_io])
    call = {"kind": "forget", "label": "selected"}
    actor._capture_watch_targets(call)
    capture = call["watchTargetCapture"]
    assert capture["versions"] == [{"path": str(path), "exists": False, "version": None}]
    assert capture["mutations"][0]["receipt"] == actual_io
    assert capture["mutations"][0]["receiptKind"] == "source-delete"
    assert actor.observer.failures == []


def test_ineligible_source_uses_actual_capture_rejection_as_explicit_absence(tmp_path):
    owned = tmp_path / "MEMORY.md"
    other = tmp_path / "DREAMS.md"
    owned.write_text("owned")
    other.write_text("other actual producer file")
    actor = _actor(owned, [_receipt(other)])
    call = {"kind": "promotion", "label": "seed"}
    actor._capture_watch_targets(call)
    capture = call["watchTargetCapture"]
    assert capture["versions"] == [] and capture["absence"] == "no-applicable-successful-watched-source-mutation"
    assert capture["mutations"][0]["applicabilityError"]["message"] == "Labelled receiver owns only its declared source"
    assert actor.observer.failures == []
