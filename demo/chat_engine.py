from __future__ import annotations

import os
import json
from dataclasses import dataclass
from collections.abc import Iterator
from typing import Protocol

import httpx

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-5.2"


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

    def stream_complete(
        self, *, messages: list[ChatMessage], memory_context: list[str]
    ) -> Iterator[str]:
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


class OpenAICompatibleChatEngine:
    name = "openai"

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> OpenAICompatibleChatEngine | None:
        base_url = os.getenv("OPENCLAW_DEMO_OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL
        api_key = os.getenv("OPENCLAW_DEMO_OPENAI_API_KEY")
        model = os.getenv("OPENCLAW_DEMO_OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        if not api_key:
            return None
        return cls(base_url=base_url, api_key=api_key, model=model)

    @classmethod
    def from_config(
        cls,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
    ) -> OpenAICompatibleChatEngine | None:
        resolved_api_key = (api_key or os.getenv("OPENCLAW_DEMO_OPENAI_API_KEY") or "").strip()
        if not resolved_api_key:
            return None
        return cls(
            base_url=(
                base_url or os.getenv("OPENCLAW_DEMO_OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL
            ).strip(),
            api_key=resolved_api_key,
            model=(model or os.getenv("OPENCLAW_DEMO_OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip(),
        )

    def complete(self, *, messages: list[ChatMessage], memory_context: list[str]) -> ChatResponse:
        api_messages = self._api_messages(messages=messages, memory_context=memory_context)
        raw = self._chat(api_messages)
        content = raw["choices"][0]["message"]["content"]
        return ChatResponse(role="assistant", content=content, raw=raw)

    def stream_complete(
        self, *, messages: list[ChatMessage], memory_context: list[str]
    ) -> Iterator[str]:
        yield from self._chat_stream(
            self._api_messages(messages=messages, memory_context=memory_context)
        )

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

    def _chat_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "messages": messages, "stream": True},
            timeout=self.timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                chunk = _parse_stream_line(line)
                if chunk is None:
                    continue
                yield chunk

    def _api_messages(
        self, *, messages: list[ChatMessage], memory_context: list[str]
    ) -> list[dict[str, str]]:
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
        return api_messages


def _parse_stream_line(line: str | bytes) -> str | None:
    text = line.decode("utf-8") if isinstance(line, bytes) else line
    if not text.startswith("data: "):
        return None
    data = text.removeprefix("data: ").strip()
    if not data or data == "[DONE]":
        return None
    payload = json.loads(data)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    delta = choices[0].get("delta", {})
    content = delta.get("content")
    return content if isinstance(content, str) else None


def engine_status() -> dict:
    configured = OpenAICompatibleChatEngine.from_env() is not None
    return {
        "openai": {
            "available": configured,
            "model": os.getenv("OPENCLAW_DEMO_OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
            "baseUrl": os.getenv("OPENCLAW_DEMO_OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL,
        },
    }
