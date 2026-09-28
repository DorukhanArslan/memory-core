import subprocess
import sys
from pathlib import Path

import memory_core
from memory_core import host
from memory_core.curation import CurationConflictError, CurationUnavailableError

# The package root since 0.2.0 (CHANGELOG.md); every other name imports from its submodule.
ROOT_API = {
    "__version__",
    "HostKit",
    "SessionState",
    "TurnUsage",
    "TurnContext",
    "TurnRecord",
    "FlushRequest",
    "FlushOutcome",
    "NewSession",
    "ResetTurn",
    "HeartbeatRun",
    "HeartbeatOutcome",
    "Memory",
    "MemoryConfig",
    "FeatureFlags",
    "EmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
    "WorkspaceLayout",
    "MEMORY_CORE_WORKSPACE_LAYOUT",
    "OPENCLAW_COMPAT_LAYOUT",
    "MemoryToolInputError",
    "CurationError",
    "UnsafeMemoryPathError",
    "WorkspaceStateMigrationRequiredError",
}


def test_root_exports_exactly_the_host_surface():
    assert len(memory_core.__all__) == len(set(memory_core.__all__))
    assert set(memory_core.__all__) == ROOT_API
    for name in memory_core.__all__:
        assert hasattr(memory_core, name), name


def test_root_exports_every_host_kit_class():
    kit_classes = {name for name in host.__all__ if isinstance(getattr(host, name), type)}

    assert kit_classes <= ROOT_API
    for name in kit_classes:
        assert getattr(memory_core, name) is getattr(host, name)


def test_memory_keeps_only_the_core_handle_methods():
    public = {name for name in vars(memory_core.Memory) if not name.startswith("_")}

    assert public == {"from_workspace", "search", "get", "curator", "langgraph_recall"}


def test_the_root_curation_error_covers_its_subclasses():
    assert issubclass(CurationUnavailableError, memory_core.CurationError)
    assert issubclass(CurationConflictError, memory_core.CurationError)


def test_import_memory_core_works_without_fcntl(tmp_path):
    # fcntl is POSIX-only; the promotion guard imports it lazily (plug-and-play on Windows).
    script = (
        "import sys\n"
        "sys.modules['fcntl'] = None\n"
        "sys.modules['msvcrt'] = None\n"
        "import memory_core\n"
        "from memory_core.consolidation import acquire_short_term_promotion_lock\n"
        f"config = memory_core.MemoryConfig(workspace_dir={str(tmp_path)!r})\n"
        "with acquire_short_term_promotion_lock(config, 0) as lock:\n"
        "    assert lock.acquired\n"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=Path(memory_core.__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
