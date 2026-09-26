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

EmptyTranscriptMode = Literal["model-prompt", "runtime-event"]


def build_current_inbound_prompt_context_prefix(context: Mapping[str, Any] | None) -> str:
    text = context.get("text") if context else None
    return text.strip() if isinstance(text, str) else ""


def build_current_inbound_prompt(*, context: Mapping[str, Any] | None, prompt: str) -> str:
    prefix = build_current_inbound_prompt_context_prefix(context)
    if not prefix:
        return prompt
    if not prompt:
        return prefix
    prompt_joiner = context.get("promptJoiner") if context else None
    return str(prompt_joiner if isinstance(prompt_joiner, str) else "\n\n").join([prefix, prompt])


def resolve_runtime_context_prompt_parts(
    *,
    effective_prompt: str,
    transcript_prompt: str | None = None,
    model_prompt: str | None = None,
    empty_transcript_mode: EmptyTranscriptMode | None = None,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict[str, Any]:
    should_extract_internal_runtime_context = transcript_prompt is not None
    extracted = (
        _extract_internal_runtime_context(effective_prompt, identity=identity)
        if should_extract_internal_runtime_context
        else {"text": effective_prompt}
    )
    extracted_model_prompt = (
        None
        if model_prompt is None
        else (
            _extract_internal_runtime_context(model_prompt, identity=identity)
            if should_extract_internal_runtime_context
            else {"text": model_prompt}
        )
    )
    model_prompt_text = (
        extracted_model_prompt["text"]
        if extracted_model_prompt is not None
        else (transcript_prompt if transcript_prompt is not None else extracted["text"])
    )
    prompt = transcript_prompt if transcript_prompt is not None else extracted["text"]

    if not prompt.strip() and empty_transcript_mode == "model-prompt":
        out: dict[str, Any] = {"prompt": extracted["text"]}
        if model_prompt_text.strip() and model_prompt_text != extracted["text"]:
            out["modelPrompt"] = model_prompt_text
        if extracted.get("runtimeContext"):
            out["runtimeContext"] = extracted["runtimeContext"]
        return out

    hidden_runtime_context = None
    if extracted_model_prompt is not None:
        hidden_runtime_context = _remove_last_prompt_occurrence(
            extracted["text"],
            extracted_model_prompt["text"],
        )
        if hidden_runtime_context is None and transcript_prompt:
            hidden_runtime_context = _remove_last_prompt_occurrence(extracted["text"], transcript_prompt)
    elif transcript_prompt:
        hidden_runtime_context = _remove_last_prompt_occurrence(extracted["text"], transcript_prompt)

    runtime_context = "\n\n".join(
        value.strip()
        for value in [hidden_runtime_context, extracted.get("runtimeContext")]
        if isinstance(value, str) and value.strip()
    )
    if not runtime_context and not prompt.strip():
        runtime_context = extracted["text"].strip()

    if not prompt.strip():
        if runtime_context:
            out = {
                "prompt": identity.runtime_event_user_prompt,
                "runtimeContext": runtime_context,
                "runtimeOnly": True,
                "runtimeSystemContext": build_runtime_event_system_context(
                    runtime_context,
                    identity=identity,
                ),
            }
            if model_prompt_text.strip() and model_prompt_text != identity.runtime_event_user_prompt:
                out["modelPrompt"] = model_prompt_text
            return out
        out = {"prompt": ""}
        if model_prompt_text:
            out["modelPrompt"] = model_prompt_text
        return out

    out = {"prompt": prompt}
    if model_prompt_text.strip() and model_prompt_text != prompt:
        out["modelPrompt"] = model_prompt_text
    if runtime_context:
        out["runtimeContext"] = runtime_context
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


def build_runtime_context_custom_message(
    runtime_context: str | None,
    *,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict[str, Any] | None:
    trimmed = runtime_context.strip() if isinstance(runtime_context, str) else ""
    if not trimmed:
        return None
    return {
        "role": "custom",
        "customType": identity.runtime_context_custom_type,
        "content": build_runtime_context_system_context(trimmed, identity=identity),
        "display": False,
        "details": {"source": identity.runtime_context_source},
        "timestamp": int(time.time() * 1000),
    }


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


def _remove_last_prompt_occurrence(text: str, prompt: str) -> str | None:
    index = text.rfind(prompt)
    if index == -1:
        return None
    before = text[:index].rstrip()
    after = text[index + len(prompt) :].lstrip()
    return "\n\n".join(part for part in [before, after] if part).strip()


def _extract_internal_runtime_context(
    text: str,
    *,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict[str, str]:
    extracted = _extract_delimited_blocks(
        text,
        identity.runtime_context_begin,
        identity.runtime_context_end,
    )
    out = {"text": extracted["text"]}
    if extracted["blocks"]:
        out["runtimeContext"] = "\n\n".join(extracted["blocks"])
    return out


def _extract_delimited_blocks(text: str, begin: str, end: str) -> dict[str, Any]:
    next_text = text
    blocks: list[str] = []
    while True:
        start = _find_delimited_token_index(next_text, begin, 0)
        if start == -1:
            return {"text": next_text, "blocks": blocks}

        cursor = start + len(begin)
        depth = 1
        finish = -1
        while depth > 0:
            next_begin = _find_delimited_token_index(next_text, begin, cursor)
            next_end = _find_delimited_token_index(next_text, end, cursor)
            if next_end == -1:
                break
            if next_begin != -1 and next_begin < next_end:
                depth += 1
                cursor = next_begin + len(begin)
                continue
            depth -= 1
            finish = next_end
            cursor = next_end + len(end)

        before = next_text[:start].rstrip()
        if finish == -1 or depth != 0:
            return {"text": before, "blocks": blocks}
        block_end = finish + len(end)
        blocks.append(next_text[start:block_end].strip())
        after = next_text[block_end:].lstrip()
        next_text = f"{before}\n\n{after}" if before and after else f"{before}{after}"


def _find_delimited_token_index(text: str, token: str, start: int) -> int:
    pattern = re.compile(rf"(?:^|\r?\n){re.escape(token)}(?=\r?\n|$)")
    match = pattern.search(text, max(0, start))
    if not match:
        return -1
    return match.start() + len(match.group(0)) - len(token)
