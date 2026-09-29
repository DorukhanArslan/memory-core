"""TurnState and ResetTurn as JSON: a turn in flight across steps (docs/host_kit.md, F2, F3)."""

from __future__ import annotations

import json

import pytest

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, ResetTurn, SessionState, TurnState

NOW_MS = 1_790_375_400_000  # 2026-09-25 22:30 UTC


def _kit(root) -> HostKit:
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False)
    kit = HostKit(memory, now_ms=lambda: NOW_MS)
    kit.ensure()
    return kit


def _session() -> SessionState:
    return SessionState(
        session_key="agent:main:main",
        session_id="s1",
        entry={"sessionId": "s1", "compactionCount": 1, "totalTokens": 900},
        last_output_tokens=12,
        seen_truncation_signatures=("sig",),
        completed_bootstrap_turn=True,
    )


def _reset() -> ResetTurn:
    return ResetTurn(
        model_prompt="startup context\n\nthe reset prompt",
        transcript_prompt="[memory-core session new]",
        bootstrap_mode="none",
        startup_context="startup context",
        prompt="the reset prompt",
    )


def _turn(tmp_path, **options) -> TurnState:
    context = _kit(tmp_path).before_turn(_session(), runtime_context="Channel: terminal")
    return TurnState.from_context(context, **options)


def test_turn_state_from_context_keeps_what_later_steps_need(tmp_path):
    context = _kit(tmp_path).before_turn(_session(), runtime_context="Channel: terminal")

    turn = TurnState.from_context(context)

    assert (turn.session, turn.system_prompt, turn.runtime_context, turn.tools) == (
        context.session,
        context.system_prompt,
        context.runtime_context,
        context.tools,
    )
    assert turn.reset is None
    assert turn.system_prompt.startswith("## Memory Recall")
    assert "Channel: terminal" in turn.runtime_context
    assert [tool["name"] for tool in turn.tools][:2] == ["memory_search", "memory_get"]


def test_turn_state_round_trips_json(tmp_path):
    turn = _turn(tmp_path)

    data = turn.to_json()

    assert data == {
        "session": turn.session.to_json(),
        "systemPrompt": turn.system_prompt,
        "runtimeContext": turn.runtime_context,
        "tools": [dict(tool) for tool in turn.tools],
        "reset": None,
    }
    assert TurnState.from_json(data) == turn


def test_turn_state_survives_json_text(tmp_path):
    turn = _turn(tmp_path, reset=_reset())

    restored = TurnState.from_json(json.loads(json.dumps(turn.to_json())))

    assert restored == turn
    assert restored.session.entry == turn.session.entry


def test_turn_state_carries_the_reset_turn(tmp_path):
    turn = _turn(tmp_path, reset=_reset())

    data = turn.to_json()

    assert data["reset"] == {
        "modelPrompt": "startup context\n\nthe reset prompt",
        "transcriptPrompt": "[memory-core session new]",
        "bootstrapMode": "none",
        "startupContext": "startup context",
        "prompt": "the reset prompt",
    }
    assert TurnState.from_json(data).reset == _reset()


def test_turn_state_tools_are_private_copies(tmp_path):
    context = _kit(tmp_path).before_turn(_session())
    turn = TurnState.from_context(context)

    turn.to_json()["tools"][0]["name"] = "changed"
    data = turn.to_json()
    data["tools"][0]["parameters"]["properties"].clear()

    assert turn.tools == context.tools
    assert turn.tools[0] is not context.tools[0]
    assert turn.tools[0]["parameters"]["properties"]
    assert TurnState.from_json(data).tools[0]["parameters"]["properties"] == {}


def test_turn_state_rejects_a_field_of_the_wrong_type(tmp_path):
    turn = _turn(tmp_path)
    good = {
        "session": turn.session,
        "system_prompt": turn.system_prompt,
        "runtime_context": turn.runtime_context,
        "tools": turn.tools,
    }
    bad = [
        {"session": turn.session.to_json()},
        {"system_prompt": None},
        {"runtime_context": 3},
        {"tools": ["memory_search"]},
        {"reset": {"modelPrompt": "x"}},
    ]

    for change in bad:
        with pytest.raises(TypeError):
            TurnState(**{**good, **change})


@pytest.mark.parametrize(
    "change",
    [
        "not an object",
        {"session": None},
        {"session": {"sessionKey": "k", "sessionId": 7}},
        {"systemPrompt": None},
        {"runtimeContext": 3},
        {"tools": "memory_search"},
        {"tools": ["memory_search"]},
        {"reset": "the reset prompt"},
        {"reset": {"modelPrompt": "x"}},
        {"drop": "session"},
        {"drop": "systemPrompt"},
        {"drop": "tools"},
    ],
    ids=repr,
)
def test_turn_state_from_json_rejects_a_bad_shape(tmp_path, change):
    good = _turn(tmp_path, reset=_reset()).to_json()
    if change == "not an object":
        data = [good]
    elif "drop" in change:
        data = {key: value for key, value in good.items() if key != change["drop"]}
    else:
        data = {**good, **change}

    with pytest.raises(ValueError):
        TurnState.from_json(data)


def test_turn_state_from_json_reads_missing_optional_keys_as_null_and_ignores_unknown_keys(
    tmp_path,
):
    turn = _turn(tmp_path)
    data = {
        key: value for key, value in turn.to_json().items() if key not in ("runtimeContext", "reset")
    }

    restored = TurnState.from_json({**data, "addedLater": {"any": "value"}})

    assert restored.runtime_context is None
    assert restored.reset is None
    assert (restored.session, restored.system_prompt, restored.tools) == (
        turn.session,
        turn.system_prompt,
        turn.tools,
    )


def test_reset_turn_round_trips_json():
    reset = _reset()
    without_startup = ResetTurn(
        model_prompt="the reset prompt",
        transcript_prompt="[memory-core session reset]",
        bootstrap_mode="full",
        startup_context=None,
        prompt="the reset prompt",
    )

    assert ResetTurn.from_json(json.loads(json.dumps(reset.to_json()))) == reset
    assert ResetTurn.from_json(without_startup.to_json()) == without_startup
    data = without_startup.to_json()
    del data["startupContext"]
    assert ResetTurn.from_json({**data, "addedLater": 1}) == without_startup


@pytest.mark.parametrize(
    "change",
    [
        {"bootstrapMode": "partial"},
        {"bootstrapMode": None},
        {"modelPrompt": None},
        {"transcriptPrompt": 5},
        {"prompt": ["the reset prompt"]},
        {"startupContext": 1},
        {"drop": "modelPrompt"},
        {"drop": "transcriptPrompt"},
        {"drop": "bootstrapMode"},
        {"drop": "prompt"},
    ],
    ids=repr,
)
def test_reset_turn_from_json_rejects_a_bad_shape(change):
    good = _reset().to_json()
    if "drop" in change:
        data = {key: value for key, value in good.items() if key != change["drop"]}
    else:
        data = {**good, **change}

    with pytest.raises(ValueError):
        ResetTurn.from_json(data)
    with pytest.raises(ValueError):
        ResetTurn.from_json("not an object")
