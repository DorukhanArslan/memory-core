from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Iterator
from typing import Protocol

import httpx

from demo import LAB_TITLE

DEFAULT_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
# D4 (Q10): the newest OpenAI GPT chat model in OpenRouter's public model list
# (GET https://openrouter.ai/api/v1/models, no auth), checked 2026-09-26. Rule: the newest
# `created` among `openai/gpt-*` ids that support tools, without a `:variant` suffix and
# without a `-pro` serving variant (OpenRouter lists `openai/gpt-6-luna-pro` five seconds
# later as "the same underlying model as GPT-6 Luna" with reasoning mode pro).
# MEMORY_CORE_DEMO_OPENAI_MODEL and the Lab settings still override it.
DEFAULT_OPENAI_MODEL = "openai/gpt-6-luna"
DEFAULT_OPENAI_MODEL_SOURCE = {
    "id": DEFAULT_OPENAI_MODEL,
    "source": "https://openrouter.ai/api/v1/models",
    "checkedAt": "2026-09-26",
    "created": "2026-09-22T18:13:06Z",
    "rule": "newest openai/gpt-* chat model with tool support; no :variant, no -pro serving variant",
}


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class ChatEngine(Protocol):
    """What the Lab needs from a chat model: a streamed completion with tools.

    Chat turns, heartbeat runs and memory flush runs all go through ``stream_chat``.
    """

    name: str
    provider: str
    model: str

    def stream_chat(self, messages: list[dict], *, tools: list[dict] | None = None) -> Iterator[dict]:
        raise NotImplementedError


def _refuses_tool_reasoning(body: dict, response: httpx.Response) -> bool:
    """True when a tool request without ``reasoning_effort`` got the 400 that names it."""
    if "tools" not in body or "reasoning_effort" in body:
        return False
    if getattr(response, "status_code", None) != 400:
        return False
    response.read()
    return _rejects_parameter(response, "reasoning_effort")


def _rejects_parameter(response: httpx.Response, name: str) -> bool:
    """True when a 400 from the provider names ``name`` as the offending parameter."""
    if response.status_code != 400:
        return False
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return False
    return isinstance(error, dict) and error.get("param") == name


class OpenAICompatibleChatEngine:
    name = "openai"

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # Set once the provider refuses function tools with its default reasoning effort
        # (api.openai.com, gpt-6-luna, 2026-09-27: "set reasoning_effort to 'none'").
        self.tool_reasoning_effort: str | None = None

    def raw_chat_text(self, messages: list[dict[str, str]]) -> str:
        raw = self._chat(messages)
        content = raw["choices"][0]["message"]["content"]
        return content if isinstance(content, str) else ""

    def raw_chat_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        return self._chat_stream(messages)

    @property
    def provider(self) -> str:
        return "openrouter" if "openrouter.ai" in self.base_url else "openai-compatible"

    def stream_chat(
        self, messages: list[dict], *, tools: list[dict] | None = None
    ) -> Iterator[dict]:
        """One streamed chat completion with optional OpenAI-style function tools.

        Yields ``{"type": "delta", "text"}`` for content and finally one
        ``{"type": "message", "content", "toolCalls", "usage", "finishReason"}``
        with the tool calls assembled from their streamed fragments. The host
        (the Lab tool loop) runs the calls; this engine never does.
        """
        body: dict = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
            if self.tool_reasoning_effort:
                body["reasoning_effort"] = self.tool_reasoning_effort
        content: list[str] = []
        calls: dict[int, dict] = {}
        usage: dict | None = None
        finish_reason: str | None = None
        with self._open_stream(body) as response:
            for line in response.iter_lines():
                payload = _parse_stream_payload(line)
                if payload is None:
                    continue
                if isinstance(payload.get("usage"), dict):
                    usage = payload["usage"]
                choices = payload.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                choice = choices[0] if isinstance(choices[0], dict) else {}
                if choice.get("finish_reason"):
                    finish_reason = str(choice["finish_reason"])
                delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                text = delta.get("content")
                if isinstance(text, str) and text:
                    content.append(text)
                    yield {"type": "delta", "text": text}
                for fragment in delta.get("tool_calls") or ():
                    if not isinstance(fragment, dict):
                        continue
                    index = fragment.get("index", len(calls))
                    call = calls.setdefault(int(index), {"id": "", "name": "", "arguments": ""})
                    if fragment.get("id"):
                        call["id"] = str(fragment["id"])
                    function = fragment.get("function") if isinstance(fragment.get("function"), dict) else {}
                    if function.get("name"):
                        call["name"] += str(function["name"])
                    if function.get("arguments"):
                        call["arguments"] += str(function["arguments"])
        tool_calls = [
            {**call, "id": call["id"] or f"call_{index}"} for index, call in sorted(calls.items())
        ]
        yield {
            "type": "message",
            "content": "".join(content),
            "toolCalls": tool_calls,
            "usage": _normalize_usage(usage),
            "finishReason": finish_reason,
        }

    def check(self) -> dict:
        """One short completion, for the settings view's connection check.

        Newer OpenAI models reject ``max_tokens`` with a 400 naming that parameter, and a
        reasoning model cannot finish under a tiny ``max_completion_tokens`` either (both
        seen with gpt-6-luna on 2026-09-27), so that answer is retried once without a cap.
        """
        ping = [{"role": "user", "content": "ping"}]
        try:
            raw = self._chat(ping, max_tokens=1)
        except httpx.HTTPStatusError as exc:
            if not _rejects_parameter(exc.response, "max_tokens"):
                raise
            raw = self._chat(ping)
        return {"model": raw.get("model") or self.model}

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "http://localhost:8000"
            headers["X-Title"] = LAB_TITLE
        return headers

    def _chat(self, messages: list[dict], *, max_tokens: int | None = None) -> dict:
        body: dict = {"model": self.model, "messages": messages}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=body,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    @contextmanager
    def _open_stream(self, body: dict) -> Iterator[httpx.Response]:
        """POST a streamed completion; a refusal of tools with reasoning is retried once.

        The retry sends ``reasoning_effort: "none"``, the fix the provider's own 400 names;
        the engine keeps it for later tool calls. Any other error status raises.
        """
        with self._stream(body) as response:
            if not _refuses_tool_reasoning(body, response):
                response.raise_for_status()
                yield response
                return
        self.tool_reasoning_effort = "none"
        with self._stream({**body, "reasoning_effort": "none"}) as response:
            response.raise_for_status()
            yield response

    def _stream(self, body: dict):
        return httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=body,
            timeout=self.timeout,
        )

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


def _parse_stream_payload(line: str | bytes) -> dict | None:
    text = line.decode("utf-8") if isinstance(line, bytes) else line
    if not text.startswith("data: "):
        return None
    data = text.removeprefix("data: ").strip()
    if not data or data == "[DONE]":
        return None
    payload = json.loads(data)
    return payload if isinstance(payload, dict) else None


def _normalize_usage(usage: dict | None) -> dict | None:
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if not isinstance(prompt, int | float) and not isinstance(completion, int | float):
        return None
    return {
        "promptTokens": int(prompt) if isinstance(prompt, int | float) else None,
        "completionTokens": int(completion) if isinstance(completion, int | float) else None,
        "totalTokens": int(usage["total_tokens"]) if isinstance(usage.get("total_tokens"), int | float) else None,
    }


SCRIPTED_REPLY = (
    "Scripted reply (no model key): the Lab ran the turn pipeline (workspace check, reindex, "
    "recall, prompt, then the flush decision) but called no model, ran no memory tool and runs "
    "no flush turn."
)


class ScriptedChatEngine:
    """Explicit keyless stand-in, labelled ``scripted``: fixed text, never a tool call.

    Only used when a request asks for ``engine: "scripted"``; it makes no
    memory decision, so nothing it returns can pass for model output.
    """

    name = "scripted"
    provider = "scripted"
    model = "lab-script"

    def stream_chat(self, messages: list[dict], *, tools: list[dict] | None = None) -> Iterator[dict]:
        del messages, tools
        yield {"type": "delta", "text": SCRIPTED_REPLY}
        yield {
            "type": "message",
            "content": SCRIPTED_REPLY,
            "toolCalls": [],
            "usage": None,
            "finishReason": "stop",
        }


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
