"""Oracle worklist of the re-pin to OpenClaw v2026.9.6 (stage 1).

Stage 1 moved the oracle target from pin 4c428153 to release tag v2026.9.6 without changing
Python behaviour. Each oracle test that fails at the tag because memory-core still follows the pin
is listed in PENDING_PORTS, grouped by area with the upstream change that moved it;
tests/integration/conftest.py marks those tests ``xfail(strict=True)``, so the suite stays
green, an unexpected pass fails it, and this module is the stage-2 worklist
(docs/upstream_port_v2026_9_6.md). Oracle operations whose upstream function no longer exists
at the tag are RETIRED_OPS; their tests carry a ``retired_upstream`` skip.

Entries are node ids relative to tests/integration/. An entry ending in ``*`` matches every
node id starting with the text before it (for long parameter ids).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

ORACLE_TAG = "v2026.9.6"
ORACLE_TAG_COMMIT = "eb377ac59e6c9fd6c7705028034812becf00271b"


@dataclass(frozen=True)
class PendingPort:
    area: str
    upstream: str
    tests: tuple[str, ...]

    @property
    def reason(self) -> str:
        return f"pending port to {ORACLE_TAG}: {self.area}; upstream {self.upstream}"


@dataclass(frozen=True)
class RetiredOp:
    operation: str
    commit: str
    stage2: str

    @property
    def reason(self) -> str:
        return f"retired upstream in {self.commit} ({ORACLE_TAG}); re-port in stage 2: {self.stage2}"


RETIRED_OPS: tuple[RetiredOp, ...] = (
    RetiredOp(
        "parseHeartbeatTasks",
        "b23c7bd0f84 (#113165)",
        "src/commands/heartbeat-task-legacy.ts analyzeLegacyHeartbeatTasks (doctor migration of "
        "tasks: blocks into cron jobs) plus the cron-owned scheduledTasks of "
        "src/infra/heartbeat-runner-prompt.ts resolveHeartbeatRunPrompt",
    ),
    RetiredOp(
        "heartbeatTaskDue",
        "b23c7bd0f84 (#113165)",
        "none for isTaskDue (cron owns due-ness); the duration and interval cases moved to the "
        "heartbeatDurations op",
    ),
    RetiredOp(
        "heartbeatSystemSection",
        "6a1dedb00c2 (#129642)",
        "src/infra/heartbeat-runner-prompt.ts resolveHeartbeatRunPrompt (the heartbeat prompt "
        "lives only in the scheduled user turn; no '## Heartbeats' section)",
    ),
    RetiredOp(
        "sessionMemoryTranscript",
        "2cc49503a60 (#107412) and 4273ca9dbd9 (#113233)",
        "src/hooks/bundled/session-memory/transcript.ts getRecentSessionProjectionFromEvents "
        "and countSessionMemoryMessages over SQLite transcript events",
    ),
)
RETIRED_BY_OPERATION = {op.operation: op for op in RETIRED_OPS}


def retired_upstream(operation: str) -> pytest.MarkDecorator:
    return pytest.mark.skip(reason=RETIRED_BY_OPERATION[operation].reason)


PENDING_PORTS: tuple[PendingPort, ...] = ()


def pending_port_reason(nodeid: str) -> str | None:
    """Return the xfail reason for a node id relative to tests/integration/, if listed."""
    for port in PENDING_PORTS:
        for entry in port.tests:
            if entry.endswith("*") and nodeid.startswith(entry[:-1]):
                return port.reason
            if nodeid == entry:
                return port.reason
    return None
