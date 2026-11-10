"""Adversarial replays of actual paired natural-host captures.

The explicit development-002 captures were produced by the pinned native runtime
and the real SDK host. A labelled byte-copy replay cache may retain that same
version. Missing captures skip these tests without any acceptance credit; an
existing invalid capture fails. No native execution or repaired happy output is
created here, and the rejected development-001 captures are never loaded.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat

import pytest

from equivalence.host_turn_barrier import build_cases
from equivalence.host_turn_barrier_evidence import validate_pair

ROOT = Path(__file__).resolve().parents[2]
CASES = build_cases()
RETAINED = (
    ROOT / ".equivalence-results/host-turn-barrier/replay-outcomes-v2",
    ROOT / "work/host-turn-barrier/attempt-002-development",
)


def _load(case):
    for root in RETAINED:
        directory = root / case["id"]
        files = [directory / name for name in
                 ("evidence/native-raw.json", "evidence/python-raw.json", "stdout.json", "sdk-output.json")]
        if not all(path.is_file() for path in files):
            continue
        for path in files:
            info = path.lstat()
            assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1, path
        native, sdk, original, python = [json.loads(path.read_text()) for path in files]
        assert len(native) == len(sdk) == 1
        assert original["ok"] is True and original["id"] == case["id"]
        pair = (case, native[0], sdk[0], original["result"], python)
        # Tamper tests must begin with a genuinely valid actual capture.
        assert validate_pair(*pair) is True
        assert original["result"] == python
        return pair
    pytest.skip("No retained development-002 or labelled byte-copy natural-host pair; "
                "missing native captures grant no acceptance credit")


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def actual_pair(request):
    return _load(request.param)


def _turn(raw, label):
    return next(turn for turn in raw["turns"] if turn["label"] == label)


def _sdk_raw(pair):
    return pair[2]["observation"]["raw"]


def _read_label(case):
    return "warmup-recall" if case["input"]["initialState"] == "warm" else "followup"


def _replace(root, old, new):
    """Keep the edited message's model-input copies coherent, not its real tool events."""
    if isinstance(root, dict):
        for key, value in list(root.items()):
            if value == old:
                root[key] = deepcopy(new)
            else:
                _replace(value, old, new)
    elif isinstance(root, list):
        for index, value in enumerate(root):
            if value == old:
                root[index] = deepcopy(new)
            else:
                _replace(value, old, new)


def _seal_sdk(pair):
    pair[2]["stdout"] = json.dumps(pair[2]["observation"], ensure_ascii=False)


def _assert_rejected(pair, message):
    with pytest.raises(ValueError, match=message):
        validate_pair(*pair)


def _move_event_before(events, name, target):
    selected = [row for row in events if row["event"] == name]
    assert len(selected) == 1
    row, = selected
    events.remove(row)
    position = next(index for index, item in enumerate(events) if item["event"] == target)
    row["atNs"] = events[position]["atNs"]
    events.insert(position, row)
    for sequence, item in enumerate(events, 1):
        item["sequence"] = sequence


def test_actual_complete_pair_validates_without_a_fixture_publication_barrier(actual_pair):
    case, native, sdk, original, python = actual_pair
    assert validate_pair(*actual_pair) is True and original == python
    assert case["covers"] == ["host.turn-barrier.outcomes"]
    assert case["input"]["followupTrigger"]["interveningHostActions"] == []
    assert native["resolvedMemorySearch"]["sync"]["onSearch"] is True
    assert native["resolvedMemorySearch"]["sync"]["watch"] is True
    assert sdk["observation"]["raw"]["ownerPolicy"] == "on-search"
    if case["input"]["initialState"] == "cold":
        assert original["warmup"] is None and original["followup"]["search"]["results"]
    else:
        assert original["warmup"]["search"]["results"]
        # This is the measured old-generation answer, not a fresh-recall guarantee.
        assert original["followup"]["search"]["results"] == []
        assert case["input"]["save"]["text"] in original["source"]["text"]


@pytest.mark.parametrize("attack", [
    "missing-start", "missing-result", "same-start-result-sequence", "wrong-tool", "wrong-arguments", "error-result",
])
def test_original_producer_needs_its_actual_dispatch_start_and_result(actual_pair, attack):
    pair = deepcopy(actual_pair)
    turn = _turn(pair[1], "save")
    call_id = turn["toolCalls"][0]["id"]
    events = [row for row in turn["toolEvents"] if row.get("stream") == "tool"
              and row["data"].get("toolCallId") == call_id]
    start = next(row for row in events if row["data"]["phase"] == "start")
    end = next(row for row in events if row["data"]["phase"] == "result")
    if attack == "missing-start":
        turn["toolEvents"].remove(start)
    elif attack == "missing-result":
        turn["toolEvents"].remove(end)
    elif attack == "same-start-result-sequence":
        end["seq"] = start["seq"]
    elif attack == "wrong-tool":
        start["data"]["name"] = end["data"]["name"] = "edit"
    elif attack == "wrong-arguments":
        start["data"]["args"]["path"] = "USER.md"
    else:
        end["data"]["isError"] = True
    _assert_rejected(pair, "actual original start/result")


@pytest.mark.parametrize("attack", ["missing-start", "wrong-parent", "wrong-arguments", "detached-result"])
def test_deferred_search_needs_the_real_nested_memory_owner(actual_pair, attack):
    pair = deepcopy(actual_pair)
    turn = _turn(pair[1], _read_label(pair[0]))
    start = next(row for row in turn["toolEvents"] if row.get("stream") == "tool"
                 and row["data"].get("phase") == "start" and row["data"].get("name") == "memory_search")
    if attack == "missing-start":
        turn["toolEvents"].remove(start)
    elif attack == "wrong-parent":
        start["data"]["parentToolCallId"] = "anotherActualCall"
    elif attack == "wrong-arguments":
        start["data"]["args"]["query"] = "an unrelated query"
    else:
        end = next(row for row in turn["toolEvents"] if row.get("stream") == "tool"
                   and row["data"].get("phase") == "result"
                   and row["data"].get("toolCallId") == start["data"]["toolCallId"])
        end["data"]["result"] = {"content": [], "details": {"results": []}}
    _assert_rejected(pair, "nested original memory owner|actual nested dispatch result")


@pytest.mark.parametrize("attack", ["wrong-carrier-call", "missing-next-input", "different-tool", "inconsistent-details"])
def test_native_reply_consumes_the_complete_actual_model_carrier(actual_pair, attack):
    pair = deepcopy(actual_pair)
    turn = _turn(pair[1], _read_label(pair[0]))
    carrier = turn["searchCarrier"]
    if attack == "wrong-carrier-call":
        carrier["toolCallId"] = "unrelatedCall"
        message = "actual deferred-tool carrier"
    elif attack == "missing-next-input":
        call = turn["toolCalls"][0]
        turn["modelCalls"][call["modelCall"] + 1]["context"]["messages"].remove(carrier)
        message = "following actual model input"
    else:
        old = deepcopy(carrier)
        wrapped = json.loads(carrier["content"][0]["text"])
        if attack == "different-tool":
            wrapped["tool"]["name"] = "memory_get"
            message = "returned another tool"
        else:
            wrapped["result"]["details"]["provider"] = "invented-provider"
            message = "details differ from their visible JSON"
        carrier["content"][0]["text"] = json.dumps(wrapped, ensure_ascii=False)
        _replace(turn["modelCalls"], old, carrier)
    _assert_rejected(pair, message)


def test_native_get_arguments_come_from_the_actual_first_search_hit(actual_pair):
    pair = deepcopy(actual_pair)
    turn = _turn(pair[1], _read_label(pair[0]))
    call = turn["toolCalls"][1]
    old = deepcopy({key: value for key, value in call.items() if key != "modelCall"})
    call["arguments"]["args"]["from"] += 1
    new = {key: value for key, value in call.items() if key != "modelCall"}
    _replace(turn["modelCalls"][call["modelCall"]]["reply"]["content"], old, new)
    turn["selectedGetArguments"]["from"] += 1
    _assert_rejected(pair, "get range was not selected")


@pytest.mark.parametrize("attack", ["supplied-operation", "disabled-maintenance", "different-workspace", "wrong-source"])
def test_real_full_caller_and_actual_corpus_cannot_be_substituted(actual_pair, attack):
    pair = deepcopy(actual_pair)
    native = pair[1]
    turn = _turn(native, "save")
    if attack == "supplied-operation":
        turn["callInput"]["replyOperation"] = {"label": "fixture supplied admission"}
        message = "admission was bypassed"
    elif attack == "disabled-maintenance":
        native["config"]["agents"]["defaults"]["compaction"]["enabled"] = False
        message = "cannot disable optional maintenance"
    elif attack == "different-workspace":
        turn["callInput"]["followupRun"]["run"]["workspaceDir"] = "/another/workspace"
        turn["followupRun"] = deepcopy(turn["callInput"]["followupRun"])
        message = "full-host model request changed"
    else:
        turn["after"]["source"]["text"] += "invented fact"
        message = "committed source or delivered native reply"
    _assert_rejected(pair, message)


@pytest.mark.parametrize("attack", ["outside-workspace", "changed-inode", "before-result", "after-terminal"])
def test_native_metadata_is_owned_and_occurs_inside_the_actual_producer_callback(actual_pair, attack):
    pair = deepcopy(actual_pair)
    native = pair[1]
    receipt = next(row for row in native["metadataOperations"] if row["turn"] == "save")
    if attack == "outside-workspace":
        receipt["before"]["absolutePath"] = receipt["after"]["absolutePath"] = "/another/MEMORY.md"
        receipt["arguments"][0] = "/another/MEMORY.md"
    elif attack == "changed-inode":
        receipt["after"]["ino"] += 1
    elif attack == "before-result":
        tool_id = _turn(native, "save")["toolCalls"][0]["id"]
        event = next(row for row in native["events"] if row["event"] == "actual-agent-event"
            and row["observation"].get("stream") == "tool"
            and row["observation"]["data"].get("phase") == "result"
            and row["observation"]["data"].get("toolCallId") == tool_id)
        receipt["startedAtNs"] = event["atNs"]
    else:
        returned = next(row for row in native["events"] if row["event"] == "actual-host-return" and row["turn"] == "save")
        receipt["startedAtNs"] = receipt["finishedAtNs"] = str(int(returned["atNs"]) + 1)
    _assert_rejected(pair, "metadata fixture escaped")


def test_native_teardown_join_cannot_supply_a_pre_read_barrier(actual_pair):
    pair = deepcopy(actual_pair)
    rows = pair[1]["events"]
    joins = [row for row in rows if row["event"].startswith("teardown-maintenance-join-")]
    assert len(joins) == 2
    for row in joins:
        rows.remove(row)
    position = next(index for index, row in enumerate(rows) if row["event"] == "public-outcome-fixed")
    for offset, row in enumerate(joins):
        row["atNs"] = rows[position]["atNs"]
        rows.insert(position + offset, row)
    for sequence, row in enumerate(rows, 1):
        row["sequence"] = sequence
    _assert_rejected(pair, "maintenance wait was inserted")


@pytest.mark.parametrize("attack", ["pid", "ppid", "argv", "environment", "stdin-hash", "different-input", "stdout", "duration"])
def test_sdk_child_and_both_process_carriers_remain_bound_to_the_actual_input(actual_pair, attack):
    pair = deepcopy(actual_pair)
    dispatch, raw = pair[2], _sdk_raw(pair)
    if attack == "pid":
        dispatch["pid"] += 1
        message = "actual process or owner"
    elif attack == "ppid":
        raw["ppid"] += 1
        message = "actual process or owner"
    elif attack == "argv":
        dispatch["argv"][-1] = "equivalence.host_update_isolation_phase_cli"
        message = "protected input carrier"
    elif attack == "environment":
        dispatch["environmentKeys"].append("UNDECLARED_KEY")
        message = "protected input carrier"
    elif attack == "stdin-hash":
        dispatch["requestJson"] += " "
        message = "protected input carrier"
    elif attack == "different-input":
        dispatch["request"]["input"]["nowMs"] += 1
        dispatch["requestJson"] = json.dumps(dispatch["request"])
        dispatch["requestSha256"] = hashlib.sha256(dispatch["requestJson"].encode()).hexdigest()
        message = "protected input carrier"
    elif attack == "stdout":
        observation = deepcopy(dispatch["observation"])
        observation["result"]["provider"] = "invented"
        dispatch["stdout"] = json.dumps(observation)
        message = "stdout differs"
    else:
        dispatch["finishedAtNs"] = dispatch["startedAtNs"]
        message = "process dispatch failed"
    if attack != "stdout":
        _seal_sdk(pair)
    _assert_rejected(pair, message)


@pytest.mark.parametrize("field,raw_field", [("pid", "pid"), ("coordinatorPid", "ppid")])
@pytest.mark.parametrize("invalid", [True, 0, -1])
def test_sdk_process_identities_are_strict_positive_integers(actual_pair, field, raw_field, invalid):
    pair = deepcopy(actual_pair)
    pair[2][field] = invalid
    _sdk_raw(pair)[raw_field] = invalid
    _seal_sdk(pair)
    _assert_rejected(pair, "process|dispatch")


def test_sdk_child_cannot_be_its_own_parent(actual_pair):
    pair = deepcopy(actual_pair)
    pair[2]["pid"] = pair[2]["coordinatorPid"]
    _sdk_raw(pair)["pid"] = pair[2]["pid"]
    _seal_sdk(pair)
    _assert_rejected(pair, "process|dispatch")


@pytest.mark.parametrize("engine", ["native", "sdk"])
def test_fixed_input_booleans_cannot_be_reassigned_as_equal_python_numbers(actual_pair, engine):
    pair = deepcopy(actual_pair)
    changed = deepcopy(pair[0]["input"])
    assert changed["policy"]["sessionMemory"] is False
    changed["policy"]["sessionMemory"] = 0
    if engine == "native":
        pair[1]["input"] = deepcopy(changed)
        pair[1]["request"] = deepcopy(changed)
    else:
        pair[2]["input"] = deepcopy(changed)
        pair[2]["request"]["input"] = deepcopy(changed)
        _sdk_raw(pair)["input"] = deepcopy(changed)
        pair[2]["requestJson"] = json.dumps(pair[2]["request"])
        pair[2]["requestSha256"] = hashlib.sha256(pair[2]["requestJson"].encode()).hexdigest()
        _seal_sdk(pair)
    _assert_rejected(pair, "input|literal|carrier")


@pytest.mark.parametrize("attack", ["missing-result-input", "changed-return", "changed-get-range", "not-admitted", "not-committed", "terminal-text", "payload"])
def test_sdk_dispatch_and_terminal_reply_use_actual_model_messages(actual_pair, attack):
    pair = deepcopy(actual_pair)
    raw = _sdk_raw(pair)
    label = _read_label(pair[0])
    turn = _turn(raw, label)
    if attack == "missing-result-input":
        turn["modelCalls"][1]["messages"].remove(turn["toolCalls"][0]["observed"]["message"])
        message = "actual dispatch and model-visible payload differ"
    elif attack == "changed-return":
        turn["toolCalls"][0]["returned"]["provider"] = "invented"
        message = "actual dispatch and model-visible payload differ"
    elif attack == "changed-get-range":
        call = turn["toolCalls"][1]
        old = deepcopy(call["assistant"])
        call["arguments"]["from"] += 1
        call["assistant"]["content"][0]["arguments"] = deepcopy(call["arguments"])
        _replace(turn["modelCalls"], old, call["assistant"])
        message = "source read did not follow its actual search"
    elif attack == "not-admitted":
        turn["outcome"]["transcript_committed"] = False
        message = "not actually admitted and completed"
    elif attack == "not-committed":
        _turn(raw, "save")["outcome"]["memory_writes_committed"] = False
        message = "producer did not actually commit"
    elif attack == "terminal-text":
        old = deepcopy(turn["terminalMessage"])
        turn["terminalMessage"]["content"][0]["text"] += " invented answer"
        _replace(turn["terminalInput"], old, turn["terminalMessage"])
        message = "terminal reply or saved source was replaced"
    else:
        turn["outcome"]["payloads"] = []
        message = "terminal reply or saved source was replaced"
    _seal_sdk(pair)
    _assert_rejected(pair, message)


@pytest.mark.parametrize("attack", ["outside-workspace", "changed-inode", "changed-device", "before-result", "changed-bytes"])
def test_sdk_metadata_is_owned_byte_preserving_and_inside_the_real_callback(actual_pair, attack):
    pair = deepcopy(actual_pair)
    raw = _sdk_raw(pair)
    operation = next(row for row in raw["metadata"] if row["label"] == "save")
    message = "metadata fixture escaped"
    if attack == "outside-workspace":
        operation["path"] = "/another/MEMORY.md"
    elif attack == "changed-inode":
        operation["after"]["stat"]["ino"] += 1
    elif attack == "changed-device":
        operation["after"]["stat"]["dev"] += 1
    elif attack == "before-result":
        event = next(row for row in raw["events"] if row["event"] == "tool-result" and row["label"] == "save")
        operation["startedAtNs"] = event["atNs"]
    else:
        operation["after"]["source"]["text"] += "changed by fixture"
        message = "metadata fixture changed bytes"
    _seal_sdk(pair)
    _assert_rejected(pair, message)


def test_sdk_close_cannot_be_moved_before_the_compared_followup(actual_pair):
    pair = deepcopy(actual_pair)
    _move_event_before(_sdk_raw(pair)["events"], "close-call", "host-call")
    _seal_sdk(pair)
    _assert_rejected(pair, "close was used as a pre-read barrier")


@pytest.mark.parametrize("field", ["debug", "provenance", "score", "reply-flags"])
def test_complete_public_fields_cannot_be_dropped_or_repaired_even_on_both_sides(actual_pair, field):
    pair = deepcopy(actual_pair)
    key = "warmup" if pair[0]["input"]["initialState"] == "warm" else "followup"
    for result in (pair[3], pair[4]):
        public = result[key]
        if field == "debug":
            del public["search"]["debug"]["managerMs"]
        elif field == "provenance":
            del public["search"]["results"][0]["provenance"]
        elif field == "score":
            public["search"]["results"][0]["score"] += 1e-9
        else:
            public["reply"]["audioAsVoice"] = 0
    pair[1]["result"] = deepcopy(pair[3])
    pair[2]["observation"]["result"] = deepcopy(pair[4])
    _sdk_raw(pair)["result"] = deepcopy(pair[4])
    _seal_sdk(pair)
    _assert_rejected(pair, "dropped or repaired native fields|complete actual host reply")


@pytest.mark.parametrize("field", ["hits", "managerMs", "withheldHits"])
def test_complete_public_numbers_cannot_be_coerced_to_equal_python_booleans(actual_pair, field):
    pair = deepcopy(actual_pair)
    key = "warmup" if pair[0]["input"]["initialState"] == "warm" else "followup"
    for result in (pair[3], pair[4]):
        original = result[key]["search"]["debug"][field]
        assert original in (0, 1) and type(original) is int
        result[key]["search"]["debug"][field] = bool(original)
    pair[1]["result"] = deepcopy(pair[3])
    pair[2]["observation"]["result"] = deepcopy(pair[4])
    _sdk_raw(pair)["result"] = deepcopy(pair[4])
    _seal_sdk(pair)
    _assert_rejected(pair, "dropped or repaired native fields|search|payload")


def test_saved_source_is_bound_to_the_original_frozen_corpus(actual_pair):
    pair = deepcopy(actual_pair)
    for result in (pair[3], pair[4]):
        result["source"]["text"] += "an invented saved fact"
        result["source"]["hex"] = result["source"]["text"].encode().hex()
    pair[1]["result"] = deepcopy(pair[3])
    pair[2]["observation"]["result"] = deepcopy(pair[4])
    _sdk_raw(pair)["result"] = deepcopy(pair[4])
    _seal_sdk(pair)
    _assert_rejected(pair, "detached from its saved corpus")
