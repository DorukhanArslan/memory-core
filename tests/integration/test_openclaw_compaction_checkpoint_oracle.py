"""Compaction checkpoint resolvers and inbound-metadata helpers against the real v2026.9.6 TS.

``resolveCompactionSource`` is private upstream; it is reached through
``requiresCompactionReplayRefresh`` and ``preserveCompactionReplayWindow``, with the Anthropic and
Responses newest-checkpoint resolvers and the two replay-plan builders compared directly. The
provider replay context hashes (``shortHash``) used to build the fixtures' checkpoint states come
from the TS oracle itself, so a hash bug cannot hide behind a self-consistent fixture.

Model identity, session and auth identity are plain parameters on the Python side. The Responses
compact-endpoint egress projection (inline image sanitiser plus the payload policy's input status
rule) is built in; the ``egress_projection`` hook stays an override and is unit tested separately.

Later sections cover the capture and suppression writers, ``resolveCompactionReplayEligibility``
(against the real OpenClaw transport host, so endpoint classes come from the plugin manifests),
``resolveCompactionReplayPressure`` and the inline image sanitiser. The measured-usage boundary
runs the Responses message converter: the oracle's real ``recordResponsesContextUsage`` builds the
fixtures, and Python rebuilds the wire input with its built-in converter
(``responses_converter.py``, compared message by message in
``test_openclaw_responses_converter_oracle.py``) and, as the override path, with the hook fed from
the real converter's output.
"""

from __future__ import annotations

import base64
import copy
import itertools
import json
import os
import random
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core import compaction_replay as cr

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)

MODELS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "provider": "anthropic",
        "api": "anthropic-messages",
        "id": "claude-x",
        "baseUrl": "https://api.anthropic.com",
    },
    "anthropic_other_id": {
        "provider": "anthropic",
        "api": "anthropic-messages",
        "id": "claude-y",
        "baseUrl": "https://api.anthropic.com",
    },
    "anthropic_other_url": {
        "provider": "anthropic",
        "api": "anthropic-messages",
        "id": "claude-x",
        "baseUrl": "https://proxy.example/anthropic",
    },
    "anthropic_no_url": {"provider": "anthropic", "api": "anthropic-messages", "id": "claude-x"},
    "responses": {
        "provider": "openai",
        "api": "openai-responses",
        "id": "gpt-x",
        "baseUrl": "https://api.openai.com/v1",
    },
    "responses_other_id": {
        "provider": "openai",
        "api": "openai-responses",
        "id": "gpt-y",
        "baseUrl": "https://api.openai.com/v1",
    },
    "azure": {
        "provider": "azure-openai",
        "api": "azure-openai-responses",
        "id": "gpt-x",
        "baseUrl": "https://example.openai.azure.com/openai/v1",
    },
    "chatgpt": {
        "provider": "openai",
        "api": "openai-chatgpt-responses",
        "id": "gpt-x",
        "baseUrl": "https://api.openai.com/v1",
    },
    "transport": {
        "provider": "openai",
        "api": "openclaw-openai-responses-transport",
        "id": "gpt-x",
        "baseUrl": "https://api.openai.com/v1",
    },
    "completions": {
        "provider": "openai",
        "api": "openai-completions",
        "id": "gpt-x",
        "baseUrl": "https://api.openai.com/v1",
    },
    "responses_no_url": {"provider": "openai", "api": "openai-responses", "id": "gpt-x"},
}
IDENTS: dict[str, dict[str, Any]] = {
    "none": {},
    "session": {"sessionId": "s1"},
    "both": {"sessionId": "s1", "authProfileId": "a1"},
    "blank": {"sessionId": "  ", "authProfileId": ""},
    "unicode": {"sessionId": "séssion-\U0001f600", "authProfileId": " a2 "},
}


@pytest.fixture(scope="module")
def oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))


def _run(oracle: OpenClawOracle, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = oracle.run({"operation": "compactionCheckpoint", "cases": cases})
    assert result["ok"] is True
    return result["rows"] if "rows" in result else result["result"]


@pytest.fixture(scope="module")
def contexts(oracle: OpenClawOracle) -> dict[tuple[str, str], dict[str, Any]]:
    keys = list(itertools.product(MODELS, IDENTS))
    rows = _run(
        oracle,
        [{"fn": "replayContext", "model": MODELS[m], "identity": IDENTS[i]} for m, i in keys],
    )
    assert all(row["error"] is None for row in rows)
    return {key: row["value"] for key, row in zip(keys, rows, strict=True)}


def _clean(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _py_model(model: dict[str, Any]) -> cr.ReplayModel:
    return cr.ReplayModel(model["provider"], model["api"], model["id"], model.get("baseUrl"))


def _py_identity(identity: dict[str, Any]) -> cr.ReplayIdentity:
    return cr.ReplayIdentity(
        identity.get("sessionId"), identity.get("authProfileId"), identity.get("enabled")
    )


def _python_row(case: dict[str, Any]) -> dict[str, Any]:
    messages = _clean(case.get("messages", []))
    model = _py_model(case["model"]) if "model" in case else None
    identity = _py_identity(case.get("identity", {}))
    if case["fn"] in _EXTENDED_FNS:
        return _extended_python_row(case, messages, model, identity)

    def ref(value: Any) -> Any:
        for index, message in enumerate(messages):
            if message is value:
                return {"ref": index}
        return value

    def ref_owner(selected: dict[str, Any] | None) -> Any:
        return None if selected is None else {**selected, "owner": ref(selected["owner"])}

    extra: dict[str, Any] = {}
    try:
        fn = case["fn"]
        if fn == "shortHash":
            value = cr.short_hash(case["text"])
        elif fn == "replayContext":
            value = {
                key: item
                for key, item in cr.build_provider_replay_context(model, identity).items()
                if item is not None
            }
        elif fn == "newestAnthropic":
            value = ref_owner(cr.resolve_newest_anthropic_compaction(messages, model, identity))
        elif fn == "newestResponses":
            value = ref_owner(
                cr.resolve_newest_openai_responses_compaction_replay(messages, model, identity)
            )
        elif fn == "requiresRefresh":
            value = cr.requires_compaction_replay_refresh(messages, model, identity)
        elif fn == "preserve":
            windowed = [
                messages[spec["ref"]] if "ref" in spec else copy.deepcopy(messages[spec["copy"]])
                for spec in case.get("windowed", [])
            ]
            out = cr.preserve_compaction_replay_window(messages, windowed, model, identity)
            ids = {id(message) for message in windowed}
            value = [ref(m) if id(m) in ids else m for m in out]
            extra["same"] = out is windowed
        elif fn == "anthropicPlan":
            plan = cr.build_anthropic_replay_plan(messages, model, identity)
            value = {**plan, "messages": [ref(m) for m in plan["messages"]]}
        elif fn == "responsesPlan":
            plan = cr.build_openai_responses_compaction_replay_plan(
                messages, model, identity, full_history=case.get("mode") == "full-history"
            )
            value = {**plan, "messages": [ref(m) for m in plan["messages"]]}
        else:
            raise AssertionError(fn)
        error = None
    except Exception as exc:  # noqa: BLE001 - the oracle reports the class name
        value, error = None, type(exc).__name__
    return _clean({"value": value, "error": error, **extra})


def _compare(oracle: OpenClawOracle, cases: list[dict[str, Any]]) -> None:
    rows = _run(oracle, cases)
    diffs = []
    for case, row in zip(cases, rows, strict=True):
        python = _python_row(case)
        if _clean(row) != python:
            diffs.append((case, row, python))
    assert diffs[:3] == []


# --- fixtures ------------------------------------------------------------------------------


def _assistant(content: Any, replay: Any = None, **extra: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "provider": "p",
        "model": "m",
        "usage": {"input": 1, "output": 2, "totalTokens": 3},
        **extra,
    }
    if replay is not None:
        message["providerReplay"] = replay
    return message


def _user(text: str = "u") -> dict[str, Any]:
    return {"role": "user", "content": text}


def _tool_result() -> dict[str, Any]:
    return {"role": "toolResult", "toolCallId": "t", "content": [{"type": "text", "text": "r"}]}


BLOCKS = [
    {"type": "text", "text": "A"},
    {"type": "toolCall", "id": "c1", "name": "x", "arguments": {}},
    {"type": "text", "text": "C"},
]


def _drop(state: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in state.items() if k not in keys}


def _anthropic_state(ctx: dict[str, Any], **over: Any) -> dict[str, Any]:
    state = {"v": 1, "type": "anthropic-compaction", "data": "SUMMARY", "replayIndex": 1, **ctx}
    state.update(over)
    return state


ANTHROPIC_MUTATIONS: list[tuple[str, Any]] = [
    ("valid", lambda s: s),
    ("idx0", lambda s: {**s, "replayIndex": 0}),
    ("idx2", lambda s: {**s, "replayIndex": 2}),
    ("idx_missing", lambda s: _drop(s, "replayIndex")),
    ("idx_neg", lambda s: {**s, "replayIndex": -1}),
    ("idx_float", lambda s: {**s, "replayIndex": 1.5}),
    ("idx_float_int", lambda s: {**s, "replayIndex": 1.0}),
    ("idx_str", lambda s: {**s, "replayIndex": "1"}),
    ("idx_null", lambda s: {**s, "replayIndex": None}),
    ("idx_bool", lambda s: {**s, "replayIndex": True}),
    ("idx_unsafe", lambda s: {**s, "replayIndex": 2**53}),
    ("idx_safe", lambda s: {**s, "replayIndex": 2**53 - 1}),
    ("enc_str", lambda s: {**s, "encryptedContent": "enc"}),
    ("enc_empty", lambda s: {**s, "encryptedContent": ""}),
    ("enc_null", lambda s: {**s, "encryptedContent": None}),
    ("enc_num", lambda s: {**s, "encryptedContent": 5}),
    ("data_empty", lambda s: {**s, "data": ""}),
    ("data_num", lambda s: {**s, "data": 5}),
    ("data_unicode", lambda s: {**s, "data": "séß\U0001f600"}),
    ("v2", lambda s: {**s, "v": 2}),
    ("v_str", lambda s: {**s, "v": "1"}),
    ("v_true", lambda s: {**s, "v": True}),
    ("v_float", lambda s: {**s, "v": 1.0}),
    ("v_missing", lambda s: _drop(s, "v")),
    ("no_provider", lambda s: _drop(s, "provider")),
    ("no_api", lambda s: _drop(s, "api")),
    ("no_model", lambda s: _drop(s, "model")),
    ("no_url_hash", lambda s: _drop(s, "baseUrlHash")),
    ("session_num", lambda s: {**s, "sessionHash": 5}),
    ("auth_null", lambda s: {**s, "authProfileHash": None}),
    ("no_hashes", lambda s: _drop(s, "sessionHash", "authProfileHash")),
    ("type_other", lambda s: {**s, "type": "anthropic-compaction-x"}),
    (
        "suppression",
        lambda s: {**s, "type": "anthropic-compaction-suppression", "data": "rejected"},
    ),
    ("suppression_bad", lambda s: {**s, "type": "anthropic-compaction-suppression", "data": "x"}),
    (
        "suppression_nov",
        lambda s: {**_drop(s, "v"), "type": "anthropic-compaction-suppression", "data": "rejected"},
    ),
    ("responses_type", lambda s: {**s, "type": "openai-responses-compaction"}),
    ("extra_fields", lambda s: {**s, "extra": {"a": [1, 2]}, "compactedWindow": "x"}),
    ("raw_string", lambda s: "anthropic-compaction"),
    ("raw_list", lambda s: []),
    ("raw_number", lambda s: 7),
    ("raw_empty", lambda s: {}),
]


def _anthropic_layouts(owner: dict[str, Any], other: dict[str, Any]) -> list[list[dict[str, Any]]]:
    plain = _assistant(list(BLOCKS))
    return [
        [_user(), owner, _user("2"), plain, _tool_result()],
        [owner],
        [_user(), _assistant(list(BLOCKS), other), _user("2"), owner, _user("3")],
        [_user(), owner, _user("2"), _assistant(list(BLOCKS), other), _tool_result()],
        [_user(), plain, _user("2"), owner, plain, owner],
        [owner, {"role": "system", "content": "s"}, owner],
        [],
        [_user(), _user("2")],
    ]


def _window_specs(count: int) -> list[list[dict[str, int]]]:
    refs = [{"ref": i} for i in range(count)]
    specs: list[list[dict[str, int]]] = [
        [],
        refs,
        refs[1:],
        refs[-2:],
        refs[:2],
        [{"copy": i} for i in range(count)],
        [{"ref": i} if i % 2 else {"copy": i} for i in range(count)],
        list(reversed(refs)),
    ]
    return specs


def _anthropic_cases(contexts: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    states = itertools.cycle(["anthropic"])
    del states
    for index, (name, mutate) in enumerate(ANTHROPIC_MUTATIONS):
        ident_key = list(IDENTS)[index % len(IDENTS)]
        ident = IDENTS[ident_key]
        ctx = contexts[("anthropic", ident_key)]
        for layout_index in range(8):
            owner_state = mutate(_anthropic_state(ctx))
            other_state = _anthropic_state(ctx, replayIndex=2, data="OLD")
            # The layouts that carry two checkpoints get a second, valid state with its own mutation.
            owner = _assistant(list(BLOCKS), owner_state)
            messages = _anthropic_layouts(owner, other_state)[layout_index]
            for enabled in (True, None, False):
                identity = {**ident, "enabled": enabled}
                base = {"messages": messages, "model": MODELS["anthropic"], "identity": identity}
                for fn in ("newestAnthropic", "anthropicPlan", "requiresRefresh"):
                    cases.append({**base, "fn": fn})
                if enabled is not None or layout_index % 2 == 0:
                    for windowed in _window_specs(len(messages))[: 3 + layout_index % 5]:
                        cases.append({**base, "fn": "preserve", "windowed": windowed})
    return cases


def test_real_openclaw_oracle_short_hash_and_replay_context_match_python(oracle):
    texts = (
        [
            "",
            "a",
            "https://api.openai.com/v1",
            "https://api.anthropic.com",
            "s1",
            "séssion-\U0001f600",
            "\U0001f600" * 5,
            "a" * 1000,
            "line\nbreak",
            "\ud800",
            "x\udc00y",
            "日本語",
            "0",
            "zzzzzzzz",
            " padded ",
        ]
        + [f"session-{i}" for i in range(220)]
        + [f"https://host{i}.example/v{i}" for i in range(60)]
    )
    cases = [{"fn": "shortHash", "text": text} for text in texts]
    models = list(MODELS.values())
    for model in models:
        for ident in IDENTS.values():
            cases.append({"fn": "replayContext", "model": model, "identity": ident})
    cases.append(
        {
            "fn": "replayContext",
            "model": {**MODELS["anthropic"], "baseUrl": "  https://x  "},
            "identity": {"sessionId": "\t s \n"},
        }
    )
    assert len(cases) >= 300
    _compare(oracle, cases)


def test_real_openclaw_oracle_anthropic_checkpoint_matches_python(oracle, contexts):
    cases = _anthropic_cases(contexts)
    assert len(cases) >= 2500
    _compare(oracle, cases)


def test_real_openclaw_oracle_anthropic_fencing_matches_python(oracle, contexts):
    cases: list[dict[str, Any]] = []
    for state_model, state_ident in itertools.product(
        ("anthropic", "anthropic_other_id", "anthropic_other_url", "anthropic_no_url"),
        IDENTS,
    ):
        for query_model, query_ident in itertools.product(
            ("anthropic", "anthropic_other_id", "anthropic_other_url", "anthropic_no_url"),
            ("none", "session", "both", "blank"),
        ):
            ctx = contexts[(state_model, state_ident)]
            for kind in ("valid", "suppression"):
                if kind == "valid":
                    replay = _anthropic_state(ctx)
                else:
                    replay = _anthropic_state(
                        ctx, type="anthropic-compaction-suppression", data="rejected"
                    )
                older = _assistant(list(BLOCKS), _anthropic_state(contexts[("anthropic", "none")]))
                messages = [
                    _user(),
                    older,
                    _user("2"),
                    _assistant(list(BLOCKS), replay),
                    _user("3"),
                ]
                identity = {**IDENTS[query_ident], "enabled": True}
                base = {"messages": messages, "model": MODELS[query_model], "identity": identity}
                cases.append({**base, "fn": "newestAnthropic"})
                cases.append({**base, "fn": "anthropicPlan"})
                cases.append({**base, "fn": "preserve", "windowed": [{"ref": 4}]})
    assert len(cases) >= 1000
    _compare(oracle, cases)


# --- Responses ---------------------------------------------------------------------------


def _responses_state(ctx: dict[str, Any], **over: Any) -> dict[str, Any]:
    state = {
        "v": 1,
        "type": "openai-responses-compaction",
        "data": "ENCRYPTED",
        "replayIndex": 1,
        **ctx,
    }
    state.update(over)
    return state


def _retained_state(ctx: dict[str, Any], **over: Any) -> dict[str, Any]:
    state = {"v": 1, "type": "openai-responses-retained-compaction", "data": "ENCRYPTED", **ctx}
    state.update(over)
    return state


def _window_message(role: str = "user", text: str = "hi", **extra: Any) -> dict[str, Any]:
    return {
        "type": "message",
        "role": role,
        "content": [{"type": "input_text", "text": text}],
        **extra,
    }


def _window_output(data: str = "ENCRYPTED", item_id: str | None = None, **extra) -> list:
    item: dict[str, Any] = {"type": "compaction", "encrypted_content": data}
    if item_id is not None:
        item["id"] = item_id
    item.update(extra)
    return [_window_message(), _window_message("developer", "dev"), item]


def _with_window(base: dict[str, Any], output: Any, **window: Any) -> dict[str, Any]:
    raw = output if isinstance(output, str) else json.dumps(output)
    return {**base, "compactedWindow": {"state": "ready", "output": raw, **window}}


def _bad_windows(ctx: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    good = _window_output()
    image = {
        "type": "input_image",
        "detail": "auto",
        "image_url": "https://example.com/a.png",
    }
    out: list[tuple[str, dict[str, Any]]] = [
        ("window_ok", _with_window(_responses_state(ctx), good)),
        (
            "window_ok_id",
            _with_window(_responses_state(ctx, id="rs_1"), _window_output(item_id="rs_1")),
        ),
        ("window_id_mismatch", _with_window(_responses_state(ctx, id="rs_1"), good)),
        ("window_id_extra", _with_window(_responses_state(ctx), _window_output(item_id="rs_9"))),
        ("window_data_mismatch", _with_window(_responses_state(ctx), _window_output("OTHER"))),
        (
            "window_refresh",
            {**_responses_state(ctx), "compactedWindow": {"state": "refresh-required"}},
        ),
        ("window_state_other", _with_window(_responses_state(ctx), good, state="x")),
        ("window_not_record", {**_responses_state(ctx), "compactedWindow": "x"}),
        ("window_null", {**_responses_state(ctx), "compactedWindow": None}),
        (
            "window_output_num",
            {**_responses_state(ctx), "compactedWindow": {"state": "ready", "output": 5}},
        ),
        ("window_bad_json", _with_window(_responses_state(ctx), "{not json")),
        ("window_nan", _with_window(_responses_state(ctx), '[{"a":NaN}]')),
        ("window_empty", _with_window(_responses_state(ctx), [])),
        ("window_not_array", _with_window(_responses_state(ctx), {"a": 1})),
        ("window_only_item", _with_window(_responses_state(ctx), [good[-1]])),
        ("window_last_not_compaction", _with_window(_responses_state(ctx), good[:-1])),
        (
            "window_item_empty_enc",
            _with_window(_responses_state(ctx, data="E"), _window_output("")),
        ),
        (
            "window_item_no_enc",
            _with_window(_responses_state(ctx), [good[0], {"type": "compaction"}]),
        ),
        ("window_item_id_num", _with_window(_responses_state(ctx), _window_output(id=5))),
        (
            "window_item_created_by",
            _with_window(_responses_state(ctx), _window_output(created_by="x")),
        ),
        (
            "window_item_created_by_num",
            _with_window(_responses_state(ctx), _window_output(created_by=1)),
        ),
        (
            "window_extra_item_field",
            _with_window(_responses_state(ctx), _window_output(extra={"a": 1})),
        ),
        (
            "window_role_assistant",
            _with_window(_responses_state(ctx), [_window_message("assistant"), good[-1]]),
        ),
        (
            "window_role_system",
            _with_window(_responses_state(ctx), [_window_message("system"), good[-1]]),
        ),
        (
            "window_msg_type",
            _with_window(_responses_state(ctx), [{**_window_message(), "type": "x"}, good[-1]]),
        ),
        (
            "window_msg_id",
            _with_window(_responses_state(ctx), [_window_message(id="m1"), good[-1]]),
        ),
        (
            "window_msg_id_num",
            _with_window(_responses_state(ctx), [_window_message(id=1), good[-1]]),
        ),
        (
            "window_msg_status",
            _with_window(_responses_state(ctx), [_window_message(status="completed"), good[-1]]),
        ),
        (
            "window_msg_status_bad",
            _with_window(_responses_state(ctx), [_window_message(status="done"), good[-1]]),
        ),
        (
            "window_msg_content_str",
            _with_window(_responses_state(ctx), [{**_window_message(), "content": "x"}, good[-1]]),
        ),
        (
            "window_text_num",
            _with_window(
                _responses_state(ctx),
                [{**_window_message(), "content": [{"type": "input_text", "text": 5}]}, good[-1]],
            ),
        ),
        (
            "window_content_unknown",
            _with_window(
                _responses_state(ctx),
                [
                    {**_window_message(), "content": [{"type": "output_text", "text": "x"}]},
                    good[-1],
                ],
            ),
        ),
        (
            "window_content_null",
            _with_window(
                _responses_state(ctx), [{**_window_message(), "content": [None]}, good[-1]]
            ),
        ),
        (
            "window_content_empty",
            _with_window(_responses_state(ctx), [{**_window_message(), "content": []}, good[-1]]),
        ),
        (
            "window_breakpoint",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [
                            {
                                "type": "input_text",
                                "text": "x",
                                "prompt_cache_breakpoint": {"mode": "explicit"},
                            }
                        ],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_breakpoint_bad",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [
                            {
                                "type": "input_text",
                                "text": "x",
                                "prompt_cache_breakpoint": {"mode": "auto"},
                            }
                        ],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_breakpoint_null",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [
                            {"type": "input_text", "text": "x", "prompt_cache_breakpoint": None}
                        ],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_image",
            _with_window(
                _responses_state(ctx), [{**_window_message(), "content": [image]}, good[-1]]
            ),
        ),
        (
            "window_image_file",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [{"type": "input_image", "detail": "high", "file_id": "f1"}],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_image_original",
            _with_window(
                _responses_state(ctx),
                [{**_window_message(), "content": [{**image, "detail": "original"}]}, good[-1]],
            ),
        ),
        (
            "window_image_detail_bad",
            _with_window(
                _responses_state(ctx),
                [{**_window_message(), "content": [{**image, "detail": "max"}]}, good[-1]],
            ),
        ),
        (
            "window_image_detail_missing",
            _with_window(
                _responses_state(ctx),
                [{**_window_message(), "content": [_drop(image, "detail")]}, good[-1]],
            ),
        ),
        (
            "window_image_no_source",
            _with_window(
                _responses_state(ctx),
                [{**_window_message(), "content": [_drop(image, "image_url")]}, good[-1]],
            ),
        ),
        (
            "window_image_null_url_file",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [
                            {
                                "type": "input_image",
                                "detail": "auto",
                                "image_url": None,
                                "file_id": "f",
                            }
                        ],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_image_url_num",
            _with_window(
                _responses_state(ctx),
                [
                    {**_window_message(), "content": [{**image, "image_url": 3, "file_id": "f"}]},
                    good[-1],
                ],
            ),
        ),
        (
            "window_file",
            _with_window(
                _responses_state(ctx),
                [
                    {**_window_message(), "content": [{"type": "input_file", "file_id": "f1"}]},
                    good[-1],
                ],
            ),
        ),
        (
            "window_file_all",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [
                            {
                                "type": "input_file",
                                "file_data": "ZGF0YQ==",
                                "file_url": "https://x/y",
                                "filename": "a.txt",
                                "detail": "low",
                            }
                        ],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_file_none",
            _with_window(
                _responses_state(ctx),
                [{**_window_message(), "content": [{"type": "input_file"}]}, good[-1]],
            ),
        ),
        (
            "window_file_detail_bad",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [{"type": "input_file", "file_id": "f", "detail": "original"}],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_file_data_null",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [{"type": "input_file", "file_id": "f", "file_data": None}],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_file_id_null",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [{"type": "input_file", "file_url": "u", "file_id": None}],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_file_url_null",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [{"type": "input_file", "file_id": "f", "file_url": None}],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_file_filename_num",
            _with_window(
                _responses_state(ctx),
                [
                    {
                        **_window_message(),
                        "content": [{"type": "input_file", "file_id": "f", "filename": 1}],
                    },
                    good[-1],
                ],
            ),
        ),
        (
            "window_deep",
            _with_window(_responses_state(ctx), [good[0], {**good[-1], "meta": _nest(70)}]),
        ),
        (
            "window_nested_ok",
            _with_window(_responses_state(ctx), [good[0], {**good[-1], "meta": _nest(20)}]),
        ),
        (
            "window_huge",
            _with_window(
                _responses_state(ctx), [_window_message(text="x" * (16 * 1024 * 1024)), good[-1]]
            ),
        ),
        (
            "window_unicode",
            _with_window(
                _responses_state(ctx), [_window_message(text="séß\U0001f600日本"), good[-1]]
            ),
        ),
        (
            "window_bigfloat",
            _with_window(
                _responses_state(ctx),
                '[{"type":"compaction","encrypted_content":"ENCRYPTED","n":1e999}]',
            ),
        ),
        (
            "window_bigfloat_ok",
            _with_window(
                _responses_state(ctx),
                '[{"type":"compaction","encrypted_content":"ENCRYPTED","n":1e300}]',
            ),
        ),
        ("window_ws_json", _with_window(_responses_state(ctx), " \n" + json.dumps(good) + " \t")),
        ("window_trailing_garbage", _with_window(_responses_state(ctx), json.dumps(good) + "x")),
    ]
    return out


def _nest(depth: int) -> Any:
    value: Any = 1
    for _ in range(depth):
        value = {"a": value}
    return value


RESPONSES_MUTATIONS: list[tuple[str, Any]] = [
    ("prefix", lambda ctx: _responses_state(ctx)),
    ("prefix_idx0", lambda ctx: _responses_state(ctx, replayIndex=0)),
    ("prefix_idx2", lambda ctx: _responses_state(ctx, replayIndex=2)),
    ("prefix_idx_missing", lambda ctx: _drop(_responses_state(ctx), "replayIndex")),
    ("prefix_idx_neg", lambda ctx: _responses_state(ctx, replayIndex=-1)),
    ("prefix_idx_float", lambda ctx: _responses_state(ctx, replayIndex=0.5)),
    ("prefix_idx_str", lambda ctx: _responses_state(ctx, replayIndex="1")),
    ("prefix_idx_null", lambda ctx: _responses_state(ctx, replayIndex=None)),
    ("prefix_id", lambda ctx: _responses_state(ctx, id="rs_abc")),
    ("prefix_id_empty", lambda ctx: _responses_state(ctx, id="")),
    ("prefix_id_64", lambda ctx: _responses_state(ctx, id="i" * 64)),
    ("prefix_id_65", lambda ctx: _responses_state(ctx, id="i" * 65)),
    ("prefix_id_emoji_33", lambda ctx: _responses_state(ctx, id="\U0001f600" * 33)),
    ("prefix_id_emoji_32", lambda ctx: _responses_state(ctx, id="\U0001f600" * 32)),
    ("prefix_id_num", lambda ctx: _responses_state(ctx, id=5)),
    ("prefix_id_null", lambda ctx: _responses_state(ctx, id=None)),
    ("prefix_data_empty", lambda ctx: _responses_state(ctx, data="")),
    ("prefix_data_num", lambda ctx: _responses_state(ctx, data=1)),
    ("prefix_v2", lambda ctx: _responses_state(ctx, v=2)),
    ("prefix_v_missing", lambda ctx: _drop(_responses_state(ctx), "v")),
    ("prefix_no_provider", lambda ctx: _drop(_responses_state(ctx), "provider")),
    ("prefix_no_url", lambda ctx: _drop(_responses_state(ctx), "baseUrlHash")),
    ("prefix_session_num", lambda ctx: _responses_state(ctx, sessionHash=1)),
    ("prefix_auth_null", lambda ctx: _responses_state(ctx, authProfileHash=None)),
    ("retained", lambda ctx: _retained_state(ctx)),
    ("retained_id", lambda ctx: _retained_state(ctx, id="rs_r")),
    ("retained_idx", lambda ctx: _retained_state(ctx, replayIndex=1)),
    ("retained_idx_null", lambda ctx: _retained_state(ctx, replayIndex=None)),
    ("retained_data_empty", lambda ctx: _retained_state(ctx, data="")),
    ("retained_window", lambda ctx: _with_window(_retained_state(ctx), _window_output())),
    (
        "retained_window_id",
        lambda ctx: _with_window(_retained_state(ctx, id="rs_r"), _window_output(item_id="rs_r")),
    ),
    (
        "retained_refresh",
        lambda ctx: {**_retained_state(ctx), "compactedWindow": {"state": "refresh-required"}},
    ),
    (
        "suppression",
        lambda ctx: _responses_state(
            ctx, type="openai-responses-compaction-suppression", data="rejected"
        ),
    ),
    (
        "suppression_bad",
        lambda ctx: _responses_state(
            ctx, type="openai-responses-compaction-suppression", data="no"
        ),
    ),
    (
        "suppression_noindex",
        lambda ctx: _drop(
            _responses_state(ctx, type="openai-responses-compaction-suppression", data="rejected"),
            "replayIndex",
        ),
    ),
    ("anthropic_type", lambda ctx: {**_responses_state(ctx), "type": "anthropic-compaction"}),
    ("raw_string", lambda ctx: "openai-responses-compaction"),
    ("raw_list", lambda ctx: []),
    ("raw_empty", lambda ctx: {}),
    ("raw_type_only", lambda ctx: {"type": "openai-responses-compaction"}),
    ("raw_retained_type_only", lambda ctx: {"type": "openai-responses-retained-compaction"}),
]


def _responses_layouts(owner: dict[str, Any], other: dict[str, Any]) -> list[list[dict[str, Any]]]:
    plain = _assistant(list(BLOCKS))
    return [
        [_user(), owner, _user("2"), plain, _tool_result()],
        [owner],
        [_user(), _assistant(list(BLOCKS), other), _user("2"), owner, _user("3")],
        [_user(), owner, _user("2"), _assistant(list(BLOCKS), other), _tool_result()],
        [_user(), plain, _user("2"), owner, plain, owner],
        [_user(), owner, {"role": "system", "content": "s"}],
    ]


def _responses_cases(contexts: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    all_mutations = list(RESPONSES_MUTATIONS)
    for index, (name, mutate) in enumerate(all_mutations):
        ident_key = list(IDENTS)[index % len(IDENTS)]
        ident = IDENTS[ident_key]
        ctx = contexts[("responses", ident_key)]
        for layout_index in range(6):
            other = _responses_state(ctx, replayIndex=2, data="OLD")
            owner = _assistant(list(BLOCKS), mutate(ctx))
            messages = _responses_layouts(owner, other)[layout_index]
            for model_key in ("responses", "responses", "azure", "completions"):
                for enabled in (None, True, False):
                    identity = {**ident, "enabled": enabled}
                    base = {"messages": messages, "model": MODELS[model_key], "identity": identity}
                    cases.append({**base, "fn": "newestResponses"})
                    cases.append({**base, "fn": "requiresRefresh"})
                    if model_key == "responses":
                        cases.append({**base, "fn": "responsesPlan"})
                        cases.append({**base, "fn": "responsesPlan", "mode": "full-history"})
                        cases.append({**base, "fn": "responsesPlan", "mode": "checkpoint"})
                        for windowed in _window_specs(len(messages))[: 2 + layout_index % 5]:
                            cases.append({**base, "fn": "preserve", "windowed": windowed})
    return cases


def test_real_openclaw_oracle_responses_checkpoint_matches_python(oracle, contexts):
    cases = _responses_cases(contexts)
    assert len(cases) >= 2500
    _compare(oracle, cases)


def test_real_openclaw_oracle_responses_windows_match_python(oracle, contexts):
    cases: list[dict[str, Any]] = []
    for ident_key in ("none", "both"):
        ctx = contexts[("responses", ident_key)]
        for name, state in _bad_windows(ctx):
            owner = _assistant(list(BLOCKS), state)
            messages = [_user(), owner, _user("2"), _assistant(["x"]), _tool_result()]
            identity = {**IDENTS[ident_key], "enabled": None}
            base = {"messages": messages, "model": MODELS["responses"], "identity": identity}
            assert name
            cases.append({**base, "fn": "newestResponses"})
            cases.append({**base, "fn": "requiresRefresh"})
            cases.append({**base, "fn": "responsesPlan"})
            cases.append({**base, "fn": "preserve", "windowed": [{"ref": 3}, {"ref": 4}]})
            cases.append({**base, "fn": "preserve", "windowed": [{"ref": 1}, {"ref": 4}]})
        retained_ctx = contexts[("responses", ident_key)]
        for name, state in _bad_windows(retained_ctx):
            retained = {**state, "type": "openai-responses-retained-compaction"}
            retained.pop("replayIndex", None)
            owner = _assistant(list(BLOCKS), retained)
            messages = [_user(), owner, _user("2"), _assistant(["x"])]
            identity = {**IDENTS[ident_key], "enabled": None}
            base = {"messages": messages, "model": MODELS["responses"], "identity": identity}
            cases.append({**base, "fn": "newestResponses"})
            cases.append({**base, "fn": "responsesPlan"})
            cases.append({**base, "fn": "preserve", "windowed": [{"ref": 3}]})
    assert len(cases) >= 600
    _compare(oracle, cases)


def test_real_openclaw_oracle_checkpoint_fencing_across_models_matches_python(oracle, contexts):
    cases: list[dict[str, Any]] = []
    response_models = (
        "responses",
        "responses_other_id",
        "azure",
        "chatgpt",
        "transport",
        "responses_no_url",
    )
    for state_model, state_ident in itertools.product(response_models, IDENTS):
        ctx = contexts[(state_model, state_ident)]
        for query_model, query_ident in itertools.product(
            (
                "responses",
                "responses_other_id",
                "azure",
                "chatgpt",
                "transport",
                "completions",
                "responses_no_url",
            ),
            ("none", "session", "both"),
        ):
            for replay in (
                _responses_state(ctx),
                _retained_state(ctx),
                _with_window(_responses_state(ctx), _window_output()),
                _responses_state(
                    ctx, type="openai-responses-compaction-suppression", data="rejected"
                ),
            ):
                older = _assistant(list(BLOCKS), _responses_state(contexts[("responses", "none")]))
                messages = [
                    _user(),
                    older,
                    _user("2"),
                    _assistant(list(BLOCKS), replay),
                    _user("3"),
                ]
                identity = {**IDENTS[query_ident], "enabled": True}
                base = {"messages": messages, "model": MODELS[query_model], "identity": identity}
                cases.append({**base, "fn": "newestResponses"})
                cases.append({**base, "fn": "requiresRefresh"})
                cases.append({**base, "fn": "preserve", "windowed": [{"ref": 4}]})
    assert len(cases) >= 1000
    _compare(oracle, cases)


def test_real_openclaw_oracle_cross_family_checkpoints_match_python(oracle, contexts):
    """An Anthropic owner under a Responses model and the reverse: both skip or reject."""
    cases: list[dict[str, Any]] = []
    anth = _anthropic_state(contexts[("anthropic", "none")])
    resp = _responses_state(contexts[("responses", "none")])
    retained = _retained_state(contexts[("responses", "none")])
    for first, second in itertools.product((anth, resp, retained, None), repeat=2):
        messages = [
            _user(),
            _assistant(list(BLOCKS), first),
            _user("2"),
            _assistant(list(BLOCKS), second),
            _user("3"),
        ]
        for model_key in ("anthropic", "responses", "completions", "azure"):
            for enabled in (True, None, False):
                base = {
                    "messages": messages,
                    "model": MODELS[model_key],
                    "identity": {"enabled": enabled},
                }
                for fn in (
                    "newestAnthropic",
                    "newestResponses",
                    "requiresRefresh",
                    "anthropicPlan",
                ):
                    cases.append({**base, "fn": fn})
                cases.append({**base, "fn": "preserve", "windowed": [{"ref": 4}]})
                cases.append({**base, "fn": "preserve", "windowed": [{"ref": 2}, {"ref": 3}]})
    assert len(cases) >= 300
    _compare(oracle, cases)


# --- inbound metadata helpers --------------------------------------------------------------

_ICTX = "⟦openclaw:ctx⟧"


def _sender_texts() -> list[str]:
    def block(label: str, payload: str) -> str:
        return f"{label} {_ICTX}\n```json\n{payload}\n```"

    senders = [
        '{"label":"Alice"}',
        '{"label":"  Alice  ","name":"A"}',
        '{"label":"","name":"Bob"}',
        '{"label":"   ","name":"\\t","username":"bob_u"}',
        '{"name":"Name"}',
        '{"username":"user"}',
        '{"e164":"+15550000"}',
        '{"id":"id-1"}',
        '{"label":5,"name":"N"}',
        '{"label":null,"id":"x"}',
        '{"label":["a"],"id":"x"}',
        '{"label":{"a":1},"name":"o"}',
        '{"label":"a`\\u200b``b"}',
        '{"label":"`\\u200b``"}',
        '{"label":"\\u00a0pad\\u00a0"}',
        '{"label":"\\ufeff"}',
        '{"label":"emoji \\ud83d\\ude00"}',
        "{}",
        "[]",
        "[1]",
        '"string"',
        "123",
        "null",
        "true",
        "{not json",
        "",
        '{"label":"A"}  ',
        '\n\n{"label":"A"}\n\n',
        '{"label":"A","label":"B"}',
        '{"__proto__":{"label":"P"},"name":"N"}',
        '{"label":NaN}',
        '{"label":"A"} trailing',
    ]
    conversations = [
        '{"message_id":"m","sender":{"name":"Carol"}}',
        '{"sender":{"username":"carol"}}',
        '{"sender":{"e164":"+1"}}',
        '{"sender":{"id":"7"}}',
        '{"sender":{"name":"","username":" u "}}',
        '{"sender":{"name":5,"id":"i"}}',
        '{"sender":{"label":"L"}}',
        '{"sender":{}}',
        '{"sender":"direct"}',
        '{"sender":"  direct  "}',
        '{"sender":""}',
        '{"sender":5}',
        '{"sender":null}',
        '{"sender":["x"]}',
        '{"sender":true}',
        '{"other":1}',
        '{"sender":{"name":"a`\\u200b``"}}',
        "[]",
        "{bad",
        "{}",
    ]
    texts: list[str] = [
        "",
        "plain",
        _ICTX,
        f"x {_ICTX} y",
        f"Sender: {_ICTX}",
        f"Sender: {_ICTX}\n",
        f"Sender: {_ICTX}\n```json",
        f'Sender: {_ICTX}\n```json\n{{"label":"A"}}',
        f"Sender: {_ICTX}\nnot fenced",
        f'  Sender: {_ICTX}  \n```json\n{{"label":"Sp"}}\n```',
        f'Sender: {_ICTX}\n  ```json  \n{{"label":"Sp2"}}\n  ```  ',
        f'Sender: {_ICTX}\n```JSON\n{{"label":"Up"}}\n```',
        f'Sender: {_ICTX}\r\n```json\r\n{{"label":"Crlf"}}\r\n```',
        f'Sender: {_ICTX}\n\n```json\n{{"label":"Gap"}}\n```',
        f'Sender:{_ICTX}\n```json\n{{"label":"Nospace"}}\n```',
        f'Sender:  {_ICTX}\n```json\n{{"label":"Twospace"}}\n```',
        f'Sender: {_ICTX}\n```json\n{{"label":"Fence"}}\n```x\n```',
        "intro\n\n" + block("Sender:", '{"label":"Mid"}') + "\n\nuser",
        block("Sender:", '{"label":"First"}') + "\n\n" + block("Sender:", '{"label":"Second"}'),
        block("Sender:", "{}") + "\n\n" + block("Sender:", '{"label":"Second"}'),
        block("Conversation info:", '{"sender":{"name":"C"}}'),
        block("Sender:", '{"label":"S"}')
        + "\n\n"
        + block("Conversation info:", '{"sender":{"name":"C"}}'),
        block("Sender:", "{}") + "\n\n" + block("Conversation info:", '{"sender":{"name":"C"}}'),
        block("Sender:", "[]") + "\n\n" + block("Conversation info:", '{"sender":"CS"}'),
        block("Conversation info:", '{"sender":{"name":"C"}}')
        + "\n\n"
        + block("Sender:", '{"label":"S"}'),
        f'Conversation info: {_ICTX}\n```json\n{{"sender":{{"name":"X"}}}}\n```\n```json\n{{"sender":{{"name":"Y"}}}}\n```',
        f'Context: {_ICTX}\nSender: {_ICTX}\n```json\n{{"label":"In"}}\n```',
        f'Sender: {_ICTX}\n```json\n{{"label":"A"}}\n```\n[Mon 2026-01-05 10:00 UTC] hi',
        f'[Mon 2026-01-05 10:00 UTC] Sender: {_ICTX}\n```json\n{{"label":"T"}}\n```',
    ]
    for payload in senders:
        texts.append(block("Sender:", payload))
        texts.append(block("Sender:", payload) + "\n\nuser text")
        texts.append(
            block("Conversation info:", '{"sender":{"name":"Fallback"}}')
            + "\n\n"
            + block("Sender:", payload)
        )
    for payload in conversations:
        texts.append(block("Conversation info:", payload))
        texts.append(block("Conversation info:", payload) + "\n\nuser text")
        texts.append(block("Sender:", "{}") + "\n\n" + block("Conversation info:", payload))
    return texts


def test_real_openclaw_oracle_inbound_leading_and_sender_label_match_python(oracle):
    from memory_core.session_entry import (
        extract_inbound_sender_label,
        strip_leading_inbound_metadata,
    )
    from test_openclaw_ts_oracle import _strip_inbound_texts

    texts = _strip_inbound_texts() + _sender_texts() + _leading_texts()
    assert len(texts) >= 500
    result = oracle.run(
        {"operation": "inboundMetadataHelpers", "cases": [{"text": text} for text in texts]}
    )
    assert result["ok"] is True
    leading_diffs = []
    sender_diffs = []
    for text, row in zip(texts, result["result"], strict=True):
        python_leading = strip_leading_inbound_metadata(text)
        if row["leading"] != python_leading:
            leading_diffs.append((text, row["leading"], python_leading))
        python_sender = extract_inbound_sender_label(text)
        if row["sender"] != python_sender:
            sender_diffs.append((text, row["sender"], python_sender))
    assert leading_diffs[:3] == []
    assert sender_diffs[:3] == []


def _leading_texts() -> list[str]:
    from memory_core.session_entry import MESSAGE_TOOL_DELIVERY_HINTS

    conv = f'Conversation info: {_ICTX}\n```json\n{{"a":1}}\n```'
    sender = f'Sender: {_ICTX}\n```json\n{{"label":"A"}}\n```'
    prose = f"Chat history since last reply: {_ICTX}\n#1 a: b\n#2 c: d"
    channel = f"Context: {_ICTX}\nbody\nmore"
    active = "Context:\n<active_memory_plugin>\nPrefers aisle.\n</active_memory_plugin>"
    texts: list[str] = []
    for hint in MESSAGE_TOOL_DELIVERY_HINTS:
        for shape in (
            "{h}",
            "{h}\n",
            "\n{h}\n",
            "{h}\n\n{h}\nuser",
            "{h}\n\n\nuser",
            "{h}\nuser\n{h}",
            "  {h}  \n\n{c}\n\nuser",
            "{c}\n\n{h}\nuser",
            "user\n{h}\nmore",
            "{h}\n{a}\nuser",
            "{a}\n{h}\nuser",
            "{h}\n\n{ch}",
            "{h}\nuser\n\n{ch}",
        ):
            texts.append(
                shape.replace("{h}", hint)
                .replace("{c}", conv)
                .replace("{a}", active)
                .replace("{ch}", channel)
            )
    blocks = [conv, sender, prose, channel, active]
    for first, second, third in itertools.product(blocks, repeat=3):
        texts.append(f"{first}\n\n{second}\n\n{third}\n\nuser")
    for block in blocks:
        for shape in (
            "{b}",
            "{b}\n",
            "{b}\n\n",
            "\n\n{b}",
            "\n \n{b}\n\nuser",
            "{b}\nuser immediately",
            "{b}\n\nuser\n\n{ch}",
            "{b}\n\nuser\n\n\n\n{ch}\n\nmore",
            "user\n\n{b}\n\nafter",
            "user\n\n{b}\n\n{ch}",
            "user\n\n\n{ch}",
            "user\n \t \n{ch}",
            "{b}\n\n{ch}",
            "{b}\n\nuser\n{ch}\n{b}",
            "[Mon 2026-01-05 10:00 UTC] {b}\n\nuser",
            "  {b}",
            "\r\n{b}\r\n\r\nuser",
        ):
            texts.append(shape.replace("{b}", block).replace("{ch}", channel))
    texts += [
        channel,
        f"\n{channel}",
        f"user\n{channel}",
        f"user\n\n{channel}\n\nrest",
        f"{channel}\n\nuser",
        f"a\n\n\n\n\n{channel}",
        f"a\n \n \n{channel}",
        f"a\r\n\r\n{channel}",
        f"  Context: {_ICTX}  \nx",
        f"x\n  Context: {_ICTX}  \ny",
        f"x\nContext: {_ICTX} extra\ny",
        f"\n\n\n{channel}",
        f"first\n{channel}\nmore\n{channel}",
        f"first\n\n{channel}\n\nmiddle\n\n{channel}",
        f"x\n{conv}\n\n{channel}",
        "Context:\nnot active memory\n",
        "Context:\n",
        "  Context:  \n",
        "Context:\n<active_memory_plugin>\nunclosed",
        active + "\n\n" + conv + "\n\nuser",
        conv + "\n\n" + active + "\n\nuser",
        "user\n" + active + "\nafter",
        active,
        active + "\n",
        active + "\n\n\n",
        "\n\n" + active + "\n\nuser",
        f"{conv}\n\n{conv}",
        f"{conv}\nno blank prose-ish\nstill header body\n\nuser",
        f"Sender: {_ICTX}\n```json\n{{}}",
        f"Sender: {_ICTX}",
        f"Sender: {_ICTX}\n",
        f"  Sender: {_ICTX}\n\n",
        f"Sender: {_ICTX}\ntext\n\n\n\nafter",
        "   ",
        "\n\n\n",
        " \n \n",
        "\r\n\r\n",
        "plain text only",
        f"{_ICTX}",
        f"x{_ICTX}",
        f"x {_ICTX}\n```json\n{{}}\n```\nrest",
        f"{_ICTX} x\nrest",
        f"\U0001f600 {conv}\n\nuser",
        f"{conv}\n\n\U0001f600 user \U0001f600\n\n{channel}",
        f"Keśava\n{sender}\n\nłódź",
        f" \n{conv}\n\nuser",
        f"﻿{conv}\n\nuser",
        f" {conv}\n\nuser",
        f"\t{conv}\n\nuser",
    ]
    return texts


def test_inbound_helper_fixture_counts():
    assert len(_leading_texts()) >= 250
    assert len(_sender_texts()) >= 150
    assert copy


# --- extended: writers, eligibility, pressure, egress ----------------------------------------

_EXTENDED_FNS = frozenset(
    {
        "window",
        "isOutput",
        "eligibility",
        "pressure",
        "estimateInput",
        "anthropicCapture",
        "anthropicSuppress",
        "responsesCapture",
        "responsesSuppress",
        "reasoningMetadata",
        "replayContextShape",
        "tracker",
    }
)


def _error_name(exc: Exception) -> str:
    if isinstance(exc, cr.ResponsesCompactionCaptureError):
        return "Error"
    return type(exc).__name__


def _extended_python_row(
    case: dict[str, Any],
    messages: list[dict[str, Any]],
    model: cr.ReplayModel | None,
    identity: cr.ReplayIdentity,
) -> dict[str, Any]:
    def ref(value: Any) -> Any:
        for index, message in enumerate(messages):
            if message is value:
                return {"ref": index}
        return value

    fn = case["fn"]
    try:
        if fn == "window":
            value = cr.read_openai_responses_compaction_window(_clean(case["replay"]), model)
        elif fn == "isOutput":
            value = cr.is_openai_responses_compaction_output(_clean(case["value"]), model)
        elif fn == "eligibility":
            value = cr.resolve_compaction_replay_eligibility(
                model,
                extra_params=case.get("extraParams"),
                api_key=case.get("apiKey"),
                env=case.get("env") or {},
            )
        elif fn == "pressure":
            table = case.get("projectionTable")

            def projector(projection: str, _msgs: list[Any], _sp: Any, include: bool) -> list[Any]:
                return copy.deepcopy(table[f"{projection}:{str(include).lower()}"])

            # Without a table the built-in converter (memory_core.responses_converter) projects.
            out = cr.resolve_compaction_replay_pressure(
                messages,
                model,
                identity,
                cr.default_replay_pressure_estimator(),
                case.get("systemPrompt"),
                projector=projector if table is not None else None,
            )
            value = None if out is None else {**out, "messages": [ref(m) for m in out["messages"]]}
        elif fn == "estimateInput":
            estimator = cr.default_replay_pressure_estimator()
            if case.get("withToolResult") is False:
                estimator = cr.ReplayPressureEstimator(
                    estimator.text, estimator.image, estimator.json
                )
            value = cr.estimate_responses_input(_clean(case["items"]), estimator)
        elif fn == "anthropicCapture":
            output = _clean(case.get("output") or {})
            capture = cr.CompactionCapture(output, model, identity)
            results = []
            for event in _clean(case.get("events", [])):
                if event["op"] == "begin":
                    results.append(
                        capture.begin(event["index"], event.get("block"), event.get("replayIndex"))
                    )
                elif event["op"] == "delta":
                    results.append(capture.delta(event["index"], event.get("delta")))
                else:
                    results.append(capture.complete(event["index"]))
            value = {"results": results, "providerReplay": output.get("providerReplay")}
        elif fn == "anthropicSuppress":
            output = _clean(case.get("output") or {})
            cr.suppress_anthropic_compaction(output, model, identity)
            value = {"providerReplay": output.get("providerReplay")}
        elif fn == "responsesCapture":
            output = _clean(case.get("output") or {})
            cr.capture_openai_responses_compaction(
                output,
                _clean(case["item"]),
                case["boundary"],
                model,
                _clean(case.get("metadata")),
                _clean(case.get("compactedOutput")),
            )
            value = {"providerReplay": output.get("providerReplay")}
        elif fn == "responsesSuppress":
            output = _clean(case.get("output") or {})
            rejected: list[Any] = []
            cr.suppress_openai_responses_compaction(
                output,
                model,
                identity,
                _clean(case.get("rejected")),
                rejected.append if case.get("withCallback") else None,
            )
            value = {"providerReplay": output.get("providerReplay"), "rejected": rejected}
        elif fn == "reasoningMetadata":
            value = cr.build_openai_responses_reasoning_replay_metadata(model, identity)
        elif fn == "replayContextShape":
            value = cr.is_openai_responses_replay_context(_clean(case["value"]))
        elif fn == "tracker":
            output = _clean(case.get("output") or {})
            tracker = cr.CompactionTracker(output, model, _clean(case.get("metadata")))
            snapshots = []
            for step in _clean(case.get("steps", [])):
                if step["op"] == "added":
                    tracker.added(step["item"], step["replayIndex"])
                else:
                    tracker.completed(step["item"], step["fallback"])
                snapshots.append(copy.deepcopy(output.get("providerReplay")))
            value = {"snapshots": snapshots}
        else:
            raise AssertionError(fn)
        error = None
    except Exception as exc:  # noqa: BLE001 - the oracle reports the class name
        value, error = None, _error_name(exc)
    return _clean({"value": value, "error": error})


def _run_op(oracle: OpenClawOracle, operation: str, cases: list[dict[str, Any]]) -> list[Any]:
    result = oracle.run({"operation": operation, "cases": cases})
    assert result["ok"] is True
    return result["result"]


def _first_diffs(cases: list[dict[str, Any]], rows: list[Any], python_rows: list[Any]) -> list[Any]:
    assert len(rows) == len(python_rows) == len(cases)
    return [
        (case, row, python)
        for case, row, python in zip(cases, rows, python_rows, strict=True)
        if _clean(row) != python
    ][:3]


# --- inline image sanitiser ------------------------------------------------------------------


def _py_inline_row(case: dict[str, Any]) -> dict[str, Any]:
    from memory_core import inline_image as ii
    from memory_core import responses_egress as eg

    fn = case["fn"]
    extra: dict[str, Any] = {}
    if fn == "url":
        value = ii.sanitize_inline_image_data_url(case["text"])
    elif fn == "storage":
        value = ii.sanitize_inline_image_data_url_for_storage(case["text"])
    elif fn == "base64":
        sanitized = ii.sanitize_inline_image_base64(case["mimeType"], case["text"])
        value = (
            None
            if sanitized is None
            else {"mimeType": sanitized.mime_type, "base64": sanitized.base64}
        )
    elif fn == "canonical":
        value = ii.canonicalize_base64(case["text"])
    elif fn == "sniff":
        value = ii.sniff_inline_image_mime(bytes.fromhex(case["hex"]))
    elif fn == "stable":
        value = cr._stable_stringify(_clean(case["value"]))
    elif fn == "hostname":
        from memory_core.js_url import url_hostname

        value = url_hostname(case["text"])
    elif fn == "payload":
        params = _clean(case["params"])
        out = eg.sanitize_responses_image_payload(params)
        value, extra["same"] = out, out is params
    else:
        raise AssertionError(fn)
    return _clean({"value": value, "error": None, **extra})


def _compare_inline(oracle: OpenClawOracle, cases: list[dict[str, Any]]) -> None:
    rows = _run_op(oracle, "inlineImage", cases)
    python_rows = [_py_inline_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []


def _png(extra: bytes = b"") -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + extra


def _image_bytes() -> dict[str, bytes]:
    return {
        "png": _png(b"\x00" * 7),
        "png_short": _png()[:8],
        "png_truncated": _png()[:7],
        "png_bad": b"\x89PNG\r\n\x1a\x0b" + b"\x00" * 9,
        "jpeg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00",
        "jpeg_short": b"\xff\xd8\xff",
        "jpeg_truncated": b"\xff\xd8",
        "webp": b"RIFF\x24\x00\x00\x00WEBPVP8 ",
        "webp_highbit": bytes([0xD2, 0xC9, 0xC6, 0xC6, 0, 0, 0, 0, 0xD7, 0xC5, 0xC2, 0xD0]),
        "webp_wave": b"RIFF\x24\x00\x00\x00WAVEfmt ",
        "webp_short": b"RIFF\x24\x00\x00\x00WEB",
        "gif87": b"GIF87a\x01\x00\x01\x00",
        "gif89": b"GIF89a\x01\x00\x01\x00",
        "gif_highbit": bytes([0xC7, 0xC9, 0xC6, 0xB8, 0xB9, 0xE1]),
        "gif_bad": b"GIF88a\x01\x00",
        "bmp": b"BM\x1e\x00\x00\x00\x00\x00",
        "bmp_short": b"B",
        "heic": b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic",
        "heic_compat": b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heix",
        "heif": b"\x00\x00\x00\x14ftypmif1\x00\x00\x00\x00mif1",
        "heif_msf1": b"\x00\x00\x00\x14ftypmsf1\x00\x00\x00\x00",
        "heic_late_brand": b"\x00\x00\x00\x20ftypisom\x00\x00\x00\x00isomiso2avc1hevc",
        "isobmff_other": b"\x00\x00\x00\x14ftypavif\x00\x00\x00\x00avif",
        "isobmff_short": b"\x00\x00\x00\x14ftypheic"[:11],
        "isobmff_highbit": b"\x00\x00\x00\x14\xe6\xf4\xf9\xf0\xe8\xe5\xe9\xe3",
        "svg": b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        "text": b"hello world",
        "empty": b"",
        "zeros": b"\x00" * 24,
    }


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _base64_texts() -> list[str]:
    rng = random.Random(11)
    texts = [
        "",
        "=",
        "==",
        "===",
        "====",
        "A",
        "AB",
        "ABC",
        "ABCD",
        "AB=C",
        "AB==",
        "AA==",
        "AAA=",
        "AAB=",
        "AAC=",
        "AAE=",
        "AAAB",
        "A=",
        "A===",
        "AA=A",
        "AAAA=",
        "AAAA==",
        "AA A A",
        "AAAA\n",
        "\tAAAA\r\n",
        "AAAA ",
        "AAAA\u0085",
        "AAAA ",
        "é",
        "AA\U0001f600",
        "AAAA\x00",
        "A\x1fA\x20AA",
        "A-A_",
        "AAA.",
        "AAAA\x7f",
        "+/+/",
        "+/+=",
        "////",
        "a" * 4096,
        "a" * 4093,
        "a" * 130 + "==",
    ]
    for kind, raw in _image_bytes().items():
        encoded = _b64(raw)
        texts += [
            encoded,
            encoded.rstrip("="),
            f" {encoded}\n",
            encoded[: len(encoded) // 2] + " \n\t" + encoded[len(encoded) // 2 :],
            encoded.replace("+", "-").replace("/", "_"),
            encoded + "!",
            encoded + "=",
        ]
        del kind
    for length in range(0, 200, 7):
        raw = bytes(rng.randrange(256) for _ in range(length))
        encoded = _b64(raw)
        texts += [encoded, encoded.rstrip("="), encoded + "A", encoded[:-1]]
    big = _png(bytes(rng.randrange(256) for _ in range(400)))
    texts += [_b64(big), _b64(big) + "\n" + "A" * 4]
    return texts


def _data_url_cases() -> list[dict[str, Any]]:
    prefixes = [
        "data:image/png;base64,",
        "DATA:IMAGE/PNG;BASE64,",
        "Data:Image/Png;Base64,",
        "data:image/png;charset=utf-8;base64,",
        "data:image/png;base64;charset=utf-8,",
        "data:image/png;BASE64 ,",
        "data: image/png ; base64 ,",
        "data:\timage/png\t;\tbase64\t,",
        "data:image/jpeg;base64,",
        "data:image/jpg;base64,",
        "data:image/webp;base64,",
        "data:image/gif;base64,",
        "data:image/bmp;base64,",
        "data:image/heic;base64,",
        "data:image/heif;base64,",
        "data:image/svg+xml;base64,",
        "data:image/x-icon;base64,",
        "data:image/png,",
        "data:image/png;base64",
        "data:image/png;base64;",
        "data:text/plain;base64,",
        "data:application/octet-stream;base64,",
        "data:;base64,",
        "data:,",
        "data:base64,",
        "data:image/png;;base64,",
        "data:image/;base64,",
        "data:image;base64,",
        "data:image/png;base64,,",
        "data:image/png;base64;base64,",
        "data:image/png;x=y;base64,",
        "data:image/png;baseX64,",
        "data:image/png;base64 x,",
        "data: image/png;base64,",
        "data:image/png ;base64,",
        "https://example.com/a.png",
        "http://example.com/a.png?x=data:,",
        "file:///tmp/a.png",
        "/tmp/a.png",
        "",
        "x",
        "data",
        "data:",
        "dat",
        "ımage",
        " data:image/png;base64,",
    ]
    payload_kinds = [
        "png",
        "jpeg",
        "webp",
        "webp_highbit",
        "gif89",
        "bmp",
        "heic",
        "heif",
        "svg",
        "text",
        "empty",
        "png_truncated",
    ]
    images = _image_bytes()
    payloads = [_b64(images[kind]) for kind in payload_kinds]
    payloads += [
        _b64(images["png"]).rstrip("="),
        " " + _b64(images["png"]) + "\n",
        "not base64!",
        "",
    ]
    cases = []
    for prefix in prefixes:
        for payload in payloads:
            cases.append(prefix + payload)
    cases += [
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
        "data:image/png;base64,é",
        "data:image/png;base64,\ud83d",
        "data:image/png;base64," + "A" * 100000,
        "data:image/png;base64," + _b64(_png(b"\x00" * 90000)),
    ]
    return [{"text": text} for text in cases]


def test_real_openclaw_oracle_canonical_base64_matches_python(oracle):
    cases = [{"fn": "canonical", "text": text} for text in _base64_texts()]
    assert len(cases) >= 300
    _compare_inline(oracle, cases)


def test_real_openclaw_oracle_signature_sniffing_matches_python(oracle):
    images = _image_bytes()
    cases = [{"fn": "sniff", "hex": raw.hex()} for raw in images.values()]
    rng = random.Random(5)
    for raw in list(images.values()):
        for cut in range(0, min(len(raw), 24)):
            cases.append({"fn": "sniff", "hex": raw[:cut].hex()})
        for _ in range(6):
            mutated = bytearray(raw)
            if mutated:
                mutated[rng.randrange(len(mutated))] ^= 1 << rng.randrange(8)
            cases.append({"fn": "sniff", "hex": bytes(mutated).hex()})
    for _ in range(120):
        cases.append(
            {
                "fn": "sniff",
                "hex": bytes(rng.randrange(256) for _ in range(rng.randrange(40))).hex(),
            }
        )
    # Every high-bit alias of the ASCII signatures, which Node's "ascii" decoding folds together.
    for signature, offset in ((b"RIFF", 0), (b"WEBP", 8), (b"GIF89a", 0), (b"ftyp", 4)):
        for flip in range(1, 1 << min(len(signature), 4)):
            raw = bytearray(
                b"\x00\x00\x00\x14ftypheic\x00\x00\x00\x00"
                if offset == 4
                else b"RIFF\x00\x00\x00\x00WEBPxxxx"
                if signature != b"GIF89a"
                else b"GIF89a...."
            )
            for i, byte in enumerate(signature):
                raw[offset + i] = byte | (0x80 if flip >> (i % 4) & 1 else 0)
            cases.append({"fn": "sniff", "hex": bytes(raw).hex()})
    assert len(cases) >= 500
    _compare_inline(oracle, cases)


def test_real_openclaw_oracle_data_url_sanitizer_matches_python(oracle):
    urls = _data_url_cases()
    cases = [{"fn": fn, **url} for url in urls for fn in ("url", "storage")]
    assert len(cases) >= 1400
    _compare_inline(oracle, cases)


def test_real_openclaw_oracle_inline_base64_sanitizer_matches_python(oracle):
    images = _image_bytes()
    mimes = [
        "image/png",
        "IMAGE/PNG",
        " image/jpeg ",
        "image/webp",
        "image/gif",
        "image/",
        "image/x",
        "text/plain",
        "",
        "png",
        "ımage/png",
    ]
    texts = [_b64(raw) for raw in images.values()] + ["", "A", " iVBORw0KGgo= \n", "iVBORw0KGgo"]
    cases = [{"fn": "base64", "mimeType": mime, "text": text} for mime in mimes for text in texts]
    assert len(cases) >= 300
    _compare_inline(oracle, cases)


def _image_item(url: Any, **extra: Any) -> dict[str, Any]:
    return {"type": "input_image", "detail": "auto", "image_url": url, **extra}


def _payload_cases() -> list[dict[str, Any]]:
    images = _image_bytes()
    png = "data:image/png;base64," + _b64(images["png"])
    bmp = "data:image/bmp;base64," + _b64(images["bmp"])
    relabeled = "data:image/jpeg;base64," + _b64(images["png"])
    spaced = "data:image/png;base64," + _b64(images["png"])[:8] + " \n" + _b64(images["png"])[8:]
    urls = [
        png,
        bmp,
        relabeled,
        spaced,
        "https://x/y.png",
        "",
        "data:,",
        "data:image/png;base64,",
        "file:///a.png",
        None,
        5,
        True,
        [],
        {},
    ]
    inputs: list[Any] = []
    for url in urls:
        inputs.append([_image_item(url)])
        inputs.append(
            [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "t"}, _image_item(url)],
                }
            ]
        )
        inputs.append(
            [
                {
                    "type": "function_call_output",
                    "call_id": "c",
                    "output": [_image_item(url, file_id="f"), {"type": "input_text", "text": "x"}],
                }
            ]
        )
        inputs.append([[_image_item(url)], {"nested": {"deep": [_image_item(url)]}}])
        inputs.append([{**_image_item(url), "type": "output_image"}])
    inputs += [
        [],
        [None, 1, "s", True, [None]],
        [{"type": "input_image"}],
        [{"type": "input_image", "image_url": "x"}],
        "x",
        5,
        None,
        {"a": 1},
        [{"1": _image_item(png), "b": 1, "0": 2}],
    ]
    cases: list[dict[str, Any]] = []
    for value in inputs:
        cases.append({"fn": "payload", "params": {"input": value}})
        cases.append({"fn": "payload", "params": {"input": value, "store": False, "model": "m"}})
    cases += [
        {"fn": "payload", "params": {}},
        {"fn": "payload", "params": {"other": 1}},
        {"fn": "payload", "params": {"input": None}},
    ]
    return cases


def test_real_openclaw_oracle_responses_image_payload_sanitizer_matches_python(oracle):
    cases = _payload_cases()
    assert len(cases) >= 150
    _compare_inline(oracle, cases)


# --- compact-endpoint egress: windows against model routes ------------------------------------

ROUTE_PROVIDERS = [
    "openai",
    "OpenAI",
    " openai ",
    "azure-openai",
    "azure-openai-responses",
    "github-copilot",
    "opencode",
    "xai",
    "custom",
    "",
]
ROUTE_APIS = [
    "openai-responses",
    "azure-openai-responses",
    "openai-chatgpt-responses",
    "openclaw-openai-responses-transport",
    "openclaw-openai-chatgpt-responses-transport",
    "openclaw-azure-openai-responses-transport",
    " OPENAI-RESPONSES ",
    "openai-completions",
    "anthropic-messages",
]
ROUTE_URLS: list[str | None] = [
    None,
    "",
    "   ",
    "https://api.openai.com/v1",
    "https://API.OpenAI.com/v1",
    "api.openai.com/v1",
    "api.openai.com:443/v1",
    "https://api.openai.com.evil.example/v1",
    "https://user:pw@api.openai.com/v1",
    "ftp://api.openai.com",
    "https://chatgpt.com/backend-api/codex",
    "https://api.x.ai/v1",
    "https://my.openai.azure.com/openai/v1",
    "https://x.cognitiveservices.azure.com",
    "https://foo.services.ai.azure.com/",
    "https://x.api.cognitive.microsoft.com",
    "https://openai.azure.com",
    "https://ß.openai.azure.com",
    "http://localhost:8080/v1",
    "https://proxy.example/v1",
    "not a url",
    "//api.openai.com",
    "https:api.openai.com",
    "[::1]:80",
]


def _route_models() -> list[dict[str, Any]]:
    models = []
    for provider, api, url in itertools.product(ROUTE_PROVIDERS, ROUTE_APIS, ROUTE_URLS):
        models.append({"provider": provider, "api": api, "id": "gpt-x", "baseUrl": url})
    rng = random.Random(21)
    sampled = rng.sample(models, 160)
    # Always cover the first-class routes and every URL and API once.
    for url in ROUTE_URLS:
        sampled.append({"provider": "openai", "api": "openai-responses", "id": "m", "baseUrl": url})
        sampled.append({"provider": "custom", "api": "openai-responses", "id": "m", "baseUrl": url})
    for api in ROUTE_APIS:
        sampled.append(
            {"provider": "openai", "api": api, "id": "m", "baseUrl": "https://x.example"}
        )
        sampled.append({"provider": "openai", "api": api, "id": "m"})
    return [{key: value for key, value in model.items() if value is not None} for model in sampled]


def _png_url(extra: bytes = b"\x00" * 7) -> str:
    return "data:image/png;base64," + _b64(_png(extra))


def _egress_windows() -> list[tuple[str, list[Any]]]:
    images = _image_bytes()
    png = _png_url()
    item = {"type": "compaction", "encrypted_content": "ENCRYPTED"}

    def with_content(*content: Any, **message: Any) -> list[Any]:
        return [{**_window_message(), "content": list(content), **message}, item]

    def image(url: Any, **extra: Any) -> dict[str, Any]:
        return _image_item(url, **extra)

    out: list[tuple[str, list[Any]]] = [
        ("plain", _window_output()),
        ("status_message", with_content({"type": "input_text", "text": "x"}, status="completed")),
        (
            "status_incomplete",
            with_content({"type": "input_text", "text": "x"}, status="incomplete"),
        ),
        (
            "status_in_progress",
            with_content({"type": "input_text", "text": "x"}, status="in_progress"),
        ),
        (
            "status_on_item",
            [_window_message(), {**item, "status": "completed"}],
        ),
        (
            "status_two",
            [
                _window_message(status="completed"),
                _window_message("developer", status="completed"),
                item,
            ],
        ),
        ("png", with_content(image(png))),
        ("png_twice", with_content(image(png), {"type": "input_text", "text": "x"}, image(png))),
        ("png_status", with_content(image(png), status="completed")),
        ("https", with_content(image("https://example.com/a.png"))),
        ("file_id", with_content({"type": "input_image", "detail": "low", "file_id": "f"})),
        ("empty_url_file", with_content(image("", file_id="f"))),
        ("empty_url", with_content(image(""))),
        ("relabeled", with_content(image("data:image/jpeg;base64," + _b64(images["png"])))),
        (
            "whitespace",
            with_content(
                image(
                    "data:image/png;base64,"
                    + _b64(images["png"])[:8]
                    + "\n"
                    + _b64(images["png"])[8:]
                )
            ),
        ),
        (
            "unpadded",
            with_content(image("data:image/png;base64," + _b64(images["png"]).rstrip("="))),
        ),
        (
            "upper_scheme",
            with_content(image(png.replace("data:image/png;base64", "DATA:IMAGE/PNG;BASE64"))),
        ),
        ("charset", with_content(image(png.replace(";base64", ";charset=utf-8;base64")))),
        ("jpeg", with_content(image("data:image/jpeg;base64," + _b64(images["jpeg"])))),
        ("webp", with_content(image("data:image/webp;base64," + _b64(images["webp"])))),
        ("gif", with_content(image("data:image/gif;base64," + _b64(images["gif89"])))),
        ("bmp", with_content(image("data:image/bmp;base64," + _b64(images["bmp"])))),
        ("heic", with_content(image("data:image/heic;base64," + _b64(images["heic"])))),
        ("svg", with_content(image("data:image/svg+xml;base64," + _b64(images["svg"])))),
        ("text_payload", with_content(image("data:image/png;base64," + _b64(images["text"])))),
        ("not_base64", with_content(image("data:image/png,rawbytes"))),
        ("no_comma", with_content(image("data:image/png;base64"))),
        ("data_only", with_content(image("data:,"))),
        (
            "webp_highbit",
            with_content(image("data:image/webp;base64," + _b64(images["webp_highbit"]))),
        ),
        ("detail_original", with_content(image(png, detail="original"))),
        (
            "file_data",
            with_content(
                {"type": "input_file", "file_data": "data:image/bmp;base64,Qk0=", "filename": "a"}
            ),
        ),
        (
            "second_message_bad_image",
            [
                _window_message(),
                {
                    **_window_message("developer"),
                    "content": [image(png), image("data:image/bmp;base64," + _b64(images["bmp"]))],
                },
                item,
            ],
        ),
        (
            "breakpoint_image",
            with_content({**image(png), "prompt_cache_breakpoint": {"mode": "explicit"}}),
        ),
        ("only_item", [item]),
        ("item_id", [_window_message(), {**item, "id": "rs_1"}]),
        (
            "item_status_in_progress",
            [_window_message(status="in_progress"), {**item, "created_by": "x"}],
        ),
    ]
    return out


def test_real_openclaw_oracle_compaction_window_egress_matches_python(oracle):
    models = _route_models()
    windows = _egress_windows()
    cases: list[dict[str, Any]] = []
    for name, output in windows:
        replay = {
            "data": "ENCRYPTED",
            "compactedWindow": {"state": "ready", "output": json.dumps(output)},
        }
        assert name
        cases.append({"fn": "window", "replay": replay})
        cases.append({"fn": "isOutput", "value": output})
        for model in models:
            cases.append({"fn": "window", "replay": replay, "model": model})
            cases.append({"fn": "isOutput", "value": output, "model": model})
    assert len(cases) >= 15000
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    # The projection rejects some windows and keeps others on a non-native route.
    kept = [
        row["value"] is not None
        for case, row in zip(cases, rows, strict=True)
        if case["fn"] == "window" and "model" in case
    ]
    assert any(kept) and not all(kept)


def test_real_openclaw_oracle_checkpoint_resolvers_use_the_route_egress_policy(oracle):
    variants = [
        {"provider": "openai", "api": "openai-responses", "id": "gpt-x", "baseUrl": url}
        for url in (
            None,
            "https://api.openai.com/v1",
            "https://proxy.example/v1",
            "https://chatgpt.com/backend-api",
            "https://api.x.ai/v1",
            "https://my.openai.azure.com/v1",
            "not a url",
        )
    ] + [
        {
            "provider": "custom",
            "api": "openclaw-openai-responses-transport",
            "id": "m",
            "baseUrl": "https://proxy.example/v1",
        },
        {"provider": "custom", "api": "azure-openai-responses", "id": "m"},
        {"provider": "OpenAI", "api": "openai-chatgpt-responses", "id": "m"},
    ]
    variants = [{k: v for k, v in model.items() if v is not None} for model in variants]
    keyed = list(itertools.product(range(len(variants)), ("none", "both")))
    rows = _run(
        oracle,
        [{"fn": "replayContext", "model": variants[m], "identity": IDENTS[i]} for m, i in keyed],
    )
    contexts_by_key = {key: row["value"] for key, row in zip(keyed, rows, strict=True)}
    cases: list[dict[str, Any]] = []
    for (m, ident_key), ctx in contexts_by_key.items():
        model = variants[m]
        for name, state in _egress_state_variants(ctx):
            retained = {**state, "type": "openai-responses-retained-compaction"}
            retained.pop("replayIndex", None)
            for replay in (state, retained):
                owner = _assistant(list(BLOCKS), replay)
                messages = [_user(), owner, _user("2"), _assistant(["x"]), _tool_result()]
                identity = {**IDENTS[ident_key], "enabled": None}
                base = {"messages": messages, "model": model, "identity": identity}
                assert name
                for fn in ("newestResponses", "requiresRefresh", "responsesPlan"):
                    cases.append({**base, "fn": fn})
                cases.append({**base, "fn": "preserve", "windowed": [{"ref": 3}, {"ref": 4}]})
    assert len(cases) >= 1000
    _compare(oracle, cases)


def _egress_state_variants(ctx: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (name, _with_window(_responses_state(ctx), output))
        for name, output in _egress_windows()
        if name
        in {
            "plain",
            "status_message",
            "status_on_item",
            "png",
            "png_status",
            "relabeled",
            "whitespace",
            "bmp",
            "empty_url",
            "https",
            "file_id",
        }
    ]


# --- eligibility -----------------------------------------------------------------------------

ELIGIBILITY_APIS = [
    "anthropic-messages",
    "ANTHROPIC-MESSAGES",
    " anthropic-messages ",
    "anthropic-messages-x",
    "openai-responses",
    "azure-openai-responses",
    "openai-chatgpt-responses",
    "openclaw-openai-responses-transport",
    "openclaw-openai-chatgpt-responses-transport",
    "openclaw-azure-openai-responses-transport",
    " openai-responses",
    "openai-completions",
    "google-generative-ai",
    "",
]
ELIGIBILITY_PROVIDERS = [
    "anthropic",
    "Anthropic",
    " ANTHROPIC ",
    "anthropic-vertex",
    "openai",
    "claude",
    "",
]
ELIGIBILITY_URLS: list[str | None] = [
    None,
    "",
    "   ",
    "https://api.anthropic.com",
    "https://api.anthropic.com/",
    "https://API.ANTHROPIC.COM/v1",
    "  https://api.anthropic.com/v1  ",
    "api.anthropic.com",
    "api.anthropic.com/v1",
    "API.Anthropic.com:443/v1",
    "api.anthropic.com:443",
    "http://api.anthropic.com",
    "ws://api.anthropic.com",
    "//api.anthropic.com",
    "https:api.anthropic.com",
    "https://user:pw@api.anthropic.com",
    "https://api.anthropic.com:8443/v1",
    "https://api.anthropic.com.evil.example",
    "https://evil.example/api.anthropic.com",
    "https://evil.example?x=api.anthropic.com",
    "https://eu.api.anthropic.com",
    "https://proxy.example/anthropic",
    "http://localhost:8080",
    "https://foo.internal",
    "not a url",
    "https://",
    "https://api.anthropic.com x",
    "https://apı.anthropic.com",
]
ELIGIBILITY_PARAMS: list[Any] = [
    None,
    {},
    {"anthropicServerCompaction": True},
    {"anthropicServerCompaction": False},
    {"anthropicServerCompaction": "true"},
    {"anthropicServerCompaction": 1},
    {"anthropicServerCompaction": None},
    {"anthropicServerCompaction": True, "anthropicCompactThreshold": 90000},
    {"other": True},
]
ELIGIBILITY_KEYS: list[Any] = [
    None,
    "",
    "   ",
    " ",
    "sk-ant-api03-abc",
    "sk-ant-oat01-abc",
    "Bearer sk-ant-oat01-abc",
    "sk-ant-OAT01-abc",
    "sk-ant-oa",
    "xsk-ant-oatx",
    " sk-ant-api03-abc ",
    "k",
]
ELIGIBILITY_ENVS: list[Any] = [
    None,
    {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"},
    {"ANTHROPIC_BASE_URL": "https://proxy.example"},
    {"ANTHROPIC_BASE_URL": "  "},
    {"ANTHROPIC_BASE_URL": " api.anthropic.com/v1 "},
    {"ANTHROPIC_BASE_URL": ""},
]


def _eligibility_cases() -> list[dict[str, Any]]:
    rng = random.Random(9)
    base = {
        "model": {
            "provider": "anthropic",
            "api": "anthropic-messages",
            "id": "claude-x",
            "baseUrl": "https://api.anthropic.com",
        },
        "extraParams": {"anthropicServerCompaction": True},
        "apiKey": "sk-ant-api03-abc",
    }

    def build(provider: str, api: str, url: Any, params: Any, key: Any, env: Any) -> dict[str, Any]:
        model: dict[str, Any] = {"provider": provider, "api": api, "id": "claude-x"}
        if url is not None:
            model["baseUrl"] = url
        case: dict[str, Any] = {"fn": "eligibility", "model": model}
        if params is not None:
            case["extraParams"] = params
        if key is not None:
            case["apiKey"] = key
        if env is not None:
            case["env"] = env
        return case

    cases = [{"fn": "eligibility", **base}]
    for api in ELIGIBILITY_APIS:
        for provider in ELIGIBILITY_PROVIDERS:
            cases.append(
                build(
                    provider,
                    api,
                    "https://api.anthropic.com",
                    {"anthropicServerCompaction": True},
                    "k",
                    None,
                )
            )
            cases.append(build(provider, api, None, {"anthropicServerCompaction": True}, "k", None))
    for url in ELIGIBILITY_URLS:
        for env in ELIGIBILITY_ENVS:
            for params in ELIGIBILITY_PARAMS[:3]:
                cases.append(build("anthropic", "anthropic-messages", url, params, "k", env))
    for key in ELIGIBILITY_KEYS:
        for params in ELIGIBILITY_PARAMS:
            cases.append(
                build(
                    "anthropic",
                    "anthropic-messages",
                    "https://api.anthropic.com",
                    params,
                    key,
                    None,
                )
            )
    axes = (
        ELIGIBILITY_PROVIDERS,
        ELIGIBILITY_APIS,
        ELIGIBILITY_URLS,
        ELIGIBILITY_PARAMS,
        ELIGIBILITY_KEYS,
        ELIGIBILITY_ENVS,
    )
    for _ in range(2500):
        cases.append(build(*(rng.choice(axis) for axis in axes)))
    return cases


def test_real_openclaw_oracle_compaction_eligibility_matches_python(oracle):
    cases = _eligibility_cases()
    assert len(cases) >= 3000
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    values = {row["value"] for row in rows}
    assert values == {True, False}


# --- capture and suppression writers ---------------------------------------------------------

WRITER_MODELS: dict[str, dict[str, Any]] = {
    **{
        name: MODELS[name]
        for name in ("anthropic", "anthropic_no_url", "responses", "azure", "responses_no_url")
    },
    "blank_url": {
        "provider": "anthropic",
        "api": "anthropic-messages",
        "id": "c",
        "baseUrl": "   ",
    },
    "unicode_url": {
        "provider": "anthropic",
        "api": "anthropic-messages",
        "id": "c",
        "baseUrl": "https://hé.example/\U0001f600",
    },
}
WRITER_IDENTS = {
    "none": {},
    "both": IDENTS["both"],
    "blank": IDENTS["blank"],
    "unicode": IDENTS["unicode"],
}


def _anthropic_capture_cases() -> list[dict[str, Any]]:
    blocks: list[Any] = [
        {"type": "compaction", "content": "SUMMARY"},
        {"type": "compaction", "content": "SUMMARY", "encrypted_content": "ENC"},
        {"type": "compaction", "content": "SUMMARY", "encrypted_content": None},
        {"type": "compaction", "content": "SUMMARY", "encrypted_content": ""},
        {"type": "compaction", "content": "SUMMARY", "encrypted_content": 5},
        {"type": "compaction"},
        {"type": "compaction", "content": ""},
        {"type": "compaction", "content": 5, "encrypted_content": "E"},
        {"type": "compaction", "content": "sé\U0001f600"},
        {"type": "text", "text": "x"},
        {"content": "SUMMARY"},
        None,
        "compaction",
        [],
    ]
    indexes: list[Any] = [0, 1, 3, -1, 1.5, 2**53, 2**53 - 1, "1", None]
    delta_sequences: list[list[dict[str, Any]]] = [
        [],
        [{"op": "delta", "index": 0, "delta": {"type": "compaction_delta", "content": " more"}}],
        [
            {"op": "delta", "index": 0, "delta": {"type": "compaction_delta", "content": " a"}},
            {
                "op": "delta",
                "index": 0,
                "delta": {"type": "compaction_delta", "content": " b", "encrypted_content": "E2"},
            },
        ],
        [
            {
                "op": "delta",
                "index": 0,
                "delta": {"type": "compaction_delta", "encrypted_content": None},
            }
        ],
        [{"op": "delta", "index": 0, "delta": {"type": "other", "content": "no"}}],
        [{"op": "delta", "index": 0, "delta": None}],
        [{"op": "delta", "index": 7, "delta": {"type": "compaction_delta", "content": "no"}}],
        [
            {
                "op": "delta",
                "index": 0,
                "delta": {"type": "compaction_delta", "content": 5, "encrypted_content": 6},
            }
        ],
    ]
    cases: list[dict[str, Any]] = []
    model_names = list(WRITER_MODELS)[:2] + ["blank_url", "unicode_url"]
    for b_index, block in enumerate(blocks):
        for r_index, replay_index in enumerate(indexes):
            for d_index, deltas in enumerate(delta_sequences):
                model_key = model_names[(b_index + r_index + d_index) % len(model_names)]
                ident_key = list(WRITER_IDENTS)[
                    (b_index * 3 + r_index + d_index) % len(WRITER_IDENTS)
                ]
                begin = {"op": "begin", "index": 0, "block": block, "replayIndex": replay_index}
                events = [begin, *deltas, {"op": "complete", "index": 0}]
                if d_index % 3 == 0:
                    events.append({"op": "complete", "index": 0})
                if d_index % 4 == 1:
                    events.insert(0, {"op": "complete", "index": 0})
                    events.append({"op": "begin", "index": 1, "block": blocks[0], "replayIndex": 2})
                    events.append({"op": "complete", "index": 1})
                preexisting = (
                    {"providerReplay": {"type": "anthropic-compaction", "data": "OLD"}}
                    if d_index % 5 == 2
                    else {}
                )
                cases.append(
                    {
                        "fn": "anthropicCapture",
                        "model": WRITER_MODELS[model_key],
                        "identity": WRITER_IDENTS[ident_key],
                        "output": preexisting,
                        "events": events,
                    }
                )
    return cases


def test_real_openclaw_oracle_anthropic_capture_matches_python(oracle):
    cases = _anthropic_capture_cases()
    assert len(cases) >= 900
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    written = [row for row in rows if row["value"]["providerReplay"] is not None]
    assert 100 < len(written) < len(rows)


def test_real_openclaw_oracle_compaction_suppression_matches_python(oracle):
    cases: list[dict[str, Any]] = []
    old = {"providerReplay": {"type": "anthropic-compaction", "data": "OLD"}}
    for model in WRITER_MODELS.values():
        for ident in WRITER_IDENTS.values():
            for output in ({}, old):
                cases.append(
                    {"fn": "anthropicSuppress", "model": model, "identity": ident, "output": output}
                )
                for rejected in (None, {"reason": "x"}, {}, "s", 0):
                    for with_callback in (False, True):
                        cases.append(
                            {
                                "fn": "responsesSuppress",
                                "model": model,
                                "identity": ident,
                                "output": output,
                                "rejected": rejected,
                                "withCallback": with_callback,
                            }
                        )
                cases.append({"fn": "reasoningMetadata", "model": model, "identity": ident})
    assert len(cases) >= 600
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []


def test_real_openclaw_oracle_replay_context_shape_matches_python(oracle):
    base = {"provider": "p", "api": "a", "model": "m"}
    values: list[Any] = [
        base,
        {**base, "baseUrlHash": "h"},
        {**base, "baseUrlHash": None},
        {**base, "baseUrlHash": 5},
        {**base, "sessionHash": "s", "authProfileHash": "a"},
        {**base, "sessionHash": None},
        {**base, "authProfileHash": False},
        {"provider": 1, "api": "a", "model": "m"},
        {"api": "a", "model": "m"},
        {"provider": "p", "model": "m"},
        {"provider": "p", "api": "a"},
        {},
        [],
        "x",
        None,
        5,
        True,
    ]
    cases = [{"fn": "replayContextShape", "value": value} for value in values]
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []


def _capture_items() -> list[dict[str, Any]]:
    return [
        {"type": "compaction", "encrypted_content": "ENCRYPTED"},
        {"type": "compaction", "encrypted_content": "ENCRYPTED", "id": "rs_1"},
        {"type": "compaction", "encrypted_content": "ENCRYPTED", "id": ""},
        {"type": "compaction", "encrypted_content": "ENCRYPTED", "id": None},
        {"type": "compaction", "encrypted_content": "sé\U0001f600", "id": "rs_é"},
        {"type": "compaction", "encrypted_content": ""},
        {"type": "compaction", "encrypted_content": None},
        {"type": "compaction"},
    ]


def _capture_metadata(ctx: dict[str, Any]) -> list[Any]:
    base = {"v": 1, "source": "openai-responses", **ctx}
    return [
        None,
        base,
        {**base, "sessionHash": "sh", "authProfileHash": "ah"},
        {**base, "sessionHash": "", "authProfileHash": ""},
        {key: value for key, value in base.items() if key != "baseUrlHash"},
        {**base, "baseUrlHash": ""},
        {key: value for key, value in base.items() if key not in ("provider", "api")},
        {**base, "extra": {"x": 1}},
    ]


def _existing_replays(ctx: dict[str, Any]) -> list[Any]:
    return [
        None,
        _responses_state(ctx, replayIndex=0),
        _responses_state(ctx, replayIndex=1),
        _responses_state(ctx, replayIndex=3),
        _drop(_responses_state(ctx), "replayIndex"),
        _retained_state(ctx),
        _responses_state(ctx, type="openai-responses-compaction-suppression", data="rejected"),
        _responses_state(ctx, replayIndex=-5),
        {"type": "openai-responses-compaction", "data": "x"},
        "junk",
    ]


def _compacted_outputs() -> list[Any]:
    images = _image_bytes()
    png_item = _image_item(_png_url())
    return [
        None,
        _window_output(),
        _window_output(item_id="rs_1"),
        _window_output(data="OTHER"),
        _window_output(item_id="rs_other"),
        [
            _window_message(status="completed"),
            {"type": "compaction", "encrypted_content": "ENCRYPTED"},
        ],
        [
            {**_window_message(), "content": [png_item]},
            {"type": "compaction", "encrypted_content": "ENCRYPTED"},
        ],
        [
            {
                **_window_message(),
                "content": [_image_item("data:image/bmp;base64," + _b64(images["bmp"]))],
            },
            {"type": "compaction", "encrypted_content": "ENCRYPTED"},
        ],
        [
            {
                **_window_message(),
                "content": [_image_item("data:image/jpeg;base64," + _b64(images["png"]))],
            },
            {"type": "compaction", "encrypted_content": "ENCRYPTED"},
        ],
        [],
        [{"type": "compaction", "encrypted_content": ""}],
        [{"type": "message"}],
        [
            _window_message(role="assistant"),
            {"type": "compaction", "encrypted_content": "ENCRYPTED"},
        ],
    ]


def test_real_openclaw_oracle_responses_capture_matches_python(oracle, contexts):
    cases: list[dict[str, Any]] = []
    boundaries: list[Any] = [0, 1, 2, 5, -1, "retained-users", "other", 1.5, None]
    rng = random.Random(4)
    for model_key in ("responses", "azure", "responses_no_url", "completions"):
        for ident_key in ("none", "both"):
            ctx = contexts[(model_key, ident_key)]
            model = MODELS[model_key]
            identity = IDENTS[ident_key]
            for item in _capture_items():
                for boundary in boundaries:
                    for metadata in _capture_metadata(ctx):
                        replays = _existing_replays(ctx)
                        output = rng.choice(replays)
                        cases.append(
                            {
                                "fn": "responsesCapture",
                                "model": model,
                                "identity": identity,
                                "item": item,
                                "boundary": boundary,
                                "metadata": metadata,
                                "output": {} if output is None else {"providerReplay": output},
                            }
                        )
            for replay in _existing_replays(ctx):
                for boundary in (0, 1, 2, 3):
                    cases.append(
                        {
                            "fn": "responsesCapture",
                            "model": model,
                            "identity": identity,
                            "item": _capture_items()[1],
                            "boundary": boundary,
                            "output": {} if replay is None else {"providerReplay": replay},
                        }
                    )
            for compacted in _compacted_outputs():
                for item in _capture_items()[:3]:
                    for boundary in (1, "retained-users"):
                        cases.append(
                            {
                                "fn": "responsesCapture",
                                "model": model,
                                "identity": identity,
                                "item": item,
                                "boundary": boundary,
                                "compactedOutput": compacted,
                            }
                        )
    # The same windows against non-native routes: the egress policy rejects status fields there.
    proxy = {
        "provider": "custom",
        "api": "openai-responses",
        "id": "m",
        "baseUrl": "https://proxy.example/v1",
    }
    for compacted in _compacted_outputs():
        for item in _capture_items()[:2]:
            cases.append(
                {
                    "fn": "responsesCapture",
                    "model": proxy,
                    "item": item,
                    "boundary": 1,
                    "compactedOutput": compacted,
                }
            )
    big = [
        _window_message(text="x" * (16 * 1024 * 1024)),
        {"type": "compaction", "encrypted_content": "ENCRYPTED"},
    ]
    cases.append(
        {
            "fn": "responsesCapture",
            "model": MODELS["responses"],
            "item": _capture_items()[0],
            "boundary": 1,
            "compactedOutput": big,
        }
    )
    assert len(cases) >= 2500
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    errors = {row["error"] for row in rows}
    assert errors == {None, "Error"}
    assert (
        sum(row["value"] is not None and row["value"]["providerReplay"] is not None for row in rows)
        > 500
    )


def test_real_openclaw_oracle_compaction_tracker_matches_python(oracle, contexts):
    cases: list[dict[str, Any]] = []
    rng = random.Random(6)

    def item(kind: str, item_id: Any, enc: Any) -> dict[str, Any]:
        out: dict[str, Any] = {"type": kind}
        if item_id is not _NOTHING:
            out["id"] = item_id
        if enc is not _NOTHING:
            out["encrypted_content"] = enc
        return out

    ids = ["rs_1", "rs_2", "", None, _NOTHING]
    encs = ["ENC", "", None, _NOTHING]
    for model_key in ("responses", "azure", "responses_no_url", "anthropic"):
        for metadata in _capture_metadata(contexts[(model_key, "none")]):
            for _ in range(24):
                steps: list[dict[str, Any]] = []
                for _step in range(rng.randrange(1, 7)):
                    kind = rng.choice(["compaction", "compaction", "reasoning"])
                    spec = item(kind, rng.choice(ids), rng.choice(encs))
                    if rng.random() < 0.45:
                        steps.append(
                            {"op": "added", "item": spec, "replayIndex": rng.choice([0, 1, 2, 4])}
                        )
                    else:
                        steps.append(
                            {"op": "completed", "item": spec, "fallback": rng.choice([0, 1, 3])}
                        )
                cases.append(
                    {
                        "fn": "tracker",
                        "model": MODELS[model_key],
                        "output": rng.choice(
                            [
                                {},
                                {},
                                {
                                    "providerReplay": _responses_state(
                                        contexts[(model_key, "none")], replayIndex=2
                                    )
                                },
                            ]
                        ),
                        "metadata": metadata,
                        "steps": steps,
                    }
                )
    assert len(cases) >= 500
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    assert any(snapshot is not None for row in rows for snapshot in row["value"]["snapshots"])


_NOTHING = object()


# --- replay pressure ---------------------------------------------------------------------------

_COST = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}
_SUMMARIES = [
    "SUMMARY",
    "",
    "séß\U0001f600" * 5,
    "日本語の要約" * 30,
    "x" * 5000,
    "line\nbreak\ttab",
]
_USAGE_KINDS: list[Any] = [
    {"input": 1, "output": 2, "totalTokens": 3},
    {"input": 1, "contextUsage": {"state": "available", "promptTokens": 90, "totalTokens": 100}},
    {"input": 1, "contextUsage": None},
    {"contextUsage": {"state": "estimated"}},
    {},
    None,
    "ab",
    5,
]


def _usage_assistant(content: Any, usage: Any, replay: Any = None) -> dict[str, Any]:
    message = _assistant(content, replay, usage=usage)
    if usage is _MISSING_USAGE:
        del message["usage"]
    return message


_MISSING_USAGE = object()


def _tails() -> list[list[dict[str, Any]]]:
    plain = _usage_assistant(["x"], {"input": 1, "output": 2})
    measured = _usage_assistant(
        ["y"], {"input": 1, "contextUsage": {"state": "available", "totalTokens": 5}}
    )
    return [
        [],
        [_user("t")],
        [plain],
        [measured],
        [_usage_assistant(["z"], None)],
        [_usage_assistant(["z"], _MISSING_USAGE)],
        [_tool_result(), measured, _user("t3")],
        [_usage_assistant(["z"], {"contextUsage": None})],
        [_usage_assistant(["z"], 5), measured],
        [{"role": "system", "content": "s"}, plain, measured, plain],
    ]


def _pressure_anthropic_cases(
    contexts: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for ident_key in ("none", "both"):
        ctx = contexts[("anthropic", ident_key)]
        for s_index, summary in enumerate(_SUMMARIES):
            for replay_index in (0, 1, 2, 3, 9, None):
                state = _anthropic_state(ctx, data=summary or "S", replayIndex=replay_index)
                if replay_index is None:
                    state = _drop(state, "replayIndex")
                if s_index == 2:
                    state["encryptedContent"] = "enc"
                for u_index, usage in enumerate(_USAGE_KINDS):
                    owner = _usage_assistant(list(BLOCKS), usage, state)
                    for t_index, tail in enumerate(_tails()):
                        if (s_index + u_index + t_index) % 3:
                            continue
                        messages = [_user(), owner, *tail]
                        for enabled in (True, None, False):
                            identity = {**IDENTS[ident_key], "enabled": enabled}
                            cases.append(
                                {
                                    "fn": "pressure",
                                    "messages": messages,
                                    "model": MODELS["anthropic"],
                                    "identity": identity,
                                }
                            )
    return cases


def _pressure_window_outputs() -> list[Any]:
    png = _image_item(_png_url())
    return [
        _window_output(),
        [
            {**_window_message(), "content": [{"type": "input_text", "text": "日本語" * 20}]},
            {"type": "compaction", "encrypted_content": "ENCRYPTED", "id": "rs_1"},
        ],
        [
            {
                **_window_message(),
                "content": [
                    png,
                    {
                        "type": "input_text",
                        "text": "t",
                        "prompt_cache_breakpoint": {"mode": "explicit"},
                    },
                ],
            },
            {"type": "compaction", "encrypted_content": "ENCRYPTED"},
        ],
        [
            {
                **_window_message("developer"),
                "content": [
                    _image_item("https://example.com/a.png"),
                    _image_item(None, file_id="f1"),
                ],
            },
            {"type": "compaction", "encrypted_content": "ENCRYPTED"},
        ],
        [
            {
                **_window_message(),
                "content": [
                    {"type": "input_file", "file_data": "ZGF0YQ==", "filename": "a"},
                    {"type": "input_file", "file_id": "f"},
                ],
            },
            {"type": "compaction", "encrypted_content": "ENCRYPTED", "created_by": "x"},
        ],
        [
            {**_window_message(status="completed"), "content": []},
            {**_window_message("system", "\U0001f600" * 40), "id": "m1"},
            {"type": "compaction", "encrypted_content": "e" * 3000},
        ],
        [{"type": "compaction", "encrypted_content": "ENCRYPTED"}],
    ]


def _pressure_responses_cases(
    contexts: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for model_key in ("responses", "azure", "chatgpt", "transport"):
        for ident_key in ("none", "both"):
            ctx = contexts[(model_key, ident_key)]
            states: list[tuple[str, dict[str, Any]]] = []
            for summary in _SUMMARIES[:4]:
                for replay_index in (0, 1, 3, None):
                    state = _responses_state(ctx, data=summary or "E", replayIndex=replay_index)
                    states.append(
                        ("prefix", _drop(state, "replayIndex") if replay_index is None else state)
                    )
            states.append(("prefix_id", _responses_state(ctx, id="rs_1")))
            for output in _pressure_window_outputs():
                for replay_index in (0, 1, 2):
                    states.append(
                        (
                            "window",
                            _with_window(_responses_state(ctx, replayIndex=replay_index), output),
                        )
                    )
                states.append(
                    ("retained", _drop(_with_window(_retained_state(ctx), output), "replayIndex"))
                )
            states += [
                (
                    "refresh",
                    {**_responses_state(ctx), "compactedWindow": {"state": "refresh-required"}},
                ),
                ("retained_refresh", _retained_state(ctx)),
                ("bad_window", _with_window(_responses_state(ctx), "{nope")),
                (
                    "suppressed",
                    _responses_state(
                        ctx, type="openai-responses-compaction-suppression", data="rejected"
                    ),
                ),
            ]
            for s_index, (kind, state) in enumerate(states):
                for u_index, usage in enumerate(_USAGE_KINDS):
                    owner = _usage_assistant(list(BLOCKS), usage, state)
                    for t_index, tail in enumerate(_tails()):
                        if (s_index + u_index + t_index) % 4:
                            continue
                        messages = [_user(), owner, *tail]
                        cases.append(
                            {
                                "fn": "pressure",
                                "messages": messages,
                                "model": MODELS[model_key],
                                "identity": {**IDENTS[ident_key], "enabled": None},
                                "kind": kind,
                            }
                        )
    return cases


def _assert_pressure_outcomes(rows: list[Any], errors: set[Any]) -> None:
    assert {row["error"] for row in rows} >= errors
    assert any(row["value"] is not None and row["value"]["messages"] for row in rows)
    assert any(row["value"] is None and row["error"] is None for row in rows)


def test_real_openclaw_oracle_anthropic_replay_pressure_matches_python(oracle, contexts):
    cases = _pressure_anthropic_cases(contexts)
    assert len(cases) >= 1000
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    _assert_pressure_outcomes(rows, {None, "TypeError"})


def test_real_openclaw_oracle_responses_replay_pressure_matches_python(oracle, contexts):
    cases = _pressure_responses_cases(contexts)
    assert len(cases) >= 1500
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    _assert_pressure_outcomes(rows, {None, "TypeError", "CompactionReplayRefreshRequiredError"})


# --- estimateResponsesInput (private upstream; the oracle loads a sibling copy) -----------------


def _estimate_items() -> list[list[Any]]:
    png = _png_url()
    texts: list[Any] = ["", "abc", "日本語" * 10, "\U0001f600" * 20, "x" * 700, "a\nb"]
    blocks: list[Any] = [
        {"type": "input_text", "text": "hello"},
        {"type": "input_text", "text": "hé日", "extra": [1, 2]},
        {"type": "output_text", "text": "out", "annotations": [{"a": 1}]},
        {"type": "input_text", "text": 5},
        {"type": "output_text"},
        _image_item(png),
        _image_item("DATA:image/png;base64,AAAA"),
        _image_item("https://example.com/a.png"),
        _image_item(None, file_id="f"),
        _image_item(5),
        {"type": "input_image"},
        {"type": "input_file", "file_data": "ZGF0YQ==", "filename": "a.txt"},
        {"type": "refusal", "refusal": "no"},
        {"type": "summary_text", "text": "s"},
        "a bare string",
        None,
        5,
        True,
        [1, 2],
        {},
        {"nested": {"deep": ["x" * 50]}},
    ]
    items: list[list[Any]] = [[]]
    rng = random.Random(31)

    def content() -> Any:
        pick = rng.random()
        if pick < 0.15:
            return rng.choice(texts)
        if pick < 0.2:
            return rng.choice([None, 5, {"a": 1}, True, []])
        return [rng.choice(blocks) for _ in range(rng.randrange(0, 5))]

    def entry() -> Any:
        kind = rng.choice(["compaction", "message", "fco", "cto", "other", "bare"])
        if kind == "compaction":
            out: dict[str, Any] = {"type": "compaction"}
            if rng.random() < 0.85:
                out["encrypted_content"] = rng.choice(["ENC", "", "日本", "e" * 400, 5, None])
            if rng.random() < 0.5:
                out["id"] = "rs_1"
            return out
        if kind == "message":
            out = {"type": "message", "role": rng.choice(["user", "assistant", "developer"])}
            if rng.random() < 0.9:
                out["content"] = content()
            if rng.random() < 0.3:
                out["status"] = "completed"
                out["id"] = "msg_1"
            return out
        if kind in ("fco", "cto"):
            out = {
                "type": "function_call_output" if kind == "fco" else "custom_tool_call_output",
                "call_id": "c1",
            }
            if rng.random() < 0.9:
                out["output"] = content()
            return out
        if kind == "other":
            return rng.choice(
                [
                    {"type": "function_call", "name": "f", "arguments": "{}", "call_id": "c"},
                    {"type": "reasoning", "summary": [], "encrypted_content": "x" * 100},
                    {"type": "message"},
                    {"type": "unknown"},
                    {"role": "user"},
                    {},
                ]
            )
        return rng.choice(["str", None, 5, True, [1], "日本"])

    for _ in range(520):
        items.append([entry() for _ in range(rng.randrange(1, 7))])
    return items


def test_real_openclaw_oracle_estimate_responses_input_matches_python(oracle):
    cases = [
        {"fn": "estimateInput", "items": value, "withToolResult": flag}
        for value in _estimate_items()
        for flag in (True, False)
    ]
    assert len(cases) >= 1000
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    assert len({row["value"] for row in rows}) > 200


# --- measured usage boundary -------------------------------------------------------------------


def _wire_assistant(
    model: dict[str, Any], content: list[Any], replay: Any = None, **extra: Any
) -> dict[str, Any]:
    message: dict[str, Any] = {
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
    if replay is not None:
        message["providerReplay"] = replay
    return message


def _wire_user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text, "timestamp": 1}


def _wire_tool_result(call_id: str, content: list[Any]) -> dict[str, Any]:
    return {
        "role": "toolResult",
        "toolCallId": call_id,
        "toolName": "read",
        "content": content,
        "isError": False,
        "timestamp": 1,
    }


def _measured_tails(model: dict[str, Any]) -> list[tuple[str, list[Any], list[Any]]]:
    """(name, target content, messages after the target)."""

    call = {"type": "toolCall", "id": "call_1|fc_1", "name": "read", "arguments": {"p": 1}}
    text = [{"type": "text", "text": "answer"}]
    del model
    return [
        ("none", text, []),
        ("user", text, [_wire_user("q3")]),
        (
            "tool",
            [*text, call],
            [
                _wire_tool_result("call_1|fc_1", [{"type": "text", "text": "result text"}]),
                _wire_user("q3"),
            ],
        ),
        (
            "tool_image",
            [call],
            [
                _wire_tool_result(
                    "call_1|fc_1",
                    [
                        {"type": "text", "text": "see"},
                        {"type": "image", "data": _b64(_png(b"\x00" * 7)), "mimeType": "image/png"},
                    ],
                ),
            ],
        ),
        ("unicode", [{"type": "text", "text": "日本語\U0001f600" * 3}], [_wire_user("é" * 40)]),
    ]


def _measured_owner_states(ctx: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    window = _window_output()
    return [
        ("prefix1", _responses_state(ctx, replayIndex=1)),
        ("prefix0", _responses_state(ctx, replayIndex=0)),
        ("window", _with_window(_responses_state(ctx, replayIndex=1), window)),
        ("retained", _drop(_with_window(_retained_state(ctx), window), "replayIndex")),
        ("prefix_id", _responses_state(ctx, id="rs_1", replayIndex=2)),
    ]


def _mutate(messages: list[dict[str, Any]], name: str, target: int) -> list[dict[str, Any]] | None:
    out = copy.deepcopy(messages)
    message = out[target]
    state = message.get("openclawResponsesInputReplay", {}).get("contextUsage")
    usage = message["usage"]
    if name == "none":
        return out
    if name.startswith("state:") and isinstance(state, dict):
        _, key, raw = name.split(":", 2)
        state[key] = json.loads(raw)
        return out
    if name == "state_drop_hash":
        state.pop("baseUrlHash", None)
    elif name == "state_session":
        state["sessionHash"] = "zz"
    elif name == "usage_total":
        usage["contextUsage"]["totalTokens"] += 1
    elif name == "usage_prompt":
        usage["contextUsage"]["promptTokens"] += 1
    elif name == "usage_state":
        usage["contextUsage"]["state"] = "estimated"
    elif name == "usage_nocontext":
        usage.pop("contextUsage")
    elif name == "usage_zero":
        usage["contextUsage"]["totalTokens"] = 0
        state["totalTokens"] = 0
    elif name == "usage_float":
        usage["contextUsage"]["totalTokens"] = 100.5
        state["totalTokens"] = 100.5
    elif name == "usage_none":
        message["usage"] = None
    elif name == "usage_missing":
        del message["usage"]
    elif name == "msg_provider":
        message["provider"] = "other"
    elif name == "msg_api":
        message["api"] = "openai-completions"
    elif name == "msg_model":
        message["model"] = "other"
    elif name == "replay_string":
        message["openclawResponsesInputReplay"] = "x"
    elif name == "replay_nocontext":
        message["openclawResponsesInputReplay"] = {}
    elif name == "replay_null_context":
        message["openclawResponsesInputReplay"]["contextUsage"] = None
    elif name == "edit_early":
        out[0]["content"] = "q1 edited"
    elif name == "drop_user":
        del out[2]
    elif name == "append_user":
        out.append(_wire_user("later"))
    elif name == "later_unstated":
        later = _wire_assistant(
            {"provider": message["provider"], "api": message["api"], "id": message["model"]},
            [{"type": "text", "text": "later"}],
        )
        later["usage"]["contextUsage"] = {"state": "available", "promptTokens": 1, "totalTokens": 2}
        out.append(later)
    elif name == "later_no_usage":
        later = _wire_assistant(
            {"provider": message["provider"], "api": message["api"], "id": message["model"]},
            [{"type": "text", "text": "later"}],
        )
        del later["usage"]
        out.append(later)
    elif name == "later_bad_state":
        later = copy.deepcopy(message)
        later["content"] = [{"type": "text", "text": "later"}]
        later["openclawResponsesInputReplay"]["contextUsage"]["prefixHash"] = "bad"
        out.append(later)
    else:
        raise AssertionError(name)
    return out


_MUTATIONS = [
    "none",
    "none",
    "state:prefixLength:0",
    "state:prefixLength:-1",
    "state:prefixLength:1.5",
    'state:prefixLength:"4"',
    "state:prefixLength:null",
    "state:prefixLength:1",
    "state:prefixLength:2",
    "state:prefixLength:99",
    'state:prefixHash:"deadbeef"',
    "state:prefixHash:5",
    'state:projection:"x"',
    'state:projection:"provider"',
    'state:projection:"transport"',
    "state:promptTokens:1",
    "state:totalTokens:1",
    "state:includeSystemPrompt:true",
    "state:includeSystemPrompt:false",
    'state:includeSystemPrompt:"true"',
    'state:provider:"other"',
    "state:api:5",
    'state:model:"other"',
    "state:baseUrlHash:5",
    "state_drop_hash",
    "state_session",
    "usage_total",
    "usage_prompt",
    "usage_state",
    "usage_nocontext",
    "usage_zero",
    "usage_float",
    "usage_none",
    "usage_missing",
    "msg_provider",
    "msg_api",
    "msg_model",
    "replay_string",
    "replay_nocontext",
    "replay_null_context",
    "edit_early",
    "drop_user",
    "append_user",
    "later_unstated",
    "later_no_usage",
    "later_bad_state",
]


def _measured_base_cases(contexts: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for model_key in ("responses", "azure", "transport"):
        model = MODELS[model_key]
        for ident_key in ("none", "both"):
            ctx = contexts[(model_key, ident_key)]
            for owner_name, state in _measured_owner_states(ctx):
                for tail_name, target_content, tail in _measured_tails(model):
                    for projection in ("transport", "provider"):
                        for system_prompt, include in (
                            (None, False),
                            ("You are helpful.", True),
                            ("You are helpful.", False),
                        ):
                            messages = [
                                _wire_user("q1"),
                                _wire_assistant(
                                    model,
                                    [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}],
                                    state,
                                ),
                                _wire_user("q2"),
                                _wire_assistant(model, target_content),
                                *tail,
                            ]
                            specs.append(
                                {
                                    "messages": messages,
                                    "model": model,
                                    "identity": IDENTS[ident_key],
                                    "target": 3,
                                    "projection": projection,
                                    "includeSystemPrompt": include,
                                    "systemPrompt": system_prompt,
                                    "promptTokens": 90,
                                    "totalTokens": 100,
                                    "name": f"{model_key}/{ident_key}/{owner_name}/{tail_name}/{projection}",
                                }
                            )
    return specs


def test_real_openclaw_oracle_measured_usage_pressure_matches_python(oracle, contexts):
    specs = _measured_base_cases(contexts)
    recorded = _run_op(
        oracle,
        "compactionCheckpoint",
        [{"fn": "recordUsage", **{k: v for k, v in spec.items() if k != "name"}} for spec in specs],
    )
    rng = random.Random(77)
    pressure_cases: list[dict[str, Any]] = []
    for spec, row in zip(specs, recorded, strict=True):
        assert row["error"] is None, (spec["name"], row)
        messages = row["value"]
        assert "openclawResponsesInputReplay" in messages[3], spec["name"]
        for mutation in dict.fromkeys(["none", *rng.sample(_MUTATIONS, 3)]):
            mutated = _mutate(messages, mutation, 3)
            for system_prompt in dict.fromkeys(
                [spec["systemPrompt"], rng.choice([None, "other prompt"])]
            ):
                pressure_cases.append(
                    {
                        "fn": "pressure",
                        "messages": mutated,
                        "model": spec["model"],
                        "identity": {**spec["identity"], "enabled": rng.choice([True, None])},
                        "systemPrompt": system_prompt,
                        "mutation": mutation,
                    }
                )
    assert len(pressure_cases) >= 3000
    tables = _run_op(
        oracle,
        "compactionCheckpoint",
        [
            {**{k: v for k, v in case.items() if k != "mutation"}, "fn": "projections"}
            for case in pressure_cases
        ],
    )
    for case, table in zip(pressure_cases, tables, strict=True):
        if table["error"] is None:
            case["projectionTable"] = table["value"]
    rows = _run_op(
        oracle,
        "compactionCheckpoint",
        [{k: v for k, v in c.items() if k != "projectionTable"} for c in pressure_cases],
    )
    # A case whose converter run threw cannot give the Python hook its wire input; when the real
    # pressure call also fails it is compared on the error only.
    keep = [
        index
        for index, case in enumerate(pressure_cases)
        if "projectionTable" in case or rows[index]["error"] is None
    ]
    cases = [pressure_cases[i] for i in keep]
    kept_rows = [rows[i] for i in keep]
    python_rows = [_python_row(case) for case in cases]
    assert _first_diffs(cases, kept_rows, python_rows) == []
    assert len(cases) > 0.9 * len(pressure_cases)
    # The built-in converter (no host hook) against every case, converter failures included.
    builtin_cases = [{k: v for k, v in c.items() if k != "projectionTable"} for c in pressure_cases]
    builtin_rows = [_python_row(case) for case in builtin_cases]
    assert _first_diffs(builtin_cases, rows, builtin_rows) == []
    measured = [row for row in rows if row["value"] and "measuredTokens" in row["value"]]
    estimated = [row for row in rows if row["value"] and "measuredTokens" not in row["value"]]
    assert len(measured) > 500
    assert len(estimated) > 300
    assert {row["error"] for row in rows} >= {None, "TypeError"}


# --- URL host extraction (the endpoint classifiers) ------------------------------------------

_URL_HOSTS = [
    "api.openai.com",
    "API.OpenAI.com",
    "chatgpt.com",
    "api.x.ai",
    "a.openai.azure.com",
    "api.anthropic.com",
    "127.0.0.1",
    "0x7f.1",
    "1.2.3",
    "1.2.3.4.5",
    "256.1.1.1",
    "[::1]",
    "[2001:db8:0:0:1:0:0:1]",
    "[::ffff:1.2.3.4]",
    "[1:0:0:2:0:0:0:3]",
    "[zz]",
    "[::1",
    "",
    "a b",
    "a%41.com",
    "a%2Fb",
    "a%zz",
    "ex_ample.com",
    "exa mple.com",
    "\u00e9xample.com",
    "\u65e5\u672c.jp",
    "a..b",
    "a.b.",
    "1.2.3.4.",
    "4294967295",
    "4294967296",
    "0300.0250.1.1",
    "0x",
    "08.1.1.1",
    "user@host",
    "a<b",
    "host.com:99999",
    "host.com:65535",
    "host.com:abc",
    "host.com:",
    "host:80",
    "[::1]:80",
    "xn--nxasmq6b.com",
    "\u00df.de",
    "a^b",
    "a|b",
    "\u00c9xample.com",
    "fa\u00df.de",
    "\u03a3\u0391\u03a3.gr",
    "a\u3002b",
    "\u2100.com",
    "\uff41\uff42\uff43.com",
    "\U0001f600.example",
    "a\x00b",
    "a\x7fb",
    "%00",
    "%",
    "-",
    "_",
    "localhost",
    "LOCALHOST",
    "foo.localhost",
]
_URL_TEMPLATES = [
    "https://{}/v1",
    "http://{}",
    "{}/v1",
    "https://u:p@{}/x",
    "https:{}",
    "https:///{}",
    "ftp://{}",
    "ws://{}:8080/",
    "custom://{}/a",
    "custom:{}",
    "//{}",
    "https://{}?x=1",
    "https://{}#f",
    "https:\\\\{}\\x",
    "file://{}/x",
    "  https://{}  ",
    "ht\ttps://{}",
    "{}:443/v1",
    "https://{}\n/x",
    "https://a@b@{}/",
    "https://{}@x.example/",
]


def test_real_openclaw_oracle_url_hostname_matches_python(oracle):
    texts = [template.format(host) for template in _URL_TEMPLATES for host in _URL_HOSTS]
    texts += [
        "",
        " ",
        "x",
        "http",
        "http:",
        "https://",
        "//",
        ":",
        "a:b",
        "1:2",
        "+x://h",
        "-x://h",
    ]
    cases = [{"fn": "hostname", "text": text} for text in texts]
    assert len(cases) >= 1000
    _compare_inline(oracle, cases)


# --- stableStringify (the measured-usage fingerprint input) -----------------------------------


def _stable_values() -> list[Any]:
    rng = random.Random(41)
    keys = [
        "a",
        "b",
        "B",
        "10",
        "9",
        chr(0xE9),
        chr(0xFFFF),
        chr(0x10000),
        chr(0x1F600),
        chr(0xD7FF),
        chr(0xE000),
        "",
        " ",
        "a b",
        '"',
        "\n",
    ]
    scalars: list[Any] = [
        None,
        True,
        False,
        0,
        1,
        -1,
        2**53 - 1,
        1.5,
        0.1,
        1e21,
        1e-7,
        1.5e-7,
        123456789.123456789,
        5e-324,
        1.7976931348623157e308,
        -0.0,
        0.000001,
        1e16,
        100.0,
        "",
        "x",
        "é\U0001f600",
        " ",
        "\x00\x1f",
        '"q"',
        "\\",
    ]

    def build(depth: int) -> Any:
        pick = rng.random()
        if depth > 3 or pick < 0.35:
            return rng.choice(scalars)
        if pick < 0.65:
            return [build(depth + 1) for _ in range(rng.randrange(0, 5))]
        return {rng.choice(keys): build(depth + 1) for _ in range(rng.randrange(0, 6))}

    return [build(0) for _ in range(400)] + scalars


def test_real_openclaw_oracle_stable_stringify_matches_python(oracle):
    values = _stable_values()
    cases = [{"fn": "stable", "value": value} for value in values]
    assert len(cases) >= 400
    _compare_inline(oracle, cases)


# --- recordResponsesContextUsage and normalizeAssistantReplayInput(fromResponse) ---------------
# ``recordResponsesContextUsage`` is the producer of the measured-usage state that
# ``resolveResponsesContextUsageBoundary`` consumes. The oracle runs it over generated target
# messages, wire requests (with and without a compaction item, a continuation id, instructions)
# and outputs; the saved ``openclawResponsesInputReplay`` must be equal, hashes included, which
# also runs the converter's replay output and ``normalizeAssistantReplayInput(.., true)`` over
# real tool-call arguments. The private normalizer is reached through a sibling copy of the
# continuation module and compared on its own with generated items and argument texts.

_RECORD_MODELS = ("responses", "azure", "transport", "responses_no_url")
_ARG_TEXTS = [
    '{"a":1}',
    "{}",
    '{ "a" : 1 }',
    '{"a":9007199254740993}',
    '{"a":-9007199254740993}',
    '{"a":9007199254740991}',
    '{"a":9007199254740992}',
    '{"a":12345678901234567890}',
    '{"a":1234567890123456}',
    '{"a":1.5e3,"b":1E2,"c":-0,"d":-0.0,"e":1e21,"f":1e-7,"g":0.1}',
    '{"a":[9007199254740993,{"b":18014398509481984}]}',
    '{"a":"9007199254740993"}',
    '{"a":9007199254740993.5}',
    '{"a":1,"a":2}',
    '{"b":1,"a":2,"10":3,"9":4}',
    "[1,2]",
    "5",
    "null",
    '"x"',
    "",
    "not json",
    '{"a":NaN}',
    '{"a":Infinity}',
    '{"a":1e999}',
    '{"a":-1e999}',
    '{"a":"\\ud83d"}',
    '{"a":"\\u00e9\\u0000\\n\\t"}',
    '{"a":1,}',
    '{"a":01}',
    '{"a":.5}',
    '{"a":1.}',
    '{"a":-}',
    '  {"a":1}  ',
    '{"a":true,"b":null,"c":false}',
    '{"k\\u00e9y":"v","\\ud83d\\ude00":1}',
    '{"a":"\\"9007199254740993\\""}',
    '{"a":{"b":{"c":[1,2,{"d":9007199254740993}]}}}',
    '{"a":-9007199254740992}',
    '{"a":123456789012345678901234567890.5}',
    '{"a":1e5,"b":1E+5,"c":1e-5}',
    '{"a":9007199254740993,"b":"x9007199254740993"}',
    '{"a":0.30000000000000004}',
    '{"a":100000000000000000000}',
    '{"a":4.9e-324}',
    '﻿{"a":1}',
    '{"a":1}{"b":2}',
    '{"a":[]}',
    '{"":1}',
]


def _arg_value(rng: random.Random) -> Any:
    return rng.choice(
        [
            *_ARG_TEXTS,
            {"a": 1},
            {},
            {"b": [1, 2, {"c": None}], "n": 1.5, "m": 1e21, "k": 100.0, "t": 2**53, "u": 1e20},
            {"10": 1, "9": 2, "a": 3},
            [1, 2],
            5,
            None,
            True,
        ]
    )


def _normalize_items(rng: random.Random, count: int) -> list[Any]:
    def part() -> Any:
        return rng.choice(
            [
                {"type": "output_text", "text": "a", "annotations": [{"x": 1}], "logprobs": []},
                {"type": "output_text", "text": "b", "annotations": [], "other": 1},
                {"type": "output_text", "text": "c"},
                {"type": "refusal", "refusal": "no", "annotations": []},
                {"type": "input_text", "text": "q", "annotations": [1]},
                "plain",
                None,
                5,
            ]
        )

    def item() -> Any:
        kind = rng.random()
        if kind < 0.3:
            call: dict[str, Any] = {
                "type": "function_call",
                "id": "fc_1",
                "status": "completed",
                "call_id": "call_1",
                "name": "read",
            }
            if rng.random() < 0.9:
                call["arguments"] = _arg_value(rng)
            if rng.random() < 0.3:
                del call["id"]
            return call
        if kind < 0.5:
            message: dict[str, Any] = {
                "type": "message",
                "role": rng.choice(["assistant", "assistant", "user", "developer"]),
                "id": "msg_1",
                "status": "completed",
                "content": rng.choice(
                    [[part() for _ in range(rng.randrange(0, 4))], "text", None, {"a": 1}]
                ),
            }
            return message
        if kind < 0.6:
            return {
                "type": "reasoning",
                "id": "rs_1",
                "status": "completed",
                "summary": [],
                "encrypted_content": "E",
            }
        if kind < 0.7:
            return {"type": "function_call_output", "call_id": "call_1", "output": "o"}
        if kind < 0.78:
            return {"type": "compaction", "encrypted_content": "ENC", "id": "cmp_1"}
        return rng.choice([None, "text", 5, [1, 2], {"role": "user"}, {}, True])

    return [item() for _ in range(count)]


def test_real_openclaw_oracle_normalize_assistant_replay_input_matches_python(oracle):
    rng = random.Random(4242)
    cases: list[dict[str, Any]] = []
    for index in range(1600):
        cases.append(
            {
                "fn": "normalizeReplayInput",
                "items": _normalize_items(rng, rng.randrange(0, 6)),
                "fromResponse": index % 2 == 0,
            }
        )
    for text in _ARG_TEXTS:
        for from_response in (True, False):
            cases.append(
                {
                    "fn": "normalizeReplayInput",
                    "items": [{"type": "function_call", "id": "x", "arguments": text}],
                    "fromResponse": from_response,
                }
            )
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = []
    for case in cases:
        try:
            value = cr.normalize_assistant_replay_input(
                _clean(case["items"]), case["fromResponse"]
            )
            error = None
        except Exception as exc:  # noqa: BLE001 - the oracle reports the class name
            value, error = None, type(exc).__name__
        python_rows.append({"value": value, "error": error})
    assert _first_diffs(cases, rows, python_rows) == []
    rewritten = [
        case
        for case, row in zip(cases, rows, strict=True)
        if case["fromResponse"]
        and row["error"] is None
        and any(
            isinstance(a, dict)
            and a.get("type") == "function_call"
            and isinstance(a.get("arguments"), str)
            and isinstance(b, dict)
            and b.get("arguments") != a["arguments"]
            for a, b in zip(case["items"], row["value"], strict=True)
        )
    ]
    assert len(rewritten) > 100


def test_real_openclaw_oracle_prefix_fingerprint_matches_python(oracle):
    rng = random.Random(777)
    cases: list[dict[str, Any]] = []
    for index in range(1200):
        case: dict[str, Any] = {
            "fn": "prefixFingerprint",
            "input": _normalize_items(rng, rng.randrange(0, 5)),
        }
        if index % 3:
            case["output"] = _normalize_items(rng, rng.randrange(0, 4))
        cases.append(case)
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = []
    for case in cases:
        try:
            value = cr.responses_continuation_prefix_fingerprint(
                _clean(case["input"]), _clean(case.get("output", []))
            )
            error = None
        except Exception as exc:  # noqa: BLE001
            value, error = None, type(exc).__name__
        python_rows.append({"value": value, "error": error})
    assert _first_diffs(cases, rows, python_rows) == []
    assert len({row["value"] for row in rows}) > 800


def _record_message(rng: random.Random, model: dict[str, Any]) -> dict[str, Any]:
    content: list[Any] = []
    for _ in range(rng.randrange(0, 4)):
        roll = rng.random()
        if roll < 0.4:
            block: dict[str, Any] = {"type": "text", "text": rng.choice(["A", "answer", "é\U0001f600"])}
            if rng.random() < 0.3:
                block["textSignature"] = json.dumps({"v": 1, "id": "msg_1", "phase": "final_answer"})
            content.append(block)
        elif roll < 0.6:
            content.append(
                {
                    "type": "thinking",
                    "thinking": "t",
                    "thinkingSignature": json.dumps(
                        {
                            "type": "reasoning",
                            "id": rng.choice(["rs_1", "rs_2"]),
                            "summary": [],
                            "encrypted_content": rng.choice(["ENC", "ENC2", ""]),
                            "status": "completed",
                        }
                    ),
                }
            )
        else:
            content.append(
                {
                    "type": "toolCall",
                    "id": rng.choice(["call_1|fc_1", "call_2", "call_3|fc_3"]),
                    "name": "read",
                    "arguments": rng.choice(
                        [
                            {"p": 1},
                            {},
                            {"n": 1.5, "m": 1e21, "k": 100.0, "t": 2**53, "u": 1e20},
                            {"10": 1, "9": 2, "a": [1, {"b": None}]},
                            "raw",
                            [1],
                            None,
                        ]
                    ),
                }
            )
    message = _wire_assistant(model, content)
    usage_roll = rng.random()
    if usage_roll < 0.62:
        state = {"state": "available", "totalTokens": rng.choice([100, 12345])}
        if rng.random() < 0.8:
            state["promptTokens"] = rng.choice([90, 0, 5])
        elif rng.random() < 0.3:
            state["promptTokens"] = None
        message["usage"]["contextUsage"] = state
    elif usage_roll < 0.7:
        message["usage"]["contextUsage"] = {
            "state": "available",
            "totalTokens": rng.choice([0, -5, 1.5, "100", None, 2**53, 2**53 - 1]),
            "promptTokens": 1,
        }
    elif usage_roll < 0.8:
        message["usage"]["contextUsage"] = {"state": rng.choice(["unavailable", "stale", 5, None])}
    elif usage_roll < 0.9:
        message["usage"]["contextUsage"] = rng.choice([None, "x", 5, [], {}])
    elif usage_roll < 0.95:
        message["usage"].pop("contextUsage", None)
    else:
        del message["usage"]
    roll = rng.random()
    if roll < 0.12:
        message["stopReason"] = rng.choice(["error", "aborted"])
    elif roll < 0.2:
        message["stopReason"] = rng.choice(["length", "toolUse", "other", None])
    if rng.random() < 0.12:
        message["providerReplay"] = rng.choice([{"v": 1}, {}, 0, "", None, "x"])
    roll = rng.random()
    if roll < 0.15:
        message["openclawResponsesInputReplay"] = rng.choice(
            [
                {},
                {"afterResponseId": "r1"},
                {"contextUsage": {"old": 1}, "afterResponseId": "r2"},
                "string",
                [],
                None,
                5,
            ]
        )
    return message


def _record_request(rng: random.Random) -> dict[str, Any]:
    def item(kind: float) -> Any:
        if kind < 0.2:
            return {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": rng.choice(["q", "é\U0001f600"])}],
            }
        if kind < 0.3:
            return {"type": "message", "role": rng.choice(["developer", "system"]), "content": "sys"}
        if kind < 0.45:
            return {
                "type": "reasoning",
                "id": "rs_1",
                "status": "completed",
                "summary": [],
                "encrypted_content": rng.choice(["ENC", "ENC2"]),
            }
        if kind < 0.55:
            return {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "read",
                "arguments": rng.choice(['{"a":1}', '{"a":9007199254740993}', "{}", "bad"]),
            }
        if kind < 0.65:
            return {"type": "function_call_output", "call_id": "call_1", "output": "o"}
        if kind < 0.75:
            return {
                "type": "message",
                "role": "assistant",
                "id": "msg_1",
                "status": "completed",
                "content": [{"type": "output_text", "text": "a", "annotations": [{"k": 1}]}],
            }
        return rng.choice(["text", None, 5, {}])

    items = [item(rng.random()) for _ in range(rng.randrange(0, 5))]
    if rng.random() < 0.85:
        items.insert(
            rng.randrange(0, len(items) + 1), {"type": "compaction", "encrypted_content": "ENC"}
        )
    if rng.random() < 0.45 and items:
        items.insert(
            0, {"type": "message", "role": rng.choice(["developer", "system", "user"]), "content": "s"}
        )
    request: dict[str, Any] = {"input": items}
    roll = rng.random()
    if roll < 0.04:
        request["input"] = rng.choice(["text", None, {"a": 1}])
    if rng.random() < 0.3:
        request["instructions"] = rng.choice(["be brief", None, ""])
    if rng.random() < 0.1:
        request["previous_response_id"] = rng.choice(["resp_1", "", None])
    if rng.random() < 0.3:
        request["model"] = "x"
    return request


def _record_output(rng: random.Random) -> Any:
    roll = rng.random()
    if roll < 0.05:
        return rng.choice([None, "x", {"a": 1}])
    if roll < 0.12:
        return [{"type": "compaction", "encrypted_content": "N"}]
    return rng.choice(
        [
            [],
            [{"type": "message", "role": "assistant", "content": []}],
            [{"type": "function_call", "call_id": "c", "name": "n", "arguments": "{}"}],
            [None, "x", 5],
        ]
    )


def _record_cases(seed: int, count: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    cases = []
    for _ in range(count):
        model = MODELS[rng.choice(_RECORD_MODELS)]
        identity = IDENTS[rng.choice(["none", "session", "both", "unicode"])]
        cases.append(
            {
                "fn": "recordContextUsage",
                "messages": [_wire_user("q"), _record_message(rng, model)],
                "target": 1,
                "model": model,
                "identity": identity,
                "request": _record_request(rng),
                "output": _record_output(rng),
                "projection": rng.choice(["transport", "provider"]),
            }
        )
    return cases


def _python_record(case: dict[str, Any]) -> dict[str, Any]:
    messages = _clean(case["messages"])
    target = messages[case["target"]]
    try:
        cr.record_responses_context_usage(
            target,
            _py_model(case["model"]),
            _py_identity(case["identity"]),
            _clean(case["request"]),
            _clean(case["output"]),
            case["projection"],
        )
        value = _clean(target.get("openclawResponsesInputReplay"))
        error = None
    except Exception as exc:  # noqa: BLE001 - the oracle reports the class name
        value, error = None, type(exc).__name__
    return {"value": value, "error": error}


def test_real_openclaw_oracle_record_responses_context_usage_matches_python(oracle):
    cases = _record_cases(515, 3000)
    rows = _run_op(oracle, "compactionCheckpoint", cases)
    python_rows = [_python_record(case) for case in cases]
    assert _first_diffs(cases, rows, python_rows) == []
    recorded = [
        row
        for row in rows
        if row["error"] is None
        and isinstance(row["value"], dict)
        and isinstance(row["value"].get("contextUsage"), dict)
        and "prefixHash" in row["value"]["contextUsage"]
    ]
    skipped = [row for row in rows if row["error"] is None and row not in recorded]
    assert len(recorded) > 500
    assert len(skipped) > 500
    assert {row["error"] for row in rows} <= {None, "TypeError"}
    assert len({row["value"]["contextUsage"]["prefixHash"] for row in recorded}) > 200
    states = [row["value"]["contextUsage"] for row in recorded]
    assert {state["includeSystemPrompt"] for state in states} == {True, False}
    assert {state["projection"] for state in states} == {"transport", "provider"}


def test_record_responses_context_usage_gates_and_state_shape():
    from memory_core import responses_converter as rc

    model = MODELS["responses"]
    identity = cr.ReplayIdentity("s1", "a1")
    user = _wire_user("q")
    target = _wire_assistant(model, [{"type": "text", "text": "answer"}])
    target["usage"]["contextUsage"] = {"state": "available", "promptTokens": 90, "totalTokens": 100}
    py_model = _py_model(model)
    before = rc.convert_responses_messages(
        py_model, [user], None, session_id="s1", auth_profile_id="a1", include_system_prompt=False
    )
    request = {"input": [{"type": "compaction", "encrypted_content": "E"}, *before]}
    cr.record_responses_context_usage(target, py_model, identity, request, [], "transport")
    state = target["openclawResponsesInputReplay"]["contextUsage"]
    assert state["prefixLength"] == 2 + 1
    assert (state["promptTokens"], state["totalTokens"], state["projection"]) == (90, 100, "transport")
    assert state["includeSystemPrompt"] is False
    assert cr.is_openai_responses_replay_context(state)
    # A continuation, a failed turn, a compaction in the output and a request without a
    # compaction item record nothing.
    for mutate in (
        lambda m, r: r.update(previous_response_id="resp_1"),
        lambda m, r: m.update(stopReason="error"),
        lambda m, r: m.update(providerReplay={"v": 1}),
        lambda m, r: r.update(input=before),
    ):
        fresh = copy.deepcopy(target)
        fresh.pop("openclawResponsesInputReplay")
        req = copy.deepcopy(request)
        mutate(fresh, req)
        cr.record_responses_context_usage(fresh, py_model, identity, req, [], "transport")
        assert "openclawResponsesInputReplay" not in fresh
    fresh = copy.deepcopy(target)
    fresh.pop("openclawResponsesInputReplay")
    cr.record_responses_context_usage(
        fresh, py_model, identity, request, [{"type": "compaction"}], "transport"
    )
    assert "openclawResponsesInputReplay" not in fresh
