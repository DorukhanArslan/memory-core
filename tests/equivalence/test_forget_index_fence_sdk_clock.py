"""V2 fixture-clock tests with labelled stand-ins; no original engines run."""
import ast
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from equivalence.forget_index_fence_sdk import _encode, _full_stat
from equivalence.forget_index_fence_sdk_clock import DatetimeClockProxy, OwnedSourceWriteClock


BASE = 1794614400000
TICK = 1794528001000


def labelled_io(*arguments):
    raise AssertionError("A source-labelled stand-in body must never execute")


def labelled_write_all(*arguments):
    raise AssertionError("A source-labelled stand-in body must never execute")


def labelled_atomic(*arguments):
    raise AssertionError("A source-labelled stand-in body must never execute")


def labelled_append(*arguments):
    raise AssertionError("A source-labelled stand-in body must never execute")


def labelled_dreams(*arguments):
    raise AssertionError("A source-labelled stand-in body must never execute")


def frame(source_function, parent=None, **values):
    return SimpleNamespace(f_code=source_function.__code__, f_locals=values, f_back=parent)


def controller(root):
    scope = {"kind": "promotion", "label": "source-labelled", "wallClockNowMs": BASE}
    policy = {"protocol": "owned-source-write-clock-v2", "ticksByCall": {
        "promotion:source-labelled": {"ordinal": 1, "actor": "promoter", "wallClockNowMs": BASE,
                                      "mtimeMs": TICK, "atimeMs": TICK}}}
    owners = {function.__code__: {"role": role, "code": {"labelledStandIn": function.__name__}}
        for function, role in ((labelled_io, "io"), (labelled_write_all, "write-all"),
                              (labelled_atomic, "atomic"), (labelled_append, "append"), (labelled_dreams, "dreams"))}
    clock = OwnedSourceWriteClock(root=root, actor="promoter", policy=policy, owners=owners,
                                 scope=lambda: scope, encode=_encode, full_stat=_full_stat)
    return clock, scope


def io_return(clock, owner, name, arguments, returned):
    observed = frame(labelled_io, owner, function=clock.original_os[name], args=arguments)
    clock.profile(observed, "call", None)
    clock.profile(observed, "return", returned)
    return observed


def prepare_written_fd(clock, owner, path, payload, *, append=False):
    flags = os.O_RDWR | os.O_APPEND if append else os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    owner.f_locals["descriptor"] = descriptor
    io_return(clock, owner, "open", (path, flags, 0o600), descriptor)
    writing = frame(labelled_write_all, owner, descriptor=descriptor, content=payload)
    clock.profile(writing, "call", None)
    written = os.write(descriptor, payload)
    io_return(clock, writing, "write", (descriptor, memoryview(payload)), written)
    clock.profile(writing, "return", None)
    synced = os.fsync(descriptor)
    io_return(clock, owner, "fsync", (descriptor,), synced)
    return descriptor


def replace_once(clock, root, payload):
    target = root / "MEMORY.md"
    stage = root / f".labelled-stage-{len(clock.receipts)}.tmp"
    owner = frame(labelled_atomic, path=target)
    descriptor = prepare_written_fd(clock, owner, stage, payload)
    rename = frame(labelled_io, owner, function=os.replace, args=(stage, target))
    clock.profile(rename, "call", None)
    clock.profile(rename, "c_call", os.replace)
    returned = os.replace(stage, target)
    clock.profile(rename, "c_return", os.replace)
    clock.profile(rename, "return", returned)
    closed = os.close(descriptor)
    io_return(clock, owner, "close", (descriptor,), closed)
    return returned, target


def test_original_read_stat_and_delete_receipts_are_passive_and_preserve_actual_returns(tmp_path, monkeypatch):
    target = tmp_path / "MEMORY.md"
    payload = b"Actual bytes before the original deletion.\n"
    target.write_bytes(payload)
    clock, _ = controller(tmp_path)
    owner = frame(labelled_atomic, path=target, content=None, expected_content=payload.decode())

    def forbidden(*arguments, **options):
        raise AssertionError("Passive original read/delete witnesses cannot perform extra source inspection")

    monkeypatch.setattr(clock, "_inspect", forbidden)
    descriptor = os.open(target, os.O_RDONLY)
    try:
        io_return(clock, owner, "open", (target, os.O_RDONLY), descriptor)
        returned = os.read(descriptor, 65536)
        io_return(clock, owner, "read", (descriptor, 65536), returned)
        info = os.fstat(descriptor)
        io_return(clock, owner, "fstat", (descriptor,), info)
    finally:
        closed = os.close(descriptor)
        io_return(clock, owner, "close", (descriptor,), closed)
    deleted = os.unlink(target)
    io_return(clock, owner, "unlink", (target,), deleted)
    reads = [row for row in clock.original_io if row.get("syscall") == "read"]
    assert reads[0]["returned"] == {"bytesHex": payload.hex(), "bytes": len(payload)}
    stats = [row for row in clock.original_io if row.get("syscall") == "fstat"]
    assert stats[0]["returnedStat"] == _full_stat(info)
    deletion = clock.original_io[-1]
    assert deletion["syscall"] == "unlink" and deletion["returned"] is None
    assert deletion["ownerArguments"] == {"path": str(target), "content": None, "expected_content": payload.decode()}
    assert not target.exists() and clock.receipts == [] and clock.failures == []


def test_narrow_datetime_proxy_returns_original_instances_and_delegates_other_apis():
    wall = [BASE]
    calls = []
    proxy = DatetimeClockProxy(datetime, lambda: wall[0], lambda receipt, caller: calls.append(receipt))

    first = proxy.now(tz=UTC)
    wall[0] += 60001
    recovered = proxy.now(tz=UTC)

    assert type(first) is datetime and first == datetime.fromtimestamp(BASE / 1000, UTC)
    assert type(recovered) is datetime and recovered - first == timedelta(milliseconds=60001)
    assert type(proxy(2026, 11, 14, tzinfo=UTC)) is datetime
    assert proxy.fromisoformat.__self__ is datetime
    assert type(proxy.fromisoformat("2026-11-14T00:00:00+00:00")) is datetime
    assert proxy.min is datetime.min and proxy.max is datetime.max
    assert [row["wallClockNowMs"] for row in calls] == [BASE, BASE + 60001]
    assert proxy.failures == []


def test_datetime_receipt_failure_retains_real_return_and_separate_outer_invalidity():
    def rejected_record(receipt, frame):
        raise RuntimeError("labelled fixture receipt failure")

    proxy = DatetimeClockProxy(datetime, lambda: BASE, rejected_record)
    returned = proxy.now(tz=UTC)

    assert type(returned) is datetime and returned.timestamp() * 1000 == BASE
    assert len(proxy.failures) == 1
    assert proxy.failures[0]["error"]["message"] == "labelled fixture receipt failure"


def test_original_temporal_source_places_datetime_now_only_in_explicit_now_fallback():
    # Source-only branch proof: do not execute or recompile the ranking owner.
    path = Path(__file__).resolve().parents[2] / "memory_core/index/temporal_decay.py"
    function = next(node for node in ast.parse(path.read_text()).body
                    if isinstance(node, ast.FunctionDef) and node.name == "apply_temporal_decay_to_hybrid_results")
    assignment = next(node for node in function.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "effective_now_ms" for target in node.targets))
    branch = assignment.value
    assert isinstance(branch, ast.IfExp)
    assert ast.dump(branch.test) == ast.dump(ast.parse("now_ms is not None", mode="eval").body)
    assert isinstance(branch.body, ast.Name) and branch.body.id == "now_ms"
    assert not any(isinstance(node, ast.Attribute) and node.attr == "now" for node in ast.walk(branch.body))
    fallbacks = [node for node in ast.walk(branch.orelse) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "now"]
    assert len(fallbacks) == 1 and isinstance(fallbacks[0].func.value, ast.Name)
    assert fallbacks[0].func.value.id == "datetime"


def test_real_atomic_stage_clock_precedes_unchanged_original_replace_and_preserves_bytes(tmp_path):
    clock, scope = controller(tmp_path)
    returned, target = replace_once(clock, tmp_path, b"source-owned complete bytes\n")

    assert returned is None and clock.failures == []
    assert target.read_bytes() == b"source-owned complete bytes\n"
    assert target.stat().st_mtime_ns == TICK * 1_000_000
    receipt = clock.receipts[0]
    assert receipt["protocol"] == "owned-source-write-clock-v2"
    assert receipt["callKey"] == "promotion:source-labelled" and receipt["tick"]["ordinal"] == 1
    assert receipt["before"]["bytes"] == receipt["after"]["bytes"] == receipt["committedState"]["bytes"]
    assert receipt["before"]["identity"] == receipt["committedState"]["identity"]
    assert receipt["originalFsyncPresent"] is True and receipt["originalFullWrite"]["returned"] is None
    assert receipt["utimeReturn"] is None and receipt["committed"] is True
    assert int(receipt["utimeReturnAtNs"]) < int(receipt["originalRenameCSettlement"]["atNs"])
    assert receipt["originalWrites"][0]["arguments"][1] == {"bytesHex": b"source-owned complete bytes\n".hex(), "bytes": 28}
    assert scope["wallClockNowMs"] == BASE


def test_real_inplace_clock_uses_owned_fd_after_full_write_fsync_before_original_close(tmp_path):
    clock, _ = controller(tmp_path)
    target = tmp_path / "MEMORY.md"
    target.write_bytes(b"prefix\n")
    owner = frame(labelled_append, path=target)
    descriptor = prepare_written_fd(clock, owner, target, b"appended\n", append=True)
    offset = os.lseek(descriptor, 0, os.SEEK_CUR)
    close = frame(labelled_io, owner, function=os.close, args=(descriptor,))
    clock.profile(close, "call", None)
    clock.profile(close, "c_call", os.close)

    assert os.fstat(descriptor).st_mtime_ns == TICK * 1_000_000
    assert os.lseek(descriptor, 0, os.SEEK_CUR) == offset
    assert clock.receipts[0]["committed"] is False
    returned = os.close(descriptor)
    clock.profile(close, "return", returned)

    assert returned is None and target.read_bytes() == b"prefix\nappended\n"
    assert clock.receipts[0]["committed"] is True and clock.failures == []
    assert clock.receipts[0]["utimeArguments"]["target"] == descriptor


def test_clock_failure_does_not_replace_actual_original_rename_return_or_bytes(tmp_path):
    clock, _ = controller(tmp_path)

    def refused_utime(target, *, ns):
        raise PermissionError("labelled source-clock refusal")

    clock.original_os["utime"] = refused_utime
    returned, target = replace_once(clock, tmp_path, b"genuine bytes survive fixture refusal\n")

    assert returned is None and target.read_bytes() == b"genuine bytes survive fixture refusal\n"
    assert len(clock.failures) == 1
    assert clock.receipts[0]["utimeError"]["message"] == "labelled source-clock refusal"
    assert clock.receipts[0]["committed"] is False


def test_two_distinct_actual_commits_for_one_call_path_fail_outer_control_only(tmp_path):
    clock, _ = controller(tmp_path)
    first, _ = replace_once(clock, tmp_path, b"first actual revision\n")
    second, target = replace_once(clock, tmp_path, b"second actual revision\n")

    assert first is second is None
    assert target.read_bytes() == b"second actual revision\n"
    assert len(clock.receipts) == 2 and all(row["committed"] for row in clock.receipts)
    assert len(clock.failures) == 1 and "Distinct committed bytes" in clock.failures[0]["error"]["message"]


def test_same_actual_bytes_repeated_keep_each_real_commit_receipt(tmp_path):
    clock, _ = controller(tmp_path)
    replace_once(clock, tmp_path, b"same real bytes\n")
    replace_once(clock, tmp_path, b"same real bytes\n")

    assert len(clock.receipts) == 2 and all(row["committed"] for row in clock.receipts)
    assert len({row["before"]["identity"]["inode"] for row in clock.receipts}) == 2
    assert clock.failures == []


def test_dreams_closed_stage_records_honest_absence_of_original_fsync(tmp_path):
    clock, _ = controller(tmp_path)
    target, stage = tmp_path / "DREAMS.md", tmp_path / ".dreams-stage.tmp"
    descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    handle = os.fdopen(descriptor, "w", encoding="utf8", newline="")
    source = frame(labelled_dreams, path=target, temporary=stage, content="original DREAMS bytes\n", fd=descriptor, handle=handle)
    handle.write(source.f_locals["content"])
    clock.profile(source, "c_return", handle.write)
    handle.close()
    clock.profile(source, "c_return", handle.__exit__)
    clock.profile(source, "c_call", os.replace)
    returned = os.replace(stage, target)
    clock.profile(source, "return", returned)

    receipt = clock.receipts[0]
    assert returned is None and clock.failures == []
    assert receipt["originalFsyncPresent"] is False and receipt["originalFsync"] is None
    assert receipt["originalFullWrite"] is None
    assert [row["method"] for row in receipt["originalTextIO"]] == ["write", "__exit__"]
    assert all("returned" not in row for row in receipt["originalTextIO"])
    assert target.stat().st_mtime_ns == TICK * 1_000_000


def test_clock_requires_exact_original_owner_code_and_canonical_owned_path(tmp_path):
    clock, _ = controller(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="escaped"):
        clock._owned(alias / "MEMORY.md")
    before = deepcopy(clock.receipts)
    clock.profile(frame(lambda: None, function=os.replace, args=("a", "b")), "c_call", os.replace)
    assert clock.receipts == before and clock.failures == []
