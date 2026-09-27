"""Marks the stage-1 worklist of the v2026.9.6 re-pin (oracle_worklist.PENDING_PORTS)."""

from __future__ import annotations

import pytest

from oracle_worklist import pending_port_reason

_PREFIX = "tests/integration/"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        nodeid = item.nodeid
        relative = nodeid[len(_PREFIX):] if nodeid.startswith(_PREFIX) else nodeid
        reason = pending_port_reason(relative)
        if reason is not None:
            item.add_marker(pytest.mark.xfail(strict=True, reason=reason))
