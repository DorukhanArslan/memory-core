"""Guard the interruption score against altered inputs and false successful writes."""
from copy import deepcopy

import pytest

from equivalence import interrupted_turn_acceptance as family
from memory_core.replay_repair import DEFAULT_MISSING_TOOL_RESULT_TEXT


def test_registration_rejects_dropping_the_cut_or_retargeting_a_failed_write():
    cases = family.build_cases()
    family.validate_registration(cases)
    with pytest.raises(ValueError, match="all four"):
        family.validate_registration(cases[:-1])
    cases[-1]["input"]["followup"]["write"]["relativePath"] = "memory/2026-11-10.md"
    with pytest.raises(ValueError, match="all four"):
        family.validate_registration(cases)


def test_a_delivered_reply_and_successful_call_id_do_not_prove_the_requested_note_was_saved():
    case = next(case for case in family.build_cases() if case["id"].endswith("edited-new-write"))
    request = case["input"]
    original, step = request["original"], request["followup"]
    cut = {"files": {"original": original["content"], "independent": None},
           "originalCalls": [original["callId"]], "originalResults": []}
    reopen = deepcopy(cut)
    reopen["files"]["original"] = request["externalEdit"]
    final = deepcopy(reopen)
    missing = {"id": original["callId"], "isError": True,
               "content": [{"type": "text", "text": DEFAULT_MISSING_TOOL_RESULT_TEXT}]}
    observation = {"cut": cut, "reopen": reopen, "final": final, "firstModelOriginalResults": [missing],
                   "newTurnToolCalls": [step["write"]["callId"]], "replies": [step["reply"]]}
    assert not family.confirms_boundary(case, observation)
    final["files"]["independent"] = step["write"]["content"]
    assert family.confirms_boundary(case, observation)
    missing["isError"] = 1
    assert not family.confirms_boundary(case, observation)
