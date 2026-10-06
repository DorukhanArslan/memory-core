"""The apply half of the deep phase, offline: what the oracle cannot reach.

``tests/integration/test_promotion_apply_oracle.py`` compares ``rejectedCandidates``, the
``memory.promotion.applied`` events, the origins ledger and the lock contract with the real
OpenClaw v2026.9.6 code. These tests cover the parts the TS test helpers cannot drive (a recall
store that changes while the model runs: upstream's plugin state is in memory there), Python-only
behavior (the default lock location, the workspace lock's reentrancy and wait) and the pieces
that are ports without a TS counterpart to call.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation import DeepConsolidation, LlmConsolidationOptions
from memory_core.consolidation.artifacts import update_dreams_file
from memory_core.consolidation.file_lock import (
    FileLockOptions,
    FileLockStaleError,
    FileLockTimeoutError,
    resolve_memory_promotion_lock_target,
    retry_delay_ms,
    with_file_lock,
)
from memory_core.consolidation.origins import (
    MemoryEntryOrigin,
    MemoryEntryOriginLedger,
    reserve_memory_entry_origins,
)
from memory_core.consolidation.promotion import (
    PromotionCandidate,
    build_promotion_applied_event,
    run_short_term_promotion,
)
from memory_core.consolidation.store import (
    MemoryWorkspaceLockHeldError,
    acquire_short_term_promotion_lock,
    memory_workspace_lock,
    workspace_lock_held,
)
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

NOW_MS = 1779811200000
KEY = "memory:memory/2026-05-08.md:3:3"
DAILY = "# 2026-05-08\n\n- Alpha fact 1.\n- Beta fact 2.\n"
PROVENANCE = {"originClass": "agent", "sessionKind": "unknown", "observedAt": 1}


def _entry(line: int = 3, **over: Any) -> dict[str, Any]:
    snippet = "- Alpha fact 1." if line == 3 else "- Beta fact 2."
    entry = {
        "key": f"memory:memory/2026-05-08.md:{line}:{line}",
        "path": "memory/2026-05-08.md",
        "startLine": line,
        "endLine": line,
        "source": "memory",
        "snippet": snippet,
        "recallCount": 4,
        "dailyCount": 0,
        "groundedCount": 0,
        "totalScore": 3.6,
        "maxScore": 1.0,
        "firstRecalledAt": "2026-05-20T16:00:00.000Z",
        "lastRecalledAt": "2026-05-25T16:00:00.000Z",
        "queryHashes": ["a1", "a2", "a3"],
        "userQueryHashes": ["a1", "a2", "a3"],
        "recallDays": ["2026-05-21"],
        "conceptTags": [],
        "provenance": dict(PROVENANCE),
    }
    entry.update(over)
    return entry


def _candidate(line: int = 3, **over: Any) -> PromotionCandidate:
    entry = _entry(line)
    raw = {
        **entry,
        "signalCount": 4,
        "avgScore": 0.9,
        "uniqueQueries": 3,
        "ageDays": 1,
        "score": 0.9,
        "components": {},
    }
    raw.update(over)
    return PromotionCandidate.from_json(raw)


def _workspace(tmp_path: Path, entries: list[dict[str, Any]] | None = None) -> MemoryConfig:
    workspace = tmp_path / "ws"
    (workspace / "memory" / ".dreams").mkdir(parents=True)
    (workspace / "memory" / "2026-05-08.md").write_text(DAILY, encoding="utf-8")
    (workspace / "MEMORY.md").write_text("# Memory\n\n- Existing global fact.\n", encoding="utf-8")
    store = {
        "version": 1,
        "updatedAt": "2026-05-25T16:00:00.000Z",
        "entries": {e["key"]: e for e in (entries if entries is not None else [_entry()])},
    }
    (workspace / "memory" / ".dreams" / "short-term-recall.json").write_text(
        json.dumps(store), encoding="utf-8"
    )
    return MemoryConfig(workspace_dir=workspace, store_path=tmp_path / "idx.sqlite")


def _run(config: MemoryConfig, tmp_path: Path, **kwargs: Any):
    params: dict[str, Any] = {
        "config": config,
        "store": SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8)),
        "now_ms": NOW_MS,
        "timezone": "Europe/Istanbul",
        "limit": 10,
        "min_score": 0.75,
        "min_recall_count": 3,
        "min_unique_queries": 3,
        "identity": OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        "candidates": [_candidate()],
        "state_dir": tmp_path / "state",
    }
    params.update(kwargs)
    return run_short_term_promotion(**params)


# --- candidates ---------------------------------------------------------------------------------


def test_candidate_json_round_trip() -> None:
    candidate = _candidate(claimHash="abc", projectKey="proj", promotedAt="2026-05-01T00:00:00.000Z")
    assert PromotionCandidate.from_json(candidate.to_json()) == candidate
    assert "provenance" not in _candidate(provenance=None).to_json()


# --- host events --------------------------------------------------------------------------------


def test_event_reaches_the_host_callback_and_the_run(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    events: list[dict[str, Any]] = []
    run = _run(config, tmp_path, on_event=events.append)
    assert [c.key for c in run.applied_candidates] == [KEY]
    assert events == [run.host_event]
    assert events[0]["type"] == "memory.promotion.applied"
    assert events[0]["applied"] == 1
    assert events[0]["candidates"] == [
        {"key": KEY, "path": "memory/2026-05-08.md", "startLine": 3, "endLine": 3, "score": 0.9, "recallCount": 4}
    ]


def test_no_event_when_nothing_was_rehydrated(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    events: list[dict[str, Any]] = []
    run = _run(config, tmp_path, on_event=events.append, min_score=0.95)
    assert events == [] and run.host_event is None
    assert [item.category for item in run.rejected_candidates] == ["score threshold"]
    assert run.rejected_candidates[0].reason == "score threshold (0.900 < 0.95)"


def test_event_bounds(tmp_path: Path) -> None:
    candidates = [_candidate(3, key=f"{'k' * 300}-{i}") for i in range(12)]
    event = build_promotion_applied_event(memory_path="/m/" + "p" * 300, applied_candidates=candidates, now_ms=NOW_MS)
    assert event["applied"] == 12 and len(event["candidates"]) == 10
    assert event["storageTruncated"] is True
    assert event["memoryPath"].endswith("…") and len(event["memoryPath"].encode()) <= 256
    assert all(item["key"].endswith("…") for item in event["candidates"])
    # More than 8 KiB of JSON (control characters escape to six bytes) drops the candidates.
    wide = [_candidate(3, key=f"k{i}" + "\x01" * 240, path="\x01" * 250) for i in range(10)]
    event = build_promotion_applied_event(memory_path="m", applied_candidates=wide, now_ms=NOW_MS)
    assert event["candidates"] == [] and event["storageTruncated"] is True


# --- the lock-time re-check -------------------------------------------------------------------


def test_store_changed_while_the_model_runs_rejects_as_candidate_changed(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    store_path = config.workspace_dir / "memory" / ".dreams" / "short-term-recall.json"

    def model(_request: Any) -> str:
        store = json.loads(store_path.read_text(encoding="utf-8"))
        store["entries"][KEY]["recallCount"] += 1
        store_path.write_text(json.dumps(store), encoding="utf-8")
        return json.dumps({"operations": [{"candidateKey": KEY, "action": "added", "priorEntries": []}]})

    deep = DeepConsolidation(model=model, options=LlmConsolidationOptions(enabled=True))
    run = _run(config, tmp_path, consolidation=deep)
    assert run.applied_candidates == ()
    assert [(i.category, i.reason) for i in run.rejected_candidates] == [
        ("candidate changed", "candidate changed during apply")
    ]
    assert "Alpha" not in (config.workspace_dir / "MEMORY.md").read_text(encoding="utf-8")


def test_promoted_while_the_model_runs_is_skipped(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    store_path = config.workspace_dir / "memory" / ".dreams" / "short-term-recall.json"

    def model(_request: Any) -> str:
        store = json.loads(store_path.read_text(encoding="utf-8"))
        store["entries"][KEY]["promotedAt"] = "2026-05-26T00:00:00.000Z"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        return json.dumps({"operations": [{"candidateKey": KEY, "action": "added", "priorEntries": []}]})

    run = _run(
        config,
        tmp_path,
        consolidation=DeepConsolidation(model=model, options=LlmConsolidationOptions(enabled=True)),
    )
    assert run.applied_candidates == ()
    assert run.rejected_candidates[0].category == "candidate changed"


def test_store_entry_origin_turning_untrusted_while_the_model_runs(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    store_path = config.workspace_dir / "memory" / ".dreams" / "short-term-recall.json"

    def model(_request: Any) -> str:
        store = json.loads(store_path.read_text(encoding="utf-8"))
        store["entries"][KEY]["provenance"]["originClass"] = "untrusted"
        store_path.write_text(json.dumps(store), encoding="utf-8")
        return json.dumps({"operations": [{"candidateKey": KEY, "action": "added", "priorEntries": []}]})

    run = _run(
        config,
        tmp_path,
        consolidation=DeepConsolidation(model=model, options=LlmConsolidationOptions(enabled=True)),
    )
    assert run.applied_candidates == ()


# --- the two locks ------------------------------------------------------------------------------


def test_default_lock_location_and_cleanup(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    run = run_short_term_promotion(
        config=config,
        store=SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8)),
        now_ms=NOW_MS,
        timezone="UTC",
        min_score=0.75,
        min_recall_count=3,
        min_unique_queries=3,
        candidates=[_candidate()],
    )
    assert run.applied_candidates
    locks = config.workspace_dir / "memory" / ".dreams" / "locks"
    assert locks.is_dir() and list(locks.iterdir()) == []
    assert oct(locks.stat().st_mode & 0o777) == "0o700"


def test_held_file_lock_stops_the_run_without_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from memory_core.consolidation import promotion

    config = _workspace(tmp_path)
    monkeypatch.setattr(
        promotion, "MEMORY_WRITE_LOCK_OPTIONS", FileLockOptions(retries=1, min_timeout_ms=1, max_timeout_ms=1)
    )
    target = resolve_memory_promotion_lock_target(tmp_path / "state", config.workspace_dir)
    Path(f"{target}.lock").parent.mkdir(parents=True, exist_ok=True)
    Path(f"{target}.lock").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    before = (config.workspace_dir / "MEMORY.md").read_text(encoding="utf-8")
    with pytest.raises(FileLockTimeoutError) as raised:
        _run(config, tmp_path)
    assert raised.value.code == "file_lock_timeout"
    assert (config.workspace_dir / "MEMORY.md").read_text(encoding="utf-8") == before
    # The holder's sidecar is not ours to remove.
    assert Path(f"{target}.lock").exists()


def test_file_lock_order_is_file_lock_then_workspace_lock(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    seen: list[str] = []
    target = resolve_memory_promotion_lock_target(tmp_path / "state", config.workspace_dir)

    def observer(event: str, _path: Path) -> None:
        # Inside the file lock the workspace lock is taken afterwards, and is gone before release.
        workspace_lock = config.workspace_dir / "memory" / ".dreams" / "short-term-promotion.lock"
        seen.append(f"{event}:{workspace_lock.exists()}")

    _run(config, tmp_path, lock_observer=observer)
    assert seen == ["acquired:False", "released:False"]
    assert not Path(f"{target}.lock").exists()


def test_dead_owner_sidecar_fails_closed(tmp_path: Path) -> None:
    import subprocess
    import sys

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    target = tmp_path / "locks" / "t"
    target.parent.mkdir()
    Path(f"{target}.lock").write_text(json.dumps({"pid": child.pid}), encoding="utf-8")
    with pytest.raises(FileLockStaleError, match=r"file lock stale for .* \[owner-process-exited pid="):
        with with_file_lock(target, FileLockOptions(retries=1, min_timeout_ms=1, max_timeout_ms=1)):
            pytest.fail("acquired a stale sidecar")
    assert Path(f"{target}.lock").exists()


def test_remove_if_unchanged_recovers_a_dead_owner(tmp_path: Path) -> None:
    import subprocess
    import sys

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    target = tmp_path / "t"
    Path(f"{target}.lock").write_text(json.dumps({"pid": child.pid}), encoding="utf-8")
    with with_file_lock(target, FileLockOptions(stale_recovery="remove-if-unchanged")) as lock:
        assert json.loads(lock.read_text(encoding="utf-8").split("\n\t")[0])["pid"] == os.getpid()
    assert not Path(f"{target}.lock").exists()


def test_retry_schedule_is_upstreams() -> None:
    options = FileLockOptions()
    delays = [retry_delay_ms(options, attempt) for attempt in range(100)]
    assert delays[0] == 25 and max(delays) == 250 and retry_delay_ms(options, 100) is None
    assert delays[:4] == [25, 30, 36, 43]


def test_workspace_lock_is_reentrant_and_waits(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    workspace = config.workspace_dir
    with memory_workspace_lock(workspace):
        assert workspace_lock_held(workspace)
        with memory_workspace_lock(workspace):  # the DREAMS.md writers re-enter it
            update_dreams_file(workspace, lambda existing, _p: (existing + "x", None))
    assert not workspace_lock_held(workspace)
    assert (workspace / "DREAMS.md").read_text(encoding="utf-8") == "x\n"
    assert not (workspace / "memory" / ".dreams" / "short-term-promotion.lock").exists()


def test_workspace_lock_times_out_when_another_owner_holds_it(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    with acquire_short_term_promotion_lock(config, NOW_MS) as held:
        assert held.acquired
        with pytest.raises(MemoryWorkspaceLockHeldError, match="Timed out waiting for memory workspace lock"):
            with memory_workspace_lock(config.workspace_dir, now_ms=NOW_MS, timeout_ms=60, retry_delay_ms=10):
                pytest.fail("entered a held lock")


def test_dreams_update_waits_for_the_workspace_lock(tmp_path: Path) -> None:
    import threading
    import time

    config = _workspace(tmp_path)
    released = threading.Event()

    def hold() -> None:
        with acquire_short_term_promotion_lock(config, int(time.time() * 1000)):
            released.wait(timeout=0.15)

    thread = threading.Thread(target=hold)
    thread.start()
    time.sleep(0.05)
    started = time.monotonic()
    update_dreams_file(config.workspace_dir, lambda existing, _p: (existing + "late", None))
    assert time.monotonic() - started >= 0.05
    thread.join()
    assert (config.workspace_dir / "DREAMS.md").read_text(encoding="utf-8") == "late\n"


# --- the origins ledger -------------------------------------------------------------------------


def _origin(entry: str, session: str, agent: str = "main") -> MemoryEntryOrigin:
    return MemoryEntryOrigin(entry, agent, session, f"agent:{agent}:{session}", "owner", 1000)


def test_ledger_uses_upstreams_table_and_never_creates_on_read(tmp_path: Path) -> None:
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / f"{agent}.sqlite")
    assert ledger.list("main") == [] and not (tmp_path / "main.sqlite").exists()
    assert ledger.delete("main", ["x"]) == 0 and not (tmp_path / "main.sqlite").exists()
    assert ledger.indexed_promotion_keys("main") is None
    ledger.record("main", [_origin("a", "s1")])
    with sqlite3.connect(tmp_path / "main.sqlite") as db:
        sql = db.execute("SELECT sql FROM sqlite_schema WHERE name = 'memory_entry_origins'").fetchone()[0]
        assert sql.endswith("STRICT") and "PRIMARY KEY (entry_key, agent_id, session_id)" in sql
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO memory_entry_origins VALUES ('b', 'main', 's', NULL, 'bogus', 1)")
    with pytest.raises(ValueError, match="belongs to another agent"):
        ledger.record("main", [_origin("a", "s2", agent="other")])
    assert [o.session_id for o in ledger.list("main")] == ["s1"]


def test_reserve_failure_rolls_back_what_it_added(tmp_path: Path) -> None:
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / f"{agent}.sqlite")
    ledger.record("a", [_origin("parent", "s1", "a")])
    ledger.record("b", [_origin("parent", "s2", "b")])
    (tmp_path / "b.sqlite").write_bytes(b"not a database")

    class Operation:
        candidate_key = "child"
        action = "merged"
        prior_entries: list[str] = []

    with pytest.raises(sqlite3.DatabaseError):
        reserve_memory_entry_origins(
            ledger, agent_ids=["a", "b"], previous_memory="", operations=[Operation()]
        )
    # Agent "a" is visited first; its new row is rolled back when "b" fails.
    assert ledger.list("a", entry_keys=["child"]) == []


def test_preimage_rotation_dedupes_a_repeated_snapshot(tmp_path: Path) -> None:
    from memory_core.consolidation.artifacts import read_memory_preimages, store_memory_preimage

    workspace = tmp_path / "ws"
    workspace.mkdir()
    store_memory_preimage(workspace, "same", NOW_MS)
    store_memory_preimage(workspace, "same", NOW_MS)
    assert len(read_memory_preimages(workspace)) == 1


def test_inactive_consolidation_object_still_turns_the_origin_filter_on(tmp_path: Path) -> None:
    config = _workspace(tmp_path, [_entry(provenance=None)])
    logger = logging.getLogger("promotion-apply-unit")
    run = _run(config, tmp_path, consolidation=DeepConsolidation(logger=logger))
    assert [i.category for i in run.rejected_candidates] == ["consolidation origin/session"]
    assert _run(config, tmp_path).applied_candidates, "no consolidation object: the filter is off"
