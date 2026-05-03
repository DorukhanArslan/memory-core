from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol

import httpx

from memory_core.memory_flush import SILENT_REPLY_TOKEN


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatResponse:
    role: str
    content: str
    raw: dict | None = None


@dataclass(frozen=True)
class FlushModelOutput:
    raw_text: str
    raw: dict | None = None


class ChatEngine(Protocol):
    name: str

    def complete(self, *, messages: list[ChatMessage], memory_context: list[str]) -> ChatResponse:
        raise NotImplementedError

    def flush(
        self,
        *,
        system_prompt: str,
        prompt: str,
        transcript: list[ChatMessage],
        target: str,
    ) -> FlushModelOutput:
        raise NotImplementedError


class FakeChatEngine:
    name = "fake"

    def complete(self, *, messages: list[ChatMessage], memory_context: list[str]) -> ChatResponse:
        latest = _latest_user_message(messages)
        context_note = "; ".join(memory_context[:3]) if memory_context else "no recalled memory"
        return ChatResponse(
            role="assistant",
            content=(
                f"Fake assistant saw memory context: {context_note}. "
                f"Latest user message: {latest}"
            ),
        )

    def flush(
        self,
        *,
        system_prompt: str,
        prompt: str,
        transcript: list[ChatMessage],
        target: str,
    ) -> FlushModelOutput:
        del system_prompt, prompt

        durable = _find_durable_statement(transcript)
        if durable is None:
            return FlushModelOutput(raw_text=SILENT_REPLY_TOKEN)

        return FlushModelOutput(
            raw_text=json.dumps(
                {
                    "shouldWrite": True,
                    "target": target,
                    "entry": f"- {durable}",
                    "reason": "Stable preference, fact, or project decision worth preserving.",
                },
                ensure_ascii=False,
            )
        )


class OpenAICompatibleChatEngine:
    name = "openai"

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> OpenAICompatibleChatEngine | None:
        base_url = os.getenv("OPENCLAW_DEMO_OPENAI_BASE_URL")
        api_key = os.getenv("OPENCLAW_DEMO_OPENAI_API_KEY")
        model = os.getenv("OPENCLAW_DEMO_OPENAI_MODEL")
        if not base_url or not api_key or not model:
            return None
        return cls(base_url=base_url, api_key=api_key, model=model)

    def complete(self, *, messages: list[ChatMessage], memory_context: list[str]) -> ChatResponse:
        api_messages = [
            {
                "role": "system",
                "content": "Use the supplied memory context when relevant. Do not invent memory.",
            },
            {
                "role": "system",
                "content": "Memory context:\n" + "\n".join(memory_context),
            },
        ]
        api_messages.extend({"role": message.role, "content": message.content} for message in messages)
        raw = self._chat(api_messages)
        content = raw["choices"][0]["message"]["content"]
        return ChatResponse(role="assistant", content=content, raw=raw)

    def flush(
        self,
        *,
        system_prompt: str,
        prompt: str,
        transcript: list[ChatMessage],
        target: str,
    ) -> FlushModelOutput:
        transcript_text = "\n".join(f"{message.role}: {message.content}" for message in transcript)
        raw = self._chat(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"{prompt}\n\nTarget: {target}\n\nTranscript:\n{transcript_text}",
                },
            ]
        )
        return FlushModelOutput(raw_text=raw["choices"][0]["message"]["content"].strip(), raw=raw)

    def _chat(self, messages: list[dict]) -> dict:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "messages": messages},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


def _latest_user_message(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return messages[-1].content if messages else ""


def _find_durable_statement(transcript: list[ChatMessage]) -> str | None:
    durable_markers = (
        "tercih ediyorum",
        "severim",
        "prefers",
        "preference",
        "bundan sonra",
        "karar",
        "decision",
        "always",
        "never",
        "project uses",
        "my name is",
        "i live in",
        "i work at",
    )
    for message in reversed(transcript):
        if message.role != "user":
            continue
        lowered = message.content.lower()
        if any(marker in lowered for marker in durable_markers):
            return message.content.strip()
    return None


def engine_status() -> dict:
    configured = OpenAICompatibleChatEngine.from_env() is not None
    return {
        "fake": {"available": True, "model": "deterministic"},
        "openai": {
            "available": configured,
            "model": os.getenv("OPENCLAW_DEMO_OPENAI_MODEL") or "",
            "baseUrl": os.getenv("OPENCLAW_DEMO_OPENAI_BASE_URL") or "",
        },
    }
