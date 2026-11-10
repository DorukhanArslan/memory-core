"""Adversarial replays of genuine captures of the six frozen boundary inputs.

These tests never hand-build a successful host capture. Native tests discover
retained executions of the exact current literal; SDK fixtures run the real six
hosts. Every baseline first validates its custody. Missing Native captures skip
replay without credit; an invalid selected capture fails. Development inputs
are distinct.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat

import pytest

from equivalence.host_turn_barrier_boundaries import build_cases


ROOT = Path(__file__).resolve().parents[2]
CASES = build_cases()
RETAINED = (
    ROOT / ".equivalence-results/host-turn-barrier-boundaries",
    ROOT / "work/host-turn-barrier-boundaries",
    ROOT / "work/turn-barrier-boundaries",
)


def _guard():
    from equivalence import host_turn_barrier_boundaries_evidence
    return host_turn_barrier_boundaries_evidence


def _read(path):
    information = path.lstat()
    assert stat.S_ISREG(information.st_mode) and information.st_nlink == 1, path
    return json.loads(path.read_text(encoding="utf8"))


def _paths(name):
    return sorted({path for root in RETAINED if root.is_dir()
                   for path in root.rglob(name)}, key=lambda path: path.stat().st_mtime_ns, reverse=True)


def _load_native(case):
    for path in _paths("native-raw.json"):
        captures = _read(path)
        assert isinstance(captures, list) and len(captures) == 1, path
        raw = captures[0]
        if raw.get("input") != case["input"]:
            continue
        # Earlier versions of the same input lacked the newly measured physical
        # admission checkpoints. They remain historical evidence, not a baseline
        # for this actor/guard generation. Invalid current captures still fail.
        context_path = path.parents[1] / "context.json"
        if not context_path.is_file():
            continue
        actor = ROOT / "equivalence/host-turn-barrier-boundaries-runtime.mjs"
        context = _read(context_path)
        approved = [row for row in context["allowedLocal"] if row["path"] == str(actor)]
        if len(approved) != 1 or approved[0]["sha256"] != hashlib.sha256(actor.read_bytes()).hexdigest():
            continue
        stdout = path.parents[1] / "stdout.json"
        if not stdout.is_file():
            continue
        returned = _read(stdout)
        if returned.get("ok") is not True:
            continue
        assert returned["id"] == case["id"], stdout
        result = returned["result"]
        assert _guard().validate_capture(case, raw, result, native=True) is True
        return case, raw, result
    pytest.skip("No retained successful Native capture of this exact frozen boundary input; no credit")


@pytest.fixture(scope="module")
def actual_sdk_cases(tmp_path_factory):
    """Actual SDK executions remain runnable even without a Native replay cache."""
    from equivalence.host_turn_barrier_boundaries_sdk import run_host_turn_barrier_boundaries_case
    root = tmp_path_factory.mktemp("actual-boundary-sdk-captures")
    captures = {}
    for case in CASES:
        directory = root / case["id"]
        result = run_host_turn_barrier_boundaries_case(case["input"], evidence_directory=directory)
        raw = _read(directory / "python-raw.json")
        assert isinstance(raw, list) and len(raw) == 1
        dispatch = raw[0]
        assert dispatch["exit"]["code"] == 0 and dispatch["input"] == case["input"]
        observation = json.loads(dispatch["stdout"])
        assert observation == dispatch["observation"] and observation["result"] == result
        captures[case["id"]] = case, dispatch, result
    return captures


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def actual_native(request):
    return _load_native(request.param)


@pytest.fixture(scope="module", params=CASES, ids=lambda case: case["id"])
def actual_sdk(request, actual_sdk_cases):
    capture = actual_sdk_cases[request.param["id"]]
    assert _guard().validate_capture(*capture, native=False) is True
    return capture


def _turn(raw, label):
    return next(row for row in raw["turns"] if row["label"] == label)


def _sdk_raw(capture):
    return capture[1]["observation"]["raw"]


def _seal_sdk(capture):
    capture[1]["stdout"] = json.dumps(capture[1]["observation"], ensure_ascii=False)


def _replace(root, old, new):
    """Update parallel carrier copies without changing a real dispatch receipt."""
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


def _reject(capture, *, native, message):
    with pytest.raises(ValueError, match=message):
        _guard().validate_capture(*capture, native=native)


def _read_turn(case):
    return "save" if case["input"]["scenario"] == "cold-publication-failure" else "followup"


def _case(scenario):
    return next(case for case in CASES if case["input"]["scenario"] == scenario)


def _sdk_case(captures, scenario):
    capture = captures[_case(scenario)["id"]]
    assert _guard().validate_capture(*capture, native=False) is True
    return capture


def _swap_events(rows, first, second):
    """Swap semantic events while keeping the original valid chronology slots."""
    left, right = rows.index(first), rows.index(second)
    first["sequence"], second["sequence"] = second["sequence"], first["sequence"]
    first["atNs"], second["atNs"] = second["atNs"], first["atNs"]
    rows[left], rows[right] = second, first


def _move_before(rows, selected, anchor):
    """Relocate a phase while preserving every original chronology slot."""
    slots = [(row["sequence"], row["atNs"]) for row in rows]
    for row in selected:
        rows.remove(row)
    position = rows.index(anchor)
    rows[position:position] = selected
    for row, (sequence, instant) in zip(rows, slots, strict=True):
        row["sequence"], row["atNs"] = sequence, instant


def _walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _sdk_lease_seal(raw):
    raw["lease"]["stdout"] = [json.dumps(row, separators=(",", ":")) + "\n"
                              for row in raw["lease"]["receipts"]]


def test_actual_native_capture_validates_without_fabricating_an_output(actual_native):
    assert _guard().validate_capture(*actual_native, native=True) is True
    assert actual_native[0]["covers"] == ["host.turn-barrier.boundaries"]


def test_actual_sdk_capture_validates_without_fabricating_an_output(actual_sdk):
    assert _guard().validate_capture(*actual_sdk, native=False) is True
    assert actual_sdk[0]["covers"] == ["host.turn-barrier.boundaries"]


@pytest.mark.parametrize("field", ["text", "replyToTag", "replyToId", "audioAsVoice"])
def test_public_delivery_keeps_every_actual_normalized_field(actual_native, field):
    case, _, result = deepcopy(actual_native)
    result["followup"]["deliveries"][0].pop(field)
    with pytest.raises(ValueError, match="(?i)boundary public"):
        _guard().validate_result(case, result)


@pytest.mark.parametrize("field", ["queuedFinal", "tool", "block", "final"])
def test_public_dispatch_result_keeps_zero_counts_as_well_as_the_final(actual_native, field):
    case, _, result = deepcopy(actual_native)
    returned = result["followup"]["dispatchReturn"]
    (returned if field == "queuedFinal" else returned["counts"]).pop(field)
    with pytest.raises(ValueError, match="(?i)boundary public"):
        _guard().validate_result(case, result)


@pytest.mark.parametrize("attack", ["missing-start", "missing-result", "same-sequence", "wrong-tool", "wrong-path"])
def test_native_foreground_producer_has_real_dispatch_start_and_result(actual_native, attack):
    capture = deepcopy(actual_native)
    turn = _turn(capture[1], "save")
    call = turn["toolCalls"][0]
    events = [row for row in turn["toolEvents"] if row.get("stream") == "tool"
              and row["data"].get("toolCallId") == call["id"]]
    start = next(row for row in events if row["data"]["phase"] == "start")
    result = next(row for row in events if row["data"]["phase"] == "result")
    if attack == "missing-start":
        turn["toolEvents"].remove(start)
    elif attack == "missing-result":
        turn["toolEvents"].remove(result)
    elif attack == "same-sequence":
        result["seq"] = start["seq"]
    elif attack == "wrong-tool":
        start["data"]["name"] = result["data"]["name"] = "edit"
    else:
        start["data"]["args"]["path"] = "USER.md"
    _reject(capture, native=True, message="(?i)native .*(dispatch|tool|model)")


@pytest.mark.parametrize("attack", ["missing-start", "wrong-parent", "wrong-query", "detached-result"])
def test_native_search_keeps_its_actual_nested_dispatch(actual_native, attack):
    capture = deepcopy(actual_native)
    turn = _turn(capture[1], _read_turn(capture[0]))
    start = next(row for row in turn["toolEvents"] if row.get("stream") == "tool"
                 and row["data"].get("phase") == "start" and row["data"].get("name") == "memory_search")
    if attack == "missing-start":
        turn["toolEvents"].remove(start)
    elif attack == "wrong-parent":
        start["data"]["parentToolCallId"] = "anotherRealDispatch"
    elif attack == "wrong-query":
        start["data"]["args"]["query"] = "different query"
    else:
        returned = next(row for row in turn["toolEvents"] if row.get("stream") == "tool"
                        and row["data"].get("phase") == "result"
                        and row["data"].get("toolCallId") == start["data"]["toolCallId"])
        returned["data"]["result"] = {"content": [], "details": {"results": []}}
    _reject(capture, native=True, message="(?i)native .*(dispatch|tool|model|carrier)")


@pytest.mark.parametrize("attack", ["wrong-call", "missing-consumption", "other-tool", "inconsistent-details"])
def test_native_model_consumes_the_complete_actual_search_carrier(actual_native, attack):
    capture = deepcopy(actual_native)
    turn = _turn(capture[1], _read_turn(capture[0]))
    carrier = turn["searchCarrier"]
    if attack == "wrong-call":
        carrier["toolCallId"] = "anotherCall"
    elif attack == "missing-consumption":
        consumers = [row for row in turn["modelCalls"] if carrier in row["context"]["messages"]]
        assert consumers
        for row in consumers:
            row["context"]["messages"].remove(carrier)
    else:
        old = deepcopy(carrier)
        wrapped = json.loads(carrier["content"][0]["text"])
        if attack == "other-tool":
            wrapped["tool"]["name"] = "memory_get"
        else:
            wrapped["result"]["details"]["fixtureAddedField"] = "not in visible JSON"
        carrier["content"][0]["text"] = json.dumps(wrapped, ensure_ascii=False)
        _replace(turn["modelCalls"], old, carrier)
    _reject(capture, native=True, message="(?i)native .*(dispatch|tool|model|carrier)")


@pytest.mark.parametrize("attack", ["different-return", "wrong-call", "wrong-tool", "missing-next-model-input"])
def test_sdk_actual_dispatch_result_reaches_its_own_consuming_model(actual_sdk, attack):
    capture = deepcopy(actual_sdk)
    raw = _sdk_raw(capture)
    turn = _turn(raw, "save")
    call = turn["toolCalls"][0]
    if attack == "different-return":
        call["returned"] = {"status": "not the observed result"}
    elif attack == "wrong-call":
        call["observed"]["message"]["toolCallId"] = "anotherCall"
    elif attack == "wrong-tool":
        call["observed"]["message"]["toolName"] = "memory_get"
    else:
        message = call["observed"]["message"]
        consumers = [row for row in turn["modelCalls"][1:] if message in row["messages"]]
        assert consumers
        for row in consumers:
            row["messages"].remove(message)
    _seal_sdk(capture)
    _reject(capture, native=False, message="(?i)SDK .*(dispatch|tool|model|carrier)")


@pytest.mark.parametrize("attack", ["missing", "wrong-file", "changed-bytes", "changed-time"])
def test_native_metadata_is_the_real_operation_on_the_bound_source(actual_native, attack):
    capture = deepcopy(actual_native)
    metadata = capture[1]["metadataOperations"]
    assert metadata
    row = metadata[0]
    if attack == "missing":
        metadata.remove(row)
    elif attack == "wrong-file":
        row["arguments"][0] = str(Path(row["arguments"][0]).with_name("USER.md"))
    elif attack == "changed-bytes":
        row["after"]["sha256"] = "0" * 64
    else:
        row["after"]["mtimeMs"] += 1
    _reject(capture, native=True, message="(?i)native .*(metadata|source)")


@pytest.mark.parametrize("attack", ["missing-abort", "missing-done", "early-next-run", "non-preemptible", "already-running"])
def test_native_pending_preemption_uses_its_real_owner_and_admission(attack):
    capture = deepcopy(_load_native(_case("pending-optional-preemption")))
    rows = capture[1]["events"]
    aborted = next(row for row in rows if row["event"] == "actual-maintenance-abort")
    done = next(row for row in rows if row["event"] == "actual-maintenance-done"
                and row["ownerId"] == aborted["ownerId"])
    if attack == "missing-abort":
        rows.remove(aborted)
    elif attack == "missing-done":
        rows.remove(done)
    elif attack == "early-next-run":
        admitted = next(row for row in rows if row["event"] == "actual-agent-run-start"
                        and row["label"] == "followup")
        _swap_events(rows, admitted, aborted)
    else:
        for row in _walk(capture[1]):
            if row.get("id") == aborted["ownerId"] and "preemptible" in row and "writesReleased" in row:
                row["preemptible" if attack == "non-preemptible" else "running"] = attack == "already-running"
    _reject(capture, native=True, message="(?i)native .*(maintenance|admission|owner)")


@pytest.mark.parametrize("scenario", ["pending-optional-preemption", "target-open-preparation",
                                     "committed-maintenance", "refused-maintenance"])
@pytest.mark.parametrize("attack", ["missing-done-callback", "early-next-model", "missing-settled-journal"])
def test_sdk_next_model_waits_for_actual_owned_settlement(actual_sdk_cases, scenario, attack):
    capture = deepcopy(_sdk_case(actual_sdk_cases, scenario))
    raw = _sdk_raw(capture)
    rows = raw["events"]
    if attack == "missing-done-callback":
        rows.remove(next(row for row in rows if row["event"] == "optional-done-observed"))
    elif attack == "early-next-model":
        admitted = next(row for row in rows if row["event"] == "model-enter" and row["label"] == "followup")
        aborted = next(row for row in rows if row["event"] in {"optional-abort-observed", "maintenance-provider-abort"})
        _swap_events(rows, admitted, aborted)
    else:
        for row in _walk(raw):
            if row.get("id") == 1 and "settled" in row and "events" in row:
                row["events"] = [event for event in row["events"] if event["phase"] != "settled"]
    _seal_sdk(capture)
    _reject(capture, native=False, message="(?i)SDK .*(maintenance|admission|owner)")


@pytest.mark.parametrize("attack", ["missing-release", "release-after-next-model",
                                  "acknowledged-before-release", "next-model-before-acknowledgment"])
def test_sdk_pending_admission_retains_the_actual_held_delivery_boundary(actual_sdk_cases, attack):
    capture = deepcopy(_sdk_case(actual_sdk_cases, "pending-optional-preemption"))
    rows = _sdk_raw(capture)["events"]
    release = next(row for row in rows if row["event"] == "delivery-ack-release" and row["label"] == "save")
    acknowledged = next(row for row in rows if row["event"] == "delivery-ack" and row["label"] == "save")
    closed = next(row for row in rows if row["event"] == "close-call")
    if attack == "missing-release":
        rows.remove(release)
    elif attack == "release-after-next-model":
        _swap_events(rows, release, closed)
    elif attack == "acknowledged-before-release":
        _swap_events(rows, release, acknowledged)
    else:
        # The owner can genuinely settle before a caller observes its abort.
        # Keep those intrinsic phases and the next model's instant untouched;
        # delay only the first turn's channel acknowledgment/return observations.
        delivering = next(row for row in rows if row["event"] == "delivery-call" and row["label"] == "followup")
        returned = next(row for row in rows if row["event"] == "host-return" and row["label"] == "save")
        _swap_events(rows, acknowledged, delivering)
        _swap_events(rows, returned, closed)
    _seal_sdk(capture)
    _reject(capture, native=False, message="(?i)(boundary lifecycle|SDK admission)")


@pytest.mark.parametrize("attack", ["started", "no-preemption", "different-actor"])
def test_sdk_pending_work_is_not_a_substituted_running_or_noop_owner(actual_sdk_cases, attack):
    capture = deepcopy(_sdk_case(actual_sdk_cases, "pending-optional-preemption"))
    raw = _sdk_raw(capture)
    for row in _walk(raw):
        if row.get("id") == 1 and "settled" in row and "events" in row:
            if attack == "started":
                row["events"][0]["phase"] = "started"
                row["events"][0]["running"] = True
            elif attack == "no-preemption":
                row["events"] = [event for event in row["events"]
                                 if event["phase"] != "foreground-preemption-requested"]
            else:
                row["id"] = 999
    _seal_sdk(capture)
    _reject(capture, native=False, message="(?i)SDK .*(maintenance|admission|owner)")


@pytest.mark.parametrize("attack", ["missing-break", "not-SIGIO", "missing-verification", "other-parent",
                                    "other-target", "missing-live-event-loop"])
def test_sdk_target_open_has_real_kernel_and_descriptor_completion_proof(actual_sdk_cases, attack):
    capture = deepcopy(_sdk_case(actual_sdk_cases, "target-open-preparation"))
    raw = _sdk_raw(capture)
    lease = raw["lease"]
    if attack in {"missing-break", "missing-verification"}:
        name = "BREAK" if attack == "missing-break" else "VERIFIED"
        lease["receipts"] = [row for row in lease["receipts"] if row["event"] != name]
        raw["events"] = [row for row in raw["events"] if not
                         (row["event"] == "lease-receipt" and row["receipt"]["event"] == name)]
    elif attack == "not-SIGIO":
        for row in _walk(raw):
            if row.get("event") == "BREAK" and "signal" in row:
                row["signal"] = 15
    elif attack == "other-parent":
        other = lease["parentPid"] + 1000
        lease["parentPid"] = other
        lease["argv"][lease["argv"].index("--owner-pid") + 1] = str(other)
        for row in _walk(raw):
            if row.get("kind") == "host-turn-barrier-boundaries-lease":
                row["ppid"] = other
    elif attack == "other-target":
        for row in _walk(raw):
            if row.get("kind") == "host-turn-barrier-boundaries-lease" and "target" in row:
                row["target"]["path"] = str(Path(row["target"]["path"]).with_name("another.md"))
    else:
        raw["events"] = [row for row in raw["events"] if row["event"] != "event-loop-live-after-actual-abort"]
    _sdk_lease_seal(raw)
    _seal_sdk(capture)
    _reject(capture, native=False, message=("(?i)SDK .*(lease|admission|maintenance)"
            "|boundary lifecycle lacks unique event-loop-live-after-actual-abort"))


@pytest.mark.parametrize("scenario", ["refused-maintenance", "refused-foreground"])
@pytest.mark.parametrize("attack", ["wrong-path", "different-inode", "one-link", "still-linked"])
def test_sdk_refusal_is_the_real_temporary_hard_link_to_its_own_source(actual_sdk_cases, scenario, attack):
    capture = deepcopy(_sdk_case(actual_sdk_cases, scenario))
    raw = _sdk_raw(capture)
    fault = raw["faults"][0]
    if attack == "wrong-path":
        fault["target"] = str(Path(fault["target"]).with_name("USER.md"))
    elif attack == "different-inode":
        fault["linkStat"]["ino"] += 1
    elif attack == "one-link":
        fault["armed"]["stat"]["nlink"] = fault["linkStat"]["nlink"] = 1
    else:
        fault["removed"]["stat"]["nlink"] = 2
        fault["linkExistsAfter"] = True
    _seal_sdk(capture)
    _reject(capture, native=False, message="(?i)SDK .*(fault|source|refusal)")


@pytest.mark.parametrize("attack", ["other-index", "existing-target", "not-symlink"])
def test_sdk_publication_fault_is_the_real_publisher_sidecar(actual_sdk_cases, attack):
    capture = deepcopy(_sdk_case(actual_sdk_cases, "cold-publication-failure"))
    raw = _sdk_raw(capture)
    fault = raw["faults"][0]
    if attack == "other-index":
        fault["target"] = str(Path(fault["target"]).with_name("another.sqlite-journal"))
    elif attack == "existing-target":
        fault["targetExists"] = True
    else:
        fault["isSymlink"] = False
    _seal_sdk(capture)
    _reject(capture, native=False, message="(?i)SDK .*(fault|source|publication)")


def test_real_rejected_native_publication_probe_is_not_relabelled_a_visible_warning():
    directory = (ROOT / "work/turn-barrier-boundaries/pending/attempt-008-v2-six-native-no-sdk"
                 / "host-turn-barrier-boundaries-publication-failure-unicode")
    rawpath = directory / "evidence/native-raw.json"
    if not rawpath.is_file():
        pytest.skip("The genuine rejected development publication capture is not retained here; no credit")
    case = _case("cold-publication-failure")
    raw, returned = _read(rawpath)[0], _read(directory / "stdout.json")
    assert raw["input"] == case["input"] and returned["ok"] is True
    # The actual first provider rejected an isError carrier and emitted a generic
    # agent failure. Its complete failed execution is retained, not repaired.
    assert returned["result"]["save"]["search"] is None
    with pytest.raises(ValueError, match="(?i)boundary public|native .*model"):
        _guard().validate_capture(case, raw, returned["result"], native=True)


def test_native_publication_error_cannot_hide_its_actual_error_flags():
    capture = deepcopy(_load_native(_case("cold-publication-failure")))
    for row in _walk(capture[1]):
        if row.get("isError") is True:
            row["isError"] = False
    _reject(capture, native=True, message="(?i)native .*(dispatch|carrier|model|error)")


def test_native_due_owner_cannot_borrow_high_accounting_from_a_low_usage_model():
    capture = deepcopy(_load_native(_case("pending-optional-preemption")))
    for call in _turn(capture[1], "save")["modelCalls"]:
        call["reply"]["usage"].update(input=128, totalTokens=160)
    _reject(capture, native=True, message="(?i)native .*(maintenance|model|usage)")


def test_sdk_due_owner_keeps_its_actual_first_turn_accounting(actual_sdk_cases):
    capture = deepcopy(_sdk_case(actual_sdk_cases, "pending-optional-preemption"))
    _turn(_sdk_raw(capture), "save")["outcome"]["session"]["entry"]["totalTokens"] = 128
    _seal_sdk(capture)
    _reject(capture, native=False, message="(?i)SDK .*(maintenance|model|admission|usage)")


def test_sdk_ordinary_external_user_cannot_gain_owner_authority(actual_sdk):
    capture = deepcopy(actual_sdk)
    raw = _sdk_raw(capture)
    for turn in raw["turns"]:
        for call in turn["modelCalls"]:
            call["trust"]["senderIsOwner"] = True
    _seal_sdk(capture)
    _reject(capture, native=False, message="(?i)SDK source producer.*owner authority")


@pytest.mark.parametrize("attack", ["running-at-abort", "borrowed-start-event", "missing-transcript", "missing-physical-SQL"])
def test_native_owner_and_admission_callbacks_keep_actual_state_and_readback(attack):
    capture = deepcopy(_load_native(_case("pending-optional-preemption")))
    raw = capture[1]
    if attack == "running-at-abort":
        for event in raw["events"]:
            if event["event"] in {"actual-maintenance-abort", "actual-delivery-ack-released"}:
                for session in event["owners"]:
                    for owner in session["owners"]:
                        owner["running"] = True
    elif attack == "borrowed-start-event":
        event = next(row for row in raw["events"] if row["event"] == "actual-agent-run-start"
                     and row["label"] == "followup")
        event["observation"].update(runId="borrowed-run", transcript=[])
    elif attack == "missing-transcript":
        for turn in raw["turns"]:
            for start in turn["agentRunStarts"]:
                start["transcript"] = []
        for event in raw["events"]:
            if event["event"] == "actual-agent-run-start":
                event["observation"]["transcript"] = []
    else:
        for row in _walk(raw):
            if "sqlite" in row:
                row["sqlite"] = []
        raw["closedSqlite"] = []
    _reject(capture, native=True, message="(?i)native .*(maintenance|admission|source|SQL|callback|readback)")


@pytest.mark.parametrize("attack", ["missing-break", "not-SIGIO", "missing-verification", "other-parent",
                                    "other-target", "missing-live-event-loop"])
def test_native_target_open_keeps_actual_kernel_and_close_proof(attack):
    capture = deepcopy(_load_native(_case("target-open-preparation")))
    raw = capture[1]
    lease = raw["lease"]
    if attack in {"missing-break", "missing-verification"}:
        name = "BREAK" if attack == "missing-break" else "VERIFIED"
        lease["events"] = [row for row in lease["events"] if row["event"] != name]
        raw["events"] = [row for row in raw["events"] if not
                         ("receipt" in row and row["event"].startswith("actual-lease-")
                          and row["receipt"]["event"] == name)]
    elif attack == "not-SIGIO":
        for row in _walk(raw):
            if row.get("event") == "BREAK" and "signal" in row:
                row["signal"] = 15
    elif attack == "other-parent":
        other = lease["ppid"] + 1000
        lease["ppid"] = other
        lease["arguments"][-1] = str(other)
        for row in _walk(raw):
            if row.get("kind") == "host-turn-barrier-boundaries-lease":
                row["ppid"] = other
    elif attack == "other-target":
        for row in _walk(raw):
            if row.get("kind") == "host-turn-barrier-boundaries-lease" and "target" in row:
                row["target"]["path"] = str(Path(row["target"]["path"]).with_name("another.md"))
    else:
        raw["events"] = [row for row in raw["events"] if row["event"] != "actual-node-event-loop-live-after-abort"]
    _reject(capture, native=True, message=("(?i)native .*(lease|admission|maintenance)"
            "|boundary lifecycle lacks unique actual-node-event-loop-live-after-abort"))


@pytest.mark.parametrize("scenario", ["refused-maintenance", "refused-foreground"])
@pytest.mark.parametrize("attack", ["wrong-path", "different-inode", "one-link", "still-linked"])
def test_native_refusal_keeps_its_own_real_hard_link_window(scenario, attack):
    capture = deepcopy(_load_native(_case(scenario)))
    arm, removed = capture[1]["faultOperations"]
    if attack == "wrong-path":
        arm["target"] = removed["target"] = "USER.md"
    elif attack == "different-inode":
        arm["aliasStat"]["ino"] += 1
    elif attack == "one-link":
        arm["after"]["nlink"] = arm["aliasStat"]["nlink"] = 1
    else:
        removed["after"]["nlink"] = 2
    _reject(capture, native=True, message="(?i)native .*(fault|source|refusal)")


@pytest.mark.parametrize("scenario", ["committed-maintenance", "refused-maintenance"])
@pytest.mark.parametrize("attack", ["wrong-producer-path", "missing-model-result", "wrong-error-flag", "detached-consumption"])
def test_native_maintenance_write_result_is_from_the_real_admitted_tool(scenario, attack):
    capture = deepcopy(_load_native(_case(scenario)))
    calls = capture[1]["maintenanceCalls"]
    if attack == "wrong-producer-path":
        calls[0]["reply"]["content"][0]["arguments"]["path"] = "MEMORY.md"
    elif attack == "missing-model-result":
        calls[1]["context"]["messages"].remove(calls[1]["producingToolResult"])
    elif attack == "wrong-error-flag":
        calls[1]["producingToolResult"]["isError"] = scenario != "refused-maintenance"
    else:
        event = next(row for row in capture[1]["events"] if row["event"] == "actual-maintenance-write-result-consumed")
        event["receipt"] = {"role": "toolResult", "toolName": "write", "content": []}
    _reject(capture, native=True, message="(?i)native .*(maintenance|dispatch|model|source)")


@pytest.mark.parametrize("scenario", ["refused-foreground", "cold-publication-failure"])
@pytest.mark.parametrize("attack", ["late-delivery", "early-next-admission"])
def test_native_real_error_is_delivered_before_the_next_admission(scenario, attack):
    capture = deepcopy(_load_native(_case(scenario)))
    rows = capture[1]["events"]
    delivered = next(row for row in rows if row["event"] == "actual-terminal-delivery" and row["label"] == "save")
    admitted = next(row for row in rows if row["event"] == "actual-agent-run-start" and row["label"] == "followup")
    if attack == "late-delivery":
        _swap_events(rows, delivered, admitted)
    else:
        attempted = next(row for row in rows if row["event"] == "host-submission-attempt" and row["label"] == "followup")
        model = next(row for row in rows if row["event"] == "actual-model-invocation"
                     and row.get("turn") == "followup" and row["index"] == 0)
        _move_before(rows, [attempted, admitted, model], delivered)
    _reject(capture, native=True, message="(?i)native .*(admission|delivery|failure|error)")


@pytest.mark.parametrize("scenario", ["refused-foreground", "cold-publication-failure"])
@pytest.mark.parametrize("attack", ["late-delivery", "early-next-admission"])
def test_sdk_real_error_is_delivered_before_the_next_admission(actual_sdk_cases, scenario, attack):
    capture = deepcopy(_sdk_case(actual_sdk_cases, scenario))
    rows = _sdk_raw(capture)["events"]
    delivered = next(row for row in rows if row["event"] == "channel-final-delivered" and row["label"] == "save")
    admitted = next(row for row in rows if row["event"] == "model-enter" and row["label"] == "followup")
    if attack == "late-delivery":
        _swap_events(rows, delivered, admitted)
    else:
        attempted = next(row for row in rows if row["event"] == "host-call" and row["label"] == "followup")
        _move_before(rows, [attempted, admitted], delivered)
    _seal_sdk(capture)
    _reject(capture, native=False, message="(?i)SDK .*(admission|delivery|failure|error)")
