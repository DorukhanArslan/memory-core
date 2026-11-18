"""The memory-core host kit: memory behaviour for one workspace as a few entry points.

HostSessionRunner owns session admission, durable records and index publication around
the application's model callback. HostKit composes the workspace memory primitives and
returns SessionState values for hosts that manage their own lifecycle. Specifications:
docs/host_session_lifecycle.md and docs/host_kit.md.
"""

from memory_core.host.flush import FlushOutcome, FlushRequest
from memory_core.host.heartbeat_run import HeartbeatOutcome, HeartbeatRun, ScheduledHeartbeatWake
from memory_core.host.kit import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    MINIMAL_PROMPT_KINDS,
    HostKit,
    NewSession,
    ResetTurn,
    TurnContext,
    TurnRecord,
)
from memory_core.host.lifecycle import (
    HostModelResult,
    HostSessionRunner,
    FlushModelExecutor,
    FlushModelRoute,
    FlushModelSelection,
    FlushModelUnavailable,
    HostTurn,
    HostTurnFailure,
    HostTurnOutcome,
)
from memory_core.host.session import SessionState, TurnUsage
from memory_core.host.tool_calls import ToolCallRepair
from memory_core.host.turn import TurnState
from memory_core.model_prompt import RuntimePromptInput
from memory_core.history_replay import HistoryReplayContext

__all__ = [
    "DEFAULT_CONTEXT_WINDOW_TOKENS",
    "MINIMAL_PROMPT_KINDS",
    "FlushModelExecutor",
    "FlushModelRoute",
    "FlushModelSelection",
    "FlushModelUnavailable",
    "FlushOutcome",
    "FlushRequest",
    "HeartbeatOutcome",
    "HeartbeatRun",
    "HostKit",
    "HostModelResult",
    "HostSessionRunner",
    "HostTurn",
    "HostTurnFailure",
    "HostTurnOutcome",
    "NewSession",
    "ResetTurn",
    "SessionState",
    "ScheduledHeartbeatWake",
    "ToolCallRepair",
    "TurnContext",
    "TurnRecord",
    "TurnState",
    "TurnUsage",
    "RuntimePromptInput",
    "HistoryReplayContext",
]
