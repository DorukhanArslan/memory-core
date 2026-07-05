from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from memory_core.live import (
    JsonlTraceSink,
    LiveIdentityStore,
    LiveTurnContext,
    LiveTurnEvent,
    SubjectMemory,
)


DEFAULT_LIVE_TASK_SESSION_ID = "demo_session"
DEFAULT_LIVE_TASK_SUBJECT_ID = "demo_subject"


@dataclass(frozen=True)
class LiveTaskSessionState:
    session_id: str
    subject_id: str
    task_id: str = "appointment_reschedule"
    current_step: str = "verify_identity"
    verified: bool = False
    requested_slot: str | None = None
    completed: bool = False
    business_action: dict[str, Any] | None = None


@dataclass(frozen=True)
class LiveTaskDemoState:
    workflow: dict[str, Any]
    transcript: list[dict[str, str]]
    workspace: str
    trace_path: str


class LiveTaskDemo:
    def __init__(self, *, workspace_dir: str | Path):
        self.workspace_dir = Path(workspace_dir)
        self.identity_dir = self.workspace_dir / "identity"
        self.trace_dir = self.workspace_dir / "trace" / "live-task"
        self._state = LiveTaskSessionState(
            session_id=DEFAULT_LIVE_TASK_SESSION_ID,
            subject_id=DEFAULT_LIVE_TASK_SUBJECT_ID,
        )
        self._transcript: list[dict[str, str]] = []

    def reset(
        self,
        *,
        session_id: str = DEFAULT_LIVE_TASK_SESSION_ID,
        subject_id: str = DEFAULT_LIVE_TASK_SUBJECT_ID,
    ) -> LiveTaskDemoState:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._bootstrap_identity()
        self._state = LiveTaskSessionState(session_id=session_id, subject_id=subject_id)
        self._transcript = []
        return self.state()

    def state(self) -> LiveTaskDemoState:
        return LiveTaskDemoState(
            workflow=asdict(self._state),
            transcript=list(self._transcript),
            workspace=str(self.workspace_dir),
            trace_path=str(self._trace_path(self._state.session_id)),
        )

    async def stream_turn(
        self,
        *,
        session_id: str,
        subject_id: str,
        user_utterance: str,
    ) -> AsyncIterator[dict[str, Any]]:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._bootstrap_identity()
        if self._state.session_id != session_id or self._state.subject_id != subject_id:
            self._state = LiveTaskSessionState(session_id=session_id, subject_id=subject_id)
            self._transcript = []

        next_state = advance_appointment_workflow(self._state, user_utterance)
        memory = SubjectMemory.open(
            workspace_dir=self.workspace_dir,
            subject_id=subject_id,
            reindex=False,
        )
        identity = LiveIdentityStore(
            self.identity_dir,
            required_files=("AGENT.md", "POLICY.md", "STYLE.md"),
        ).load()
        trace_sink = JsonlTraceSink(self._trace_path(session_id))
        context = LiveTurnContext(
            subject_id=subject_id,
            session_id=session_id,
            user_utterance=user_utterance,
            transcript_window=_format_transcript(self._transcript),
            workflow_state=asdict(next_state),
        )
        assistant_parts: list[str] = []
        started_at = time.monotonic()
        async for event in memory.stream_live_turn(
            context,
            llm=lambda messages: _fake_live_task_stream(messages, next_state),
            identity=identity,
            trace_sink=trace_sink,
        ):
            if event.text:
                assistant_parts.append(event.text)
            yield latency_event_payload(
                event_type=event.type,
                text=event.text,
                data=event.data,
                started_at=started_at,
                now=time.monotonic(),
            )

        self._state = next_state
        self._transcript.append({"role": "user", "content": user_utterance})
        self._transcript.append({"role": "assistant", "content": "".join(assistant_parts).strip()})

    def record_summary(
        self,
        *,
        session_id: str,
        subject_id: str,
        transcript: str | None = None,
    ) -> dict[str, Any]:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        memory = SubjectMemory.open(
            workspace_dir=self.workspace_dir,
            subject_id=subject_id,
            reindex=False,
        )
        transcript_text = transcript or _format_transcript(self._transcript)
        result = memory.record_session_summary(
            session_id=session_id,
            transcript=transcript_text,
            summary_llm=_fake_summary_llm,
            timezone="Europe/Istanbul",
            trace_sink=JsonlTraceSink(self._trace_path(session_id)),
        )
        return {
            "wrote": result.wrote,
            "path": result.path,
            "text": result.text,
            "raw_text": result.raw_text,
            "durable_facts": list(result.durable_facts),
            "preferences": list(result.preferences),
            "follow_ups": list(result.follow_ups),
            "admin_review_suggestions": list(result.admin_review_suggestions),
        }

    def _bootstrap_identity(self) -> None:
        self.identity_dir.mkdir(parents=True, exist_ok=True)
        defaults = {
            "AGENT.md": (
                "You are a live task agent for appointment changes. "
                "Keep replies concise and suitable for text-to-speech."
            ),
            "POLICY.md": (
                "Verify the subject before changing an appointment. "
                "Do not confirm a change until the subject explicitly approves it."
            ),
            "STYLE.md": "Use short sentences. Ask for one missing item at a time.",
            "ESCALATION.md": (
                "Escalate if identity cannot be verified or the requested appointment is unclear."
            ),
        }
        for filename, content in defaults.items():
            path = self.identity_dir / filename
            if not path.exists():
                path.write_text(content + "\n", encoding="utf-8")

    def _trace_path(self, session_id: str) -> Path:
        return self.trace_dir / f"{session_id}.jsonl"


def advance_appointment_workflow(
    state: LiveTaskSessionState,
    utterance: str,
) -> LiveTaskSessionState:
    text = utterance.casefold()
    if state.current_step == "verify_identity":
        if _looks_like_identity_proof(text):
            return replace(state, current_step="collect_new_time", verified=True)
        return state
    if state.current_step == "collect_new_time":
        if _looks_like_time_request(text):
            return replace(state, current_step="confirm_change", requested_slot=utterance.strip())
        return state
    if state.current_step == "confirm_change":
        if _is_confirmation(text):
            return replace(
                state,
                current_step="completed",
                completed=True,
                business_action={
                    "type": "appointment_rescheduled",
                    "requested_slot": state.requested_slot,
                },
            )
        if _is_rejection(text):
            return replace(state, current_step="collect_new_time")
    return state


def latency_event_payload(
    *,
    event_type: str,
    text: str,
    data: dict[str, Any] | None,
    started_at: float,
    now: float,
) -> dict[str, Any]:
    return {
        "type": event_type,
        "text": text,
        "data": data or {},
        "elapsed_ms": int(round((now - started_at) * 1000)),
    }


async def _fake_live_task_stream(
    messages: list[dict[str, str]],
    state: LiveTaskSessionState,
) -> AsyncIterator[str | dict[str, Any]]:
    del messages
    yield {"type": "workflow_state", "state": asdict(state)}
    for chunk in _response_chunks(state):
        yield chunk


def _response_chunks(state: LiveTaskSessionState) -> tuple[str, ...]:
    if state.current_step == "verify_identity":
        return ("Kimliğinizi doğrulamak için ", "doğum tarihinizi paylaşır mısınız?")
    if state.current_step == "collect_new_time":
        return ("Kimliğiniz doğrulandı. ", "Randevuyu hangi gün ve saate almak istersiniz?")
    if state.current_step == "confirm_change":
        return ("Yeni zamanı not ettim. ", "Değişikliği onaylıyor musunuz?")
    if state.current_step == "completed":
        return ("Randevu değişikliğini onayladım. ", "Kayıt güncellenecek.")
    return ("Devam edebiliriz.",)


def _fake_summary_llm(messages: list[dict[str, str]]) -> str:
    del messages
    return json.dumps(
        {
            "durable_facts": ["Subject completed an appointment reschedule flow."],
            "follow_ups": ["Confirm appointment change with the scheduling system."],
        }
    )


def _format_transcript(transcript: list[dict[str, str]]) -> str:
    return "\n".join(f"{item['role']}: {item['content']}" for item in transcript)


def _looks_like_identity_proof(text: str) -> bool:
    return any(char.isdigit() for char in text) or "kimlik" in text or "dogum" in text or "doğum" in text


def _looks_like_time_request(text: str) -> bool:
    return any(marker in text for marker in ("bugün", "bugun", "yarın", "yarin", "saat", ":"))


def _is_confirmation(text: str) -> bool:
    return any(marker in text for marker in ("evet", "onay", "tamam", "olur"))


def _is_rejection(text: str) -> bool:
    return any(marker in text for marker in ("hayır", "hayir", "vazgeç", "vazgec"))
