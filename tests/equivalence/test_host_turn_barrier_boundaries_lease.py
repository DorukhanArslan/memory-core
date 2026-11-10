"""Real kernel leases and bounded path/protocol authority; no acceptance credit."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="The declared fixture requires Linux read leases")
HELPER = Path(__file__).resolve().parents[2] / "equivalence/host_turn_barrier_boundaries_lease.py"
RELATIVE = "memory/2026-11-10.md"


def _line(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(5), "An owned fixture process did not produce its bounded receipt"
    value = process.stdout.readline()
    assert value, process.stderr.read().decode() if process.poll() is not None else "Fixture stdout closed"
    return json.loads(value)


def _send(process, name, request_id):
    process.stdin.write((json.dumps({"command": name, "id": request_id}) + "\n").encode())
    return _line(process)


def _arguments(workspace, *, owner_pid=None, relative=RELATIVE):
    return [sys.executable, str(HELPER), "--workspace", str(workspace), "--relative-path", relative,
            "--owner-pid", str(os.getpid() if owner_pid is None else owner_pid)]


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / RELATIVE).write_bytes(b"")
    return tmp_path


@contextmanager
def _process(arguments):
    process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, bufsize=0)
    try:
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def _peer(target):
    # The parent and worker communicate through actual process pipes. The worker
    # performs a genuine append-mode open, then holds its writable descriptor.
    script = """
import concurrent.futures,json,sys
def emit(event):print(json.dumps({'event':event}),flush=True)
def opened():return open(sys.argv[1],'a')
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
 future=pool.submit(opened);emit('SUBMITTED')
 assert sys.stdin.readline().strip()=='ping';emit('LIVE')
 handle=future.result(timeout=5);emit('OPENED')
 assert sys.stdin.readline().strip()=='close'
 handle.write('append\\n');handle.close();emit('CLOSED')
"""
    return [sys.executable, "-c", script, str(target)]


def test_real_kernel_gate_and_descriptor_close_proof(workspace):
    target = workspace / RELATIVE
    with _process(_arguments(workspace)) as helper:
        armed = _line(helper)
        assert armed["event"] == "ARMED" and armed["held"] is True and armed["leaseType"] == 0
        assert armed["ppid"] == os.getpid() and armed["pid"] == helper.pid
        assert armed["script"] == {"path": str(HELPER), "sha256": hashlib.sha256(HELPER.read_bytes()).hexdigest()}
        assert armed["target"]["ino"] == target.stat().st_ino
        assert armed["target"]["sha256"] == hashlib.sha256(b"").hexdigest()
        with _process(_peer(target)) as peer:
            assert _line(peer)["event"] == "SUBMITTED"
            broken = _line(helper)
            assert broken["event"] == "BREAK" and broken["held"] is True
            peer.stdin.write(b"ping\n")
            assert _line(peer)["event"] == "LIVE"
            assert target.read_bytes() == b""
            released = _send(helper, "RELEASE", "release-real-open")
            assert released["event"] == "RELEASED" and released["held"] is False
            assert _line(peer)["event"] == "OPENED"
            peer.stdin.write(b"close\n")
            assert _line(peer)["event"] == "CLOSED"
            assert peer.wait(timeout=5) == 0
        verified = _send(helper, "VERIFY", "verify-actual-close")
        assert verified["event"] == "VERIFIED" and verified["held"] is True and verified["leaseType"] == 0
        assert verified["target"]["sha256"] == hashlib.sha256(b"append\n").hexdigest()
        assert _send(helper, "RELEASE", "release-proof")["event"] == "RELEASED"
        assert _send(helper, "STOP", "stop")["event"] == "CLOSED"
        assert helper.wait(timeout=5) == 0


def test_verify_cannot_claim_closed_writer_while_real_writable_descriptor_is_open(workspace):
    with _process(_arguments(workspace)) as helper:
        assert _line(helper)["event"] == "ARMED"
        with _process(_peer(workspace / RELATIVE)) as peer:
            assert _line(peer)["event"] == "SUBMITTED"
            assert _line(helper)["event"] == "BREAK"
            peer.stdin.write(b"ping\n")
            assert _line(peer)["event"] == "LIVE"
            assert _send(helper, "RELEASE", "release")["event"] == "RELEASED"
            assert _line(peer)["event"] == "OPENED"
            refused = _send(helper, "VERIFY", "prove-still-open")
            assert refused["event"] == "ERROR" and refused["error"]["errno"] in {11, 13}
            peer.stdin.write(b"close\n")
            assert _line(peer)["event"] == "CLOSED"
            assert peer.wait(timeout=5) == 0
        assert _send(helper, "STOP", "stop")["event"] == "CLOSED"
        assert helper.wait(timeout=5) == 2


def test_duplicate_release_is_an_error_and_never_another_release_receipt(workspace):
    with _process(_arguments(workspace)) as helper:
        assert _line(helper)["event"] == "ARMED"
        assert _send(helper, "RELEASE", "first")["event"] == "RELEASED"
        refused = _send(helper, "RELEASE", "second")
        assert refused["event"] == "ERROR" and "second time" in refused["error"]["message"]
        assert _send(helper, "STOP", "stop")["event"] == "CLOSED"
        assert helper.wait(timeout=5) == 2


@pytest.mark.parametrize("substitution", ["workspace-alias", "target-alias", "hardlink", "nonempty",
                                          "outside", "wrong-parent"])
def test_lease_refuses_other_paths_bytes_and_process_ownership(workspace, substitution):
    target, root = workspace / RELATIVE, workspace
    extra = {}
    if substitution == "workspace-alias":
        root = workspace / "alias"
        root.symlink_to(workspace, target_is_directory=True)
    elif substitution == "target-alias":
        target.unlink()
        other = workspace / "other.md"
        other.write_bytes(b"")
        target.symlink_to(other)
    elif substitution == "hardlink":
        os.link(target, workspace / "alias.md")
    elif substitution == "nonempty":
        target.write_bytes(b"not the declared empty fixture")
    elif substitution == "outside":
        extra["relative"] = "../outside.md"
    else:
        extra["owner_pid"] = os.getpid() + 1
    result = subprocess.run(_arguments(root, **extra), input=b'{"command":"STOP","id":"stop"}\n',
                            capture_output=True, timeout=5)
    assert result.returncode != 0 and result.stdout == b""


def test_eof_cannot_stand_in_for_a_successful_stop_receipt(workspace):
    result = subprocess.run(_arguments(workspace), input=b"", capture_output=True, timeout=5)
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 2 and [row["event"] for row in rows] == ["ARMED", "CLOSED"]
    assert rows[-1]["reason"] == "stdin-eof-before-STOP"
