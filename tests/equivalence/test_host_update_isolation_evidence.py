"""Actual SDK update/isolation hosts and adversarial evidence replays.

Every capture below is a real SDK run of a frozen literal, including the real
hard-link refusal and the real unusable publication sidecar. The attacks then
rewrite a self-consistent copy; the guard must refuse each one.
"""
from copy import deepcopy
import json

import pytest

from equivalence.host_restart_session import build_cases as restart_cases
from equivalence.host_update_isolation import build_cases
from equivalence.host_update_isolation_evidence import (
    EMPTY_ANSWER, STALE_ERROR, expected_sources, validate_capture, validate_result,
)
from equivalence.host_update_isolation_sdk import run_host_update_isolation

ASCII, UNICODE, REFUSAL, PUBLICATION = range(4)


@pytest.fixture(scope="module")
def captures(tmp_path_factory):
    root = tmp_path_factory.mktemp("real-update-isolation-hosts")
    rows = []
    for case in build_cases():
        directory = root / case["id"]
        result = run_host_update_isolation(case["input"], evidence_directory=directory)
        raw = json.loads((directory / "python-raw.json").read_text())[0]
        rows.append((case, raw, result))
    return rows


def _read(result, name):
    return next(read for read in result["phases"][1]["reads"] if read["session"] == name)


def _update_raw(raw):
    return raw["phases"][1]["observation"]["raw"]


@pytest.mark.parametrize("index", range(4))
def test_actual_sdk_update_custody(captures, index):
    case, raw, result = captures[index]
    assert validate_capture(case, raw, result, native=False) is True
    assert validate_result(case, result) is True


def test_real_hosts_show_the_declared_outcomes(captures):
    for index in (ASCII, UNICODE):
        case, _, result = captures[index]
        update = case["input"]["phases"][1]["update"]
        assert result["phases"][1]["update"] == {"committed": True, "answer": update["ack"]}
        assert update["new"] in _read(result, "current")["answer"]
        assert _read(result, "superseded")["search"]["results"] == []
        assert _read(result, "superseded")["answer"] == EMPTY_ANSWER
    case, raw, result = captures[REFUSAL]
    update = case["input"]["phases"][1]["update"]
    assert result["phases"][1]["update"] == {"committed": False, "answer": update["failureAck"]}
    assert result["phases"][1]["source"] == result["phases"][0]["source"]
    assert update["old"] in _read(result, "current")["answer"] and update["new"] not in json.dumps(result, ensure_ascii=False)
    refused = _update_raw(raw)["turns"][0]["toolCalls"][0]["observed"]
    assert refused["message"]["isError"] is True and refused["payload"]["status"] == "error"
    case, raw, result = captures[PUBLICATION]
    update = case["input"]["phases"][1]["update"]
    assert [item["failed"] for item in result["phases"][1]["publications"]] == [True, False]
    assert result["phases"][1]["publications"][0]["error"] == STALE_ERROR
    stale = _read(result, "stale")
    assert stale["search"]["stale"] is True and STALE_ERROR in stale["search"]["warning"]
    assert update["old"] in stale["search"]["results"][0]["snippet"] and update["new"] in stale["answer"]
    assert "stale" not in _read(result, "current")["search"]
    committed = _update_raw(raw)["turns"][0]["toolCalls"][0]["observed"]
    assert committed["message"]["isError"] is False and committed["payload"]["afterWriteError"] == STALE_ERROR


def test_every_host_keeps_the_other_agents_source_and_reads_unchanged(captures):
    for case, _, result in captures:
        first, second = result["phases"]
        assert second["isolatedSource"] == first["isolatedSource"]
        assert [read["session"] for read in first["reads"]] == ["before", "supersededBefore", "isolatedBefore"]
        assert _read(result, "isolated") == first["reads"][2] | {"session": "isolated"}
        own = case["input"]["phases"][0]["save"]["entries"][0]["text"]
        assert own not in json.dumps(first["reads"][2], ensure_ascii=False)


def _empty(read):
    read["search"]["results"] = []
    read["search"]["debug"].update(hits=0, candidateHits=0)
    read["get"], read["answer"] = None, EMPTY_ANSWER


def _attack(name, case, raw, result):
    update = case["input"]["phases"][1]["update"]
    second = result["phases"][1]
    child = _update_raw(raw)
    if name == "invented-commit":
        second["update"] = {"committed": True, "answer": update["ack"]}
    elif name == "hidden-refusal-source":
        text = expected_sources(case)["before"].replace(update["old"], update["new"])
        second["source"].update(text=text, hex=text.encode().hex())
    elif name == "dropped-stale-flag":
        for key in ("stale", "warning", "action"):
            del _read(result, "stale")["search"][key]
    elif name == "stale-read-reports-current-index":
        hit = _read(result, "stale")["search"]["results"][0]
        hit["snippet"] = hit["snippet"].replace(update["old"], update["new"])
    elif name == "stale-read-hides-committed-source":
        read = _read(result, "stale")
        read["get"]["text"] = read["get"]["text"].replace(update["new"], update["old"])
        read["answer"] = read["get"]["text"]
    elif name == "missing-stale-read":
        del second["reads"][0]
    elif name == "publication-failure-hidden":
        second["publications"][0].update(failed=False, error=None)
    elif name == "publication-error-rewritten":
        second["publications"][0]["error"] = "an operator supplied this reason"
    elif name == "failed-final-publication":
        second["publications"][-1].update(failed=True, error=STALE_ERROR)
    elif name == "superseded-still-served":
        read = _read(result, "superseded")
        before = deepcopy(result["phases"][0]["reads"][0])
        read.update(search=before["search"], get=before["get"], answer=before["answer"])
    elif name == "unrelated-fact-lost":
        _empty(_read(result, "unrelated"))
    elif name == "isolated-read-changed":
        read = _read(result, "isolated")
        read["get"]["text"] = "- " + update["new"]
        read["answer"] = read["get"]["text"]
    elif name == "isolated-source-changed":
        second["isolatedSource"] = deepcopy(second["source"])
    elif name == "reordered-reads":
        second["reads"][-2], second["reads"][-1] = second["reads"][-1], second["reads"][-2]
    elif name == "answer-not-from-source":
        _read(result, "current")["answer"] = "- " + update["new"]
    elif name == "extra-publication":
        second["publications"].append(deepcopy(second["publications"][-1]))
    elif name == "stale-warning-after-final":
        _read(result, "current")["search"].update(stale=True, warning="Memory index is stale.")
    elif name == "superseded-text-in-current-answer":
        read = _read(result, "current")
        read["get"]["text"] += "\n- " + update["old"]
        read["answer"] = read["get"]["text"]
    elif name == "producer-read-empty":
        _empty(result["phases"][0]["reads"][0])
    elif name == "producer-source-changed":
        result["phases"][0]["source"]["text"] += "- An undeclared entry.\n"
    elif name == "missing-fault-window":
        child["mutations"] = []
    elif name == "undeclared-mutation":
        child["mutations"].append({"operation": "undeclared", "stage": "before-update-tool",
                                   "before": {"kind": "file", "nlink": 1}, "after": {"kind": "file", "nlink": 2}})
    elif name == "fault-never-linked":
        child["mutations"][0]["after"]["nlink"] = 1
    elif name == "fault-never-removed":
        child["mutations"][1]["after"]["nlink"] = 2
    elif name == "sidecar-not-symlink":
        child["mutations"][0]["after"]["kind"] = "missing"
    elif name == "sidecar-left-in-place":
        child["mutations"][1]["after"]["kind"] = "symlink"
    elif name == "swapped-tool":
        child["turns"][0]["toolCalls"][0]["name"] = "add_memory_entry"
    elif name == "second-update-call":
        child["turns"][0]["toolCalls"].append(deepcopy(child["turns"][0]["toolCalls"][0]))
    elif name == "refusal-reported-as-success":
        child["turns"][0]["toolCalls"][0]["observed"]["message"]["isError"] = False
    elif name == "success-reported-as-refusal":
        child["turns"][0]["toolCalls"][0]["observed"]["message"]["isError"] = True
    elif name == "after-write-error-dropped":
        del child["turns"][0]["toolCalls"][0]["observed"]["payload"]["afterWriteError"]
    elif name == "after-write-error-invented":
        child["turns"][0]["toolCalls"][0]["observed"]["payload"]["afterWriteError"] = STALE_ERROR
    elif name == "index-failure-reported-ready":
        child["turns"][0]["outcome"]["index_status"] = "ready"
    elif name == "foreign-phase":
        raw["phases"][1]["request"]["phase"]["update"]["new"] += " An undeclared fact."
    elif name == "swapped-phases":
        raw["phases"].reverse()
    elif name == "failed-child":
        raw["phases"][1]["exit"]["code"] = 1
    elif name == "same-process":
        raw["phases"][1]["pid"] = raw["phases"][0]["pid"]
    elif name == "foreign-input":
        raw["input"]["nowMs"] += 1
    elif name == "foreign-kind":
        raw["kind"] = "host-restart-recall"
    else:
        raise AssertionError(name)


RESULT_ATTACKS = [
    (REFUSAL, "invented-commit"), (REFUSAL, "hidden-refusal-source"),
    (PUBLICATION, "dropped-stale-flag"), (PUBLICATION, "stale-read-reports-current-index"),
    (PUBLICATION, "stale-read-hides-committed-source"), (PUBLICATION, "missing-stale-read"),
    (PUBLICATION, "publication-failure-hidden"), (PUBLICATION, "publication-error-rewritten"),
    (ASCII, "failed-final-publication"), (ASCII, "superseded-still-served"), (UNICODE, "superseded-still-served"),
    (ASCII, "unrelated-fact-lost"), (ASCII, "isolated-read-changed"), (ASCII, "isolated-source-changed"),
    (ASCII, "reordered-reads"), (ASCII, "answer-not-from-source"), (ASCII, "extra-publication"),
    (ASCII, "stale-warning-after-final"), (UNICODE, "superseded-text-in-current-answer"),
    (ASCII, "producer-read-empty"), (ASCII, "producer-source-changed"),
]
CUSTODY_ATTACKS = [
    (REFUSAL, "missing-fault-window"), (ASCII, "undeclared-mutation"), (REFUSAL, "fault-never-linked"),
    (REFUSAL, "fault-never-removed"), (PUBLICATION, "sidecar-not-symlink"), (PUBLICATION, "sidecar-left-in-place"),
    (PUBLICATION, "missing-fault-window"), (ASCII, "swapped-tool"), (ASCII, "second-update-call"),
    (REFUSAL, "refusal-reported-as-success"), (ASCII, "success-reported-as-refusal"),
    (PUBLICATION, "after-write-error-dropped"), (ASCII, "after-write-error-invented"),
    (PUBLICATION, "index-failure-reported-ready"), (ASCII, "foreign-phase"), (ASCII, "swapped-phases"),
    (ASCII, "failed-child"), (ASCII, "same-process"), (ASCII, "foreign-input"), (ASCII, "foreign-kind"),
]


@pytest.mark.parametrize(("index", "attack"), RESULT_ATTACKS)
def test_rejects_self_consistent_result_substitutions(captures, index, attack):
    case, original, public = captures[index]
    raw, result = deepcopy(original), deepcopy(public)
    _attack(attack, case, raw, result)
    # Keep the copy self-consistent: the hosts' own results carry the same rewrite.
    for child, phase in zip(raw["phases"], result["phases"]):
        child["observation"]["result"] = deepcopy(phase)
    with pytest.raises(ValueError):
        validate_result(case, result)
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=False)


@pytest.mark.parametrize(("index", "attack"), CUSTODY_ATTACKS)
def test_rejects_self_consistent_custody_substitutions(captures, index, attack):
    case, original, public = captures[index]
    raw, result = deepcopy(original), deepcopy(public)
    _attack(attack, case, raw, result)
    assert validate_result(case, result) is True
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=False)


def test_public_result_that_differs_from_the_hosts_own_results_is_refused(captures):
    case, original, public = captures[ASCII]
    raw, result = deepcopy(original), deepcopy(public)
    raw["phases"][1]["observation"]["result"]["reads"][0]["answer"] += " "
    with pytest.raises(ValueError, match="hosts' own results"):
        validate_capture(case, raw, result, native=False)


def test_one_literals_capture_cannot_validate_another_literal(captures):
    _, raw, result = captures[ASCII]
    with pytest.raises(ValueError):
        validate_capture(captures[UNICODE][0], raw, result, native=False)
    with pytest.raises(ValueError):
        validate_capture(captures[REFUSAL][0], raw, result, native=False)


def test_restart_literal_cannot_borrow_the_update_validator(captures):
    _, raw, result = captures[ASCII]
    with pytest.raises(ValueError, match="independently frozen"):
        validate_capture(restart_cases()[0], raw, result, native=False)


def test_update_literal_cannot_borrow_the_restart_validator(captures):
    from equivalence.host_restart_session_evidence import validate_capture as restart_validator

    case, raw, result = captures[ASCII]
    with pytest.raises((KeyError, TypeError, ValueError)):
        restart_validator(case, raw, result, native=False)


def test_sdk_runner_rejects_undeclared_inputs_before_any_host_process():
    case = build_cases()[ASCII]
    for mutate in (lambda value: value.update(kind="host-restart-recall"),
                   lambda value: value.update(source="memory/2026-11-09.md"),
                   lambda value: value["phases"].reverse(),
                   lambda value: value["policy"].update(indexLifecycle="managed"),
                   lambda value: value["phases"][1].update(fault={"operation": "undeclared-fault"}),
                   lambda value: value["phases"][1].update(extra=True)):
        changed = deepcopy(case["input"])
        mutate(changed)
        with pytest.raises(ValueError):
            run_host_update_isolation(changed)
