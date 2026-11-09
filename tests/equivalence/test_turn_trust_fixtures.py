"""Shared literal requests cannot pre-decide owner/taint/provenance outputs."""
import json

from equivalence.turn_trust_fixtures import build_turn_trust_cases


def test_turn_trust_inputs_are_literal_deterministic_json_and_uncredited():
    cases = build_turn_trust_cases()
    assert cases == build_turn_trust_cases()
    assert len({case["id"] for case in cases}) == len(cases) == 2
    assert json.loads(json.dumps(cases, ensure_ascii=False, allow_nan=False)) == cases
    assert all(case["covers"] == [] and case["input"]["kind"] == "turn-trust" for case in cases)
    identities = [response["turnId"] for case in cases for turn in case["input"]["turns"]
                  for attempt in turn["attempts"] for response in attempt["responses"]]
    assert all(identity.strip() for identity in identities) and len(set(identities)) == len(identities)
    for case in cases:
        for turn in case["input"]["turns"]:
            assert "tainted" not in turn and "initiallyTainted" not in turn
            assert turn["prompt"]["__openclaw"]["senderIsOwner"] == turn["senderIsOwner"]
            assert all("turnTainted" not in response.get("__openclaw", {})
                       for attempt in turn["attempts"] for response in attempt["responses"])


def test_scripts_cover_same_turn_retry_new_turn_nonowner_and_real_error_source():
    cases = build_turn_trust_cases()
    network = cases[0]["input"]
    assert len(network["turns"][0]["attempts"]) == 2
    calls = [block for turn in network["turns"] for attempt in turn["attempts"]
             for response in attempt["responses"] for block in response["content"] if block["type"] == "toolCall"]
    assert calls[0]["name"] == "web_fixture" and calls[1]["name"] == "write_memory"
    writes = [call["arguments"]["path"] for call in calls if call["name"] == "write_memory"]
    assert writes == ["memory/2026-11-10.md", "memory/2026-11-10.md", "memory/clean.md"]
    presentation, = network["turns"][1]["presentationObservations"]
    assert presentation["presentationOnly"] is True and presentation["resultContentSource"] == "network"
    assert presentation["argsHash"] == presentation["resultHash"] == ""
    assert "toolCallId" not in presentation
    failure = cases[1]["input"]
    assert failure["turns"][0]["senderIsOwner"] is False
    assert failure["tools"][-1]["resultContentSource"] == "network" and "error" in failure["tools"][-1]
    assert failure["turns"][1]["attempts"][0]["responses"][0]["content"][0]["name"] == "network_failure"
