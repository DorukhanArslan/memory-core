"""Gate the retained v2026.9.6 regression oracle modules.

Integration modules named ``test_*_oracle.py`` require a nonempty ``OPENCLAW_ORACLE_REPO``.
Without it, skip them before fixture setup; ordinary integration tests still run offline.
An explicitly configured but broken oracle remains a failure. These historical
regressions are separate from the current full-equivalence acceptance suite.
Any oracle result with ``ok: false`` raises :class:`OracleHarnessError`; a
runner failure is never treated as an expected behavior mismatch.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from demo.openclaw_oracle import ORACLE_REPO_ENV, OpenClawOracle

_INTEGRATION_DIR = Path(__file__).parent


class OracleHarnessError(RuntimeError):
    """The oracle runner itself failed; never an expected behavior mismatch."""


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    oracle_enabled = bool(os.getenv(ORACLE_REPO_ENV))
    for item in items:
        if (
            not oracle_enabled
            and item.path.parent == _INTEGRATION_DIR
            and item.path.name.endswith("_oracle.py")
        ):
            item.add_marker(pytest.mark.skip(reason=f"{ORACLE_REPO_ENV} is not set"))


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
