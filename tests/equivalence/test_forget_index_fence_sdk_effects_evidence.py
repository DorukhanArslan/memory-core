"""Read-only positive/adversarial replay of an explicitly selected V3 SDK run."""

from copy import deepcopy
from functools import lru_cache
import json
import os
from pathlib import Path

import pytest

from equivalence.forget_index_fence_sdk_effects_evidence import validate_sdk_effects_v3
from equivalence.forget_index_fence_v3 import build_cases


ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _actual():
    selected = os.environ.get("MEMORY_FORGET_INDEX_FENCE_V3_SDK_CAPTURE")
    if selected is None:
        pytest.skip("No independently selected actual V3 SDK capture; no acceptance credit")
    filename = Path(selected).resolve(strict=True)
    assert filename.is_file() and not filename.is_symlink() and filename.stat().st_nlink == 1
    values = json.loads(filename.read_bytes())
    assert isinstance(values, list) and len(values) == 1
    dispatch = values[0]
    case = next(case for case in build_cases() if case["input"] == dispatch["input"])
    processes = dispatch["observation"]["processes"]
    return case, processes


def _context(*, require_tasks=False):
    case, processes = _actual()
    process = next(
        process
        for process in processes
        if not require_tasks or process["observation"]["queuedSearchTasks"]
    )
    observation = process["observation"]
    events = {row["sequence"]: row for row in observation["originalCalls"]}
    returns = {
        row["callSequence"]: row
        for row in observation["originalCalls"]
        if row["event"] == "original-return"
    }
    return case, process, observation, events, returns


def _validate(context, observation=None, *, events=None, returns=None):
    case, process, actual, actual_events, actual_returns = context
    return validate_sdk_effects_v3(
        case,
        observation or actual,
        process,
        actual_events if events is None else events,
        actual_returns if returns is None else returns,
        recorded_root=Path(actual["sourceProvenanceBefore"]["root"]),
        approved_sdk_root=Path(os.environ["MEMORY_FORGET_INDEX_FENCE_SDK_SOURCE_ROOT"]).resolve(
            strict=True
        ),
        recorded_adapter_root=Path(process["request"]["adapterRoot"]),
        approved_adapter_root=Path(os.environ["MEMORY_FORGET_INDEX_FENCE_ADAPTER_ROOT"]).resolve(
            strict=True
        ),
    )


def test_actual_v3_sdk_process_effects_are_independently_authenticated():
    case, processes = _actual()
    for process in processes:
        observation = process["observation"]
        events = {row["sequence"]: row for row in observation["originalCalls"]}
        returns = {
            row["callSequence"]: row
            for row in observation["originalCalls"]
            if row["event"] == "original-return"
        }
        result = _validate((case, process, observation, events, returns))
        assert list(result["waits"]) == [row["label"] for row in observation["searchEffectWaits"]]


@pytest.mark.parametrize(
    "attack",
    [
        "task-future",
        "task-owner",
        "task-executor",
        "task-job",
        "task-source",
        "task-admission-order",
        "task-parent",
        "wait-public",
        "wait-tool",
        "wait-owner",
        "wait-future",
        "wait-empty",
        "wait-value",
        "wait-before-public",
        "wait-capability",
        "wait-duplicate",
        "state-epoch",
        "forged-condition",
        "omit-task",
    ],
)
def test_v3_effect_receipts_cannot_relabel_genuine_source_work(attack):
    context = _context(require_tasks=True)
    observation = dict(context[2])
    assert _validate(context)["waits"]
    observation["queuedSearchTasks"] = deepcopy(observation["queuedSearchTasks"])
    observation["searchEffectWaits"] = deepcopy(observation["searchEffectWaits"])
    task = observation["queuedSearchTasks"][0]
    wait = next(row for row in observation["searchEffectWaits"] if row["publisherFutures"])
    if attack == "task-future":
        task["futureObjectId"] = "999999999999"
    elif attack == "task-owner":
        task["storeObjectId"] = "999999999999"
    elif attack == "task-executor":
        task["executorObjectId"] = "999999999999"
    elif attack == "task-job":
        task["job"]["id"] += 123
    elif attack == "task-source":
        task["functionCode"]["sourceSha256"] = "0" * 64
    elif attack == "task-admission-order":
        task["submitReturnedAtNs"] = "0"
    elif attack == "task-parent":
        task["parentCallSequences"] = [task["submitSequence"]]
    elif attack == "wait-public":
        wait["publicReturnSequence"] += 1
    elif attack == "wait-tool":
        wait["toolObjectId"] = "999999999999"
    elif attack == "wait-owner":
        wait["storeObjectId"] = "999999999999"
    elif attack == "wait-future":
        wait["publisherFutures"][0]["futureObjectId"] = "999999999999"
    elif attack == "wait-empty":
        wait["tasksAtEntry"] = []
        wait["tasksAtReturn"] = []
        wait["publisherFutures"] = []
    elif attack == "wait-value":
        wait["publisherFutures"][0]["returned"] = {"fabricated": True}
    elif attack == "wait-before-public":
        wait["enteredAtNs"] = "0"
    elif attack == "wait-capability":
        wait["factoryCapabilities"]["recallOrigins"] = not wait["factoryCapabilities"][
            "recallOrigins"
        ]
    elif attack == "wait-duplicate":
        observation["searchEffectWaits"].append(deepcopy(wait))
    elif attack == "state-epoch":
        wait["publisherAfter"]["jobs"][0]["readRevision"] += 1
    elif attack == "forged-condition":
        wait["conditionWaits"].append(
            {
                "enteredAtNs": wait["enteredAtNs"],
                "returnedAtNs": wait["returnedAtNs"],
                "returned": True,
                "stateBefore": wait["publisherBefore"],
                "stateAfter": wait["publisherAfter"],
            }
        )
    elif attack == "omit-task":
        observation["queuedSearchTasks"].clear()
    with pytest.raises((ValueError, KeyError)):
        _validate(context, observation)


@pytest.mark.parametrize(
    "attack", ["missing", "entry", "receiver", "code", "self-repaired", "frame"]
)
def test_v3_future_return_requires_actual_retained_entry_and_cleared_self(attack):
    context = _context(require_tasks=True)
    assert _validate(context)["waits"]
    events, returns = dict(context[3]), dict(context[4])
    call = next(
        row
        for row in events.values()
        if row["event"] == "original-call" and row["name"] == "Future.result"
    )
    returned = deepcopy(returns[call["sequence"]])
    returns[call["sequence"]] = returned
    if attack == "missing":
        del returns[call["sequence"]]
    elif attack == "entry":
        returned["returnLookup"]["entryCallSequence"] += 1
    elif attack == "receiver":
        returned["returnLookup"]["entryReceiverObjectId"] = "999999999999"
    elif attack == "code":
        returned["returnLookup"]["entryCode"]["sourceSha256"] = "0" * 64
    elif attack == "self-repaired":
        returned["returnLookup"]["receiverLocal"] = {"objectId": call["receiverObjectId"]}
    elif attack == "frame":
        returned["returnLookup"]["frameObjectId"] = "999999999999"
    with pytest.raises((ValueError, KeyError)):
        _validate(context, events=events, returns=returns)


@pytest.mark.parametrize("attack", ["scope", "body", "sink"])
def test_v3_host_effect_requires_its_actual_original_producer_and_sink(attack):
    context = _context(require_tasks=True)
    assert _validate(context)["waits"]
    observation = dict(context[2])
    observation["hostEvents"] = deepcopy(observation["hostEvents"])
    observation["hostEventReceipts"] = deepcopy(observation["hostEventReceipts"])
    assert observation["hostEventReceipts"], "Selected original packet has no host event boundary"
    events = dict(context[3])
    receipt = observation["hostEventReceipts"][0]
    if attack == "scope":
        receipt["callScope"]["label"] = "foreign-unobserved-search"
    elif attack == "body":
        observation["hostEvents"][0]["fabricatedField"] = True
    else:
        producer = next(
            row
            for row in events.values()
            if row["event"] == "original-call"
            and row["name"] == "record_short_term_recalls"
            and row["callLabel"] == receipt["callScope"]["label"]
        )
        producer = deepcopy(producer)
        events[producer["sequence"]] = producer
        producer["arguments"]["on_event"]["qualname"] = "foreign_callback"
    with pytest.raises((ValueError, KeyError)):
        _validate(context, observation, events=events)


@pytest.mark.parametrize("attack", ["parent-subset", "job-epoch", "job-final-state"])
def test_v3_coherently_rewritten_copies_cannot_erase_original_lineage(attack):
    context = _context(require_tasks=True)
    assert _validate(context)["waits"]
    observation = dict(context[2])
    observation["queuedSearchTasks"] = deepcopy(observation["queuedSearchTasks"])
    observation["searchEffectWaits"] = deepcopy(observation["searchEffectWaits"])
    observation["publicCalls"] = deepcopy(observation["publicCalls"])
    selected = observation["queuedSearchTasks"][0]
    fid = selected["futureObjectId"]
    copies = [selected]
    for wait in observation["searchEffectWaits"]:
        copies.extend(
            row
            for row in (*wait["tasksAtEntry"], *wait["tasksAtReturn"])
            if row["futureObjectId"] == fid
        )
    for public in observation["publicCalls"].values():
        copies.extend(
            row for row in public.get("effectsAtPublicSettle", []) if row["futureObjectId"] == fid
        )
    for row in copies:
        if attack == "parent-subset":
            row["parentCallSequences"] = row["parentCallSequences"][-1:]
        elif "job" in row:
            if attack == "job-epoch":
                row["job"]["readRevision"] += 1
            else:
                row["job"]["fabricatedFinalState"] = True
    with pytest.raises((ValueError, KeyError)):
        _validate(context, observation)
