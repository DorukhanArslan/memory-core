# OpenClaw Memory Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port OpenClaw memory behavior into the Python demo while keeping the FastAPI/web UI shell.

**Architecture:** Keep `memory_core/` as the reusable memory/index/tool package and `demo/` as the observable chat lab. Add focused Python ports for short-term promotion artifacts and dreaming sweeps, then expose them through FastAPI endpoints and UI panels. Keep tests parity-focused and source-backed: file paths, gates, locks, phase signals, corpus behavior, and reset behavior must be observable.

**Tech Stack:** Python 3.12, FastAPI, SQLite FTS/vector store, pytest, ruff, browser-facing HTML/CSS/vanilla JS.

---

## File Structure

- Modify `demo/short_term_promotion.py`: add OpenClaw phase signals, score components, promotion lock, audit, repair, and richer candidate output.
- Create `demo/dreaming.py`: deterministic manual light/REM/deep dreaming sweeps over the short-term store and `DREAMS.md`.
- Modify `demo/app.py`: wire dreaming/audit endpoints, global reset cleanup, state serialization, and reindex behavior.
- Modify `demo/templates/index.html`: add Dreaming sweep, Audit, Repair controls and expandable details.
- Modify `demo/static/styles.css`: style dreaming/audit panels without changing the full-screen layout.
- Modify `memory_core/workspace.py`: ensure `.dreams` session corpus discovery and reset-safe path behavior remain correct.
- Modify `tests/demo/test_demo_app.py`: endpoint, reset, UI, and integration tests.
- Create `tests/demo/test_short_term_promotion_parity.py`: pure promotion parity tests.
- Create `tests/demo/test_dreaming_parity.py`: pure dreaming sweep tests.
- Modify `tests/integration/test_memory_tools.py`: corpus behavior tests if needed.

## Task 1: Short-Term Promotion Artifacts And Lock

**Files:**
- Modify: `demo/short_term_promotion.py`
- Test: `tests/demo/test_short_term_promotion_parity.py`

- [ ] **Step 1: Write failing tests for lock and artifact constants**

Create `tests/demo/test_short_term_promotion_parity.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from demo.short_term_promotion import (
    SHORT_TERM_LOCK_RELATIVE_PATH,
    SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH,
    acquire_short_term_promotion_lock,
    audit_short_term_promotion_artifacts,
)
from memory_core.config import MemoryConfig


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_lock_constants_match_openclaw_paths():
    assert SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH.as_posix() == "memory/.dreams/phase-signals.json"
    assert SHORT_TERM_LOCK_RELATIVE_PATH.as_posix() == "memory/.dreams/short-term-promotion.lock"


def test_active_short_term_lock_blocks_second_owner(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))

    with acquire_short_term_promotion_lock(config=config, now_ms=now) as first:
        assert first.acquired is True
        second = acquire_short_term_promotion_lock(config=config, now_ms=now)
        with second as blocked:
            assert blocked.acquired is False
            assert blocked.reason == "locked"


def test_stale_short_term_lock_is_repaired(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    lock_path = tmp_path / SHORT_TERM_LOCK_RELATIVE_PATH
    lock_path.parent.mkdir(parents=True)
    stale_time = datetime(2026, 5, 8, 12, 0, tzinfo=UTC) - timedelta(minutes=5)
    lock_path.write_text('{"pid": 999999, "createdAt": "old"}\n', encoding="utf-8")
    old_seconds = stale_time.timestamp()
    lock_path.touch(times=(old_seconds, old_seconds))

    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    with acquire_short_term_promotion_lock(config=config, now_ms=now) as lock:
        assert lock.acquired is True
        assert lock.stole_stale is True


def test_audit_reports_unreadable_recall_store(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    store_path = tmp_path / "memory" / ".dreams" / "short-term-recall.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_text("{not-json", encoding="utf-8")

    audit = audit_short_term_promotion_artifacts(config=config, now_ms=ms(datetime(2026, 5, 8, tzinfo=UTC)))

    assert audit.exists is True
    assert audit.invalid_entry_count == 0
    assert audit.issues[0].code == "recall-store-unreadable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/demo/test_short_term_promotion_parity.py -v
```

Expected: FAIL because lock/audit names are not defined.

- [ ] **Step 3: Implement constants, lock result, context manager, and audit shell**

In `demo/short_term_promotion.py`, add imports and definitions near the existing constants:

```python
import os
import time
from contextlib import contextmanager

SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH = Path("memory") / ".dreams" / "phase-signals.json"
SHORT_TERM_LOCK_RELATIVE_PATH = Path("memory") / ".dreams" / "short-term-promotion.lock"
SHORT_TERM_LOCK_STALE_MS = 60_000


@dataclass(frozen=True)
class ShortTermLockResult:
    acquired: bool
    path: str
    reason: str | None = None
    stole_stale: bool = False


@dataclass(frozen=True)
class ShortTermAuditIssue:
    severity: str
    code: str
    message: str
    fixable: bool


@dataclass(frozen=True)
class ShortTermAuditSummary:
    store_path: str
    lock_path: str
    updated_at: str | None
    exists: bool
    entry_count: int
    promoted_count: int
    spaced_entry_count: int
    concept_tagged_entry_count: int
    invalid_entry_count: int
    issues: list[ShortTermAuditIssue]
```

Add these functions below helper constants:

```python
@contextmanager
def acquire_short_term_promotion_lock(*, config: MemoryConfig, now_ms: int):
    lock_path = config.workspace_dir / SHORT_TERM_LOCK_RELATIVE_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stole_stale = False
    try:
        handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if _lock_is_stale(lock_path, now_ms):
            lock_path.unlink(missing_ok=True)
            stole_stale = True
            handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        else:
            yield ShortTermLockResult(
                acquired=False,
                path=lock_path.as_posix(),
                reason="locked",
            )
            return
    with os.fdopen(handle, "w", encoding="utf-8") as file:
        file.write(json.dumps({"pid": os.getpid(), "createdAt": _iso(now_ms)}) + "\n")
    try:
        yield ShortTermLockResult(
            acquired=True,
            path=lock_path.as_posix(),
            stole_stale=stole_stale,
        )
    finally:
        lock_path.unlink(missing_ok=True)


def _lock_is_stale(lock_path: Path, now_ms: int) -> bool:
    try:
        age_ms = now_ms - int(lock_path.stat().st_mtime * 1000)
    except OSError:
        return False
    return age_ms > SHORT_TERM_LOCK_STALE_MS


def audit_short_term_promotion_artifacts(
    *,
    config: MemoryConfig,
    now_ms: int,
) -> ShortTermAuditSummary:
    del now_ms
    store_path = config.workspace_dir / SHORT_TERM_STORE_RELATIVE_PATH
    lock_path = config.workspace_dir / SHORT_TERM_LOCK_RELATIVE_PATH
    issues: list[ShortTermAuditIssue] = []
    exists = store_path.exists()
    updated_at = None
    entry_count = 0
    promoted_count = 0
    spaced_entry_count = 0
    concept_tagged_entry_count = 0
    invalid_entry_count = 0
    if exists:
        try:
            raw = json.loads(store_path.read_text(encoding="utf-8"))
            entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
            updated_at = str(raw.get("updatedAt") or "") if isinstance(raw, dict) else None
            for entry in entries.values():
                if not isinstance(entry, dict):
                    invalid_entry_count += 1
                    continue
                entry_count += 1
                if entry.get("promotedAt"):
                    promoted_count += 1
                if len(entry.get("recallDays") or []) >= 2:
                    spaced_entry_count += 1
                if entry.get("conceptTags"):
                    concept_tagged_entry_count += 1
        except Exception:
            issues.append(
                ShortTermAuditIssue(
                    severity="error",
                    code="recall-store-unreadable",
                    message="Short-term recall store could not be read.",
                    fixable=True,
                )
            )
    return ShortTermAuditSummary(
        store_path=store_path.as_posix(),
        lock_path=lock_path.as_posix(),
        updated_at=updated_at,
        exists=exists,
        entry_count=entry_count,
        promoted_count=promoted_count,
        spaced_entry_count=spaced_entry_count,
        concept_tagged_entry_count=concept_tagged_entry_count,
        invalid_entry_count=invalid_entry_count,
        issues=issues,
    )
```

- [ ] **Step 4: Run task tests**

Run:

```bash
pytest tests/demo/test_short_term_promotion_parity.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add demo/short_term_promotion.py tests/demo/test_short_term_promotion_parity.py
git commit -m "feat: add short-term promotion lock audit"
```

## Task 2: Phase Signals And Score Components

**Files:**
- Modify: `demo/short_term_promotion.py`
- Test: `tests/demo/test_short_term_promotion_parity.py`

- [ ] **Step 1: Add failing tests for phase signals and components**

Append to `tests/demo/test_short_term_promotion_parity.py`:

```python
from demo.short_term_promotion import (
    record_short_term_phase_signals,
    rank_short_term_promotion_candidates,
    record_short_term_recalls,
)


def test_phase_signals_are_recorded_and_decay_old_keys(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    changed = record_short_term_phase_signals(
        config=config,
        keys=["memory:memory/2026-05-08.md:2:2:abc"],
        phase="light",
        now_ms=now,
    )

    phase_path = tmp_path / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH
    raw = phase_path.read_text(encoding="utf-8")

    assert changed == 1
    assert '"lightHits": 1' in raw
    assert '"remHits": 0' in raw


def test_candidate_output_includes_score_components_and_phase_boost(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    daily = tmp_path / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("# 2026-05-08\n\n- User prefers lowercase answers.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- User prefers lowercase answers.",
        "score": 0.9,
    }
    for query in ("lowercase", "answer case", "writing style"):
        record_short_term_recalls(config=config, query=query, results=[result], now_ms=now)

    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=5,
        min_score=0,
        min_recall_count=1,
        min_unique_queries=1,
    )
    record_short_term_phase_signals(
        config=config,
        keys=[candidates[0].key],
        phase="rem",
        now_ms=now,
    )
    boosted = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now,
        limit=5,
        min_score=0,
        min_recall_count=1,
        min_unique_queries=1,
    )

    assert boosted[0].components["frequency"] > 0
    assert boosted[0].components["phaseBoost"] > 0
    assert boosted[0].score >= candidates[0].score
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/demo/test_short_term_promotion_parity.py -v
```

Expected: FAIL because phase signal recording and `components` are missing.

- [ ] **Step 3: Add phase signal dataclasses and scoring components**

Modify `PromotionCandidate` and `PromotionEvaluation` in `demo/short_term_promotion.py` to include:

```python
    age_days: float = 0.0
    concept_tags: tuple[str, ...] = ()
    components: dict[str, float] = None
```

Use `field(default_factory=dict)` if dataclasses complain about mutable defaults:

```python
from dataclasses import dataclass, field
```

and:

```python
    components: dict[str, float] = field(default_factory=dict)
```

Add phase signal functions:

```python
def record_short_term_phase_signals(
    *,
    config: MemoryConfig,
    keys: list[str],
    phase: str,
    now_ms: int,
) -> int:
    if phase not in {"light", "rem"}:
        raise ValueError(f"unsupported dreaming phase: {phase}")
    path = config.workspace_dir / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH
    store = _read_phase_signal_store(path, now_ms)
    now_iso = _iso(now_ms)
    changed = 0
    for key in keys:
        entry = store["entries"].get(key) or {"key": key, "lightHits": 0, "remHits": 0}
        if phase == "light":
            entry["lightHits"] = _int(entry.get("lightHits"), 0) + 1
            entry["lastLightAt"] = now_iso
        else:
            entry["remHits"] = _int(entry.get("remHits"), 0) + 1
            entry["lastRemAt"] = now_iso
        store["entries"][key] = entry
        changed += 1
    store["updatedAt"] = now_iso
    if changed:
        _write_json_atomic(path, store)
    return changed


def _read_phase_signal_store(path: Path, now_ms: int) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updatedAt": _iso(now_ms), "entries": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "updatedAt": _iso(now_ms), "entries": {}}
    entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
    return {"version": 1, "updatedAt": str(raw.get("updatedAt") or _iso(now_ms)), "entries": entries}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
```

In `evaluate_short_term_promotion_candidates`, load `phaseSignals` and compute:

```python
phase_signals = _read_phase_signal_store(
    config.workspace_dir / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH,
    now_ms,
)
components = _candidate_components(entry, now_ms, phase_signals.get("entries", {}))
score = _clamp(sum(components.values()))
```

Add:

```python
def _candidate_components(
    entry: dict[str, Any],
    now_ms: int,
    phase_entries: dict[str, Any],
) -> dict[str, float]:
    recall_count = _int(entry.get("recallCount"), 0)
    daily_count = _int(entry.get("dailyCount"), 0)
    grounded_count = _int(entry.get("groundedCount"), 0)
    total_signals = recall_count + daily_count + grounded_count
    avg_score = float(entry.get("totalScore") or 0) / max(1, recall_count + daily_count)
    recall_days = len(entry.get("recallDays") or [])
    unique_queries = len(entry.get("queryHashes") or [])
    recency = _recency_score(str(entry.get("lastRecalledAt") or ""), now_ms)
    phase_boost = _phase_signal_boost(phase_entries.get(str(entry.get("key") or "")), now_ms)
    return {
        "frequency": min(1, total_signals / 6) * 0.24,
        "relevance": _clamp(avg_score) * 0.30,
        "diversity": min(1, max(recall_days, unique_queries) / 4) * 0.15,
        "recency": recency * 0.15,
        "consolidation": min(1, daily_count / 2) * 0.10,
        "conceptual": min(1, len(entry.get("conceptTags") or []) / 4) * 0.06,
        "phaseBoost": phase_boost,
    }


def _phase_signal_boost(entry: dict[str, Any] | None, now_ms: int) -> float:
    if not entry:
        return 0.0
    light_hits = _int(entry.get("lightHits"), 0)
    rem_hits = _int(entry.get("remHits"), 0)
    light = min(0.06, light_hits * 0.02)
    rem = min(0.09, rem_hits * 0.03)
    del now_ms
    return light + rem
```

- [ ] **Step 4: Run task tests**

Run:

```bash
pytest tests/demo/test_short_term_promotion_parity.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add demo/short_term_promotion.py tests/demo/test_short_term_promotion_parity.py
git commit -m "feat: add promotion phase signals"
```

## Task 3: Promotion Apply Uses Lock, Markers, Audit, Repair

**Files:**
- Modify: `demo/short_term_promotion.py`
- Test: `tests/demo/test_short_term_promotion_parity.py`

- [ ] **Step 1: Add failing tests for locked apply and repair**

Append:

```python
from demo.short_term_promotion import (
    repair_short_term_promotion_artifacts,
    run_short_term_promotion,
)
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore


def fake_store(config: MemoryConfig):
    return SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8))


def test_promotion_run_returns_locked_result_when_lock_is_active(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    (tmp_path / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))

    with acquire_short_term_promotion_lock(config=config, now_ms=now):
        run = run_short_term_promotion(
            config=config,
            store=fake_store(config),
            now_ms=now,
            timezone="Europe/Istanbul",
        )

    assert run.parsed.should_write is False
    assert run.parsed.reason == "promotion locked"


def test_repair_removes_invalid_entries_and_stale_lock(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    dreams = tmp_path / "memory" / ".dreams"
    dreams.mkdir(parents=True)
    (dreams / "short-term-recall.json").write_text(
        '{"version": 1, "updatedAt": "2026-05-08T00:00:00Z", "entries": {"bad": null}}\n',
        encoding="utf-8",
    )
    lock = dreams / "short-term-promotion.lock"
    lock.write_text('{"pid": 999999}\n', encoding="utf-8")
    old = datetime(2026, 5, 8, 11, 55, tzinfo=UTC).timestamp()
    lock.touch(times=(old, old))

    result = repair_short_term_promotion_artifacts(
        config=config,
        now_ms=ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC)),
    )

    assert result["removedInvalidEntries"] == 1
    assert result["removedStaleLock"] is True
    assert not lock.exists()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/demo/test_short_term_promotion_parity.py -v
```

Expected: FAIL for missing repair and locked promotion behavior.

- [ ] **Step 3: Wrap promotion apply in lock and add repair**

In `run_short_term_promotion`, wrap the body:

```python
    with acquire_short_term_promotion_lock(config=config, now_ms=now_ms) as lock:
        if not lock.acquired:
            return MemoryPromotionRun(
                target="MEMORY.md",
                raw_text="short-term promotion skipped: locked",
                parsed=ParsedFlushOutput(
                    should_write=False,
                    target="MEMORY.md",
                    entry="",
                    reason="promotion locked",
                ),
                diff="",
                indexed_files=0,
                chunks=store.count_chunks(),
                evaluated_candidates=[],
                reindex_error=None,
            )
        return _run_short_term_promotion_unlocked(
            config=config,
            store=store,
            now_ms=now_ms,
            timezone=timezone,
            limit=limit,
            min_score=min_score,
            min_recall_count=min_recall_count,
            min_unique_queries=min_unique_queries,
        )
```

Move the existing body into `_run_short_term_promotion_unlocked(...)`.

Add repair:

```python
def repair_short_term_promotion_artifacts(
    *,
    config: MemoryConfig,
    now_ms: int,
) -> dict[str, Any]:
    store_path = config.workspace_dir / SHORT_TERM_STORE_RELATIVE_PATH
    removed_invalid = 0
    rewrote_store = False
    if store_path.exists():
        try:
            store = json.loads(store_path.read_text(encoding="utf-8"))
            entries = store.get("entries", {})
            for key in list(entries.keys()):
                if not isinstance(entries.get(key), dict):
                    del entries[key]
                    removed_invalid += 1
            if removed_invalid:
                store["updatedAt"] = _iso(now_ms)
                _write_json_atomic(store_path, store)
                rewrote_store = True
        except Exception:
            _write_json_atomic(store_path, {"version": 1, "updatedAt": _iso(now_ms), "entries": {}})
            rewrote_store = True
    lock_path = config.workspace_dir / SHORT_TERM_LOCK_RELATIVE_PATH
    removed_stale_lock = False
    if lock_path.exists() and _lock_is_stale(lock_path, now_ms):
        lock_path.unlink(missing_ok=True)
        removed_stale_lock = True
    return {
        "changed": rewrote_store or removed_stale_lock,
        "removedInvalidEntries": removed_invalid,
        "rewroteStore": rewrote_store,
        "removedStaleLock": removed_stale_lock,
    }
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/demo/test_short_term_promotion_parity.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add demo/short_term_promotion.py tests/demo/test_short_term_promotion_parity.py
git commit -m "feat: apply promotion lock and repair"
```

## Task 4: Dreaming Sweeps

**Files:**
- Create: `demo/dreaming.py`
- Test: `tests/demo/test_dreaming_parity.py`

- [ ] **Step 1: Write failing dreaming tests**

Create `tests/demo/test_dreaming_parity.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from demo.dreaming import run_dreaming_sweep
from demo.short_term_promotion import (
    SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH,
    record_short_term_recalls,
)
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fake_store(config: MemoryConfig):
    return SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8))


def seed_candidate(config: MemoryConfig, now_ms: int):
    daily = config.workspace_dir / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("# 2026-05-08\n\n- User prefers lowercase answers.\n", encoding="utf-8")
    result = {
        "path": "memory/2026-05-08.md",
        "startLine": 3,
        "endLine": 3,
        "snippet": "- User prefers lowercase answers.",
        "score": 0.9,
    }
    for query in ("lowercase", "answer case", "writing style"):
        record_short_term_recalls(config=config, query=query, results=[result], now_ms=now_ms)


def test_light_dreaming_records_phase_signal(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    seed_candidate(config, now)

    run = run_dreaming_sweep(
        config=config,
        store=fake_store(config),
        phase="light",
        now_ms=now,
        timezone="Europe/Istanbul",
    )

    assert run["phase"] == "light"
    assert run["phaseSignalsRecorded"] == 1
    assert (tmp_path / SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH).exists()


def test_rem_dreaming_writes_dreams_md(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    seed_candidate(config, now)

    run = run_dreaming_sweep(
        config=config,
        store=fake_store(config),
        phase="rem",
        now_ms=now,
        timezone="Europe/Istanbul",
    )

    dreams = tmp_path / "DREAMS.md"
    assert run["phase"] == "rem"
    assert dreams.exists()
    assert "Dreaming sweep" in dreams.read_text(encoding="utf-8")


def test_deep_dreaming_runs_promotion(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    (tmp_path / "MEMORY.md").write_text("# MEMORY.md\n", encoding="utf-8")
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    seed_candidate(config, now)

    run = run_dreaming_sweep(
        config=config,
        store=fake_store(config),
        phase="deep",
        now_ms=now,
        timezone="Europe/Istanbul",
    )

    assert run["phase"] == "deep"
    assert run["promotion"]["parsed"]["shouldWrite"] is True
    assert "lowercase answers" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/demo/test_dreaming_parity.py -v
```

Expected: FAIL because `demo.dreaming` does not exist.

- [ ] **Step 3: Implement deterministic dreaming sweep**

Create `demo/dreaming.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from demo.short_term_promotion import (
    DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    DEFAULT_PROMOTION_MIN_SCORE,
    DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
    rank_short_term_promotion_candidates,
    record_short_term_phase_signals,
    run_short_term_promotion,
)
from memory_core.config import MemoryConfig


def run_dreaming_sweep(
    *,
    config: MemoryConfig,
    store: Any,
    phase: str,
    now_ms: int,
    timezone: str,
    limit: int = 5,
) -> dict[str, Any]:
    if phase not in {"light", "rem", "deep"}:
        raise ValueError(f"unsupported dreaming phase: {phase}")
    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now_ms,
        limit=limit,
        min_score=0,
        min_recall_count=1,
        min_unique_queries=1,
    )
    keys = [candidate.key for candidate in candidates]
    phase_signals = 0
    promotion = None
    files_changed: list[str] = []
    if phase in {"light", "rem"} and keys:
        phase_signals = record_short_term_phase_signals(
            config=config,
            keys=keys,
            phase="light" if phase == "light" else "rem",
            now_ms=now_ms,
        )
        files_changed.append("memory/.dreams/phase-signals.json")
    if phase == "rem":
        _append_dreams_md(config=config, now_ms=now_ms, phase=phase, candidates=candidates)
        files_changed.append("DREAMS.md")
    if phase == "deep":
        promotion_run = run_short_term_promotion(
            config=config,
            store=store,
            now_ms=now_ms,
            timezone=timezone,
            min_score=DEFAULT_PROMOTION_MIN_SCORE,
            min_recall_count=DEFAULT_PROMOTION_MIN_RECALL_COUNT,
            min_unique_queries=DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
        )
        promotion = {
            "target": promotion_run.target,
            "rawText": promotion_run.raw_text,
            "parsed": {
                "shouldWrite": promotion_run.parsed.should_write,
                "target": promotion_run.parsed.target,
                "entry": promotion_run.parsed.entry,
                "reason": promotion_run.parsed.reason,
                "error": promotion_run.parsed.error,
            },
            "diff": promotion_run.diff,
        }
        if promotion_run.parsed.should_write:
            files_changed.append("MEMORY.md")
    return {
        "phase": phase,
        "candidateCount": len(candidates),
        "candidateKeys": keys,
        "phaseSignalsRecorded": phase_signals,
        "filesChanged": files_changed,
        "promotion": promotion,
    }


def _append_dreams_md(*, config: MemoryConfig, now_ms: int, phase: str, candidates: list[Any]) -> None:
    path = config.workspace_dir / "DREAMS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.fromtimestamp(now_ms / 1000, tz=UTC).isoformat()
    lines = [f"\n## Dreaming sweep {now}", "", f"- Phase: {phase}", f"- Candidates: {len(candidates)}"]
    for candidate in candidates[:5]:
        lines.append(f"- {candidate.snippet}")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/demo/test_dreaming_parity.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add demo/dreaming.py tests/demo/test_dreaming_parity.py
git commit -m "feat: add dreaming sweeps"
```

## Task 5: API State, Endpoints, And Reset

**Files:**
- Modify: `demo/app.py`
- Test: `tests/demo/test_demo_app.py`

- [ ] **Step 1: Add failing endpoint tests**

Append to `tests/demo/test_demo_app.py`:

```python
def test_memory_audit_and_repair_endpoints(monkeypatch):
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    store_path = demo_app.DEMO_WORKSPACE / "memory" / ".dreams" / "short-term-recall.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("{not-json", encoding="utf-8")

    audit = client.get("/api/memory/audit")
    repair = client.post("/api/memory/repair", json={})

    assert audit.status_code == 200
    assert audit.json()["memoryAudit"]["issues"][0]["code"] == "recall-store-unreadable"
    assert repair.status_code == 200
    assert repair.json()["memoryRepair"]["changed"] is True


def test_dreaming_endpoint_runs_light_sweep(monkeypatch):
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/dreaming/run",
        json={"phase": "light", "openai": {"apiKey": "request-key"}},
    )

    assert response.status_code == 200
    assert response.json()["dreamingSweep"]["phase"] == "light"


def test_reset_clears_dreaming_artifacts():
    client = TestClient(app)
    dreams = demo_app.DEMO_WORKSPACE / "memory" / ".dreams"
    dreams.mkdir(parents=True, exist_ok=True)
    (dreams / "phase-signals.json").write_text("{}", encoding="utf-8")

    client.post("/api/chat/reset", json={})

    assert not (demo_app.DEMO_WORKSPACE / "memory" / ".dreams" / "phase-signals.json").exists()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/demo/test_demo_app.py -v
```

Expected: FAIL for missing endpoints/state.

- [ ] **Step 3: Wire app state and endpoints**

In `demo/app.py`, import:

```python
from demo.dreaming import run_dreaming_sweep
from demo.short_term_promotion import (
    audit_short_term_promotion_artifacts,
    repair_short_term_promotion_artifacts,
)
```

Add globals:

```python
DREAMING_SWEEP: dict[str, Any] | None = None
MEMORY_AUDIT: dict[str, Any] | None = None
MEMORY_REPAIR: dict[str, Any] | None = None
```

In `_state_payload`, include:

```python
            "dreamingSweep": DREAMING_SWEEP,
            "memoryAudit": MEMORY_AUDIT,
            "memoryRepair": MEMORY_REPAIR,
```

Add serializers:

```python
def _serialize_audit(audit) -> dict[str, Any]:
    return {
        "storePath": audit.store_path,
        "lockPath": audit.lock_path,
        "updatedAt": audit.updated_at,
        "exists": audit.exists,
        "entryCount": audit.entry_count,
        "promotedCount": audit.promoted_count,
        "spacedEntryCount": audit.spaced_entry_count,
        "conceptTaggedEntryCount": audit.concept_tagged_entry_count,
        "invalidEntryCount": audit.invalid_entry_count,
        "issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "message": issue.message,
                "fixable": issue.fixable,
            }
            for issue in audit.issues
        ],
    }
```

Add endpoints:

```python
@app.get("/api/memory/audit")
def memory_audit():
    global MEMORY_AUDIT
    audit = audit_short_term_promotion_artifacts(config=demo_config(), now_ms=_now_ms())
    MEMORY_AUDIT = _serialize_audit(audit)
    return _state_payload()


@app.post("/api/memory/repair")
def memory_repair(payload: dict):
    del payload
    global MEMORY_REPAIR
    MEMORY_REPAIR = repair_short_term_promotion_artifacts(
        config=demo_config(),
        now_ms=_now_ms(),
    )
    return _state_payload()


@app.post("/api/dreaming/run")
def dreaming_run(payload: dict):
    global DREAMING_SWEEP
    try:
        phase = str(payload.get("phase") or "light")
        store = demo_store(payload)
        DREAMING_SWEEP = run_dreaming_sweep(
            config=demo_config(),
            store=store,
            phase=phase,
            now_ms=_now_ms(),
            timezone=DEMO_TIMEZONE,
        )
        return _state_payload()
    except DemoPayloadError as exc:
        return _json_error(str(exc))
    except Exception as exc:
        return _json_error(f"dreaming failed: {_safe_exception_message(exc, (_payload_api_key(payload),))}")
```

In `chat_reset`, clear new globals:

```python
    global PROMOTION_SWEEP, DREAMING_SWEEP, MEMORY_AUDIT, MEMORY_REPAIR
    PROMOTION_SWEEP = None
    DREAMING_SWEEP = None
    MEMORY_AUDIT = None
    MEMORY_REPAIR = None
```

- [ ] **Step 4: Run endpoint tests**

Run:

```bash
pytest tests/demo/test_demo_app.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add demo/app.py tests/demo/test_demo_app.py
git commit -m "feat: expose dreaming and audit endpoints"
```

## Task 6: UI Observability

**Files:**
- Modify: `demo/templates/index.html`
- Modify: `demo/static/styles.css`
- Test: `tests/demo/test_demo_app.py`

- [ ] **Step 1: Add failing UI assertions**

In `test_demo_home_loads`, add:

```python
    assert "dreaming-run" in response.text
    assert "memory-audit" in response.text
    assert "memory-repair" in response.text
    assert "Dreaming Sweep" in response.text
    assert "Audit / Repair" in response.text
    assert "phaseSignalsRecorded" in response.text
```

- [ ] **Step 2: Run UI test to verify failure**

Run:

```bash
pytest tests/demo/test_demo_app.py::test_demo_home_loads -v
```

Expected: FAIL for missing UI text/IDs.

- [ ] **Step 3: Add controls and render details**

In `demo/templates/index.html`, add controls near the existing promotion button:

```html
<select id="dreaming-phase" aria-label="Dreaming phase">
  <option value="light">light</option>
  <option value="rem">rem</option>
  <option value="deep">deep</option>
</select>
<button id="dreaming-run" type="button">Dreaming sweep</button>
<button id="memory-audit" type="button">Audit</button>
<button id="memory-repair" type="button">Repair</button>
```

In the pipeline render function, add:

```javascript
panel.append(stepNode("Dreaming Sweep", state.dreamingSweep ? renderJsonView(state.dreamingSweep) : textBlock("Not run yet.")));
panel.append(stepNode("Audit / Repair", auditRepairNode()));
```

Add:

```javascript
function auditRepairNode() {
  const wrap = document.createElement("div");
  wrap.append(sectionBlock("Audit", state.memoryAudit ? renderJsonView(state.memoryAudit) : textBlock("Not run yet.")));
  wrap.append(sectionBlock("Repair", state.memoryRepair ? renderJsonView(state.memoryRepair) : textBlock("Not run yet.")));
  return wrap;
}
```

Wire buttons:

```javascript
document.querySelector("#dreaming-run").onclick = async () => {
  state = await requestJson("/api/dreaming/run", {
    phase: document.querySelector("#dreaming-phase").value,
    openai: openAIConfig()
  });
  render();
};
document.querySelector("#memory-audit").onclick = async () => {
  state = await requestJson("/api/memory/audit", null, "GET");
  render();
};
document.querySelector("#memory-repair").onclick = async () => {
  state = await requestJson("/api/memory/repair", {});
  render();
};
```

If `requestJson` does not support GET, update it:

```javascript
async function requestJson(url, body = {}, method = "POST") {
  const options = {method, headers: {"Content-Type": "application/json"}};
  if (method !== "GET") options.body = JSON.stringify(body || {});
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}
```

- [ ] **Step 4: Add compact CSS**

In `demo/static/styles.css`, add:

```css
.memory-controls select {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0.55rem 0.7rem;
  background: #ffffff;
  color: var(--ink);
  font: inherit;
}

.pipeline-step .kv-grid {
  margin-top: 0.75rem;
}
```

- [ ] **Step 5: Run UI tests**

Run:

```bash
pytest tests/demo/test_demo_app.py::test_demo_home_loads tests/demo/test_demo_app.py::test_demo_css_uses_full_screen_layout -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add demo/templates/index.html demo/static/styles.css tests/demo/test_demo_app.py
git commit -m "feat: show dreaming and audit controls"
```

## Task 7: End-To-End Verification

**Files:**
- Modify as needed from prior tasks only.

- [ ] **Step 1: Run full test suite**

Run:

```bash
pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run:

```bash
ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 3: Restart local server**

Run:

```bash
kill "$(lsof -ti tcp:8000)" 2>/dev/null || true
python -m uvicorn demo.app:app --host 127.0.0.1 --port 8000
```

Expected: server reports `Uvicorn running on http://127.0.0.1:8000`.

- [ ] **Step 4: Smoke check UI/API**

Run:

```bash
curl -s http://127.0.0.1:8000/ | rg -n "Dreaming sweep|Audit|Repair|OpenClaw defaults"
curl -s http://127.0.0.1:8000/api/chat/state | python -m json.tool | rg -n "dreamingSweep|memoryAudit|memoryRepair|dailyMemoryPath"
```

Expected: all searched labels/fields appear.

- [ ] **Step 5: Commit final fixes**

If Step 1-4 required small fixes:

```bash
git add demo memory-core tests
git commit -m "test: verify openclaw memory parity"
```

If no files changed, skip this commit.

## Self-Review

- Spec coverage: promotion gates, phase signals, lock, audit/repair, dreaming sweeps, search corpus, reset, and UI observability each have a task.
- Scope: TypeScript extension host is intentionally excluded; Python behavior port is implemented through focused modules.
- Placeholder scan: no `TBD`, `TODO`, or unspecified test steps.
- Type consistency: endpoints use `dreamingSweep`, `memoryAudit`, and `memoryRepair`; tests assert those exact keys.
