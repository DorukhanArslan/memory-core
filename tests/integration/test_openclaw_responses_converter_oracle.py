"""The Responses message converter against the real v2026.9.6 TS.

``convertResponsesMessages`` / ``convertProviderResponsesMessages``
(``openai-responses-replay-messages-internal.ts``) are run by the oracle over generated message
histories (roles, tool calls and results, images, reasoning, thinking blocks, unicode, failed
turns, async calls, compaction checkpoints) for both projections, several models and identities,
and :mod:`memory_core.responses_converter` must return the same wire ``input`` (or fail with the
same error class). The building blocks (tool-result text extraction, the thinking replay mode, the
provider and transport transcript transforms) are compared on their own as well, so a divergence
points at one function.

Known deviation, left out of the fixtures on purpose: the structured redaction of
``redactModelVisibleSecrets`` (field-name based masking); see docs/gap4-compaction-notes.md.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import random
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core import compaction_replay as cr
from memory_core import responses_converter as rc
from memory_core import tool_result_text as trt
from memory_core import transcript_transform as tt

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)

_URL = "https://api.openai.com/v1"
MODELS: dict[str, dict[str, Any]] = {
    "responses": {"provider": "openai", "api": "openai-responses", "id": "gpt-x", "baseUrl": _URL},
    "reasoning": {
        "provider": "openai",
        "api": "openai-responses",
        "id": "gpt-r",
        "baseUrl": _URL,
        "reasoning": True,
    },
    "reasoning_no_dev": {
        "provider": "openai",
        "api": "openai-responses",
        "id": "gpt-r",
        "baseUrl": _URL,
        "reasoning": True,
        "compat": {"supportsDeveloperRole": False},
    },
    "reasoning_dev": {
        "provider": "openai",
        "api": "openai-responses",
        "id": "gpt-r",
        "baseUrl": _URL,
        "reasoning": True,
        "compat": {"supportsDeveloperRole": True},
    },
    "text_only": {
        "provider": "openai",
        "api": "openai-responses",
        "id": "gpt-t",
        "baseUrl": _URL,
        "input": ["text"],
    },
    "azure": {
        "provider": "azure-openai-responses",
        "api": "azure-openai-responses",
        "id": "gpt-x",
        "baseUrl": "https://example.openai.azure.com/openai/v1",
    },
    "chatgpt": {"provider": "openai", "api": "openai-chatgpt-responses", "id": "gpt-x"},
    "transport": {
        "provider": "openai",
        "api": "openclaw-openai-responses-transport",
        "id": "gpt-x",
        "baseUrl": _URL,
    },
    "copilot": {
        "provider": "github-copilot",
        "api": "openai-responses",
        "id": "gpt-x",
        "baseUrl": "https://api.githubcopilot.com",
    },
    "opencode": {
        "provider": "opencode",
        "api": "openai-responses",
        "id": "gpt-x",
        "baseUrl": "https://opencode.ai/zen/v1",
    },
    "foreign_provider": {
        "provider": "deepseek",
        "api": "openai-responses",
        "id": "ds-x",
        "baseUrl": "https://api.deepseek.com/v1",
    },
    "completions_video": {
        "provider": "openai",
        "api": "openai-completions",
        "id": "gpt-x",
        "input": ["text", "image", "video"],
    },
    "anthropic": {
        "provider": "anthropic",
        "api": "anthropic-messages",
        "id": "claude-sonnet-4",
        "baseUrl": "https://api.anthropic.com",
    },
    "fable51": {
        "provider": "anthropic",
        "api": "anthropic-messages",
        "id": "claude-fable-5-1",
        "baseUrl": "https://api.anthropic.com",
    },
    "fable5": {
        "provider": "anthropic",
        "api": "anthropic-messages",
        "id": "claude-fable-5",
        "baseUrl": "https://api.anthropic.com",
    },
}
RESPONSES_MODELS = [
    "responses",
    "reasoning",
    "reasoning_no_dev",
    "text_only",
    "azure",
    "chatgpt",
    "transport",
    "copilot",
    "opencode",
    "foreign_provider",
]
IDENTS: dict[str, dict[str, Any]] = {
    "none": {},
    "both": {"sessionId": "s1", "authProfileId": "a1"},
    "unicode": {"sessionId": "séssion-\U0001f600", "authProfileId": " a2 "},
}
_COST = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}


@pytest.fixture(scope="module")
def oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))


def _clean(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _py_model(model: dict[str, Any]) -> cr.ReplayModel:
    return cr.ReplayModel(
        model["provider"],
        model["api"],
        model["id"],
        model.get("baseUrl"),
        tuple(model.get("input", ("text", "image"))),
        model.get("reasoning", False),
        model.get("compat"),
        model.get("params"),
    )


def _error_name(exc: Exception) -> str:
    return type(exc).__name__


def _run(oracle: OpenClawOracle, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = oracle.run({"operation": "compactionCheckpoint", "cases": cases})
    assert result["ok"] is True
    return result["result"]


def _first_diffs(cases: list[Any], rows: list[Any], python_rows: list[Any]) -> list[Any]:
    assert len(rows) == len(python_rows) == len(cases)
    return [
        (case, row, python)
        for case, row, python in zip(cases, rows, python_rows, strict=True)
        if _clean(row) != _clean(python)
    ][:3]


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


_PNG = _b64(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 7)

# --- message building blocks ------------------------------------------------------------------


def _assistant(model: dict[str, Any], content: Any, **extra: Any) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content,
        "api": model["api"],
        "provider": model["provider"],
        "model": model["id"],
        "usage": {
            "input": 10,
            "output": 5,
            "cacheRead": 0,
            "cacheWrite": 0,
            "totalTokens": 15,
            "cost": dict(_COST),
        },
        "stopReason": "stop",
        "timestamp": 1,
        **extra,
    }


def _user(content: Any = "hello") -> dict[str, Any]:
    return {"role": "user", "content": content, "timestamp": 1}


def _tool_result(call_id: str, content: Any, **extra: Any) -> dict[str, Any]:
    return {
        "role": "toolResult",
        "toolCallId": call_id,
        "toolName": "read",
        "content": content,
        "isError": False,
        "timestamp": 1,
        **extra,
    }


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _image(data: str = _PNG, mime: str = "image/png") -> dict[str, Any]:
    return {"type": "image", "data": data, "mimeType": mime}


def _call(call_id: str, name: str = "read", arguments: Any = None, **extra: Any) -> dict[str, Any]:
    return {
        "type": "toolCall",
        "id": call_id,
        "name": name,
        "arguments": {"path": "a.txt"} if arguments is None else arguments,
        **extra,
    }


def _reasoning_json(**over: Any) -> str:
    item = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "ENC"}
    item.update(over)
    return json.dumps({k: v for k, v in item.items() if v != "__drop__"})


def _thinking(
    text: str = "pondering", signature: str | None = None, **extra: Any
) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "thinking", "thinking": text, **extra}
    if signature is not None:
        block["thinkingSignature"] = signature
    return block


# --- tool result text -------------------------------------------------------------------------


def _tool_text_cases() -> list[list[Any]]:
    big = "x" * 9000
    uri = "data:image/png;base64," + "A" * 60
    return [
        [],
        [_text("hello")],
        [_text("a"), _text("b"), _text("")],
        [_text("")],
        [_text("é\U0001f600 日本")],
        [_text("lone \ud83d surrogate"), _text("tail \ude00")],
        [_text(f"see {uri} here"), _text(f"({uri})"), _text(f"x{uri}y")],
        [_text("DATA:IMAGE/PNG;BASE64,QUJD x"), _text("data:text/plain,hello world")],
        [_image()],
        [_image(), _text("caption")],
        [_image(""), _image("   "), {"type": "image"}],
        [{"type": "audio", "data": "QUJD", "mimeType": "audio/wav"}],
        [{"type": "audio", "data": "QUJD", "mimeType": "audio/wav"}, _image()],
        [{"type": "file", "data": "QUJD", "mimeType": "image/png"}],
        [{"type": "file", "data": "QUJD", "mime_type": "audio/mpeg"}],
        [{"type": "input_image", "data": "x"}, {"type": "image_url", "data": "y"}],
        [{"type": "json", "value": {"a": 1, "b": [1, 2, 3], "c": "d"}}],
        [{"type": "json", "value": {"b": 1, "a": 2, "10": 3, "9": 4, "x": None}}],
        [{"type": "resource", "data": "QUJD", "mimeType": "application/octet-stream"}],
        [{"type": "resource", "data": "hello", "mimeType": "text/plain"}],
        [{"type": "resource", "data": "{}", "mimeType": "application/json; charset=utf-8"}],
        [{"type": "resource", "data": "<a/>", "mediaType": "application/atom+xml"}],
        [{"type": "resource", "data": "zip", "contentType": "application/zip"}],
        [{"type": "resource", "data": "q", "mimeType": " "}],
        [{"type": "json", "encrypted_content": "secret", "blob": "x", "bytes": 5, "Buffer": 1}],
        [{"type": "json", "encrypted_stdout": "s", "ok": True}],
        [{"type": "big", "value": big}],
        [_text("lead"), {"type": "big", "value": big}],
        [{"type": "nums", "n": [1.5, 1e21, 1e-7, -0.0, 100.0, 2**53, 0.1]}],
        [{"type": "uni", "kéy": "\U0001f600\ud83d", "\U0001f600": "v"}],
        [{"type": "nested", "a": {"b": {"c": [{"d": uri}]}}}],
        [{"type": "empty"}, {}],
        [{"type": "x", "u": None}],
        [[1, 2, 3], ["a"]],
        [None, 5, "str", True],
        [{"type": "text"}, {"type": "text", "text": 5}, {"type": "text", "text": None}],
        [{"type": "thinking", "thinking": "t"}],
        [{"type": "a", "v": "a" * 8100}, {"type": "b", "v": "b" * 50}],
    ]


def _py_tool_text(case: dict[str, Any]) -> dict[str, Any]:
    blocks = _clean(case["blocks"])
    try:
        value: Any = {
            "text": trt.extract_tool_result_text(
                blocks,
                include_structured=(case.get("options") or {}).get("includeStructured", False),
            ),
            "placeholder": trt.describe_tool_result_media_placeholder(blocks),
            "hasImage": [trt.is_image_with_media_payload(b) for b in blocks],
            "blocks": [trt.extract_tool_result_block_text(b) for b in blocks],
        }
        error = None
    except Exception as exc:  # noqa: BLE001
        value, error = None, _error_name(exc)
    return {"value": value, "error": error}


def test_real_openclaw_oracle_tool_result_text_matches_python(oracle):
    cases = [
        {"fn": "toolResultText", "blocks": blocks, "options": options}
        for blocks in _tool_text_cases()
        for options in (None, {"includeStructured": True})
    ]
    rows = _run(oracle, cases)
    python_rows = [_py_tool_text(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    assert len({json.dumps(row["value"]) for row in rows}) > 30


# --- model-bound thinking replay mode ---------------------------------------------------------

_REPLAY_IDS = [
    None,
    "",
    " ",
    "gpt-x",
    "claude-sonnet-4",
    "claude-sonnet-5",
    "Claude-Sonnet-5-1",
    "anthropic/claude-sonnet-5",
    "claude-opus-5",
    "claude-opus-5-5",
    "claude-opus-5-5-20260101",
    "opus",
    "opus-5",
    "opus-5-5",
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-fable-5-1-20260101",
    "claude-fable-5-10",
    "claude.fable.5.1",
    "claude fable 5 1",
    "us.anthropic.claude-fable-5-1-v1:0",
    "bedrock/claude-fable-5",
    "claude-mythos-5",
    "claude-mythos-5-1",
    "claude-mythos-preview",
    "global.anthropic.claude-sonnet-5-v1",
    "vertex/claude-opus-5@20260101",
    "CLAUDE-FABLE-5",
    "claude-",
    "xclaude-fable-5",
    "x-claude-fable-5",
    "x/claude-fable-5",
]


def test_real_openclaw_oracle_bound_thinking_replay_mode_matches_python(oracle):
    rng = random.Random(5)
    apis = ["anthropic-messages", "openclaw-anthropic-messages-transport", "openai-responses", None]
    providers = ["anthropic", "Anthropic", " anthropic ", "openai", "bedrock", None]
    params = [
        None,
        {},
        {"canonicalModelId": "claude-fable-5-1"},
        {"canonicalModelId": 5},
        {"canonicalModelId": "claude-sonnet-5"},
        {"canonicalModelId": "gpt-x"},
    ]
    cases = []
    for _ in range(1600):
        source = {
            "provider": rng.choice(providers),
            "api": rng.choice(apis),
            "modelId": rng.choice(_REPLAY_IDS),
            "responseModelId": rng.choice([None, None, *_REPLAY_IDS]),
        }
        target = {
            "provider": rng.choice(providers),
            "api": rng.choice(apis),
            "modelId": rng.choice(_REPLAY_IDS),
            "modelParams": rng.choice(params),
        }
        cases.append({"fn": "boundReplayMode", "source": source, "target": target})
    rows = _run(oracle, cases)
    python_rows = [
        {
            "value": tt.resolve_model_bound_thinking_replay_mode(c["source"], c["target"]),
            "error": None,
        }
        for c in cases
    ]
    assert _first_diffs(cases, rows, python_rows) == []
    assert {row["value"] for row in rows} == {"default", "preserve", "drop"}


# --- generated histories ----------------------------------------------------------------------


class _Gen:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def pick(self, items: list[Any]) -> Any:
        return self.rng.choice(items)

    def source_model(self, model: dict[str, Any]) -> dict[str, Any]:
        roll = self.rng.random()
        if roll < 0.55:
            return model
        if roll < 0.65:
            return {**model, "id": model["id"] + "-other"}
        if roll < 0.72:
            return {**model, "api": "openai-chatgpt-responses"}
        if roll < 0.8:
            return {**model, "provider": "somewhere"}
        if roll < 0.87:
            return MODELS["anthropic"]
        if roll < 0.92:
            return MODELS[self.pick(["fable5", "fable51"])]
        return MODELS[self.pick(RESPONSES_MODELS)]

    def call_id(self) -> str:
        return self.pick(
            [
                "call_1",
                "call_2|fc_2",
                "call_3|item with spaces/é",
                " call_4 ",
                " call_5|fc_5 ",
                "x" * 80,
                "y" * 70 + "|" + "z" * 90,
                "call|" + "\U0001f600" * 20,
                "call_6|msg_6",
                "toolu_01|abc",
                "a|b|c",
                "|",
                "call_7|",
                "|fc_8",
                "weird!@#$%^&*()_+",
                "trail___",
                "call_9|fc_trail___",
                "é" * 5,
            ]
        )

    def args(self) -> Any:
        return self.pick(
            [
                {"path": "a.txt"},
                {},
                {"a": 1, "b": [1, 2, {"c": None}], "d": "é\U0001f600"},
                {"n": 1.5, "m": 1e21, "k": 100.0},
                {"10": 1, "9": 2, "a": 3},
                "raw string",
                [1, 2],
                5,
                None,
            ]
        )

    def text_block(self) -> dict[str, Any]:
        text = self.pick(["answer", "", "  ", "é\U0001f600 日本語", "lone \ud83d x", "multi\nline"])
        block = _text(text)
        roll = self.rng.random()
        if roll < 0.15:
            block["textSignature"] = "msg_sig"
        elif roll < 0.3:
            block["textSignature"] = json.dumps({"v": 1, "id": "msg_v1", "phase": "final_answer"})
        elif roll < 0.4:
            block["textSignature"] = json.dumps({"v": 1, "phase": "commentary"})
        elif roll < 0.45:
            block["textSignature"] = json.dumps({"v": 1})
        elif roll < 0.5:
            block["textSignature"] = json.dumps({"v": 2, "id": "x"})
        elif roll < 0.55:
            block["textSignature"] = "{not json"
        elif roll < 0.58:
            block["textSignature"] = json.dumps({"v": 1, "id": "m" * 90})
        elif roll < 0.6:
            block["textSignature"] = "null"
        return block

    def thinking_block(self, model: dict[str, Any], ident: dict[str, Any]) -> dict[str, Any]:
        meta = cr.build_openai_responses_reasoning_replay_metadata(
            _py_model(model), cr.ReplayIdentity(ident.get("sessionId"), ident.get("authProfileId"))
        )
        wrong = {**meta, "model": "other"}
        roll = self.rng.random()
        if roll < 0.12:
            return _thinking("plain thought")
        if roll < 0.2:
            return _thinking("", _reasoning_json())
        if roll < 0.35:
            return _thinking(signature=_reasoning_json())
        if roll < 0.45:
            return _thinking(signature=_reasoning_json(encrypted_content="__drop__"))
        if roll < 0.55:
            return _thinking(signature=_reasoning_json(__openclaw_replay=meta))
        if roll < 0.62:
            return _thinking(signature=_reasoning_json(__openclaw_replay=wrong))
        if roll < 0.68:
            return _thinking(signature=_reasoning_json(), openclawReasoningReplay=meta)
        if roll < 0.74:
            return _thinking(signature=_reasoning_json(), openclawReasoningReplay=wrong)
        if roll < 0.78:
            return _thinking(signature=_reasoning_json(), openclawReasoningReplay="bad")
        if roll < 0.82:
            return _thinking(signature=_reasoning_json(id="rs_x" * 30))
        if roll < 0.85:
            return _thinking(
                signature=_reasoning_json(summary=[{"type": "summary_text", "text": "s"}])
            )
        if roll < 0.88:
            return _thinking(signature="{not json")
        if roll < 0.9:
            return _thinking(signature=json.dumps({"type": "message"}))
        if roll < 0.92:
            return _thinking(signature=json.dumps([1]))
        if roll < 0.94:
            return _thinking("redacted", "opaque", redacted=True)
        if roll < 0.96:
            return _thinking(
                signature=_reasoning_json(id="fc_1", nested={"encrypted_content": "q"})
            )
        return _thinking(signature=_reasoning_json(id="rs_2", encrypted_content=""))

    def assistant(
        self, model: dict[str, Any], ident: dict[str, Any], calls: list[str]
    ) -> dict[str, Any]:
        source = self.source_model(model)
        content: list[Any] = []
        for _ in range(self.rng.randrange(0, 5)):
            roll = self.rng.random()
            if roll < 0.4:
                content.append(self.text_block())
            elif roll < 0.6:
                content.append(self.thinking_block(source, ident))
            else:
                call_id = self.call_id()
                calls.append(call_id)
                extra: dict[str, Any] = {}
                if self.rng.random() < 0.15:
                    extra["async"] = True
                if self.rng.random() < 0.1:
                    extra["thoughtSignature"] = "sig"
                content.append(
                    _call(call_id, self.pick(["read", "exec", "é"]), self.args(), **extra)
                )
        extra = {}
        roll = self.rng.random()
        if roll < 0.08:
            extra["stopReason"] = "error"
        elif roll < 0.14:
            extra["stopReason"] = "aborted"
        elif roll < 0.18:
            extra["stopReason"] = "length"
        elif roll < 0.22:
            extra["stopReason"] = "toolUse"
        if self.rng.random() < 0.15:
            extra["responseId"] = self.pick(["resp_1", "resp_2"])
        if self.rng.random() < 0.1:
            extra["turnId"] = self.pick(["turn_1", "turn_2"])
        if self.rng.random() < 0.05:
            extra["responseModel"] = self.pick(["claude-fable-5-1", "gpt-x"])
        if self.rng.random() < 0.03:
            content = self.pick(["plain string content", None, {"type": "text", "text": "obj"}])
        return _assistant(source, content, **extra)

    def tool_result(self, calls: list[str]) -> dict[str, Any]:
        call_id = self.pick(calls) if calls and self.rng.random() < 0.8 else self.call_id()
        content = self.pick(
            [
                [_text("result text")],
                [_text("a"), _text("b")],
                [_text("")],
                [],
                [_image()],
                [_text("see"), _image()],
                [_image(), _image("   ")],
                [{"type": "audio", "data": "QUJD", "mimeType": "audio/wav"}],
                [{"type": "json", "v": {"k": [1, 2]}}],
                [{"type": "blob", "data": "QUJD", "mimeType": "application/pdf"}],
                [_text("é\U0001f600 日本"), {"type": "json", "v": 1}],
                [_text("data:image/png;base64," + "A" * 50)],
                [_text("lone \ud83d")],
            ]
        )
        extra: dict[str, Any] = {}
        if self.rng.random() < 0.1:
            extra["isError"] = True
        if self.rng.random() < 0.05:
            extra["details"] = {"openclawSyntheticMissingToolResult": True}
            content = [_text("No result provided")]
        return _tool_result(call_id, content, **extra)

    def user(self) -> dict[str, Any]:
        content = self.pick(
            [
                "hello",
                "é\U0001f600 日本語",
                "lone \ud83d",
                "",
                [_text("hi"), _image()],
                [_image()],
                [_text("a"), _image(), _text("b")],
                [_image(""), _text("x")],
                [_text(""), _text("é")],
                [{"type": "video", "data": "QUJD", "mimeType": "video/mp4"}, _text("v")],
                [{"type": "file", "data": "QUJD"}],
                [{"type": "image", "data": "   "}],
            ]
        )
        message = _user(content)
        if self.rng.random() < 0.1:
            message["runtimeContextCarrier"] = True
        return message

    def checkpoint(self, model: dict[str, Any], ident: dict[str, Any]) -> dict[str, Any]:
        ctx = {
            k: v
            for k, v in cr.build_provider_replay_context(
                _py_model(model),
                cr.ReplayIdentity(ident.get("sessionId"), ident.get("authProfileId")),
            ).items()
            if v is not None
        }
        state: dict[str, Any] = {
            "v": 1,
            "type": "openai-responses-compaction",
            "data": "ENCRYPTED",
            "replayIndex": self.pick([0, 1, 2]),
            **ctx,
        }
        roll = self.rng.random()
        if roll < 0.35:
            window = [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hi"}],
                },
                {"type": "compaction", "encrypted_content": "ENCRYPTED"},
            ]
            state["compactedWindow"] = {"state": "ready", "output": json.dumps(window)}
        elif roll < 0.5:
            state["type"] = "openai-responses-retained-compaction"
            state.pop("replayIndex")
        elif roll < 0.6:
            state["compactedWindow"] = {"state": "refresh-required"}
        content = [_text("A"), _text("B"), _text("C")]
        return _assistant(model, content, providerReplay=state)

    def history(self, model: dict[str, Any], ident: dict[str, Any]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        calls: list[str] = []
        use_checkpoint = self.rng.random() < 0.12
        for index in range(self.rng.randrange(1, 9)):
            roll = self.rng.random()
            if use_checkpoint and index == 1:
                messages.append(self.checkpoint(model, ident))
            elif roll < 0.3:
                messages.append(self.user())
            elif roll < 0.62:
                messages.append(self.assistant(model, ident, calls))
            elif roll < 0.92:
                messages.append(self.tool_result(calls))
            else:
                messages.append(
                    {"role": self.pick(["system", "custom", "bashExecution"]), "content": "x"}
                )
        if self.rng.random() < 0.7 and messages and messages[-1]["role"] != "user":
            messages.append(self.user())
        # async result ordering and delivery-order replay state
        if self.rng.random() < 0.12:
            for message in messages:
                if message["role"] == "assistant" and self.rng.random() < 0.5:
                    message["openclawResponsesInputReplay"] = {
                        "afterResponseId": self.pick(["resp_1", "resp_2", "resp_x"]),
                        "before": [rc.responses_input_fingerprint(_user_wire("hello"))],
                        "after": [],
                    }
        return messages


def _user_wire(text: str) -> dict[str, Any]:
    return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}


def _python_convert(case: dict[str, Any]) -> dict[str, Any]:
    messages = _clean(case["messages"])
    model = _py_model(case["model"])
    identity = case.get("identity", {})
    options = case.get("options") or {}
    kwargs: dict[str, Any] = {
        "session_id": identity.get("sessionId"),
        "auth_profile_id": identity.get("authProfileId"),
        "replay_responses_item_ids": options.get("replayResponsesItemIds"),
        "replay_mode": options.get("replayMode"),
        "include_system_prompt": case.get("includeSystemPrompt"),
    }
    try:
        if case["projection"] == "provider":
            value = rc.convert_provider_responses_messages(
                model, messages, case.get("systemPrompt"), **kwargs
            )
        else:
            value = rc.convert_responses_messages(
                model,
                messages,
                case.get("systemPrompt"),
                replay_reasoning_items=options.get("replayReasoningItems"),
                **kwargs,
            )
        error = None
    except Exception as exc:  # noqa: BLE001 - the oracle reports the class name
        value, error = None, _error_name(exc)
    return {"value": value, "error": error}


_SYSTEM_PROMPTS = [
    None,
    "",
    "You are helpful.",
    "stable\n<!-- OPENCLAW_CACHE_BOUNDARY -->\ndynamic",
    "a<!-- OPENCLAW_CACHE_BOUNDARY -->b",
    "x\n<!-- OPENCLAW-RELOCATABLE-BOUNDARY -->\nfacts\n<!-- /OPENCLAW-RELOCATABLE-BOUNDARY -->",
    "é\U0001f600 lone \ud83d",
]


def _convert_cases(count: int, seed: int) -> list[dict[str, Any]]:
    gen = _Gen(seed)
    cases = []
    for _ in range(count):
        model_key = gen.pick(RESPONSES_MODELS)
        ident = IDENTS[gen.pick(list(IDENTS))]
        model = MODELS[model_key]
        options: dict[str, Any] = {}
        roll = gen.rng.random()
        if roll < 0.08:
            options["replayReasoningItems"] = False
        elif roll < 0.16:
            options["replayResponsesItemIds"] = False
        elif roll < 0.2:
            options["replayMode"] = "full-history"
        case: dict[str, Any] = {
            "fn": "convert",
            "model": model,
            "identity": ident,
            "projection": gen.pick(["transport", "provider"]),
            "systemPrompt": gen.pick(_SYSTEM_PROMPTS),
            "messages": gen.history(model, ident),
            "options": options,
        }
        if gen.rng.random() < 0.5:
            case["includeSystemPrompt"] = gen.pick([True, False])
        if case["projection"] == "provider":
            options.pop("replayReasoningItems", None)
        cases.append(case)
    return cases


def test_real_openclaw_oracle_responses_converter_matches_python(oracle):
    cases = _convert_cases(4000, 2026)
    rows = _run(oracle, cases)
    python_rows = [_python_convert(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    ok = [row for row in rows if row["error"] is None]
    assert len(ok) > 0.7 * len(rows)
    errors = {row["error"] for row in rows if row["error"]}
    assert errors <= {"TypeError", "CompactionReplayRefreshRequiredError"}, errors
    types = {item.get("type") for row in ok for item in row["value"] if isinstance(item, dict)}
    assert {"message", "function_call", "function_call_output", "reasoning"} <= types
    assert len({json.dumps(row["value"]) for row in ok}) > 2000


def _fixed_histories() -> list[list[dict[str, Any]]]:
    model = MODELS["responses"]
    call = _call("call_1|fc_1")
    return [
        [_user("q"), _assistant(model, [_text("a")]), _user("q2")],
        [
            _user("q"),
            _assistant(model, [_text("a"), call]),
            _tool_result("call_1|fc_1", [_text("r")]),
            _user("q2"),
        ],
        [_user("q"), _assistant(model, [call]), _user("q2")],
        [_user("q"), _tool_result("call_1|fc_1", [_text("orphan")])],
        [
            _user([_text("look"), _image()]),
            _assistant(model, [_thinking(signature=_reasoning_json()), _text("a")]),
        ],
        [_user("q"), _assistant(model, [], stopReason="error")],
        [_user("q"), _assistant(model, [_text("partial")], stopReason="aborted")],
        [_user("q"), _assistant(model, [_thinking("t")], stopReason="length"), _user("again")],
        [],
        [_user("\ud83d lone")],
    ]


def test_real_openclaw_oracle_responses_converter_fixed_histories_match_python(oracle):
    cases = []
    for key in RESPONSES_MODELS:
        for projection in ("transport", "provider"):
            for messages in _fixed_histories():
                cases.append(
                    {
                        "fn": "convert",
                        "model": MODELS[key],
                        "identity": {},
                        "projection": projection,
                        "systemPrompt": "sys",
                        "messages": messages,
                        "options": {},
                    }
                )
    rows = _run(oracle, cases)
    python_rows = [_python_convert(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    assert sum(1 for row in rows if row["error"] is None) > 0.9 * len(rows)


# --- the transforms on their own --------------------------------------------------------------


def _zero_timestamps(value: Any) -> Any:
    if isinstance(value, list):
        return [_zero_timestamps(item) for item in value]
    if isinstance(value, dict):
        return {k: 0 if k == "timestamp" else _zero_timestamps(v) for k, v in value.items()}
    return value


def _py_transform(case: dict[str, Any]) -> dict[str, Any]:
    messages = copy.deepcopy(_clean(case["messages"]))
    model = _py_model(case["model"])

    def normalize(tool_id: str, _model: Any, _source: Any) -> str:
        return f"n:{tool_id}"

    options = case.get("options") or {}
    try:
        if case["style"] == "provider":
            value = tt.transform_provider_messages(
                messages, model, normalize if case.get("normalize") else None
            )
        else:
            value = tt.transform_transport_messages(
                messages,
                model,
                normalize if case.get("normalize") else None,
                normalize_same_model_tool_call_ids=options.get(
                    "normalizeSameModelToolCallIds", False
                ),
                preserve_cross_model_tool_call_thought_signature=options.get(
                    "preserveCrossModelToolCallThoughtSignature", False
                ),
                preserve_unframed_tool_results=options.get("preserveUnframedToolResults", False),
            )
        error = None
    except Exception as exc:  # noqa: BLE001
        value, error = None, _error_name(exc)
    return {"value": _zero_timestamps(value), "error": error}


def test_real_openclaw_oracle_transcript_transforms_match_python(oracle):
    gen = _Gen(404)
    cases = []
    keys = [*RESPONSES_MODELS, "completions_video", "anthropic", "fable5", "fable51"]
    for _ in range(3000):
        model = MODELS[gen.pick(keys)]
        ident = IDENTS["none"]
        style = gen.pick(["provider", "transport"])
        options: dict[str, Any] = {}
        if style == "transport" and gen.rng.random() < 0.5:
            options = {
                "normalizeSameModelToolCallIds": gen.pick([True, False]),
                "preserveCrossModelToolCallThoughtSignature": gen.pick([True, False]),
                "preserveUnframedToolResults": gen.pick([True, False]),
            }
        cases.append(
            {
                "fn": "transform",
                "style": style,
                "model": model,
                "normalize": gen.rng.random() < 0.7,
                "options": options,
                "messages": gen.history(model, ident),
            }
        )
    rows = _run(oracle, cases)
    for row in rows:
        row["value"] = _zero_timestamps(row["value"])
    python_rows = [_py_transform(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    assert sum(1 for row in rows if row["error"] is None) > 0.7 * len(rows)
