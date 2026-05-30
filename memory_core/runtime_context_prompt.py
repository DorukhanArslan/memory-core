from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import Any, Literal

from memory_core.branding import (
    MemoryBranding,
    OPENCLAW_COMPAT_BRANDING,
    MEMORY_CORE_BRANDING,
)

INTERNAL_RUNTIME_CONTEXT_BEGIN = MEMORY_CORE_BRANDING.runtime_context_begin
INTERNAL_RUNTIME_CONTEXT_END = MEMORY_CORE_BRANDING.runtime_context_end
OPENCLAW_RUNTIME_CONTEXT_NOTICE = (
    "This context is runtime-generated, not user-authored. Keep internal details private."
)
OPENCLAW_NEXT_TURN_RUNTIME_CONTEXT_HEADER = OPENCLAW_COMPAT_BRANDING.next_turn_runtime_context_header
OPENCLAW_RUNTIME_EVENT_HEADER = OPENCLAW_COMPAT_BRANDING.runtime_event_header
OPENCLAW_RUNTIME_CONTEXT_CUSTOM_TYPE = OPENCLAW_COMPAT_BRANDING.runtime_context_custom_type
OPENCLAW_RUNTIME_EVENT_USER_PROMPT = OPENCLAW_COMPAT_BRANDING.runtime_event_user_prompt
MEMORY_CORE_RUNTIME_CONTEXT_CUSTOM_TYPE = MEMORY_CORE_BRANDING.runtime_context_custom_type

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
    branding: MemoryBranding = MEMORY_CORE_BRANDING,
) -> dict[str, Any]:
    should_extract_internal_runtime_context = transcript_prompt is not None
    extracted = (
        _extract_internal_runtime_context(effective_prompt, branding=branding)
        if should_extract_internal_runtime_context
        else {"text": effective_prompt}
    )
    extracted_model_prompt = (
        None
        if model_prompt is None
        else (
            _extract_internal_runtime_context(model_prompt, branding=branding)
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
                "prompt": branding.runtime_event_user_prompt,
                "runtimeContext": runtime_context,
                "runtimeOnly": True,
                "runtimeSystemContext": build_runtime_event_system_context(
                    runtime_context,
                    branding=branding,
                ),
            }
            if model_prompt_text.strip() and model_prompt_text != branding.runtime_event_user_prompt:
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
    branding: MemoryBranding = MEMORY_CORE_BRANDING,
) -> str:
    return _build_runtime_context_message_content(runtime_context, kind="next-turn", branding=branding)


def build_runtime_event_system_context(
    runtime_context: str,
    *,
    branding: MemoryBranding = MEMORY_CORE_BRANDING,
) -> str:
    return _build_runtime_context_message_content(
        runtime_context,
        kind="runtime-event",
        branding=branding,
    )


def build_runtime_context_custom_message(
    runtime_context: str | None,
    *,
    branding: MemoryBranding = MEMORY_CORE_BRANDING,
) -> dict[str, Any] | None:
    trimmed = runtime_context.strip() if isinstance(runtime_context, str) else ""
    if not trimmed:
        return None
    return {
        "role": "custom",
        "customType": branding.runtime_context_custom_type,
        "content": build_runtime_context_system_context(trimmed, branding=branding),
        "display": False,
        "details": {"source": branding.runtime_context_source},
        "timestamp": int(time.time() * 1000),
    }


def _build_runtime_context_message_content(
    runtime_context: str,
    *,
    kind: Literal["next-turn", "runtime-event"],
    branding: MemoryBranding,
) -> str:
    header = (
        branding.runtime_event_header
        if kind == "runtime-event"
        else branding.next_turn_runtime_context_header
    )
    return "\n".join([header, OPENCLAW_RUNTIME_CONTEXT_NOTICE, "", runtime_context])


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
    branding: MemoryBranding = MEMORY_CORE_BRANDING,
) -> dict[str, str]:
    extracted = _extract_delimited_blocks(
        text,
        branding.runtime_context_begin,
        branding.runtime_context_end,
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
