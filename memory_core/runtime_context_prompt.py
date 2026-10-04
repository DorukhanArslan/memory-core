from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import Any, Literal

from memory_core.runtime_identity import (
    # Explicit re-export: callers import the compat identity from this module.
    OPENCLAW_COMPAT_RUNTIME_IDENTITY as OPENCLAW_COMPAT_RUNTIME_IDENTITY,
)
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity

OPENCLAW_RUNTIME_CONTEXT_NOTICE = (
    "This context is runtime-generated, not user-authored. Keep internal details private."
)
# Public API (memory_core.__all__).
MEMORY_CORE_RUNTIME_CONTEXT_CUSTOM_TYPE = MEMORY_CORE_RUNTIME_IDENTITY.runtime_context_custom_type

RuntimeContextFragmentKind = Literal["runtime-instruction", "conversation-data", "heartbeat-outcome"]


def build_current_inbound_prompt_context_prefix(
    context: Mapping[str, Any] | None,
    *,
    prefer_resumable_text: bool = False,
) -> str:
    """Trimmed inbound context text (``resumableText`` first when asked, run/runtime-context-prompt.ts)."""

    if not context:
        return ""
    text = context.get("text")
    if prefer_resumable_text and context.get("resumableText") is not None:
        text = context.get("resumableText")
    return text.strip() if isinstance(text, str) else ""


def build_current_inbound_prompt(
    *,
    context: Mapping[str, Any] | None,
    prompt: str,
    prefer_resumable_text: bool = False,
) -> str:
    prefix = build_current_inbound_prompt_context_prefix(
        context, prefer_resumable_text=prefer_resumable_text
    )
    joiner = context.get("promptJoiner") if context else None
    return str(joiner if isinstance(joiner, str) else "\n\n").join(
        part for part in (prefix, prompt) if part
    )


def append_current_inbound_context(
    context: Mapping[str, Any] | None,
    fragments: list[Mapping[str, Any]],
    legacy_text: str | None = None,
) -> dict[str, Any]:
    """Append turn additions to the full and resumed projections, keeping provenance."""

    if legacy_text is None:
        legacy_text = "\n\n".join(str(fragment.get("text", "")) for fragment in fragments)
    base = dict(context or {})

    def append(text: Any) -> str:
        return "\n\n".join(part for part in (text, legacy_text) if part)

    out = dict(base)
    out["text"] = append(base.get("text"))
    if base.get("resumableText") is not None:
        out["resumableText"] = append(base["resumableText"])
    existing = base.get("fragments")
    if existing is None:
        existing = (
            [{"kind": "conversation-data", "text": base["text"]}] if base.get("text") else []
        )
    out["fragments"] = [*existing, *fragments]
    return out


def resolve_runtime_context_prompt_parts(
    *,
    effective_prompt: str,
    transcript_prompt: str | None = None,
    fragments: list[Mapping[str, Any]] | None = None,
    allow_runtime_only: bool | None = None,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict[str, Any]:
    """Select explicit producer context; prompt text is never interpreted as provenance."""

    kept = [f for f in (fragments or []) if str(f.get("text", "")).strip()]
    runtime_context = "\n\n".join(str(f["text"]) for f in kept)
    transcript = transcript_prompt if transcript_prompt is not None else effective_prompt
    runtime_only = not transcript.strip() and bool(runtime_context) and allow_runtime_only is not False
    prompt = identity.runtime_event_user_prompt if runtime_only else (transcript or effective_prompt)
    out: dict[str, Any] = {"prompt": prompt}
    if effective_prompt and effective_prompt != prompt:
        out["modelPrompt"] = effective_prompt
    if runtime_context:
        out["runtimeContext"] = runtime_context
    if runtime_only:
        out["runtimeOnly"] = True
    return out


def build_runtime_context_system_context(
    runtime_context: str,
    *,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> str:
    return _build_runtime_context_message_content(runtime_context, kind="next-turn", identity=identity)


def build_runtime_event_system_context(
    runtime_context: str,
    *,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> str:
    return _build_runtime_context_message_content(
        runtime_context,
        kind="runtime-event",
        identity=identity,
    )


def build_runtime_context_message_content(
    runtime_context: str,
    *,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> str:
    """Delimited block only; the stable system prompt explains the markers once."""

    return "\n".join([identity.runtime_context_begin, runtime_context, identity.runtime_context_end])


def build_runtime_context_custom_message(
    runtime_context: str | None,
    fragments: list[Mapping[str, Any]] | None = None,
    *,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict[str, Any] | None:
    trimmed = runtime_context.strip() if isinstance(runtime_context, str) else ""
    if not trimmed:
        return None
    details: dict[str, Any] = {
        "source": identity.runtime_context_source,
        "runtimeContextCarrier": True,
    }
    if fragments:
        details["fragments"] = [dict(f) for f in fragments]
    return {
        "role": "custom",
        "customType": identity.runtime_context_custom_type,
        "content": build_runtime_context_message_content(trimmed, identity=identity),
        "display": False,
        "details": details,
        "timestamp": int(time.time() * 1000),
    }


def prepend_runtime_context_for_model(
    messages: list[dict[str, Any]],
    runtime_context: str,
    *,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> list[dict[str, Any]]:
    """Project per-request instructions into the transient carrier without changing history."""

    if not runtime_context.strip():
        return messages
    begin = identity.runtime_context_begin

    def prepend(text: str) -> str:
        if text.startswith(f"{begin}\n"):
            return f"{begin}\n{runtime_context}\n\n{text[len(begin) + 1 :]}"
        return build_runtime_context_message_content(
            "\n\n".join(part for part in (runtime_context, text) if part), identity=identity
        )

    carrier_index = next(
        (
            i
            for i, m in enumerate(messages)
            if m.get("role") == "user" and m.get("runtimeContextCarrier") is True
        ),
        -1,
    )
    if carrier_index == -1:
        last = messages[-1].get("timestamp", 0) if messages else 0
        return [
            *messages,
            {
                "role": "user",
                "content": prepend(""),
                "runtimeContextCarrier": True,
                "timestamp": last,
            },
        ]
    carrier = messages[carrier_index]
    content = carrier.get("content")
    if isinstance(content, str):
        updated_content: Any = prepend(content)
    else:
        parts = list(content or [])
        first_text = next((i for i, p in enumerate(parts) if p.get("type") == "text"), -1)
        if first_text < 0:
            updated_content = [{"type": "text", "text": prepend("")}, *parts]
        else:
            parts[first_text] = {**parts[first_text], "text": prepend(parts[first_text].get("text", ""))}
            updated_content = parts
    return [
        {**carrier, "content": updated_content} if i == carrier_index else m
        for i, m in enumerate(messages)
    ]


def _build_runtime_context_message_content(
    runtime_context: str,
    *,
    kind: Literal["next-turn", "runtime-event"],
    identity: RuntimeIdentity,
) -> str:
    header = (
        identity.runtime_event_header
        if kind == "runtime-event"
        else identity.next_turn_runtime_context_header
    )
    # Wrap the runtime context body in delimited internal-context markers so
    # strip helpers can fully remove the block when it leaks into user-visible
    # surfaces (OpenClaw #92589).
    return "\n".join(
        [
            header,
            OPENCLAW_RUNTIME_CONTEXT_NOTICE,
            "",
            identity.runtime_context_begin,
            runtime_context,
            identity.runtime_context_end,
        ]
    )


def _find_delimited_token_index(text: str, token: str, start: int) -> int:
    pattern = re.compile(rf"(?:^|\r?\n)[ \t]*{re.escape(token)}[ \t]*(?=\r?\n|$)")
    match = pattern.search(text, max(0, start))
    if not match:
        return -1
    return match.start() + match.group(0).index(token)
