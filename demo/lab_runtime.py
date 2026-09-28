"""The Lab runtime: one in-process Lab over the memory-core package (demo-only glue).

Everything that decides memory behaviour comes from ``memory-core``: the host kit
(``memory_core.host.HostKit``, built per request by :meth:`LabRuntime.kit`) seeds the
workspace and runs the BOOTSTRAP.md lifecycle, builds the injected context and
the memory tools; search, the flush plan and trigger, the session-memory hook,
heartbeat and consolidation come from the core. This module only holds what a
host holds: paths, settings, sessions and turns, provider resolution (keys stay
request-scoped or in the environment and are never returned), file guards for
the editor, the event bus, the index bookkeeping and the before/after file
snapshots.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from demo.chat_engine import DEFAULT_OPENAI_BASE_URL, DEFAULT_OPENAI_MODEL
from demo.lab_events import LabEventBus, Snapshot, WorkspaceSnapshots, diff_snapshots
from demo.live_task_demo import LiveTaskDemo
from demo.workspace_context import DEMO_WORKSPACE_TEMPLATES
from memory_core.bootstrap import (
    DEFAULT_BOOTSTRAP_MAX_CHARS,
    DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
    OPENCLAW_COMPAT_LAYOUT,
    MEMORY_CORE_WORKSPACE_LAYOUT,
    WorkspaceInitResult,
    WorkspaceLayout,
    bootstrap_status,
    migrate_tools_md,
    read_workspace_setup_state,
)
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.curation import (
    APPEND_DAILY_NOTE,
    MEMORY_ENTRY_OPERATIONS,
    SET_PROACTIVE_PREFERENCES,
    UPSERT_USER_DIRECTIVE,
    CurationPolicy,
)
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.host import DEFAULT_CONTEXT_WINDOW_TOKENS, HostKit, SessionState, TurnRecord
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace

LAB_TIMEZONE = "Europe/Istanbul"
# The Lab host's 12/24-hour format for every Current time line it builds (the flush plan, the
# heartbeat turn and the bare /new and /reset prompt): one value, as memory_core.current_time asks
# of a host. Upstream detects the host OS's format instead (edecdbd05ef #111527).
LAB_TIME_FORMAT = "24"
LAB_WORKSPACE_DIRNAME = "memory-core-lab-workspace"
LIVE_TASK_WORKSPACE_DIRNAME = "memory-core-live-task-demo-workspace"
LAB_SESSION_SOURCE = "lab"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SESSION_KINDS = ("main", "group", "channel", "direct", "subagent", "cron", "heartbeat")
LAYOUTS: dict[str, WorkspaceLayout] = {
    "memory-core": MEMORY_CORE_WORKSPACE_LAYOUT,
    # The upstream v2026.9.6 map alone (no OpenClaw brand in the Lab UI).
    "upstream": OPENCLAW_COMPAT_LAYOUT,
}
SEARCH_MODES = ("hybrid", "vector", "text")
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
FILE_MAX_BYTES = 2 * 1024 * 1024
WARNING_MODES = ("off", "once", "always")
CONTEXT_INJECTION_MODES = ("always", "continuation-skip", "never")

# Lab feature flags: (default, label, extension). Curation flags feed CurationPolicy.
LAB_FLAGS: dict[str, tuple[bool, str, bool]] = {
    "curated_memory_writes": (True, "Küratörlü yazımlar", True),
    "curation.memory_md": (True, "MEMORY.md küratörlüğü", True),
    "curation.user_md": (True, "USER.md direktifleri", True),
    "curation.daily_note": (True, "Günlük not", True),
    "curation.proactive_preferences": (True, "PROACTIVE_PREFERENCES.md", True),
    "lab_file_editing": (True, "Lab dosya düzenleme", True),
}
CURATION_FLAG = "curated_memory_writes"
# Lab flag -> the curation operations it gates (per-target policy, D5).
_TARGET_FLAGS = {
    "curation.memory_md": MEMORY_ENTRY_OPERATIONS,
    "curation.user_md": (UPSERT_USER_DIRECTIVE,),
    "curation.daily_note": (APPEND_DAILY_NOTE,),
    "curation.proactive_preferences": (SET_PROACTIVE_PREFERENCES,),
}


def _relative_to_root(root: Path, path: str | None) -> str | None:
    if path is None:
        return None
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path


class LabError(Exception):
    """An API error with an HTTP status and a stable ``code``."""

    def __init__(
        self, status: int, message: str, *, code: str | None = None, **extra: Any
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.extra = extra

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": self.message}
        if self.code:
            body["code"] = self.code
        body.update(self.extra)
        return body


def validate_id(value: Any, name: str) -> str:
    text = "" if value is None else str(value)
    if not SAFE_ID_RE.match(text):
        raise LabError(400, f"{name} must match ^[A-Za-z0-9_-]{{1,64}}$", code="invalid_id")
    return text


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def redact_secrets(message: str, secret_values: tuple[str, ...]) -> str:
    for secret in secret_values:
        if secret:
            message = message.replace(secret, "[redacted]")
    return message


def redact_payload(value: Any, secret_values: tuple[str, ...]) -> Any:
    """Every string in a JSON-like value with the configured key values replaced."""
    if not secret_values:
        return value
    if isinstance(value, str):
        return redact_secrets(value, secret_values)
    if isinstance(value, dict):
        return {key: redact_payload(item, secret_values) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [redact_payload(item, secret_values) for item in value]
    return value


def safe_exception_message(exc: BaseException, secret_values: tuple[str, ...] = ()) -> str:
    message = str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {redact_secrets(message, secret_values)}"


def local_date(now_ms: int, timezone: str = LAB_TIMEZONE) -> date:
    return datetime.fromtimestamp(now_ms / 1000, tz=UTC).astimezone(ZoneInfo(timezone)).date()


def now_ms() -> int:
    return int(time.time() * 1000)


# --- provider resolution ---------------------------------------------------------------


@dataclass(frozen=True)
class ChatResolution:
    base_url: str
    model: str
    key_source: str  # "request" | "env" | "none"
    api_key: str = field(default="", repr=False)

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    def public(self) -> dict[str, Any]:
        return {"baseUrl": self.base_url, "model": self.model, "keySource": self.key_source}


@dataclass(frozen=True)
class EmbeddingResolution:
    mode: str  # "hybrid" | "fts-only"
    base_url: str | None
    model: str | None
    key_source: str
    reason: str | None
    api_key: str = field(default="", repr=False)

    @property
    def available(self) -> bool:
        return self.mode == "hybrid"

    def public(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "provider": "openai-compatible" if self.available else "none",
            "baseUrl": self.base_url,
            "model": self.model if self.available else "fts-only",
            "keySource": self.key_source,
            "reason": self.reason,
            "label": "hibrit" if self.available else "yalnız FTS",
        }


class CountingEmbeddingProvider:
    """Wraps a real provider and emits ``embedding.request`` for every call."""

    def __init__(self, inner: OpenAICompatibleEmbeddingProvider, bus: LabEventBus) -> None:
        self._inner = inner
        self._bus = bus
        self.provider_id = inner.provider_id
        self.model = inner.model

    def cache_key_data(self) -> dict[str, str]:
        return self._inner.cache_key_data()

    def embed_query(self, text: str) -> list[float]:
        self._bus.emit(
            "embedding.request",
            summary=f"embed_query · {self.model}",
            data={"kind": "query", "model": self.model, "inputs": 1},
        )
        return self._inner.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._bus.emit(
            "embedding.request",
            summary=f"embed_documents · {len(texts)} · {self.model}",
            data={"kind": "documents", "model": self.model, "inputs": len(texts)},
        )
        return self._inner.embed_documents(texts)


# --- settings, sessions, turns -------------------------------------------------------------


@dataclass
class LabSettings:
    chat_base_url: str | None = None
    chat_model: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    layout: str = "memory-core"
    max_chars: int = DEFAULT_BOOTSTRAP_MAX_CHARS
    total_max_chars: int = DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS
    warning_mode: str = "always"
    context_injection: str = "always"
    context_window_tokens: int | None = None
    heartbeat_every: str = "30m"
    heartbeat_light_context: bool = False
    flags: dict[str, bool] = field(
        default_factory=lambda: {name: spec[0] for name, spec in LAB_FLAGS.items()}
    )

    @property
    def effective_context_window_tokens(self) -> int:
        return self.context_window_tokens or DEFAULT_CONTEXT_WINDOW_TOKENS


@dataclass
class LabSession:
    """One Lab session: the host kit's ``SessionState`` plus what the Lab host keeps.

    ``state`` is the value every kit call takes and returns (key, id, kind, the flush-gate
    entry, the truncation signatures, the bootstrap turn); ``last_turn`` is the last
    ``HostKit.after_turn`` result, which the status-bar flush meter shows.
    """

    kind: str
    created_at: int
    state: SessionState
    messages: list[dict[str, str]] = field(default_factory=list)
    turn_ids: list[int] = field(default_factory=list)
    token_source: str | None = None
    last_turn: TurnRecord | None = None
    pending_reset: dict[str, Any] | None = None

    @property
    def id(self) -> str:
        return self.state.session_id

    @property
    def key(self) -> str:
        return self.state.session_key

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "kind": self.kind,
            "startedAt": self.created_at,
            "turns": len(self.turn_ids),
            "transcriptMessages": len(self.messages),
            "pendingReset": bool(self.pending_reset),
        }


def new_session_id() -> str:
    return secrets.token_hex(4)


def new_session(kind: str) -> LabSession:
    """A kind's first session. Its key ``lab:<kind>`` stays across ``/new`` (upstream sessionKey,
    decision Q10); ``/new`` and ``/reset`` give it a new id."""
    return LabSession(
        kind=kind,
        created_at=now_ms(),
        state=SessionState.new(
            session_key=f"lab:{kind}", session_id=new_session_id(), kind=kind  # type: ignore[arg-type]
        ),
    )


# --- the index -----------------------------------------------------------------------------


class LabStore(SQLiteMemoryStore):
    """The Lab's index for one search mode.

    Every reindex, the Lab's own or the host kit's after a curated, flush or session-memory
    write, updates the Lab's index status and revisions (``index_is_stale``) and emits
    ``index.reindexed`` for ``turn_id``; ``last_reindex`` holds the numbers.
    """

    def __init__(
        self,
        config: MemoryConfig,
        embeddings: EmbeddingProvider | None,
        *,
        lab: LabRuntime,
        turn_id: int | None = None,
    ) -> None:
        super().__init__(config, embeddings)
        self._lab = lab
        self.turn_id = turn_id
        self.last_reindex: dict[str, Any] = {}

    def reindex(self, workspace: MemoryWorkspace) -> int:
        started = time.perf_counter()
        files = super().reindex(workspace)
        self.last_reindex = self._lab.record_reindex(
            self, files, ms=int((time.perf_counter() - started) * 1000)
        )
        return files


# --- the runtime ---------------------------------------------------------------------------


class LabRuntime:
    """All Lab state for one process. Tests build their own with a temp ``base_dir``."""

    def __init__(self, base_dir: str | os.PathLike[str] | None = None) -> None:
        base = Path(base_dir) if base_dir is not None else Path(tempfile.gettempdir())
        self.root = base / LAB_WORKSPACE_DIRNAME
        self.live_root = base / LIVE_TASK_WORKSPACE_DIRNAME
        self.bus = LabEventBus()
        self.snapshots = WorkspaceSnapshots(self.root, self.bus)
        self.settings = LabSettings()
        self.lock = threading.Lock()
        self.sessions: dict[str, LabSession] = {}
        self.turns: dict[int, dict[str, Any]] = {}
        self.turn_order: list[int] = []
        self._next_turn_id = 1
        self.curated_writes: list[dict[str, Any]] = []
        self._next_write_id = 1
        self.heartbeat_runs: list[dict[str, Any]] = []
        self._next_heartbeat_run_id = 1
        self.clock_offset_ms = 0
        self.index_status: dict[str, Any] = {"files": 0, "chunks": 0, "lastReindexAt": None}
        self._index_revisions: dict[str, str] = {}
        self.consolidation_results: dict[str, Any] = {}
        self.provider_status: dict[str, Any] = {"chat": None, "embedding": None}
        self._ensure_lock = threading.Lock()
        self.live_task = LiveTaskDemo(workspace_dir=self.live_root)

    @contextmanager
    def locked(self, timeout: float = 120.0) -> Iterator[None]:
        """The Lab lock for a mutating request; ``409 busy`` instead of waiting forever."""
        if not self.lock.acquire(timeout=timeout):
            raise LabError(409, "another Lab operation is still running", code="busy")
        try:
            yield
        finally:
            self.lock.release()

    # clocks

    def now_ms(self) -> int:
        return now_ms()

    def heartbeat_now_ms(self) -> int:
        """Virtual heartbeat clock (demo-only): shifts automation due checks, job runs and
        migrated anchors only."""
        return now_ms() + self.clock_offset_ms

    def today(self) -> str:
        return local_date(self.now_ms()).isoformat()

    def yesterday(self) -> str:
        return (local_date(self.now_ms()) - timedelta(days=1)).isoformat()

    # layout and config

    @property
    def layout(self) -> WorkspaceLayout:
        return LAYOUTS[self.settings.layout]

    def layout_for(self, name: str | None) -> WorkspaceLayout:
        if name in (None, ""):
            return self.layout
        if name not in LAYOUTS:
            raise LabError(400, "layout must be 'memory-core' or 'upstream'", code="invalid_layout")
        return LAYOUTS[str(name)]

    def config(self, *, mode: str = "text") -> MemoryConfig:
        if mode not in SEARCH_MODES:
            raise LabError(400, "mode must be hybrid, vector or text", code="invalid_mode")
        flags = FeatureFlags(
            vector_search=mode != "text",
            text_search=mode != "vector",
            curated_memory_writes=self.settings.flags.get(CURATION_FLAG, True),
        )
        return MemoryConfig(
            workspace_dir=self.root,
            store_path=self.root / ".memory-core" / f"lab-{mode}.sqlite",
            flags=flags,
        )

    # providers

    def resolve_chat(self, payload: dict[str, Any] | None) -> ChatResolution:
        body = _object(payload or {}, "openai")
        base_url = (
            optional_text(body.get("baseUrl"))
            or self.settings.chat_base_url
            or optional_text(os.getenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL"))
            or DEFAULT_OPENAI_BASE_URL
        )
        model = (
            optional_text(body.get("model"))
            or self.settings.chat_model
            or optional_text(os.getenv("MEMORY_CORE_DEMO_OPENAI_MODEL"))
            or DEFAULT_OPENAI_MODEL
        )
        request_key = optional_text(body.get("apiKey"))
        env_key = None if body.get("ignoreEnvKey") else optional_text(
            os.getenv("MEMORY_CORE_DEMO_OPENAI_API_KEY")
        )
        if request_key:
            return ChatResolution(base_url.rstrip("/"), model, "request", request_key)
        if env_key:
            return ChatResolution(base_url.rstrip("/"), model, "env", env_key)
        return ChatResolution(base_url.rstrip("/"), model, "none")

    def resolve_embedding(self, payload: dict[str, Any] | None) -> EmbeddingResolution:
        """Q9: a real OpenAI-compatible embedding endpoint, else FTS-only; never fake vectors.

        The endpoint is the request's or the settings' or ``MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL``,
        else the chat base URL. An openrouter.ai endpoint serves no ``/embeddings``, so it
        yields FTS-only. The chat key is reused only for the chat endpoint itself, so a key is
        never sent to a host it was not configured for.
        """
        payload = payload or {}
        body = _object(payload, "embedding")
        chat = self.resolve_chat(payload)
        explicit = (
            optional_text(body.get("baseUrl"))
            or self.settings.embedding_base_url
            or optional_text(os.getenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL"))
        )
        base_url = (explicit or chat.base_url).rstrip("/")
        model = (
            optional_text(body.get("model"))
            or self.settings.embedding_model
            or optional_text(os.getenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_MODEL"))
            or DEFAULT_EMBEDDING_MODEL
        )
        if "openrouter.ai" in base_url:
            return EmbeddingResolution(
                "fts-only",
                base_url,
                model,
                "none",
                "openrouter.ai serves no /embeddings endpoint: FTS-only",
            )
        request_key = optional_text(body.get("apiKey"))
        env_key = optional_text(os.getenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY"))
        if request_key:
            return EmbeddingResolution("hybrid", base_url, model, "request", None, request_key)
        if env_key:
            return EmbeddingResolution("hybrid", base_url, model, "env", None, env_key)
        if base_url == chat.base_url and chat.has_key:
            return EmbeddingResolution("hybrid", base_url, model, chat.key_source, None, chat.api_key)
        return EmbeddingResolution(
            "fts-only",
            base_url,
            model,
            "none",
            "no embedding API key (MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY or the request): FTS-only",
        )

    def secret_values(self, payload: dict[str, Any] | None) -> tuple[str, ...]:
        payload = payload or {}
        values = [
            optional_text(_object(payload, "openai").get("apiKey")),
            optional_text(_object(payload, "embedding").get("apiKey")),
            optional_text(os.getenv("MEMORY_CORE_DEMO_OPENAI_API_KEY")),
            optional_text(os.getenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY")),
        ]
        return tuple(value for value in values if value)

    def embedding_provider(self, resolution: EmbeddingResolution) -> EmbeddingProvider | None:
        if not resolution.available or resolution.base_url is None:
            return None
        inner = OpenAICompatibleEmbeddingProvider(
            api_key=resolution.api_key, model=resolution.model or DEFAULT_EMBEDDING_MODEL,
            base_url=resolution.base_url,
        )
        return CountingEmbeddingProvider(inner, self.bus)

    def default_search_mode(self, resolution: EmbeddingResolution) -> str:
        return "hybrid" if resolution.available else "text"

    def store(
        self, resolution: EmbeddingResolution, *, mode: str | None = None, turn_id: int | None = None
    ) -> LabStore:
        """The index for one search mode; FTS-only never gets (or calls) an embedder."""
        resolved_mode = mode or self.default_search_mode(resolution)
        if resolved_mode not in SEARCH_MODES:
            raise LabError(400, "mode must be hybrid, vector or text", code="invalid_mode")
        if resolved_mode != "text" and not resolution.available:
            raise LabError(
                400,
                f"{resolved_mode} search needs an embedding provider; this Lab runs FTS-only "
                f"({resolution.reason})",
                code="fts_only",
                embeddings=resolution.public(),
            )
        provider = self.embedding_provider(resolution) if resolved_mode != "text" else None
        return LabStore(self.config(mode=resolved_mode), provider, lab=self, turn_id=turn_id)

    def curation_policy(self, layout: WorkspaceLayout) -> CurationPolicy:
        """The Lab's curation flags as a policy for ``layout`` (per-target flags, D5)."""
        policy = CurationPolicy.for_layout(
            layout,
            max_file_chars=self.settings.max_chars,
            total_max_chars=self.settings.total_max_chars,
        )
        disabled = [
            operation
            for flag, operations in _TARGET_FLAGS.items()
            if not self.settings.flags.get(flag, True)
            for operation in operations
        ]
        return policy.without(*disabled) if disabled else policy

    def kit(
        self,
        store: LabStore | None = None,
        *,
        layout: str | None = None,
        max_chars: int | None = None,
        total_max_chars: int | None = None,
        context_injection: str | None = None,
    ) -> HostKit:
        """The host kit over the Lab workspace with the Lab's settings (built per request).

        ``store`` is the turn's index (default: the FTS-only one, for calls that do not
        search); the other arguments are the prompt inspector's per-request overrides.
        """
        store = store or LabStore(self.config(), None, lab=self)
        resolved_layout = self.layout_for(layout)
        settings = self.settings
        return HostKit(
            Memory(config=store.config, workspace=MemoryWorkspace(self.root), store=store),
            layout=resolved_layout,
            templates=DEMO_WORKSPACE_TEMPLATES,
            seed_bootstrap=True,
            timezone=LAB_TIMEZONE,
            time_format=LAB_TIME_FORMAT,
            curation_policy=self.curation_policy(resolved_layout),
            bootstrap_max_chars=max_chars or settings.max_chars,
            bootstrap_total_max_chars=total_max_chars or settings.total_max_chars,
            context_injection=context_injection or settings.context_injection,  # type: ignore[arg-type]
            truncation_warning_mode=settings.warning_mode,  # type: ignore[arg-type]
            # The Lab shows promotion and dreaming, so memory_search records recalls like
            # upstream with dreaming enabled (tools.ts:491-507).
            dreaming_enabled=True,
            # One host clock: the flush target, the reset prompt and the curator's day are the
            # Lab's (the heartbeat's virtual clock only moves due checks, schedule_now_ms).
            now_ms=lambda: self.now_ms(),
        )

    def reindex(self, store: LabStore) -> dict[str, Any]:
        store.reindex(MemoryWorkspace(self.root))
        return store.last_reindex

    def record_reindex(self, store: LabStore, files: int, *, ms: int) -> dict[str, Any]:
        """Index bookkeeping after ``store`` reindexed ``files`` files in ``ms`` ms."""
        chunks = store.count_chunks()
        self.index_status = {
            "files": files,
            "chunks": chunks,
            "lastReindexAt": self.now_ms(),
            "store": store.path.name,
            "ms": ms,
        }
        self._index_revisions[str(store.path)] = self.memory_revision()
        self.bus.emit(
            "index.reindexed",
            summary=f"{files} dosya · {chunks} parça · {ms} ms",
            data={"files": files, "chunks": chunks, "ms": ms, "store": store.path.name},
            turn_id=store.turn_id,
        )
        return {"indexedFiles": files, "chunks": chunks, "ms": ms}

    def memory_revision(self) -> str:
        workspace = MemoryWorkspace(self.root)
        parts = []
        for file in workspace.discover_indexable_files():
            try:
                info = file.abs_path.stat()
            except OSError:
                continue
            parts.append(f"{file.rel_path}:{info.st_size}:{info.st_mtime_ns}")
        return "|".join(sorted(parts))

    def index_is_stale(self, store: SQLiteMemoryStore) -> bool:
        return self._index_revisions.get(str(store.path)) != self.memory_revision()

    # workspace lifecycle

    @contextmanager
    def tracked(self, source: str, *, turn_id: int | None = None) -> Iterator[list[dict[str, Any]]]:
        """Snapshot before and after the block; emit ``file.changed`` per difference."""
        before = self.snapshots.take()
        changes: list[dict[str, Any]] = []
        try:
            yield changes
        finally:
            changes.extend(
                self.snapshots.record(before, self.snapshots.take(), source=source, turn_id=turn_id)
            )

    @contextmanager
    def lifecycle(
        self, source: str = "lifecycle", *, turn_id: int | None = None
    ) -> Iterator[Callable[[WorkspaceInitResult], None]]:
        """Track a block that runs the kit's ensure (``HostKit.ensure``, ``on_new_session``,
        ``heartbeat_prompt``); the yielded callable emits the ``bootstrap.*`` events of its result.
        """
        with self._ensure_lock:
            layout = self.layout
            before_status = bootstrap_status(self.root, layout) if self.root.is_dir() else None

            def report(result: WorkspaceInitResult) -> None:
                if result.bootstrap_seeded:
                    self.bus.emit(
                        "bootstrap.seeded",
                        summary=f"{layout.bootstrap_file} yazıldı (bootstrap bekliyor)",
                        data={"file": layout.bootstrap_file, "created": list(result.created_files)},
                        turn_id=turn_id,
                    )
                if before_status == "pending" and result.bootstrap_status == "complete":
                    self.bus.emit(
                        "bootstrap.completed",
                        summary="bootstrap tamamlandı",
                        data={
                            "setupCompletedAt": result.state.setup_completed_at,
                            "bootstrapRemoved": result.bootstrap_removed,
                        },
                        turn_id=turn_id,
                    )
                if result.bootstrap_removed:
                    self.bus.emit(
                        "bootstrap.file_deleted",
                        summary=f"{layout.bootstrap_file} silindi (yaşam döngüsü)",
                        data={"path": layout.bootstrap_file, "source": "lifecycle"},
                        turn_id=turn_id,
                    )

            with self.tracked(source, turn_id=turn_id):
                yield report

    def ensure(self, *, turn_id: int | None = None) -> WorkspaceInitResult:
        """``HostKit.ensure`` with the Lab templates (upstream runs it every reply)."""
        with self.lifecycle(turn_id=turn_id) as report:
            result = self.kit().ensure()
            report(result)
        return result

    def reset_workspace(self, mode: str, *, keep_memory: bool = False) -> None:
        """``seeded``: Lab templates plus an empty ``memory/`` (setup complete, no invented text).

        ``fresh``: an empty directory and the Lab templates, so the package seeds
        BOOTSTRAP.md and the ritual is pending. ``keep_memory`` keeps MEMORY.md and
        ``memory/`` (they count as setup evidence, so BOOTSTRAP.md is not seeded).
        """
        if mode not in {"seeded", "fresh"}:
            raise LabError(400, "mode must be 'seeded' or 'fresh'", code="invalid_mode")
        with self.tracked("reset"):
            kept: dict[str, bytes] = {}
            if keep_memory and self.root.is_dir():
                kept = _collect_memory_files(self.root, self.layout)
            if self.root.exists():
                shutil.rmtree(self.root)
            self.root.mkdir(parents=True, exist_ok=True)
            for rel_path, data in kept.items():
                target = self.root / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if mode == "seeded":
                (self.root / "memory").mkdir(exist_ok=True)
            result = self.kit().ensure()
        self.sessions.clear()
        self.turns.clear()
        self.turn_order.clear()
        self.curated_writes.clear()
        self.heartbeat_runs.clear()
        self.consolidation_results.clear()
        self._index_revisions.clear()
        self.index_status = {"files": 0, "chunks": 0, "lastReindexAt": None}
        self.snapshots.reset()
        self.snapshots.set_baseline("reset")
        self.bus.emit(
            "workspace.reset",
            summary=f"çalışma alanı sıfırlandı ({mode}{', bellek korundu' if keep_memory else ''})",
            data={"mode": mode, "keepMemory": keep_memory, "root": str(self.root)},
        )
        self.bus.emit(
            "bootstrap.seeded" if result.bootstrap_seeded else "bootstrap.completed",
            summary=(
                "BOOTSTRAP.md yazıldı (bootstrap bekliyor)"
                if result.bootstrap_seeded
                else "kurulum tamam (bootstrap yok)"
            ),
            data={
                "status": result.bootstrap_status,
                "created": list(result.created_files),
                "createdDirs": list(result.created_dirs),
            },
        )

    def ensure_exists(self) -> None:
        if not self.root.is_dir():
            self.reset_workspace("seeded")

    def migrate_tools_md(self) -> dict[str, Any]:
        """``memory_core.bootstrap.migrate_tools_md`` on the Lab workspace (upstream doctor step).

        v2026.9.6 no longer loads TOOLS.md; this archives it under
        ``.memory-core/backups/tools-md-migration/`` and merges customised notes into AGENTS.md
        ``## Tools``. File changes go through the Lab's snapshot tracking like any write.
        """
        with self.tracked("tools_md_migration"):
            result = migrate_tools_md(self.root)
        payload = {
            "changes": list(result.changes),
            "warnings": list(result.warnings),
            "archivePath": _relative_to_root(self.root, result.archive_path),
            "merged": result.merged,
        }
        if result.changes:
            summary = (
                "TOOLS.md AGENTS.md ## Tools bölümüne taşındı, özgün dosya arşivlendi"
                if result.merged
                else "dokunulmamış TOOLS.md arşivlendi ve kaldırıldı"
            )
        elif result.warnings:
            summary = "TOOLS.md taşınamadı: " + result.warnings[0]
        else:
            summary = "TOOLS.md yok: taşınacak bir şey yok"
        self.bus.emit("workspace.tools_md_migrated", summary=summary, data=payload)
        return payload

    # sessions and turns

    def session(self, kind: str) -> LabSession:
        if kind not in SESSION_KINDS:
            raise LabError(400, f"sessionKind must be one of {', '.join(SESSION_KINDS)}", code="invalid_kind")
        session = self.sessions.get(kind)
        if session is None:
            session = new_session(kind)
            self.sessions[kind] = session
        return session

    def replace_session(self, kind: str, state: SessionState) -> LabSession:
        """The kind's next session after ``/new`` or ``/reset`` (``NewSession.session``)."""
        session = LabSession(kind=kind, created_at=now_ms(), state=state)
        self.sessions[kind] = session
        self.snapshots.set_baseline("session")
        return session

    def allocate_turn_id(self) -> int:
        turn_id = self._next_turn_id
        self._next_turn_id += 1
        return turn_id

    def store_turn(self, detail: dict[str, Any]) -> None:
        turn_id = int(detail["id"])
        if turn_id not in self.turns:
            self.turn_order.append(turn_id)
        self.turns[turn_id] = detail

    def turn_summaries(self) -> list[dict[str, Any]]:
        return [summarize_turn(self.turns[turn_id]) for turn_id in self.turn_order]

    def allocate_write_id(self) -> str:
        write_id = f"cw{self._next_write_id}"
        self._next_write_id += 1
        return write_id

    def allocate_heartbeat_run_id(self) -> int:
        run_id = self._next_heartbeat_run_id
        self._next_heartbeat_run_id += 1
        return run_id

    # file guards

    def resolve_path(self, rel_path: Any, *, must_exist: bool = True) -> tuple[str, Path]:
        """Validate a workspace-relative path: no ``..``, no absolute paths, no symlinks."""
        if not isinstance(rel_path, str) or not rel_path.strip():
            raise LabError(400, "path is required", code="invalid_path")
        if len(rel_path) > 512 or "\0" in rel_path or "\\" in rel_path:
            raise LabError(400, "path contains forbidden characters", code="invalid_path")
        if rel_path.startswith("/") or re.match(r"^[A-Za-z]:", rel_path):
            raise LabError(400, "path must be relative to the workspace root", code="outside_root")
        parts = rel_path.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise LabError(400, "path must not contain empty, '.' or '..' segments", code="outside_root")
        root_real = self.root.resolve()
        current = self.root
        for part in parts:
            current = current / part
            if os.path.islink(current):
                raise LabError(400, f"{rel_path} goes through a symlink", code="symlink")
        target = self.root.joinpath(*parts)
        try:
            resolved = target.resolve()
        except OSError as exc:
            raise LabError(400, f"path cannot be resolved: {exc}", code="invalid_path") from exc
        if resolved != root_real and root_real not in resolved.parents:
            raise LabError(400, "path resolves outside the workspace root", code="outside_root")
        if must_exist:
            if not target.exists():
                raise LabError(404, f"{rel_path} does not exist", code="not_found")
            if not target.is_file():
                raise LabError(400, f"{rel_path} is not a regular file", code="not_a_file")
        return "/".join(parts), target

    def writable(self, rel_path: str, *, enforce_flag: bool = True) -> tuple[bool, str | None]:
        parts = rel_path.split("/")
        layout = self.layout
        if enforce_flag and not self.settings.flags.get("lab_file_editing", True):
            return False, "Lab dosya düzenleme kapalı (lab_file_editing)"
        if any(part.startswith(".") for part in parts):
            return False, "gizli dizin (salt-okunur)"
        if len(parts) == 1:
            if parts[0] in layout.load_order:
                return True, None
            return False, "etkin düzenin dosyası değil"
        if parts[0] == "memory":
            if parts[-1].endswith(".md"):
                return True, None
            return False, "memory/ altında yalnız .md dosyaları yazılır"
        if parts[0] in layout.extra_dirs:
            return True, None
        return False, "yazılabilir alan dışında"

    def read_file(self, rel_path: Any) -> dict[str, Any]:
        path, target = self.resolve_path(rel_path)
        info = target.stat()
        if info.st_size > FILE_MAX_BYTES:
            raise LabError(400, f"{path} is larger than 2 MiB", code="too_large")
        raw = target.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LabError(400, f"{path} is not valid UTF-8", code="not_utf8") from exc
        writable, reason = self.writable(path)
        payload: dict[str, Any] = {
            "path": path,
            "content": content,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "chars": _utf16_len(content),
            "bytes": len(raw),
            "mtimeMs": info.st_mtime_ns // 1_000_000,
            "writable": writable,
        }
        if reason:
            payload["readOnlyReason"] = reason
        return payload

    def write_file(
        self,
        rel_path: Any,
        content: Any,
        base_sha256: Any,
        *,
        source: str = "editor",
        turn_id: int | None = None,
        delete: bool = False,
        enforce_flag: bool = True,
    ) -> dict[str, Any]:
        """Guarded editor write: 409 when ``baseSha256`` no longer matches the disk."""
        if not delete and not isinstance(content, str):
            raise LabError(400, "content must be a string", code="invalid_content")
        if not delete and len(content.encode("utf-8")) > FILE_MAX_BYTES:
            raise LabError(400, "content is larger than 2 MiB", code="too_large")
        path, target = self.resolve_path(rel_path, must_exist=False)
        writable, reason = self.writable(path, enforce_flag=enforce_flag)
        if not writable:
            raise LabError(403, f"{path} is read-only: {reason}", code="read_only")
        if target.exists() and not target.is_file():
            raise LabError(400, f"{path} is not a regular file", code="not_a_file")
        current_raw = target.read_bytes() if target.is_file() else None
        current_sha = hashlib.sha256(current_raw).hexdigest() if current_raw is not None else None
        base = optional_text(base_sha256)
        if base != current_sha:
            current: dict[str, Any] | None = None
            if current_raw is not None:
                current = {
                    "sha256": current_sha,
                    "content": current_raw.decode("utf-8", errors="replace"),
                }
            raise LabError(
                409,
                f"{path} changed on disk since it was read",
                code="conflict",
                current=current,
            )
        first_event = self.bus.last_id
        with self.tracked(source, turn_id=turn_id) as changes:
            if delete:
                if target.is_file():
                    target.unlink()
            else:
                _atomic_write(self.root, target, content)
        if delete:
            self.bus.emit(
                "file.saved",
                summary=f"{path} silindi ({source})",
                data={"path": path, "deleted": True, "source": source},
                turn_id=turn_id,
            )
        else:
            data = target.read_bytes()
            self.bus.emit(
                "file.saved",
                summary=f"{path} kaydedildi ({source})",
                data={
                    "path": path,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "chars": _utf16_len(content),
                    "bytes": len(data),
                    "source": source,
                },
                turn_id=turn_id,
            )
        self.ensure(turn_id=turn_id)
        sha = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
        diff = next((change["diff"] for change in changes if change["path"] == path), "")
        events, _ = self.bus.since(first_event)
        return {"path": path, "sha256": sha, "diff": diff, "events": events}

    # snapshots for diffs

    def diff_since(self, since: str) -> list[dict[str, Any]]:
        baseline, since_ts = self.baseline_for(since)
        current = self.snapshots.take()
        changes = diff_snapshots(baseline, current)
        for change in changes:
            change["sources"] = self.snapshots.sources_since(change["path"], since_ts)
        return changes

    def baseline_for(self, since: str) -> tuple[Snapshot, int | None]:
        if not isinstance(since, str) or not since:
            raise LabError(400, "since is required", code="invalid_since")
        if since.startswith("turn:"):
            turn_id = since.removeprefix("turn:")
            if not turn_id.isdigit():
                raise LabError(400, "since=turn:<id> needs a numeric id", code="invalid_since")
            name = f"turn:{int(turn_id)}"
        elif since.startswith("mark:"):
            validate_id(since.removeprefix("mark:"), "mark id")
            name = since
        elif since in {"session", "reset"}:
            name = since
        else:
            raise LabError(400, "since must be turn:<id>, session, reset or mark:<id>", code="invalid_since")
        baseline = self.snapshots.baseline(name)
        if baseline is None:
            raise LabError(404, f"no baseline named {name}", code="no_baseline")
        return baseline, self.snapshots.baseline_times.get(name)

    # small readers

    def identity_name(self) -> str | None:
        path = self.root / "IDENTITY.md"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        match = _IDENTITY_NAME_RE.search(text)
        return match.group(1).strip() if match else None

    def setup_state(self) -> dict[str, Any]:
        state = read_workspace_setup_state(self.root)
        return {
            "bootstrapSeededAt": state.bootstrap_seeded_at,
            "setupCompletedAt": state.setup_completed_at,
        }


_IDENTITY_NAME_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:\*\*)?Name(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def summarize_turn(detail: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "sessionId", "sessionKey", "sessionKind", "startedAt", "ms", "user", "assistant",
        "engine", "chips", "failedStage", "reset", "error", "toolCalls",
    )
    return {key: detail[key] for key in keys if key in detail}


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise LabError(400, f"{key} must be an object", code="invalid_payload")
    return value


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _atomic_write(root: Path, target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.path.islink(target.parent):
        raise LabError(400, "parent directory is a symlink", code="symlink")
    tmp = target.parent / f".{target.name}.lab-{secrets.token_hex(4)}.tmp"
    try:
        with open(tmp, "x", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    del root


def _collect_memory_files(root: Path, layout: WorkspaceLayout) -> dict[str, bytes]:
    kept: dict[str, bytes] = {}
    memory_md = root / layout.memory_file
    if memory_md.is_file() and not memory_md.is_symlink():
        kept[layout.memory_file] = memory_md.read_bytes()
    memory_dir = root / "memory"
    if memory_dir.is_dir() and not memory_dir.is_symlink():
        for path in memory_dir.rglob("*"):
            if path.is_file() and not path.is_symlink():
                kept[path.relative_to(root).as_posix()] = path.read_bytes()
    return kept
