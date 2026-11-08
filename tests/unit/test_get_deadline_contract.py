"""Real worker/cancellation paths driven by a host-controlled monotonic timer."""

from copy import deepcopy
import threading

import pytest

from memory_core.cancellation import CancellationSignal, OperationAbortedError
from memory_core.config import MemoryConfig
from memory_core.supplements import RegisteredMemoryCorpusSupplement, StaticMemoryCorpusSupplement
from memory_core.tools.common import MemoryToolError, MemoryToolInputError
from memory_core.tools.corpus import attempt_corpus, unavailable_corpus
from memory_core.tools.deadline import (
    DeadlineWorker,
    MemorySearchDeadlineControl,
    MemoryToolDeadlineContext,
    is_memory_search_deadline_error,
    run_memory_corpus_deadline,
    run_memory_search_with_deadline,
)
from memory_core.tools.get_factory import create_memory_get_tool
import memory_core.tools.memory_get as get_module


class _Timers:
    def __init__(self):
        self.now = 0
        self.lock = threading.Lock()
        self.pending = []

    def clock(self):
        with self.lock:
            return self.now

    def schedule(self, delay, callback):
        entry = {"at": self.clock() + delay, "callback": callback, "cancelled": False}
        with self.lock:
            self.pending.append(entry)

        def cancel():
            entry["cancelled"] = True

        return cancel

    def advance(self, delta, *, service=True):
        with self.lock:
            self.now += delta
        if service:
            while True:
                with self.lock:
                    due = next((entry for entry in self.pending
                                if not entry["cancelled"] and entry["at"] <= self.now), None)
                    if due is None:
                        return
                    due["cancelled"] = True
                due["callback"]()

    @staticmethod
    def wait(event, _seconds):
        if not event.wait(3):
            raise AssertionError("The real worker did not settle after its controlled event")
        return True

    def context(self, signal=None):
        return MemoryToolDeadlineContext(
            signal=signal, clock=self.clock, schedule=self.schedule, wait=self.wait,
        )


class _Call:
    def __init__(self, run):
        self.done = threading.Event()
        self.value = None
        self.error = None

        def work():
            try:
                self.value = run()
            except BaseException as error:
                self.error = error
            finally:
                self.done.set()

        threading.Thread(target=work, daemon=True).start()

    def finish(self):
        assert self.done.wait(3), "The tool did not finish after its timer or parent cancellation"
        return self


def _registered(plugin_id, reader):
    return RegisteredMemoryCorpusSupplement(
        plugin_id, StaticMemoryCorpusSupplement([]), reader=reader,
    )


def test_supervised_deadline_uses_owned_error_identity_and_ignores_late_completion():
    timers = _Timers()
    entered, release = threading.Event(), threading.Event()
    signals = []

    def run(signal):
        signals.append(signal)
        entered.set()
        release.wait(3)
        return "late provider result"

    call = _Call(lambda: run_memory_search_with_deadline(30_000, run, context=timers.context()))
    try:
        assert entered.wait(3)
        timers.advance(30_000)
        call.finish()
        error = call.error
        assert error is signals[0].reason
        assert str(error) == "memory_search timed out after 30s"
        assert is_memory_search_deadline_error(error)
        assert call.value is None

        class Forged(OperationAbortedError):
            def __eq__(self, _other):
                return True

            def __hash__(self):
                return hash(error)

        copied = Forged(str(error))
        copied.__dict__.update(error.__dict__)
        assert not is_memory_search_deadline_error(copied)
        assert unavailable_corpus("memory", None, copied).deadline is False
    finally:
        release.set()


def test_unserviced_timer_cannot_admit_a_successful_task_that_finished_after_budget():
    timers = _Timers()

    def run(_signal):
        timers.advance(30_000, service=False)
        return "too late"

    with pytest.raises(OperationAbortedError) as raised:
        run_memory_search_with_deadline(30_000, run, context=timers.context())
    assert is_memory_search_deadline_error(raised.value)
    assert len(timers.pending) == 1
    assert timers.pending[0]["cancelled"] is True


def test_already_settled_worker_success_survives_a_later_join():
    timers = _Timers()
    worker = DeadlineWorker("memory_search", lambda _signal: "early", context=timers.context())
    assert worker._worker._done.wait(3)
    timers.advance(40_000)
    assert worker.wait().value == "early"
    assert worker.wait().status == "ok"
    assert not worker.signal.aborted


def test_balanced_pause_resume_preserves_remaining_active_budget():
    timers = _Timers()
    release = threading.Event()
    control = MemorySearchDeadlineControl()
    worker = DeadlineWorker(
        "memory_search", lambda _signal: release.wait(3), context=timers.context(), control=control,
    )
    try:
        timers.advance(10_000)
        control.report("pause")
        control.report("pause")
        timers.advance(50_000)
        control.report("resume")
        timers.advance(50_000)
        assert not worker.signal.aborted
        control.report("resume")
        timers.advance(19_999)
        assert not worker.signal.aborted
        timers.advance(1)
        assert worker.wait().deadline is True
        assert str(worker.wait().exception) == "memory_search timed out after 30s"
    finally:
        release.set()


def test_corpus_owner_preserves_its_bare_callback_semantics():
    timers = _Timers()
    signals = []

    def ignoring(signal, _control):
        signals.append(signal)
        timers.advance(30_000)
        return "callback handled its own cancellation"

    assert run_memory_corpus_deadline("memory_get", ignoring, context=timers.context()) == (
        "callback handled its own cancellation"
    )
    assert is_memory_search_deadline_error(signals[0].reason)


def test_corpus_owner_rejects_newly_detected_overdue_completion():
    timers = _Timers()

    def overdue(_signal, _control):
        timers.advance(30_000, service=False)
        return "overdue"

    with pytest.raises(OperationAbortedError) as raised:
        run_memory_corpus_deadline("memory_get", overdue, context=timers.context())
    assert str(raised.value) == "memory_get timed out after 30s"
    assert is_memory_search_deadline_error(raised.value)
    assert len(timers.pending) == 1
    assert timers.pending[0]["cancelled"] is True


def test_genuine_deadline_retains_only_a_published_partial_value():
    timers = _Timers()
    published, release = threading.Event(), threading.Event()
    partial = [{"path": "memory/partial.md", "snippet": "published"}]

    def task():
        published.set()
        release.wait(3)
        return [{"path": "late.md"}]

    def guarded(signal, _control):
        return attempt_corpus(
            "memory", None, task, signal=signal, context=timers.context(),
            get_partial_value=lambda: deepcopy(partial),
        )

    call = _Call(lambda: run_memory_corpus_deadline(
        "memory_search", guarded, context=timers.context(),
    ))
    try:
        assert published.wait(3)
        timers.advance(30_000)
        call.finish()
        assert call.error is None
        assert call.value.outcome == "partial"
        assert call.value.value == partial
        assert call.value.deadline is True
    finally:
        release.set()


def test_get_wiki_deadline_uses_real_registered_callback_and_complete_envelope(tmp_path):
    timers = _Timers()
    entered, release = threading.Event(), threading.Event()
    calls = []

    def reader(**options):
        calls.append(options)
        entered.set()
        release.wait(3)
        return {"path": "late.md", "content": "late"}

    tool = create_memory_get_tool(
        MemoryConfig(tmp_path), supplements=[_registered("wiki", reader)], execution=timers.context(),
    )
    call = _Call(lambda: tool.execute("call-1", {"path": "wiki.md", "corpus": "wiki"}))
    try:
        assert entered.wait(3)
        timers.advance(30_000)
        call.finish()
        assert call.error is None
        assert call.value["details"] == {
            "path": "wiki.md", "text": "",
            "corpora": [{"corpus": "wiki", "outcome": "unavailable",
                         "error": "memory_get timed out after 30s"}],
            "warning": "Wiki corpus unavailable: memory_get timed out after 30s",
            "error": "memory_get timed out after 30s", "timedOut": True, "timeoutMs": 30_000,
        }
        assert calls == [{"lookup": "wiki.md", "agent_id": "main"}]
    finally:
        release.set()


def test_get_all_keeps_a_completed_builtin_read_when_wiki_times_out(tmp_path, monkeypatch):
    timers = _Timers()
    entered, release, memory_committed = threading.Event(), threading.Event(), threading.Event()
    (tmp_path / "MEMORY.md").write_text("Saved builtin fact.\n", encoding="utf-8")
    actual_attempt = get_module.attempt_corpus

    def observed_attempt(*args, **kwargs):
        result = actual_attempt(*args, **kwargs)
        memory_committed.set()
        return result

    monkeypatch.setattr(get_module, "attempt_corpus", observed_attempt)

    def reader(**_options):
        entered.set()
        release.wait(3)
        return None

    tool = create_memory_get_tool(
        MemoryConfig(tmp_path), supplements=[_registered("wiki", reader)], execution=timers.context(),
    )
    call = _Call(lambda: tool.execute("call-1", {"path": "MEMORY.md", "corpus": "all"}))
    try:
        assert entered.wait(3) and memory_committed.wait(3)
        timers.advance(30_000)
        call.finish()
        assert call.error is None
        result = call.value["details"]
        assert result["text"] == "Saved builtin fact."
        assert result["status"] == "ok"
        assert result["corpora"] == [
            {"corpus": "memory", "outcome": "ok"},
            {"corpus": "wiki", "outcome": "unavailable", "error": "memory_get timed out after 30s"},
        ]
        assert result["timedOut"] is True
    finally:
        release.set()


def test_get_wiki_timeout_keeps_completed_supplement_priority_snapshot(tmp_path):
    timers = _Timers()
    fifth_started, release = threading.Event(), threading.Event()

    def pending(**_options):
        release.wait(3)
        return {"path": "late.md", "content": "late"}

    def fifth(**options):
        # Four workers start a/b/c/d. Reaching e proves that b's real
        # successful value was committed before its worker took another task.
        fifth_started.set()
        return pending(**options)

    providers = [
        _registered("a", pending),
        _registered("b", lambda **_: {"path": "completed.md", "content": "committed"}),
        _registered("c", pending), _registered("d", pending), _registered("e", fifth),
    ]
    tool = create_memory_get_tool(
        MemoryConfig(tmp_path), supplements=providers, execution=timers.context(),
    )
    call = _Call(lambda: tool.execute("call-1", {"path": "wiki.md", "corpus": "wiki"}))
    try:
        assert fifth_started.wait(3)
        timers.advance(30_000)
        call.finish()
        assert call.error is None
        assert call.value["details"]["path"] == "completed.md"
        assert call.value["details"]["text"] == "committed"
        assert call.value["details"]["timedOut"] is True
        snapshot = deepcopy(call.value)
        release.set()
        assert call.value == snapshot
    finally:
        release.set()


def test_get_parent_abort_raises_the_original_reason_without_timeout_metadata(tmp_path):
    timers, parent = _Timers(), CancellationSignal()
    entered, release = threading.Event(), threading.Event()

    def reader(**_options):
        entered.set()
        release.wait(3)
        return None

    tool = create_memory_get_tool(
        MemoryConfig(tmp_path), supplements=[_registered("wiki", reader)], execution=timers.context(),
    )
    reason = MemoryToolError("operator stopped this call")
    call = _Call(lambda: tool.execute("call-1", {"path": "wiki.md", "corpus": "all"}, parent))
    try:
        assert entered.wait(3)
        parent.abort(reason)
        call.finish()
        assert call.error is reason
        assert not is_memory_search_deadline_error(call.error)
        assert call.value is None
    finally:
        release.set()


def test_builtin_only_get_ignores_caller_abort_but_wiki_validates_arguments_first(tmp_path):
    (tmp_path / "MEMORY.md").write_text("Readable builtin fact.\n", encoding="utf-8")
    parent = CancellationSignal()
    parent.abort(None)

    def forbidden_timer(*_args):
        pytest.fail("A builtin-only get must not create a corpus deadline")

    tool = create_memory_get_tool(
        MemoryConfig(tmp_path), execution=MemoryToolDeadlineContext(signal=parent, schedule=forbidden_timer),
    )
    assert tool.execute("call-1", {"path": "MEMORY.md"})["details"]["text"] == "Readable builtin fact."
    with pytest.raises(MemoryToolInputError, match="path required"):
        tool.execute("call-2", {"path": False, "corpus": "wiki"})


def test_registered_search_callback_omits_defaults_and_preserves_false_context():
    calls = []
    provider = RegisteredMemoryCorpusSupplement(
        "wiki", StaticMemoryCorpusSupplement([]), searcher=lambda **kwargs: calls.append(kwargs) or [],
    )
    assert provider.search_native(query="leaf") == []
    assert calls == [{"query": "leaf"}]
    provider.search_native(query="leaf", agent_id="main", sandboxed=False, max_results=2)
    assert calls[-1] == {"query": "leaf", "agent_id": "main", "sandboxed": False, "max_results": 2}
