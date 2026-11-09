"""A rejected source must not require MEMORY, a promotion lock, or a model."""
from copy import deepcopy
import os
from pathlib import Path

import pytest

from equivalence.promotion_apply_reconcile_fixtures import build_promotion_apply_reconcile_cases
from memory_core.config import MemoryConfig
from memory_core.consolidation import DeepConsolidation, LlmConsolidationOptions
from memory_core.consolidation import promotion
from memory_core.consolidation.file_lock import FileLockOptions, resolve_memory_promotion_lock_target, with_file_lock
from memory_core.consolidation.store import read_canonical_recall_store, recall_store_path, write_recall_store
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY


def _setup(tmp_path: Path, *, blocked_origin=False):
    value = deepcopy(build_promotion_apply_reconcile_cases()[0]["input"])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if blocked_origin:
        entry, = value["recall"]["entries"].values()
        entry["provenance"]["originClass"] = "untrusted"
        source = workspace / entry["path"]
        source.parent.mkdir()
        source.write_text("# Source facts\n\n" + entry["snippet"] + "\n")
    write_recall_store(recall_store_path(workspace), value["recall"])
    config = MemoryConfig(workspace, store_path=tmp_path / "index.sqlite", flags=FeatureFlags(vector_search=False))
    store = SQLiteMemoryStore(config, None)
    candidates = [promotion.PromotionCandidate.from_json(item) for item in value["candidates"]]
    return value, config, store, candidates


def _run(value, config, store, candidates, tmp_path, **extra):
    options = value["options"]
    return promotion.run_short_term_promotion(
        config=config, store=store, candidates=candidates, now_ms=value["nowMs"],
        timezone=options["timezone"], limit=options["limit"], min_score=options["minScore"],
        min_recall_count=options["minRecallCount"], min_unique_queries=options["minUniqueQueries"],
        memory_file_max_chars=options["memoryFileMaxChars"],
        max_prior_entry_loss_fraction=options["maxPriorEntryLossFraction"],
        state_dir=tmp_path / "state", identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, **extra,
    )


def _assert_rejected_noop(run, category="source rehydration"):
    assert run.applied_candidates == ()
    assert run.appended == run.reconciled_existing == run.indexed_files == run.chunks == 0
    assert run.compacted_dates == () and run.diff == "" and run.host_event is None
    assert run.outcome.should_write is False and run.outcome.reason == "no live promotion candidates"
    assert len(run.evaluated_candidates) == 1
    assert len(run.rejected_candidates) == 1 and run.rejected_candidates[0].category == category


@pytest.mark.parametrize("active_model", (False, True))
def test_missing_source_returns_authoritative_rejection_with_directory_memory(tmp_path, active_model):
    value, config, store, candidates = _setup(tmp_path)
    memory = config.workspace_dir / "MEMORY.md"
    memory.mkdir()
    before = memory.stat()
    recall_before = read_canonical_recall_store(recall_store_path(config.workspace_dir), value["nowMs"])
    events, locks, model_requests = [], [], []

    def model(request):
        model_requests.append(request)
        raise AssertionError("A rejected source cannot invoke the model")

    deep = DeepConsolidation(model=model, options=LlmConsolidationOptions(enabled=True)) if active_model else None
    run = _run(value, config, store, candidates, tmp_path, consolidation=deep,
               on_event=events.append, lock_observer=lambda *args: locks.append(args))
    _assert_rejected_noop(run)
    rejection, = run.rejected_candidates
    assert rejection.reason == "source rehydration failed" and rejection.candidate == candidates[0]
    assert events == locks == model_requests == []
    assert not (tmp_path / "state").exists() and not (config.workspace_dir / "DREAMS.md").exists()
    assert (memory.stat().st_dev, memory.stat().st_ino, memory.stat().st_mtime_ns) == (
        before.st_dev, before.st_ino, before.st_mtime_ns)
    assert read_canonical_recall_store(recall_store_path(config.workspace_dir), value["nowMs"]) == recall_before


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="Requires actual POSIX read denial for this user")
def test_missing_source_does_not_read_a_permission_denied_memory_file(tmp_path):
    value, config, store, candidates = _setup(tmp_path)
    memory = config.workspace_dir / "MEMORY.md"
    content = b"User-owned inaccessible memory must remain unchanged.\n"
    memory.write_bytes(content)
    memory.chmod(0)
    try:
        with pytest.raises(PermissionError):
            memory.read_bytes()
        run = _run(value, config, store, candidates, tmp_path)
        _assert_rejected_noop(run)
        assert memory.stat().st_mode & 0o777 == 0
    finally:
        memory.chmod(0o600)
    assert memory.read_bytes() == content


def test_missing_source_leaves_a_genuinely_held_promotion_sidecar_untouched(tmp_path, monkeypatch):
    value, config, store, candidates = _setup(tmp_path)
    (config.workspace_dir / "MEMORY.md").mkdir()
    target = resolve_memory_promotion_lock_target(tmp_path / "state", config.workspace_dir)
    # Only bound a regression's retry duration; both holders use the real lock
    # owner and real exclusive sidecar rather than a fabricated lock result.
    options = FileLockOptions(retries=0)
    monkeypatch.setattr(promotion, "MEMORY_WRITE_LOCK_OPTIONS", options)
    observations = []
    with with_file_lock(target, options) as sidecar:
        held_bytes = sidecar.read_bytes()
        run = _run(value, config, store, candidates, tmp_path,
                   lock_observer=lambda *args: observations.append(args))
        _assert_rejected_noop(run)
        assert sidecar.read_bytes() == held_bytes and observations == []
    assert not sidecar.exists()


def test_authoritative_blocked_origin_is_retained_before_early_return(tmp_path):
    value, config, store, candidates = _setup(tmp_path, blocked_origin=True)
    (config.workspace_dir / "MEMORY.md").mkdir()
    run = _run(value, config, store, candidates, tmp_path)
    _assert_rejected_noop(run, category="origin")
    rejection, = run.rejected_candidates
    assert candidates[0].provenance["originClass"] == "agent"
    assert rejection.candidate.provenance["originClass"] == "untrusted"
    assert rejection.reason == "origin filter (untrusted)"


def test_defensive_private_empty_commit_does_not_read_directory_memory(tmp_path):
    value, config, store, candidates = _setup(tmp_path)
    (config.workspace_dir / "MEMORY.md").mkdir()
    plan = promotion._plan_apply_stage(config=config, ranked=candidates, now_ms=value["nowMs"],
        consolidation=False, daily_provenance={}, limit=5, min_score=0, min_recall_count=0,
        min_unique_queries=0, max_age_days=30)
    evaluations = promotion.evaluate_short_term_promotion_candidates(config=config, now_ms=value["nowMs"],
        min_score=0, min_recall_count=0, min_unique_queries=0, max_age_days=30)
    run, commit = promotion._commit_promotion(config=config, store=store, now_ms=value["nowMs"], timezone="UTC",
        memory_file_max_chars=10000, max_promoted_snippet_tokens=200, max_prior_entry_loss_fraction=0.25,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, consolidation=None, plan=plan, preplan=None,
        ranked=candidates, evaluations=evaluations, agent_id=None, origin_agent_ids=[], origins=None)
    _assert_rejected_noop(run)
    assert commit is None
