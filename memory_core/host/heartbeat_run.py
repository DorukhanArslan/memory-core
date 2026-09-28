"""One heartbeat run a host's scheduler started (docs/host_kit.md, entry point 6).

``HostKit.heartbeat_prompt`` returns a :class:`HeartbeatRun`: the turn (or its skip reason),
the due jobs whose tasks it carries, the other due jobs (the host's to run) and the context of
the model call. :meth:`HeartbeatRun.complete` reads the reply (``decide_heartbeat_reply``),
records the runs of the jobs in the turn and the session's token snapshot. Heartbeat runs never
decide a memory flush (upstream skips session maintenance for heartbeats).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from memory_core.automation import AutomationJob, AutomationStore, record_automation_job_run
from memory_core.heartbeat import HeartbeatReplyDecision, HeartbeatTurn, decide_heartbeat_reply
from memory_core.host.session import SessionState, TurnUsage, apply_turn_usage

if TYPE_CHECKING:
    from memory_core.host.kit import TurnContext


@dataclass(frozen=True)
class HeartbeatOutcome:
    """The session after the run, the reply decision, the job runs recorded and the transcript.

    ``transcript`` is what the host records: the heartbeat row and the raw reply, which the
    session corpus filter drops again. The host delivers ``decision.text`` only when
    ``decision.deliver``.
    """

    session: SessionState
    decision: HeartbeatReplyDecision
    jobs_recorded: tuple[AutomationJob, ...]
    transcript: tuple[dict[str, str], ...]


class HeartbeatRun:
    """A prepared heartbeat turn; ``context`` is ``None`` when it is skipped (no model call)."""

    def __init__(
        self,
        *,
        session: SessionState,
        turn: HeartbeatTurn,
        jobs: tuple[AutomationJob, ...],
        host_jobs: tuple[AutomationJob, ...],
        context: TurnContext | None,
        transcript_prompt: str,
        started_at_ms: int,
        store: AutomationStore,
        agent_id: str,
    ) -> None:
        self.session = session
        self.turn = turn
        self.jobs = jobs
        self.host_jobs = host_jobs
        self.context = context
        self.transcript_prompt = transcript_prompt
        self.started_at_ms = started_at_ms
        self._store = store
        self._agent_id = agent_id
        self._completed = False

    def complete(
        self,
        reply: str | None,
        *,
        usage: TurnUsage | None = None,
        response_prefix: str | None = None,
        ended_at_ms: int | None = None,
    ) -> HeartbeatOutcome:
        """Read the reply and record the run (``RuntimeError`` for a second call).

        The jobs are re-read first: a job the host edited or removed while the run was in flight
        (no longer equal to the copy the run loaded) is neither written back nor brought back.
        The others get ``record_automation_job_run`` from ``started_at_ms`` to ``ended_at_ms``
        (default: the start) in one ``save_jobs`` call. A failed model call is not completed:
        its jobs stay due.
        """
        if self._completed:
            raise RuntimeError("the heartbeat run is already completed")
        self._completed = True
        decision = decide_heartbeat_reply(reply, response_prefix=response_prefix)
        current = {job.id: job for job in self._store.list_jobs(agent_id=self._agent_id)}
        recorded = tuple(
            record_automation_job_run(
                job, started_at_ms=self.started_at_ms, ended_at_ms=ended_at_ms
            )
            for job in self.jobs
            if current.get(job.id) == job
        )
        if recorded:
            self._store.save_jobs(recorded)
        return HeartbeatOutcome(
            # A skipped run made no model call, so it has no usage to record.
            session=self.session if self.context is None else apply_turn_usage(self.session, usage),
            decision=decision,
            jobs_recorded=recorded,
            transcript=(
                {"role": "user", "content": self.transcript_prompt},
                {"role": "assistant", "content": reply or ""},
            ),
        )
