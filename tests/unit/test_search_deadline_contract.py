"""Actual search supervision, retained evidence, cancellation and retry admission."""

from dataclasses import replace
import threading

import pytest

from memory_core.cancellation import CancellationSignal
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.supplements import RegisteredMemoryCorpusSupplement, StaticMemoryCorpusSupplement
from memory_core.tools.deadline import MemoryToolDeadlineContext
from memory_core.tools.memory_search import (
    MemorySearchToolContext,
    execute_memory_search_tool,
    memory_search_tool_cooldown_key,
    read_memory_search_tool_cooldown_failure,
)


class Clock:
    """A host scheduler whose real production callbacks own timer outcomes."""

    def __init__(self):
        self.now = 0
        self.condition = threading.Condition()
        self.timers = []

    def read(self):
        with self.condition:
            return self.now

    def schedule(self, delay, callback):
        with self.condition:
            timer = {"at": self.now + delay, "callback": callback, "cancelled": False}
            self.timers.append(timer)
            self.condition.notify_all()

        def cancel():
            with self.condition:
                timer["cancelled"] = True
                self.condition.notify_all()

        return cancel

    def advance(self, milliseconds, *, dispatch=True):
        with self.condition:
            target = self.now + milliseconds
        while dispatch:
            with self.condition:
                due = [timer for timer in self.timers if not timer["cancelled"] and timer["at"] <= target]
                if not due:
                    break
                timer = min(due, key=lambda candidate: candidate["at"])
                self.now = timer["at"]
                timer["cancelled"] = True
            timer["callback"]()
        with self.condition:
            self.now = target

    def context(self, signal=None):
        return MemoryToolDeadlineContext(signal=signal, clock=self.read, schedule=self.schedule)

    def wait_for_cancelled_timer(self):
        with self.condition:
            assert self.condition.wait_for(
                lambda: any(timer["cancelled"] for timer in self.timers), timeout=2,
            )


class Backend:
    supports_partial_results = True
    embeddings = None

    def __init__(self, config, search):
        self.config = config
        self.path = config.resolved_store_path()
        self.flags = config.effective_flags()
        self.perform = search
        self.calls = []
        self.keyword_queries = 0
        self.state = {"backend": "host", "provider": "none", "custom": {"indexIdentity": {"status": "valid"}}}

    def status(self):
        return self.state

    def index_identity(self):
        return self.state["custom"]["indexIdentity"]

    def search(self, query, **options):
        self.calls.append((query, options))
        return self.perform(**options)

    def search_memory_keywords(self, *args, **kwargs):
        self.keyword_queries += 1
        return [row("fresh-after-deadline.md")]


def row(path="memory/captured.md", source="memory"):
    return {"path": path, "source": source, "startLine": 1, "endLine": 1,
            "score": 0.9, "snippet": "Captured evidence.", "provenance": None}


def setup(tmp_path, perform, *, clock=None, signal=None, **context_options):
    clock = clock or Clock()
    config = MemoryConfig(workspace_dir=tmp_path, session_search=False,
                          flags=FeatureFlags(vector_search=False), citation_mode="off")
    backend = Backend(config, perform)
    context = MemorySearchToolContext(clock=clock.read, execution=clock.context(signal), **context_options)
    return config, backend, context, clock


def call(config, backend, context, **params):
    return execute_memory_search_tool(config, backend, {"query": "captured", **params}, context=context)


def background(run):
    result = {}

    def work():
        try:
            result["value"] = run()
        except BaseException as error:
            result["exception"] = error

    thread = threading.Thread(target=work)
    thread.start()
    return thread, result


def join(thread):
    thread.join(2)
    assert not thread.is_alive()


@pytest.mark.parametrize("elapsed,timed_out", [(29_999, False), (30_000, True), (30_001, True)])
def test_completion_checks_absolute_budget_even_before_timer_dispatch(tmp_path, elapsed, timed_out):
    clock = Clock()

    def perform(**options):
        clock.advance(elapsed, dispatch=False)
        return [row()]

    config, backend, context, _ = setup(tmp_path, perform, clock=clock)
    result = call(config, backend, context)
    assert result.get("timedOut", False) is timed_out
    if timed_out:
        assert result["results"] == []
        assert result["error"] == "memory_search timed out after 30s"
        assert result["warning"] == "Memory search did not finish within its time limit."
    else:
        assert result["results"][0]["path"] == "memory/captured.md"
        assert result["debug"]["searchMs"] == elapsed


def test_partial_uses_predeadline_memory_snapshot_and_ignores_late_publication(tmp_path):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def perform(**options):
        options["on_partial_results"]([row(), row("sessions/private", "sessions")])
        entered.set()
        try:
            assert release.wait(2)
            options["on_partial_results"]([row("memory/late.md")])
            return [row("memory/late.md")]
        finally:
            finished.set()

    config, backend, context, clock = setup(tmp_path, perform)
    thread, output = background(lambda: call(config, backend, context, corpus="memory"))
    assert entered.wait(2)
    clock.advance(30_000)
    join(thread)
    result = output["value"]
    assert result["partial"] is True and result["timedOut"] is True
    assert [hit["path"] for hit in result["results"]] == ["memory/captured.md"]
    assert result["results"][0]["provenance"] is None
    assert result["debug"]["effectiveMode"] == "keyword-only"
    assert result["debug"]["searchMs"] == 30_000
    assert result["debug"]["fallback"] == "memory_search timed out after 30s"
    assert backend.keyword_queries == 0
    key = memory_search_tool_cooldown_key(config, backend)
    assert read_memory_search_tool_cooldown_failure(key, now_ms=clock.read) is None
    release.set()
    assert finished.wait(2)
    assert [hit["path"] for hit in result["results"]] == ["memory/captured.md"]


def test_invalidated_snapshot_cannot_be_rescued_by_a_new_keyword_query(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def perform(**options):
        options["on_partial_results"]([row()])
        options["on_partial_results"](None)
        entered.set()
        assert release.wait(2)
        options["signal"].throw_if_aborted()

    config, backend, context, clock = setup(tmp_path, perform)
    thread, output = background(lambda: call(config, backend, context))
    assert entered.wait(2)
    clock.advance(30_000)
    join(thread)
    release.set()
    assert output["value"]["unavailable"] is True
    assert "partial" not in output["value"]
    assert backend.keyword_queries == 0


def test_parent_abort_keeps_exception_identity_and_does_not_record_cooldown(tmp_path):
    entered, release = threading.Event(), threading.Event()
    signal = CancellationSignal()
    reason = RuntimeError("caller cancelled this run")

    def perform(**options):
        options["on_partial_results"]([row()])
        entered.set()
        assert release.wait(2)
        options["signal"].throw_if_aborted()

    config, backend, context, clock = setup(tmp_path, perform, signal=signal)
    thread, output = background(lambda: call(config, backend, context))
    assert entered.wait(2)
    signal.abort(reason)
    join(thread)
    release.set()
    assert output["exception"] is reason
    key = memory_search_tool_cooldown_key(config, backend)
    assert read_memory_search_tool_cooldown_failure(key, now_ms=clock.read) is None


def test_preaborted_parent_precedes_argument_validation_and_backend_admission(tmp_path):
    signal = CancellationSignal()
    reason = RuntimeError("already cancelled")
    signal.abort(reason)
    config, backend, context, _ = setup(tmp_path, lambda **kwargs: [], signal=signal)
    with pytest.raises(RuntimeError) as raised:
        execute_memory_search_tool(config, backend, {"query": ""}, context=context)
    assert raised.value is reason
    assert backend.calls == []


def test_disabled_session_search_does_not_admit_a_deadline_or_backend(tmp_path):
    config, backend, context, clock = setup(tmp_path, lambda **options: [])
    result = call(config, backend, context, corpus="sessions")
    assert result["unavailable"] is True
    assert result["error"] == "Session transcript search is not enabled."
    assert backend.calls == [] and clock.timers == []


def test_message_and_copied_properties_do_not_forge_deadline_provenance(tmp_path):
    class ProviderFailure(RuntimeError):
        deadline = True
        timeout_ms = 30_000

    def perform(**options):
        options["on_partial_results"]([row()])
        raise ProviderFailure("memory_search timed out after 30s")

    config, backend, context, _ = setup(tmp_path, perform)
    result = call(config, backend, context)
    assert result["unavailable"] is True
    assert "timedOut" not in result and "partial" not in result
    assert result["warning"] == "Memory search is unavailable due to an embedding/provider error."


def test_cooldown_expires_at_boundary_and_config_changes_revoke_old_failure(tmp_path):
    attempts = 0

    def perform(**options):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("provider unavailable")
        return [row()]

    config, backend, context, clock = setup(tmp_path, perform)
    assert call(config, backend, context)["unavailable"] is True
    clock.advance(59_999)
    assert call(config, backend, context)["unavailable"] is True
    assert attempts == 1
    clock.advance(1)
    assert call(config, backend, context)["results"]
    assert attempts == 2

    def fail(**options):
        raise RuntimeError("another failure")

    backend.perform = fail
    assert call(config, backend, context)["unavailable"] is True
    backend.perform = lambda **options: [row()]
    changed = replace(config, citation_mode="on")
    assert call(changed, backend, context)["results"]


def test_closed_manager_refreshes_once_and_drops_old_partial_generation(tmp_path):
    clock = Clock()

    def closed(**options):
        options["on_partial_results"]([row("memory/retired.md")])
        raise RuntimeError("memory index manager is closed")

    config, backend, context, _ = setup(tmp_path, closed, clock=clock)
    fresh = Backend(config, lambda **options: [row("memory/fresh.md")])
    refreshes = []

    def refresh():
        refreshes.append(True)
        clock.advance(4)
        return fresh

    result = call(config, backend, replace(context, refresh_store=refresh))
    assert [hit["path"] for hit in result["results"]] == ["memory/fresh.md"]
    assert result["debug"]["managerMs"] == 4
    assert len(backend.calls) == len(fresh.calls) == len(refreshes) == 1


@pytest.mark.parametrize("owner", ["workspace", "index", "agent"])
def test_refresh_cannot_route_to_another_workspace_index_or_agent(tmp_path, owner):
    def closed(**options):
        raise RuntimeError("memory index manager is closed")

    config, backend, context, _ = setup(tmp_path, closed)
    changes = {
        "workspace": {"workspace_dir": tmp_path / "other", "store_path": config.resolved_store_path()},
        "index": {"store_path": tmp_path / "other.sqlite"},
        "agent": {"agent_id": "another", "store_path": config.resolved_store_path()},
    }
    other = Backend(replace(config, **changes[owner]), lambda **options: [row()])
    result = call(config, backend, replace(context, refresh_store=lambda: other))
    assert result["unavailable"] is True
    assert result["error"] == (
        "Refreshed memory search store belongs to a different workspace, index, or agent; "
        "create a new tool with its matching store."
    )
    assert other.calls == []


def test_refresh_is_not_repeated_and_parent_abort_prevents_refresh(tmp_path):
    signal = CancellationSignal()
    reason = RuntimeError("caller stopped")

    def cancelled_closed(**options):
        signal.abort(reason)
        raise RuntimeError("database connection is not open")

    config, backend, context, _ = setup(tmp_path, cancelled_closed, signal=signal)
    refreshes = []
    context = replace(context, refresh_store=lambda: refreshes.append(True))
    with pytest.raises(RuntimeError) as raised:
        call(config, backend, context)
    assert raised.value is reason and refreshes == []

    def closed(**options):
        raise RuntimeError("database handle is closed")

    config, backend, context, _ = setup(tmp_path, closed)
    fresh = Backend(config, closed)

    def refresh():
        refreshes.append(True)
        return fresh

    result = call(config, backend, replace(context, refresh_store=refresh))
    assert result["unavailable"] is True
    assert len(refreshes) == len(backend.calls) == len(fresh.calls) == 1


def test_memory_pause_does_not_erase_wiki_success_committed_before_late_join(tmp_path):
    paused, resume, resumed, release = (threading.Event() for _ in range(4))

    def perform(**options):
        options["on_partial_results"]([row()])
        options["deadline_control"].report("pause")
        paused.set()
        assert resume.wait(2)
        options["deadline_control"].report("resume")
        resumed.set()
        assert release.wait(2)
        options["signal"].throw_if_aborted()

    config, backend, context, clock = setup(tmp_path, perform)
    wiki_row = {"corpus": "wiki", "path": "wiki/early", "score": 0.8, "snippet": "Early wiki evidence."}
    wiki = RegisteredMemoryCorpusSupplement(
        "wiki", StaticMemoryCorpusSupplement([]), searcher=lambda **kwargs: [wiki_row],
    )
    thread, output = background(lambda: execute_memory_search_tool(
        config, backend, {"query": "captured", "corpus": "all"},
        context=context, supplements=[wiki],
    ))
    assert paused.wait(2)
    with clock.condition:
        # Timer 0 belongs to paused primary memory. Cancellation of timer 1
        # proves the independent wiki owner committed its success already.
        assert clock.condition.wait_for(
            lambda: len(clock.timers) >= 2 and clock.timers[1]["cancelled"], timeout=2,
        )
    clock.advance(45_000)
    assert thread.is_alive()
    resume.set()
    assert resumed.wait(2)
    clock.advance(30_000)
    join(thread)
    release.set()
    result = output["value"]
    assert result["partial"] is True
    assert [hit["path"] for hit in result["results"]] == ["memory/captured.md", "wiki/early"]
    assert result["results"][1] == wiki_row
    assert result["corpora"] == [
        {"corpus": "memory", "outcome": "partial", "error": "memory_search timed out after 30s"},
        {"corpus": "wiki", "outcome": "ok"},
    ]
    assert result["debug"]["searchMs"] == 75_000
