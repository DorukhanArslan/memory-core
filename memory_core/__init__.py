"""memory-core: memory for LLM agents, an unofficial Python port of OpenClaw memory-core.

The package root holds what a host needs to run memory for its agent: the host kit
(:mod:`memory_core.host`), the core handle and its configuration, the embedding provider
interface with its OpenAI-compatible implementation, the workspace layouts and the errors a
host handles. Every other helper is imported from its submodule (CHANGELOG.md lists where
each name moved in 0.2.0).
"""

from memory_core.bootstrap import (
    OPENCLAW_COMPAT_LAYOUT,
    MEMORY_CORE_WORKSPACE_LAYOUT,
    WorkspaceLayout,
    WorkspaceStateMigrationRequiredError,
)
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.curation import CurationError
from memory_core.embeddings import EmbeddingProvider, OpenAICompatibleEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.host import (
    FlushOutcome,
    FlushRequest,
    HeartbeatOutcome,
    HeartbeatRun,
    HostKit,
    NewSession,
    ResetTurn,
    SessionState,
    ToolCallRepair,
    TurnContext,
    TurnRecord,
    TurnState,
    TurnUsage,
)
from memory_core.tools.common import MemoryToolInputError
from memory_core.workspace import UnsafeMemoryPathError

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # The host kit: one HostKit per workspace, one SessionState per session, and the
    # handles its entry points return.
    "HostKit",
    "SessionState",
    "TurnUsage",
    "TurnContext",
    "TurnState",
    "TurnRecord",
    "FlushRequest",
    "FlushOutcome",
    "NewSession",
    "ResetTurn",
    "HeartbeatRun",
    "HeartbeatOutcome",
    "ToolCallRepair",
    # The core handle a kit is built on, and its configuration.
    "Memory",
    "MemoryConfig",
    "FeatureFlags",
    # Hybrid search needs an embedder.
    "EmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
    # Which workspace files exist and are injected.
    "WorkspaceLayout",
    "MEMORY_CORE_WORKSPACE_LAYOUT",
    "OPENCLAW_COMPAT_LAYOUT",
    # Errors that reach a host.
    "MemoryToolInputError",
    "CurationError",
    "UnsafeMemoryPathError",
    "WorkspaceStateMigrationRequiredError",
]
