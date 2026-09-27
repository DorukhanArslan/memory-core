"""Marks the stage-1 worklist of the v2026.9.6 re-pin (oracle_worklist.PENDING_PORTS).

A listed test is ``xfail(strict=True, raises=AssertionError)``: it may only fail on a value
assertion. Any oracle result with ``ok: false`` (timeout, runner error, missing checkout, invalid
JSON) raises :class:`OracleHarnessError` instead, which is not an ``AssertionError``, so a harness
regression fails the test even when it is on the worklist.
"""

from __future__ import annotations

import pytest

from demo.openclaw_oracle import OpenClawOracle
from oracle_worklist import pending_port_reason

_PREFIX = "tests/integration/"


class OracleHarnessError(RuntimeError):
    """The oracle runner itself failed; never an expected worklist failure."""


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        nodeid = item.nodeid
        relative = nodeid[len(_PREFIX):] if nodeid.startswith(_PREFIX) else nodeid
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
