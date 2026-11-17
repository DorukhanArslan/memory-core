"""Production assembly of transient runtime context and model-bound messages.

The source is a host's actual harness context. Conversion happens after runtime
classification; durable messages and legacy continuation APIs stay untouched.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import math
import re
from typing import Any

from memory_core._intl_zone_names import en_us_short_time_zone_name
from memory_core.bootstrap._js import js_trim
from memory_core.current_time import resolve_cron_style_now, resolve_user_timezone, utc_and_local_instants
from memory_core.prompt_section import build_prompt_section
from memory_core.replay_history import normalize_assistant_replay_content
from memory_core.runtime_context_prompt import (
    build_current_inbound_prompt, build_runtime_context_custom_message,
    build_runtime_context_message_content, escape_internal_runtime_context_delimiters,
    project_runtime_context_fragments, resolve_runtime_context_prompt_parts,
)
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY
from memory_core.session_context import convert_to_llm
from memory_core.session_entry import strip_inbound_metadata

MEMORY_PROMPT_TOOL_NAMES = ("memory_search", "memory_get", "sessions_search", "sessions_history", "session_status")
_LEADING_ENVELOPE = re.compile(r"^\[[A-Za-z]{3} [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}[^\]]*\] *")
_TIMESTAMP_ENVELOPE = re.compile(r"^\[.*[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}")


@dataclass(frozen=True)
class RuntimePromptInput:
    """Trusted host facts for one turn; text never grants runtime authority."""

    fragments: Sequence[Mapping[str, Any]] = ()
    transcript_prompt: str | None = None
    current_inbound_context: Mapping[str, Any] | None = None
    suppress_next_user_message_persistence: bool = False
    offered_tool_names: Sequence[str] | None = None
    citations_mode: str | None = None
    timezone: str | None = None
    host_timezone: str | None = None
    host_time_format: str | None = None
    include_clock: bool = False
    append_only_runtime_context: bool = False

    def __post_init__(self):
        copied = tuple(deepcopy(dict(fragment)) for fragment in self.fragments)
        if any(fragment.get("kind") not in {"runtime-instruction", "conversation-data", "heartbeat-outcome"}
               or not isinstance(fragment.get("text"), str) for fragment in copied):
            raise ValueError("Runtime fragments require an explicit supported kind and string text")
        if self.transcript_prompt is not None and not isinstance(self.transcript_prompt, str):
            raise TypeError("transcript_prompt must be a string or None")
        object.__setattr__(self, "fragments", copied)
        object.__setattr__(self, "current_inbound_context", deepcopy(self.current_inbound_context))
        if self.offered_tool_names is not None:
            object.__setattr__(self, "offered_tool_names", tuple(self.offered_tool_names))


def _is_context(message, identity):
    return message.get("role") == "custom" and message.get("customType") == identity.runtime_context_custom_type


def _active_user(messages):
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "user":
            return index
        content = message.get("content")
        if message.get("role") == "assistant" and not any(
            isinstance(block, Mapping) and block.get("type") in {"toolCall", "toolUse", "functionCall"}
            for block in (content if isinstance(content, list) else [])
        ):
            return -1
    return -1


def _text_block(block):
    return isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str)


def _stamp(text, timestamp, timezone):
    if (not timezone or not js_trim(text) or _TIMESTAMP_ENVELOPE.search(text)
            or "Current time: " in text or text.startswith("[Inter-session message]")
            or isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp)):
        return text
    try:
        label, zone = resolve_user_timezone(timezone)
        _utc, local = utc_and_local_instants(timestamp, zone)
        weekday = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[local.weekday()]
        short_zone = en_us_short_time_zone_name(label, local)
        return f"[{weekday} {local.year:04d}-{local.month:02d}-{local.day:02d} {local.hour:02d}:{local.minute:02d} {short_zone}] {text}"
    except (ValueError, OverflowError):
        return text


def _normalize_user_messages(messages, *, timezone, append_only, live_user_index):
    active = _active_user(messages)
    result = []
    for index, message in enumerate(messages):
        if message.get("role") != "user":
            result.append(message)
            continue
        preserve = append_only or index == active or (live_user_index >= 0 and index >= live_user_index)

        def transform(text):
            envelope = _LEADING_ENVELOPE.match(text)
            if envelope or "Current time: " in text:
                if preserve:
                    return text
                prefix = envelope.group(0) if envelope else ""
                return prefix + strip_inbound_metadata(text[len(prefix):])
            return _stamp(text if preserve else strip_inbound_metadata(text), message.get("timestamp"), timezone)

        content = message.get("content")
        if isinstance(content, list) and len(content) == 1 and _text_block(content[0]):
            content = content[0]["text"]
        if isinstance(content, str):
            result.append({**message, "content": transform(content)})
        elif isinstance(content, list):
            parts, first = [], True
            for block in content:
                if _text_block(block):
                    text = transform(block["text"]) if first else (
                        block["text"] if preserve else strip_inbound_metadata(block["text"]))
                    parts.append({**block, "text": text})
                    first = False
                else:
                    parts.append(block)
            result.append({**message, "content": parts})
        else:
            result.append(message)
    return result


def _valid_fragments(details, identity):
    if (not isinstance(details, Mapping) or details.get("source") != identity.runtime_context_source
            or details.get("runtimeContextCarrier") is not True or not isinstance(details.get("fragments"), list)):
        return None
    fragments = details["fragments"]
    if any(not isinstance(fragment, Mapping) or fragment.get("kind") not in {
        "runtime-instruction", "conversation-data", "heartbeat-outcome"
    } or not isinstance(fragment.get("text"), str) for fragment in fragments):
        return None
    return fragments


def normalize_model_messages(messages, *, session_version, append_only_runtime_context=False,
                             timezone=None, retained_carrier=None, identity=MEMORY_CORE_RUNTIME_IDENTITY):
    """Project the supported harness message boundary before generic conversion.

    This owner handles runtime context, ordinary user text/blocks and replay
    metadata. Provider media reconstruction and sender-context synthesis remain
    separate host capabilities.
    """
    if session_version not in (None, 3, 4):
        raise ValueError(f"Unsupported session prompt projection version: {session_version}")
    normalized = normalize_assistant_replay_content(messages)
    cleaned = []
    for message in normalized:
        value = message
        if message.get("role") == "toolResult" and "details" in message:
            value = {key: item for key, item in value.items() if key != "details"}
        metadata = value.get("__openclaw")
        blocked = metadata.get("beforeAgentRunBlocked") if isinstance(metadata, Mapping) else None
        if isinstance(blocked, Mapping):
            safe = {key: blocked[key] for key in ("blockedBy", "blockedAt")
                    if key in blocked and (isinstance(blocked[key], str) if key == "blockedBy"
                        else isinstance(blocked[key], (int, float)) and not isinstance(blocked[key], bool))}
            value = {**value, "__openclaw": {**metadata, "beforeAgentRunBlocked": safe}}
        cleaned.append(value)
    live_index = next((index for index, message in enumerate(cleaned) if message is retained_carrier), -1)
    live_user = next((index for index in range(live_index + 1, len(cleaned))
                      if cleaned[index].get("role") == "user"), -1) if live_index >= 0 else -1
    normalized = _normalize_user_messages(cleaned, timezone=timezone, append_only=append_only_runtime_context,
                                          live_user_index=live_user)
    if not append_only_runtime_context:
        last_user = max((index for index, message in enumerate(normalized) if message.get("role") == "user"), default=-1)
        start = last_user
        while start > 0 and _is_context(normalized[start - 1], identity):
            start -= 1
        normalized = [message for index, message in enumerate(normalized)
                      if not _is_context(message, identity) or (last_user >= 0 and (
                          start <= index < last_user or message is retained_carrier))]
    if session_version == 4:
        projected = []
        for message in normalized:
            fragments = _valid_fragments(message.get("details"), identity) if _is_context(message, identity) else None
            if fragments is not None:
                projected.append({**message, "content": build_runtime_context_message_content(
                    project_runtime_context_fragments(fragments, identity=identity), identity=identity)})
            elif message.get("role") in {"user", "custom"}:
                content = message.get("content")
                value = (escape_internal_runtime_context_delimiters(content, identity=identity)
                         if isinstance(content, str) else [
                             {**block, "text": escape_internal_runtime_context_delimiters(block["text"], identity=identity)}
                             if _text_block(block) else block for block in content])
                projected.append({**message, "content": value})
            else:
                projected.append(message)
        normalized = projected
    if not append_only_runtime_context:
        carrier_index = next((index for index, message in enumerate(normalized) if _is_context(message, identity)), -1)
        user_index = next((index for index in range(carrier_index + 1, len(normalized))
                           if normalized[index].get("role") == "user"), -1)
        if carrier_index >= 0 and user_index >= 0:
            boundary = next((index for index in range(user_index + 1, len(normalized))
                             if normalized[index].get("role") == "user"), len(normalized))
            normalized = ([message for message in normalized[:boundary] if not _is_context(message, identity)]
                          + [message for message in normalized if _is_context(message, identity)]
                          + [message for message in normalized[boundary:] if not _is_context(message, identity)])
    converted = convert_to_llm(normalized)
    return [{**message, "runtimeContextCarrierRetained": append_only_runtime_context}
            if message.get("role") == "user" and message.get("runtimeContextCarrier") is True else message
            for message in converted]


class ModelPrompt:
    """One admitted prompt's transient carrier and actual assembly receipts."""

    def __init__(self, effective_prompt, options, *, tools, workspace_prompt, citations_mode,
                 identity, now_ms, session_version, user_key):
        self.options, self.identity, self.session_version = options, identity, session_version
        self.user_key, self.closed = user_key, False
        registry = {tool["name"]: deepcopy(dict(tool)) for tool in tools}
        offered = options.offered_tool_names if options.offered_tool_names is not None else tuple(registry)
        if len(set(offered)) != len(offered) or set(offered) - registry.keys():
            raise ValueError("Model tools must select unique genuine host registrations")
        self.tools = [registry[name] for name in offered]
        mode = options.citations_mode or citations_mode
        guidance = build_prompt_section(set(offered), citations_mode=mode)
        self.memory_guidance = {"toolAvailability": {name: name in offered for name in MEMORY_PROMPT_TOOL_NAMES}, "lines": guidance}
        self.memory_prompt_calls = [{"arguments": {"available_tools": list(offered), "citations_mode": mode},
                                     "returnValue": deepcopy(guidance),
                                     "toolAvailability": deepcopy(self.memory_guidance["toolAvailability"])}]
        self.system_prompt = "\n".join(guidance)
        if js_trim(workspace_prompt):
            self.system_prompt += ("\n" if self.system_prompt else "") + js_trim(workspace_prompt)
        configured_zone = options.timezone if options.timezone is not None else ""
        self.timezone = resolve_user_timezone(configured_zone, host_timezone=options.host_timezone)[0]
        time_format = options.host_time_format or "24"
        self.clock = (resolve_cron_style_now(now_ms, configured_zone, time_format,
                       host_timezone=options.host_timezone) if options.include_clock else None)
        self.clock_call = ({"arguments": {"now_ms": now_ms, "timezone": configured_zone,
                            "time_format": time_format, "host_timezone": options.host_timezone},
                            "returnValue": deepcopy(self.clock)} if self.clock is not None else None)
        fragments = [deepcopy(dict(fragment)) for fragment in options.fragments]
        if self.clock is not None:
            fragments.append({"kind": "runtime-instruction", "text": self.clock["timeLine"]})
        self.prompt_submission = resolve_runtime_context_prompt_parts(
            effective_prompt=effective_prompt, transcript_prompt=options.transcript_prompt,
            fragments=fragments, allow_runtime_only=not options.suppress_next_user_message_persistence, identity=identity)
        inbound = options.current_inbound_context
        inline = inbound if self.prompt_submission.get("runtimeOnly") else None
        self.session_prompt = build_current_inbound_prompt(context=inline, prompt=self.prompt_submission["prompt"])
        self.model_prompt = build_current_inbound_prompt(
            context=inline, prompt=self.prompt_submission.get("modelPrompt", self.prompt_submission["prompt"]))
        inbound_fragments = ((inbound.get("fragments") if session_version == 4 else None)
                             if inbound is not None else None)
        if inbound_fragments is None:
            inbound_fragments = ([{"kind": "conversation-data", "text": inbound["text"]}]
                                 if inbound and inbound.get("text") else [])
        context_fragments = fragments if self.prompt_submission.get("runtimeOnly") else [*inbound_fragments, *fragments]
        runtime_text = "\n\n".join(fragment["text"] for fragment in context_fragments if fragment["text"])
        self.carrier = build_runtime_context_custom_message(runtime_text or None, context_fragments,
                                                           identity=identity, now_ms=now_ms)
        self.skip_submission = not js_trim(self.session_prompt)

    def request(self, messages):
        if self.closed:
            raise RuntimeError("The model prompt owner is closed")
        source = deepcopy(list(messages))
        user_index = next((index for index, message in enumerate(source)
                           if message.get("role") == "user" and message.get("idempotencyKey") == self.user_key), -1)
        if user_index < 0:
            user_index = _active_user(source)
        if user_index >= 0 and self.model_prompt != self.session_prompt and js_trim(self.model_prompt):
            user = source[user_index]
            content = user.get("content")
            if isinstance(content, str) and content == self.session_prompt:
                source[user_index] = {**user, "content": self.model_prompt}
            elif isinstance(content, list):
                replaced, parts = False, []
                for block in content:
                    if not replaced and _text_block(block) and block["text"] == self.session_prompt:
                        parts.append({**block, "text": self.model_prompt})
                        replaced = True
                    else:
                        parts.append(block)
                source[user_index] = {**user, "content": parts}
        if self.carrier is not None:
            source.insert(user_index if user_index >= 0 else len(source), self.carrier)
        projected = normalize_model_messages(source, session_version=self.session_version,
            append_only_runtime_context=self.options.append_only_runtime_context,
            timezone=self.timezone, retained_carrier=self.carrier, identity=self.identity)
        return {"systemPrompt": self.system_prompt, "tools": deepcopy(self.tools), "messages": projected}

    def close(self):
        self.closed = True
        self.carrier = None
