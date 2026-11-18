"""Select host-owned event occurrences for a heartbeat and build its reminder text."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re

from memory_core._heartbeat_constants import HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS
from memory_core.bootstrap._js import js_trim, truncate_utf16_safe, utf16_len


@dataclass(frozen=True)
class HeartbeatSystemEvent:
    """One occurrence from the host's selected session event queue."""
    id: str
    text: str
    context_key: str = ""


@dataclass(frozen=True)
class HeartbeatEventSelection:
    has_tagged_cron: bool
    exec_events: tuple[HeartbeatSystemEvent, ...]
    cron_events: tuple[HeartbeatSystemEvent, ...]
    cron_noise: tuple[HeartbeatSystemEvent, ...]

    def occurrences(self, *, has_tasks: bool) -> tuple[str, ...]:
        prompt_events = () if has_tasks else (self.exec_events or self.cron_events)
        return tuple(event.id for event in (*self.cron_noise, *prompt_events))


def select_heartbeat_events(events: Sequence[HeartbeatSystemEvent], *, exec_wake: bool, cron_wake: bool,
                            wake_payload: bool, inspects_run_queue: bool) -> HeartbeatEventSelection:
    from memory_core.heartbeat import is_heartbeat_acknowledgement_text
    from memory_core.session_entry import is_exec_completion_event

    visible = [event for event in events if not event.context_key.startswith("heartbeat-delivery:")]
    tagged = any(event.context_key.startswith("cron:") for event in visible)
    inspect = exec_wake or cron_wake or (wake_payload and inspects_run_queue) or tagged
    exec_events, cron_events, noise = [], [], []
    for event in visible:
        if event.context_key.startswith("session-created:"):
            continue
        if is_exec_completion_event(event.text):
            if inspect:
                exec_events.append(event)
        elif cron_wake or event.context_key.startswith("cron:"):
            text = js_trim(event.text).lower()
            quiet = (not text or is_heartbeat_acknowledgement_text(event.text, max_ack_chars=0)
                     or bool(re.match(r"heartbeat_ok(?:[^a-z0-9_]|$)", text))
                     or "heartbeat poll" in text or "heartbeat wake" in text)
            (noise if quiet else cron_events).append(event)
    return HeartbeatEventSelection(tagged, tuple(exec_events), tuple(cron_events), tuple(noise))


_STRUCTURED = re.compile(r"exec (completed|failed) \(([a-z0-9_-]{1,64}), (code -?[0-9]+|signal [^)]+)\)(?: :: ([\s\S]*))?", re.I | re.ASCII)


def _exec_prompt(events: tuple[HeartbeatSystemEvent, ...], relay: bool, use_tool: bool) -> str:
    output = []
    no_output_failure = False
    for event in events:
        text = js_trim(event.text)
        match = _STRUCTURED.fullmatch(text)
        if not match or js_trim(match[4] or ""):
            if text:
                output.append(text)
        elif match[1].lower() != "completed" or match[3].lower() != "code 0":
            no_output_failure = True
            output.append(f"Exec {match[1]} ({match[2]}, {match[3]}) without captured stdout/stderr.")
    content = js_trim("\n".join(output))
    if utf16_len(content) > 8000:
        content = truncate_utf16_safe(content, 8000) + "\n\n[truncated]"
    if not content:
        instruction = HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS if use_tool else "Reply NO_REPLY only."
        return ("An async command completion event was triggered, but no command output was found. "
                + instruction + " Do not mention, summarize, or reuse output from any earlier run.")
    if not relay:
        instruction = ("Handle the result internally. " + HEARTBEAT_RESPONSE_TOOL_INSTRUCTIONS if use_tool
                       else "Handle the result internally and reply NO_REPLY only.")
        return ("An async command completion event was triggered, but user delivery is disabled for this run. "
                + instruction + " Do not mention, summarize, or reuse command output.")
    if no_output_failure:
        return ("An async command you ran earlier completed without captured stdout/stderr. The completion details are:\n\n"
                + content + "\n\nTell the user the command completed without captured output and include the exit status or signal. "
                "Do not ask the user to provide missing logs, and do not try to retrieve logs from an exec/session id.")
    return ("An async command you ran earlier has completed. The command completion details are:\n\n" + content
            + "\n\nPlease relay the command output to the user in a helpful way. If the command succeeded, share the relevant output. "
              "If it failed, explain what went wrong.")


def heartbeat_event_prompt(selection: HeartbeatEventSelection, *, relay: bool, use_tool: bool) -> str | None:
    if selection.exec_events:
        return _exec_prompt(selection.exec_events, relay, use_tool)
    if selection.cron_events:
        content = js_trim("\n".join(event.text for event in selection.cron_events))
        instruction = ("Please relay this reminder to the user in a helpful and friendly way." if relay else
                       "Handle this reminder internally. Do not relay it to the user unless explicitly requested.")
        return "A scheduled reminder has been triggered. The reminder content is:\n\n" + content + "\n\n" + instruction
    return None
