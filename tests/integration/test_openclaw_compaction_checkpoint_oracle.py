"""Compaction checkpoint resolvers and inbound-metadata helpers against the real v2026.9.6 TS.

``resolveCompactionSource`` is private upstream; it is reached through
``requiresCompactionReplayRefresh`` and ``preserveCompactionReplayWindow``, with the Anthropic and
Responses newest-checkpoint resolvers and the two replay-plan builders compared directly. The
provider replay context hashes (``shortHash``) used to build the fixtures' checkpoint states come
from the TS oracle itself, so a hash bug cannot hide behind a self-consistent fixture.

Model identity, session and auth identity are plain parameters on the Python side. The Responses
compact-endpoint egress projection (image sanitiser plus payload policy) is a host hook in Python,
so every window fixture uses a native OpenAI route and https/file image references, where that
projection is the identity upstream.
"""

from __future__ import annotations

import copy
import itertools
import json
import os
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
