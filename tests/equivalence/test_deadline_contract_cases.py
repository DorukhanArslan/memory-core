"""Fixture integrity; actual native execution establishes the paired outcomes."""
from copy import deepcopy
import json

import pytest

from equivalence.deadline_contract import build_deadline_contract_cases, run_deadline_contract
from equivalence.search_contract import decode_search_tool_envelope


def _case(identifier):
    return next(case for case in build_deadline_contract_cases()
                if case["id"] == "deadline-contract-" + identifier)


def _run(identifier, **kwargs):
    return run_deadline_contract(_case(identifier)["input"], **kwargs)


def _payload(call):
    return call["result"]["details"]


def test_matrix_is_unique_deterministic_standard_json_and_explicitly_bounded():
    cases = build_deadline_contract_cases()
    assert cases == build_deadline_contract_cases()
    assert len(cases) == len({case["id"] for case in cases}) == 33
    assert json.loads(json.dumps(cases, ensure_ascii=False, allow_nan=False)) == cases
    assert all(set(case["covers"]) <= {case["requirement"] + ".outcomes", case["requirement"] + ".boundaries"}
               for case in cases)
    assert {case["requirement"] for case in cases} == {"tools.deadline-cooldown", "tools.unavailable-partial"}
    assert {case["input"]["kind"] for case in cases} == {"deadline", "control", "provenance", "tool"}
    assert sum(case["input"]["kind"] == "tool" for case in cases) == 15
    assert sum(case["input"].get("toolName") == "memory_get" for case in cases) == 3
    assert all(case["operation"] == ("deadline-partial-get-runtime" if case["input"].get("toolName") == "memory_get"
                                     else "deadline-partial-runtime" if case["input"]["kind"] == "tool"
                                     else "deadline-partial") for case in cases)
    assert all("No manager or index constructor is substituted" in case["driverScope"]
               if case["input"].get("toolName") == "memory_get" else "skips the index constructor"
               in case["driverScope"] for case in cases)
    assert all("no global ordering contract" in case["normalizationPolicy"] for case in cases)


def test_reviewed_four_conditions_require_real_whole_tool_scenarios():
    cases = build_deadline_contract_cases()
    expected = {
        "tools.deadline-cooldown.outcomes": (15, 5),
        "tools.deadline-cooldown.boundaries": (5, 5),
        "tools.unavailable-partial.outcomes": (7, 7),
        "tools.unavailable-partial.boundaries": (8, 8),
    }
    for condition, (total, whole_tools) in expected.items():
        covered = [case for case in cases if condition in case["covers"]]
        assert len(covered) == total
        assert sum(case["input"]["kind"] == "tool" for case in covered) == whole_tools
    assert _case("source-bare-corpus-ignoring-task")["covers"] == []
    assert _case("source-error-identity")["covers"] == []
    assert _case("source-balanced-control")["covers"] == []
    assert _case("get-builtin-pre-aborted-read-remains-unguarded")["covers"] == []
    assert _case("get-wiki-owned-timeout-late-result-and-recovery")["covers"] == [
        "tools.unavailable-partial.outcomes", "tools.unavailable-partial.boundaries",
    ]


def test_every_adapter_calls_actual_owners_without_mutating_its_input_or_returning_non_json():
    for case in build_deadline_contract_cases():
        before = deepcopy(case)
        observed = run_deadline_contract(case["input"])
        json.dumps(observed, ensure_ascii=False, allow_nan=False)
        assert case == before


def test_absolute_owner_enforces_exact_cutoff_without_an_overdue_timer_callback():
    assert "result" in _run("source-absolute-before")["outcome"]
    for identifier in ("source-absolute-at", "source-absolute-after"):
        result = _run(identifier)
        assert result["outcome"]["error"]["deadline"] is True
        assert result["signal"]["aborted"] is True and result["signal"]["reasonIsOutcomeError"] is True
        assert result["clockSteps"][0]["op"] == "set-time"


def test_pre_aborted_caller_never_enters_provider_and_retains_original_error_metadata():
    string = _run("source-parent-pre-abort-string")
    coded = _run("source-parent-pre-abort-error")
    assert string["events"] == coded["events"] == []
    assert string["signal"] is None and coded["signal"] is None
    assert coded["outcome"]["error"] == {
        "name": "Error", "message": "Caller stopped", "code": "CALLER_STOP", "deadline": False,
    }


def test_owned_deadline_beats_provider_wrapped_abort_and_rejects_marker_copies():
    wrapped = _run("source-deadline-beats-provider-abort-wrapper")
    assert wrapped["outcome"]["error"]["deadline"] is True
    provider_error = next(event["error"] for event in wrapped["events"] if event["event"] == "provider:rejected")
    assert provider_error["code"] == "PROVIDER_CANCELLED" and provider_error["deadline"] is False
    identity = _run("source-error-identity")
    assert identity["owned"]["deadline"] is True
    assert all(not identity[key]["deadline"] for key in ("ordinary", "copy", "cloned"))
    assert len({error["message"] for error in identity.values()}) == 1


def test_bare_corpus_owner_truthfully_awaits_ignoring_callback_after_its_signal_expires():
    result = _run("source-bare-corpus-ignoring-task")
    assert "result" in result["outcome"]
    assert result["signal"]["aborted"] is True
    assert result["signal"]["reason"]["deadline"] is True
    assert result["signal"]["reasonIsOutcomeError"] is False


def test_readiness_budget_and_balanced_control_use_the_actual_owner():
    assert "result" in _run("source-readiness-preserves-remaining-budget")["outcome"]
    assert _run("source-readiness-remaining-budget-expires")["outcome"]["error"]["deadline"] is True
    assert _run("source-parent-abort-while-paused")["outcome"]["error"]["code"] == "CALLER_STOP"
    assert _run("source-balanced-control")["events"] == [
        {"listener": "first", "action": "pause"}, {"listener": "during", "action": "pause"},
        {"listener": "during", "action": "resume"},
    ]


def test_actual_cooldown_suppresses_memory_and_sessions_but_allows_wiki_then_exact_expiry():
    result = _run("cooldown-admission-expiry-corpus-independence")
    calls = result["calls"]
    assert len(result["memoryDispatches"]) == 2 and len(result["wikiDispatches"]["alpha"]) == 2
    assert calls[0]["result"] == calls[1]["result"] == calls[2]["result"] == calls[5]["result"]
    assert _payload(calls[0])["unavailable"] is True
    assert _payload(calls[3])["results"][0]["corpus"] == "wiki"
    assert _payload(calls[4])["corpora"][0]["outcome"] == "unavailable"
    assert _payload(calls[6])["results"][0]["path"] == "memory/recovered.md"


def test_configuration_change_and_parent_abort_do_not_require_a_manual_cooldown_reset():
    configured = _run("configuration-change-clears-cooldown")
    assert len(configured["memoryDispatches"]) == 2
    assert _payload(configured["calls"][0])["unavailable"] is True
    assert _payload(configured["calls"][1])["results"]
    cancelled = _run("caller-abort-does-not-poison-admission")
    assert cancelled["calls"][0]["error"]["code"] == "CALLER_STOP"
    assert _payload(cancelled["calls"][1])["results"]
    assert len(cancelled["memoryDispatches"]) == 2


def test_accepted_partial_is_frozen_before_late_callbacks_and_next_query_is_admitted():
    result = _run("accepted-partial-late-update-explicit-recovery")
    partial, fresh = map(_payload, result["calls"])
    assert partial["partial"] is True and partial["timedOut"] is True and partial["timeoutMs"] == 30_000
    assert [row["path"] for row in partial["results"]] == ["memory/snapshot.md"]
    assert partial["mode"] == "keyword-only"
    assert partial["debug"]["searchMs"] == partial["debug"]["toolMs"] == 30_000
    assert partial["debug"]["fallback"] == "memory_search timed out after 30s"
    assert fresh["results"][0]["path"] == "memory/fresh.md" and "partial" not in fresh and "timedOut" not in fresh
    assert len(result["memoryDispatches"]) == 2
    assert any(event["event"] == "partial" and event["rows"][0]["path"] == "memory/late-snapshot.md"
               for event in result["lanes"]["memory"])


def test_invalidated_or_session_only_snapshots_never_become_timeout_fallback():
    invalidated = _run("partial-invalidation-withholds-old-snapshot")
    first = _payload(invalidated["calls"][0])
    assert first["unavailable"] is True and first["results"] == [] and "partial" not in first
    assert len(invalidated["memoryDispatches"]) == 1
    sessions = _run("sessions-cannot-salvage-memory-or-session-partials")
    assert _payload(sessions["calls"][0])["results"] == [] and "partial" not in _payload(sessions["calls"][0])
    assert sessions["memoryDispatches"][0]["options"]["sources"] == ["sessions"]
    assert _payload(sessions["calls"][1])["results"][0]["corpus"] == "wiki"


def test_independent_wiki_success_is_not_expired_when_memory_joins_after_readiness():
    result = _run("readiness-and-independent-wiki-settlement")
    published, timed_out = map(_payload, result["calls"])
    assert {row["source"] for row in published["results"]} == {"memory", "wiki"}
    assert "warning" not in published
    wiki_done = next(event for event in result["lanes"]["wiki:alpha"] if event["event"] == "fulfilled")
    memory_done = next(event for event in result["lanes"]["memory"] if event["event"] == "fulfilled")
    assert memory_done["time"] - wiki_done["time"] > 30_000
    assert timed_out["timedOut"] is True and timed_out["results"][0]["source"] == "memory"
    assert timed_out["corpora"][-1]["outcome"] == "unavailable"
    owner_barrier = next(step for step in result["clockSteps"] if "timerClears" in step)
    assert owner_barrier["timerClears"] == 2 and owner_barrier["timerClearCount"] >= 2


def test_provider_timeout_text_stays_unowned_and_failed_wiki_recovers_on_explicit_query():
    spoofed = _run("provider-timeout-text-stays-unowned-with-wiki-survival")
    first, mixed, recovered = map(_payload, spoofed["calls"])
    assert first["error"] == "memory_search timed out after 30s" and "timedOut" not in first
    assert mixed["results"][0]["corpus"] == "wiki" and "timedOut" not in mixed
    assert recovered["results"] and "warning" not in recovered
    wiki = _run("wiki-failure-independent-memory-and-later-recovery")
    assert _payload(wiki["calls"][0])["warning"]
    assert "warning" not in _payload(wiki["calls"][1])
    assert len(wiki["memoryDispatches"]) == len(wiki["wikiDispatches"]["alpha"]) == 2


def test_both_timeout_flags_and_later_recovery_preserve_every_corpus():
    result = _run("both-corpora-timeout-wiki-retry-and-later-recovery")
    first, wiki, recovered = map(_payload, result["calls"])
    assert first["timedOut"] is True and first["timeoutMs"] == 30_000
    assert [corpus["corpus"] for corpus in first["corpora"]] == ["memory", "wiki"]
    assert all(corpus["outcome"] == "unavailable" for corpus in first["corpora"])
    assert wiki["results"][0]["corpus"] == "wiki"
    assert {row["source"] for row in recovered["results"]} == {"memory", "wiki"}
    assert "timedOut" not in recovered and "warning" not in recovered


def test_clock_commands_counts_and_provider_protocol_are_complete_not_projected():
    case = _case("cooldown-admission-expiry-corpus-independence")
    result = run_deadline_contract(case["input"])
    assert len(result["clockSteps"]) == len(case["input"]["commands"])
    for command, observed in zip(case["input"]["commands"], result["clockSteps"], strict=True):
        assert all(observed[key] == value for key, value in command.items())
    options = result["memoryDispatches"][0]["options"]
    assert {"maxResults", "minScore", "sources", "signalPresent", "partialCallbackPresent",
            "deadlineControlPresent", "onDebugPresent"} == options.keys()
    assert all(options[field] is True for field in (
        "signalPresent", "partialCallbackPresent", "deadlineControlPresent", "onDebugPresent",
    ))
    assert result["clockSteps"][-1]["dispatchCounts"] == {"memory": 2, "wiki:alpha": 2}


def test_raw_evidence_retains_original_envelopes_timer_events_and_global_interleaving(tmp_path):
    result = _run("accepted-partial-late-update-explicit-recovery", evidence_directory=tmp_path)
    (raw,) = json.loads((tmp_path / "python-raw.json").read_text())
    assert raw["managerFixture"] is True and raw["constructorSkipped"] is True
    assert raw["timerEvents"] and raw["memoryOptionSurfaces"]
    assert raw["clockSteps"] == result["clockSteps"]
    for public, original in zip(result["calls"], raw["pythonEnvelopes"], strict=True):
        assert isinstance(original["result"]["content"][0]["text"], str)
        assert decode_search_tool_envelope(original["result"]) == public["result"]
    for lane, events in result["lanes"].items():
        assert [{key: value for key, value in event.items() if key != "lane"}
                for event in raw["globalEvents"] if event["lane"] == lane] == events


def test_get_wiki_deadline_keeps_late_provider_result_out_and_allows_explicit_recovery():
    result = _run("get-wiki-owned-timeout-late-result-and-recovery")
    expired, recovered = map(_payload, result["calls"])
    assert expired["timedOut"] is True and expired["timeoutMs"] == 30_000
    assert expired["text"] == "" and "status" not in expired
    assert recovered["status"] == "ok" and recovered["text"] == "Fresh wiki excerpt."
    assert recovered["opaque"] == [None, False] and "warning" not in recovered
    assert result["memoryDispatches"] == [] and len(result["wikiDispatches"]["alpha"]) == 2
    assert result["wikiDispatches"]["alpha"][0] == {
        "lookup": "wiki/cedar", "fromLine": 1, "lineCount": 2, "agentId": "main",
    }


def test_native_builtin_get_pre_abort_behavior_and_all_abort_recovery_use_real_files(tmp_path):
    builtin = _run("get-builtin-pre-aborted-read-remains-unguarded", evidence_directory=tmp_path)
    assert _payload(builtin["calls"][0])["status"] == "ok"
    assert _payload(builtin["calls"][0])["text"] == "Builtin memory."
    (raw,) = json.loads((tmp_path / "python-raw.json").read_text())
    assert raw["managerFixture"] is False and raw["constructorSkipped"] is False
    assert raw["managerAcquisition"] == "not-required" and raw["indexManagerConstructed"] is False
    assert bytes(raw["files"]["MEMORY.md"]) == b"Builtin memory.\n"
    assert raw["memoryOptionSurfaces"] == []
    result = _run("get-all-parent-abort-and-later-explicit-query")
    assert result["calls"][0]["error"]["code"] == "CALLER_STOP"
    fresh = _payload(result["calls"][1])
    assert fresh["text"] == "Builtin memory." and "warning" not in fresh
    assert all(corpus["outcome"] == "ok" for corpus in fresh["corpora"])


def test_get_runtime_family_uses_harness_dispatch_and_retains_complete_evidence(tmp_path):
    from equivalence.cases import run_python

    for case in build_deadline_contract_cases():
        if case["input"].get("toolName") != "memory_get":
            continue
        routed = deepcopy(case)
        directory = tmp_path / case["id"]
        routed["_diagnosticDirectory"] = directory
        result = run_python(routed)
        (raw,) = json.loads((directory / "python-raw.json").read_text())
        assert raw["managerAcquisition"] == "not-required" and raw["indexManagerConstructed"] is False
        assert len(result["calls"]) == len(raw["pythonEnvelopes"])
        for public, original in zip(result["calls"], raw["pythonEnvelopes"], strict=True):
            if "result" in original:
                assert isinstance(original["result"]["content"][0]["text"], str)
                assert decode_search_tool_envelope(original["result"]) == public["result"]
            else:
                assert original == public


def test_unknown_operation_is_rejected():
    with pytest.raises(ValueError, match="Unsupported deadline-contract operation"):
        run_deadline_contract({"kind": "invented"})
