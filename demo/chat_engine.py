from __future__ import annotations

import os
import json
from dataclasses import dataclass
from collections.abc import Iterator
from typing import Protocol

import httpx

DEFAULT_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENAI_MODEL = "openai/gpt-4o-mini"


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
class FlushWriteCall:
    path: str
    content: str
    call_id: str
    name: str = "write"


@dataclass(frozen=True)
class FlushModelOutput:
    raw_text: str
    raw: dict | None = None
    writes: tuple[FlushWriteCall, ...] = ()


class ChatEngine(Protocol):
    name: str

    def complete(
        self,
        *,
        messages: list[ChatMessage],
        memory_context: list[str],
        workspace_context: str = "",
    ) -> ChatResponse:
        raise NotImplementedError

    def stream_complete(
        self,
        *,
        messages: list[ChatMessage],
        memory_context: list[str],
        workspace_context: str = "",
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
        base_url = os.getenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL
        api_key = os.getenv("MEMORY_CORE_DEMO_OPENAI_API_KEY")
        model = os.getenv("MEMORY_CORE_DEMO_OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
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
        resolved_api_key = (api_key or os.getenv("MEMORY_CORE_DEMO_OPENAI_API_KEY") or "").strip()
        if not resolved_api_key:
            return None
        return cls(
            base_url=(
                base_url or os.getenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL
            ).strip(),
            api_key=resolved_api_key,
            model=(model or os.getenv("MEMORY_CORE_DEMO_OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip(),
        )

    def complete(
        self,
        *,
        messages: list[ChatMessage],
        memory_context: list[str],
        workspace_context: str = "",
    ) -> ChatResponse:
        api_messages = self._api_messages(
            messages=messages,
            memory_context=memory_context,
            workspace_context=workspace_context,
        )
        raw = self._chat(api_messages)
        content = raw["choices"][0]["message"]["content"]
        return ChatResponse(role="assistant", content=content, raw=raw)

    def stream_complete(
        self,
        *,
        messages: list[ChatMessage],
        memory_context: list[str],
        workspace_context: str = "",
    ) -> Iterator[str]:
        yield from self._chat_stream(
            self._api_messages(
                messages=messages,
                memory_context=memory_context,
                workspace_context=workspace_context,
            )
        )

    def flush(
        self,
        *,
        system_prompt: str,
        prompt: str,
        transcript: list[ChatMessage],
        target: str,
    ) -> FlushModelOutput:
        raw = self._chat(
            (
                [
                    {"role": "system", "content": system_prompt},
                    *[
                        {"role": message.role, "content": message.content}
                        for message in transcript
                        if message.role in {"system", "user", "assistant"}
                    ],
                    {"role": "user", "content": prompt},
                ]
            ),
            tools=[_memory_flush_write_tool(target)],
        )
        message = raw["choices"][0]["message"]
        writes = _extract_write_tool_calls(message)
        if writes:
            raw_text = "\n".join(f"{write.name}({write.path})" for write in writes)
        else:
            content = message.get("content")
            raw_text = content.strip() if isinstance(content, str) else ""
        return FlushModelOutput(raw_text=raw_text, raw=raw, writes=writes)

    def raw_chat_text(self, messages: list[dict[str, str]]) -> str:
        raw = self._chat(messages)
        content = raw["choices"][0]["message"]["content"]
        return content if isinstance(content, str) else ""

    def raw_chat_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        return self._chat_stream(messages)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "http://localhost:8000"
            headers["X-Title"] = "memory-core Lab"
        return headers

    def _chat(self, messages: list[dict], *, tools: list[dict] | None = None) -> dict:
        body: dict = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=body,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _chat_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
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
        self,
        *,
        messages: list[ChatMessage],
        memory_context: list[str],
        workspace_context: str = "",
    ) -> list[dict[str, str]]:
        api_messages = [
            {
                "role": "system",
                "content": (
                    "Use injected workspace files as standing instructions and stable context. "
                    "Use supplied memory context when relevant. Do not invent memory."
                ),
            },
        ]
        if workspace_context.strip():
            api_messages.append({"role": "system", "content": workspace_context})
        api_messages.append(
            {
                "role": "system",
                "content": "Memory context:\n" + "\n".join(memory_context),
            }
        )
        api_messages.extend({"role": message.role, "content": message.content} for message in messages)
        return api_messages


def _memory_flush_write_tool(target: str) -> dict:
    return _memory_write_tool(target, context="memory flush")


def _memory_write_tool(target: str, *, context: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "write",
            "description": (
                "Write content to a file. "
                f"During {context}, this tool may only append to {target}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": f"The memory flush target path. Must be {target}.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Durable memory content to append.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    }


def _extract_write_tool_calls(message: dict) -> tuple[FlushWriteCall, ...]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return ()
    writes = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict) or function.get("name") != "write":
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                payload = json.loads(arguments)
            except json.JSONDecodeError:
                continue
        elif isinstance(arguments, dict):
            payload = arguments
        else:
            continue
        path = payload.get("path")
        content = payload.get("content")
        if isinstance(path, str) and isinstance(content, str):
            writes.append(
                FlushWriteCall(
                    path=path,
                    content=content,
                    call_id=str(call.get("id") or ""),
                    name="write",
                )
            )
    return tuple(writes)


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
            "model": os.getenv("MEMORY_CORE_DEMO_OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
            "baseUrl": os.getenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL,
        },
    }
