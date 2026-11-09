"""Actual catalog commits, source publication, and deferred owner settlement."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from memory_core import secret_registry
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.session_publication import SessionPublicationController
from memory_core.index.sqlite_store import MemoryIndexRequiresFullReindexError, SQLiteMemoryStore
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.workspace import MemoryWorkspace

NOW = 1_794_182_400_000


class ManualCall:
    def __init__(self, callback):
        self.callback, self.cancelled = callback, False

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.callback()


class ManualScheduler:
    def __init__(self):
        self.calls = []

    def __call__(self, delay, callback):
        call = ManualCall(callback)
        self.calls.append((delay, call))
        return call


def _key(session):
    return f"agent:main:dm:{session}"


def _append(catalog, session, text, event_id):
    return catalog.append_message(session, {"role": "user", "content": [{"type": "text", "text": text}]},
        session_key=_key(session), event_id=event_id, now_ms=NOW)


def _owner(tmp_path, *, bootstrap=True, sessions=True):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "MEMORY.md").write_text("Durable unrelated memory.\n", encoding="utf8")
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    for session in ("alpha", "beta"):
        catalog.upsert_session(_key(session), {"sessionId": session, "updatedAt": NOW})
        _append(catalog, session, f"Initial {session} preference.", session + "-initial")
    config = MemoryConfig(workspace_dir=root, store_path=tmp_path / "index.sqlite",
        flags=FeatureFlags(vector_search=False, temporal_decay=False))
    workspace = MemoryWorkspace(root, session_catalog=catalog,
        index_sources=["memory", "sessions"] if sessions else ["memory"])
    store = SQLiteMemoryStore(config, None)
    if bootstrap:
        store.reindex(workspace)
    return store, workspace, catalog


def _rows(store, source=None):
    return [row for row in store.read_published_index()["chunks"] if source is None or row["source"] == source]


def _started(tmp_path):
    store, workspace, catalog = _owner(tmp_path)
    scheduler = ManualScheduler()
    controller = SessionPublicationController(store, workspace, catalog, scheduler=scheduler)
    controller.start()
    assert controller.wait_idle(3)
    return store, workspace, catalog, scheduler, controller


def test_constructor_is_inert_and_start_discovers_real_missed_commits(tmp_path):
    store, workspace, catalog = _owner(tmp_path)
    controller = SessionPublicationController(store, workspace, catalog)
    before = store.read_published_index()
    assert controller.status()["notStarted"] and controller.status()["pending"] is None
    assert controller.status()["jobCount"] == 0
    _append(catalog, "alpha", "Committed while the controller was not started.", "before-start")
    assert store.read_published_index() == before
    try:
        controller.start()
        assert controller.wait_idle(3)
        state = controller.status()
        assert state["state"] == "idle" and state["pending"] is False
        assert state["generation"] == state["publishedGeneration"] > 0
        assert "not started" in next(row["text"] for row in _rows(store) if row["path"].endswith("/alpha.jsonl"))
        assert _rows(store, "memory") == [row for row in before["chunks"] if row["source"] == "memory"]
        assert state["jobs"][0]["discovery"]["catalogRevisionAfter"] == catalog.snapshot().revision
    finally:
        controller.close()


def test_real_peer_commits_use_one_first_event_timer_and_targeted_publication(tmp_path):
    store, workspace, catalog, scheduler, controller = _started(tmp_path)
    before = store.read_published_index()
    peer = MemorySessionCatalog(catalog.path, store_path=catalog.store_path, clock_ms=lambda: NOW)
    try:
        _append(peer, "alpha", "First committed update.", "first-update")
        _append(catalog, "alpha", "Second committed update.", "second-update")
        assert _append(peer, "alpha", "Second committed update.", "second-update")["appended"] is False
        assert [delay for delay, _ in scheduler.calls] == [5.0]
        assert controller.status()["pending"] and controller.wait_idle(0)
        assert store.read_published_index() == before
        # A memory edit is not part of this session publication claim.
        (workspace.root / "MEMORY.md").write_text("Changed outside the selected session source.\n")
        scheduler.calls[0][1].fire()
        assert controller.wait_idle(3)
        assert controller.status()["pending"] is False
        assert "Second committed" in next(row["text"] for row in _rows(store) if row["path"].endswith("/alpha.jsonl"))
        assert _rows(store, "memory") == [row for row in before["chunks"] if row["source"] == "memory"]
        assert next(row for row in _rows(store) if row["path"].endswith("/beta.jsonl")) == next(
            row for row in before["chunks"] if row["path"].endswith("/beta.jsonl"))
    finally:
        controller.close()


def test_explicit_reconcile_removes_only_no_longer_admitted_session_sources(tmp_path):
    store, workspace, _catalog, _scheduler, controller = _started(tmp_path)
    memory = _rows(store, "memory")
    try:
        workspace.is_session_forgotten = lambda session: session == "alpha"
        state = controller.reconcile(timeout=3)
        assert state["pending"] is False
        assert {row["path"] for row in _rows(store, "sessions")} == {"sessions/main/beta.jsonl"}
        assert _rows(store, "memory") == memory
        assert workspace.index_sources == ("memory", "sessions")
    finally:
        controller.close()


def test_failed_claim_is_retained_without_timer_retry_and_explicit_flush_recovers(tmp_path, monkeypatch):
    store, _workspace, catalog, scheduler, controller = _started(tmp_path)
    original = store.reindex_sources
    failure = OSError("actual selected-source producer refused")
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(kwargs)
        raise failure

    monkeypatch.setattr(store, "reindex_sources", refuse)
    try:
        _append(catalog, "alpha", "Pending after an actual failed source operation.", "failed-update")
        scheduler.calls[0][1].fire()
        assert controller.wait_idle(3)
        state = controller.status()
        assert state["state"] == "failed" and state["pending"]
        assert state["pendingPaths"] == ["sessions/main/alpha.jsonl"]
        assert not state["timerPending"] and len(attempts) == 1
        with pytest.raises(OSError) as raised:
            controller.flush(timeout=3)
        assert raised.value is failure and len(attempts) == 2
        monkeypatch.setattr(store, "reindex_sources", original)
        assert controller.flush(timeout=3)["state"] == "idle"
        assert "Pending after" in next(row["text"] for row in _rows(store) if row["path"].endswith("/alpha.jsonl"))
        assert any(job["state"] == "failed" for job in controller.status()["jobs"])
    finally:
        controller.close()


@pytest.mark.parametrize("fire_while_active", [False, True])
def test_arrival_during_real_publication_keeps_its_own_pending_generation(tmp_path, monkeypatch, fire_while_active):
    store, _workspace, catalog, scheduler, controller = _started(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = store.reindex_sources

    def block(*args, **kwargs):
        assert controller.owns_current_job()
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "reindex_sources", block)
    try:
        _append(catalog, "alpha", "First physical publication.", "inflight-alpha")
        scheduler.calls[0][1].fire()
        assert entered.wait(3) and not controller.wait_idle(0)
        _append(catalog, "beta", "Arrived after source admission.", "inflight-beta")
        assert len(scheduler.calls) == 2
        if fire_while_active:
            scheduler.calls[1][1].fire()
        release.set()
        assert controller.wait_idle(3)
        if not fire_while_active:
            assert controller.status()["pendingPaths"] == ["sessions/main/beta.jsonl"]
            assert controller.status()["publishedGeneration"] < controller.status()["generation"]
            assert "Arrived after" not in next(row["text"] for row in _rows(store) if row["path"].endswith("/beta.jsonl"))
            scheduler.calls[1][1].fire()
            assert controller.wait_idle(3)
        assert "Arrived after" in next(row["text"] for row in _rows(store) if row["path"].endswith("/beta.jsonl"))
        assert controller.status()["pending"] is False
    finally:
        release.set()
        controller.close()


def test_close_cancels_default_real_timer_without_early_flush_and_restart_recovers(tmp_path):
    store, workspace, catalog = _owner(tmp_path)
    controller = SessionPublicationController(store, workspace, catalog)
    controller.start()
    assert controller.wait_idle(3)
    before = store.read_published_index()
    _append(catalog, "alpha", "Durable event left behind a cancelled timer.", "close-pending")
    assert controller.status()["timerPending"]
    controller.close()
    assert controller.status()["closed"] and controller.status()["pending"]
    assert store.read_published_index() == before
    with pytest.raises(RuntimeError, match="closed"):
        controller.start()
    resumed = SessionPublicationController(store, workspace, catalog)
    try:
        resumed.start()
        assert resumed.wait_idle(3)
        assert "cancelled timer" in next(row["text"] for row in _rows(store) if row["path"].endswith("/alpha.jsonl"))
    finally:
        resumed.close()


def test_close_joins_admitted_work_and_job_cannot_close_its_own_owner(tmp_path, monkeypatch):
    store, _workspace, catalog, scheduler, controller = _started(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = store.reindex_sources

    def block(*args, **kwargs):
        assert controller.owns_current_job()
        with pytest.raises(RuntimeError, match="own controller"):
            controller.close()
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "reindex_sources", block)
    _append(catalog, "alpha", "Must settle before close returns.", "joined-close")
    scheduler.calls[0][1].fire()
    assert entered.wait(3)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(controller.close)
        try:
            assert not controller.wait_idle(0) and not future.done()
        finally:
            release.set()
        future.result(timeout=3)
    assert controller.status()["closed"] and controller.status()["activeJobs"] == 0
    assert "before close" in next(row["text"] for row in _rows(store) if row["path"].endswith("/alpha.jsonl"))


def test_controller_never_hides_a_cold_scoped_rebuild_refusal(tmp_path):
    store, workspace, catalog = _owner(tmp_path, bootstrap=False)
    controller = SessionPublicationController(store, workspace, catalog)
    try:
        controller.start()
        assert controller.wait_idle(3)
        assert controller.status()["state"] == "failed" and store.read_index_meta() is None
        with pytest.raises(MemoryIndexRequiresFullReindexError):
            controller.flush(timeout=3)
        store.reindex(workspace)
        assert controller.flush(timeout=3)["pending"] is False
    finally:
        controller.close()


def test_memory_only_controller_has_no_executor_or_reconciliation_claim(tmp_path):
    store, workspace, catalog = _owner(tmp_path, sessions=False)
    controller = SessionPublicationController(store, workspace, catalog)
    before = store.read_published_index()
    try:
        controller.start()
        assert controller.reconcile(timeout=1)["pending"] is False
        assert controller.wait_idle(0) and controller.status()["jobCount"] == 0
        assert store.read_published_index() == before
    finally:
        controller.close()


@pytest.mark.parametrize("malformed", [False, True])
def test_diagnostics_redact_secrets_and_broken_exception_text_cannot_strand_jobs(tmp_path, monkeypatch, malformed):
    store, _workspace, catalog, scheduler, controller = _started(tmp_path)
    credential = "actual-controller-credential-987654321"
    secret_registry.register_secret_value_for_redaction(credential)

    class UnformattableError(Exception):
        def __str__(self):
            raise RuntimeError("cannot format this source failure")

    error = UnformattableError() if malformed else OSError("source refused " + credential)

    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(store, "reindex_sources", refuse)
    try:
        _append(catalog, "alpha", "Actual diagnostic failure.", "diagnostic-failure")
        scheduler.calls[0][1].fire()
        assert controller.wait_idle(3)
        state = controller.status()
        assert state["state"] == "failed" and state["activeJobs"] == 0
        assert credential not in repr(state)
        if malformed:
            assert state["lastError"]["message"] == "Session publication diagnostic could not be formatted"
    finally:
        controller.close()
        secret_registry.reset_secret_redaction_registry()


def test_executor_admission_failure_retains_claim_without_phantom_active_job(tmp_path, monkeypatch):
    _store, _workspace, catalog, scheduler, controller = _started(tmp_path)

    def refuse(*args, **kwargs):
        raise RuntimeError("actual executor admission failed")

    monkeypatch.setattr(controller._executor, "submit", refuse)
    try:
        _append(catalog, "alpha", "Queue survives admission refusal.", "admission-refusal")
        scheduler.calls[0][1].fire()
        assert controller.wait_idle(0)
        assert controller.status()["pendingPaths"] == ["sessions/main/alpha.jsonl"]
        assert controller.status()["lastError"]["message"] == "actual executor admission failed"
    finally:
        controller.close()


def test_scheduler_admission_failure_keeps_real_committed_target_for_explicit_flush(tmp_path):
    store, workspace, catalog = _owner(tmp_path)

    def refuse_scheduler(*args):
        raise RuntimeError("actual timer admission failed")

    controller = SessionPublicationController(store, workspace, catalog, scheduler=refuse_scheduler)
    try:
        controller.start()
        assert controller.wait_idle(3)
        result = _append(catalog, "alpha", "The committed target outlives timer failure.", "timer-refusal")
        assert result["appended"] and catalog.transcript_listener_diagnostics()
        assert controller.status()["pendingPaths"] == ["sessions/main/alpha.jsonl"]
        assert controller.status()["lastError"]["message"] == "actual timer admission failed"
        assert controller.flush(timeout=3)["pending"] is False
        assert "timer failure" in next(row["text"] for row in _rows(store) if row["path"].endswith("/alpha.jsonl"))
    finally:
        controller.close()


def test_foreign_agent_notifications_and_closed_controller_callbacks_cannot_admit_work(tmp_path):
    store, _workspace, catalog, scheduler, controller = _started(tmp_path)
    foreign = MemorySessionCatalog(catalog.path, agent_id="other", clock_ms=lambda: NOW)
    key = "agent:other:dm:alpha"
    foreign.upsert_session(key, {"sessionId": "alpha", "updatedAt": NOW})
    foreign.append_message("alpha", {"role": "user", "content": "Foreign namespace"},
        session_key=key, event_id="foreign", now_ms=NOW)
    assert not scheduler.calls and controller.status()["generation"] == 0
    before = store.read_published_index()
    controller.close()
    _append(catalog, "alpha", "After the owner closed.", "after-close")
    assert not scheduler.calls and controller.status()["generation"] == 0
    assert store.read_published_index() == before


def test_successor_admitted_during_previous_worker_exit_keeps_physical_custody(tmp_path, monkeypatch):
    store, _workspace, catalog, scheduler, controller = _started(tmp_path)
    old_released, finish_old = threading.Event(), threading.Event()
    successor_entered, finish_successor = threading.Event(), threading.Event()
    condition, publish = controller._condition, store.reindex_sources
    gated = False
    publications = 0

    class CompletionGate:
        """Pause at lock release without replacing a publisher or its result."""
        def __enter__(self):
            return condition.__enter__()

        def __exit__(self, *args):
            nonlocal gated
            condition.__exit__(*args)
            if controller.owns_current_job() and not controller._active and not gated:
                gated = True
                old_released.set()
                assert finish_old.wait(3)

        def __getattr__(self, name):
            return getattr(condition, name)

    def observed_publish(*args, **kwargs):
        nonlocal publications
        publications += 1
        if publications == 2:
            successor_entered.set()
            assert finish_successor.wait(3)
        return publish(*args, **kwargs)

    monkeypatch.setattr(controller, "_condition", CompletionGate())
    monkeypatch.setattr(store, "reindex_sources", observed_publish)
    try:
        _append(catalog, "alpha", "First exiting publication.", "exit-first")
        scheduler.calls[0][1].fire()
        assert old_released.wait(3)
        _append(catalog, "beta", "Successor keeps its actual source lane.", "exit-successor")
        scheduler.calls[1][1].fire()
        finish_old.set()
        assert successor_entered.wait(3)
        assert not controller.wait_idle(0)
        finish_successor.set()
        assert controller.wait_idle(3)
        assert controller.status()["publishedGeneration"] == controller.status()["generation"]
        assert "Successor keeps" in next(row["text"] for row in _rows(store) if row["path"].endswith("/beta.jsonl"))
    finally:
        finish_old.set()
        finish_successor.set()
        controller.close()


def test_binding_refuses_other_workspace_and_properties_are_read_only(tmp_path):
    store, workspace, catalog = _owner(tmp_path)
    controller = SessionPublicationController(store, workspace, catalog)
    assert controller.store is store and controller.workspace is workspace and controller.catalog is catalog
    with pytest.raises(AttributeError):
        controller.store = store
    with pytest.raises(ValueError, match="exact store"):
        controller.assert_bound(workspace=MemoryWorkspace(tmp_path / "foreign", session_catalog=catalog))
    assert not controller.owns_current_job()
    controller.close()
