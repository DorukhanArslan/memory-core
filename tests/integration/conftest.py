"""Marks the stage-1 worklist of the v2026.9.6 re-pin (oracle_worklist.PENDING_PORTS).

A listed test is ``xfail(strict=True, raises=AssertionError)``: it may only fail on a value
assertion. Any oracle result with ``ok: false`` (timeout, runner error, missing checkout, invalid
JSON) raises :class:`OracleHarnessError` instead, which is not an ``AssertionError``, so a harness
regression fails the test even when it is on the worklist.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from demo.openclaw_oracle import OpenClawOracle
from oracle_worklist import pending_port_reason

_PREFIX = "tests/integration/"


class OracleHarnessError(RuntimeError):
    """The oracle runner itself failed; never an expected worklist failure."""


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        nodeid = item.nodeid
        relative = nodeid[len(_PREFIX) :] if nodeid.startswith(_PREFIX) else nodeid
        reason = pending_port_reason(relative)
        if reason is not None:
            item.add_marker(pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason))


@pytest.fixture(autouse=True)
def _oracle_errors_are_harness_errors(monkeypatch: pytest.MonkeyPatch):
    run = OpenClawOracle.run

    def checked_run(self: OpenClawOracle, payload: dict) -> dict:
        result = run(self, payload)
        if not isinstance(result, dict) or result.get("ok") is not True:
            error = result.get("error") if isinstance(result, dict) else result
            raise OracleHarnessError(f"oracle {payload.get('operation')!r} failed: {error!r}")
        return result

    monkeypatch.setattr(OpenClawOracle, "run", checked_run)


def pytest_sessionstart(session: pytest.Session) -> None:
    """Empty upstream's cross-process state-lock directory when no oracle runner is alive.

    Every runner call leaves three lock files there, one set per state directory, and a long
    suite grows it past six thousand files. Back-to-back runner calls then stalled about once in
    ten calls (an unexplained link: a freshly emptied directory ran the heartbeat group four
    times without a stall). The files are only locks, so they are safe to drop between runs.
    """
    if not hasattr(os, "getuid"):
        return
    try:
        alive = subprocess.run(
            ["pgrep", "-f", "openclaw_oracle_runner"], capture_output=True, check=False
        ).stdout.strip()
    except OSError:
        return
    if alive:
        return
    shutil.rmtree(
        Path(tempfile.gettempdir()) / f"openclaw-state-locks-{os.getuid()}", ignore_errors=True
    )
