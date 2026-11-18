"""Fixed end-to-end overflow scenarios for the pinned embedded run and the SDK host."""
from __future__ import annotations

from hashlib import sha256
import json

REQUIREMENT = "compaction.provider-overflow"
OPERATION = "provider-overflow-host-runtime"
POINTS = (REQUIREMENT + ".outcomes", REQUIREMENT + ".boundaries")
INITIAL_SIX = "77b7bd35784aae65eebd31c37fc1a47fb8a8c64a1d0de671bec0684b8dfe2160"
DIGEST = "01ada926fda02fa67ac56d666cfebe52900abe0015789403aedc8f3cfef493c1"
NOW = 1_777_824_000_000
ERROR = "Context length exceeded: requested 70000 tokens, maximum is 64000 tokens."


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def _definitions():
    short = [{"role": "user", "text": "A pear needs water."},
             {"role": "assistant", "text": "I recorded the pear."},
             {"role": "user", "text": "A second tree has flowers."},
             {"role": "assistant", "text": "Noted the flowers."}]
    long = [{"role": "user", "text": "In the north orchard, a pear tree was replanted beside the well. ", "repeat": 90},
            {"role": "assistant", "text": "I took notes on water, flowers and the winter crop. ", "repeat": 70},
            {"role": "user", "text": "A second tree now flowers. "},
            {"role": "assistant", "text": "I have recorded the flowers."}]
    common = {"clock": NOW, "contextWindow": 16000, "compaction": {"keepRecentTokens": 512},
              "history": [], "prompt": "Continue with the orchard.", "promptRepeat": 1,
              "fileRepeat": 1, "provider": "fixture-prompt-runtime-model", "model": "orchard-model",
              "sequence": [{"text": "Finished."}]}
    mid = {"keepRecentTokens": 512, "midTurnPrecheck": {"enabled": True}}
    inputs = {
        "advisory": {"prompt": "orchard branch ", "promptRepeat": 6800,
                     "sequence": [{"text": "The orchard received the full request."}]},
        "small-terminal": {"history": short, "contextWindow": 64000, "sequence": [{"error": ERROR}]},
        "compact-retry": {"history": long, "contextWindow": 64000,
                          "sequence": [{"error": ERROR}, {"text": "The orchard was compacted."},
                                       {"text": "This orchard is ready."}]},
        "midturn-terminal": {"compaction": mid, "fileRepeat": 12000,
                             "prompt": "Inspect the orchard, then close the notebook. ", "promptRepeat": 1150,
                             "sequence": [{"read": 1}]},
        "midturn-truncate": {"compaction": mid, "fileRepeat": 9000, "prompt": "Review the orchard.",
                             "sequence": [{"read": 8}, {"text": "The orchard is open."}]},
        "canonical-checkpoint": {"provider": "openai", "model": "gpt-5.4", "checkpoint": "retained",
                                 "prompt": "Reopen the orchard boundary. ", "promptRepeat": 4200,
                                 "sequence": []},
    }
    inputs["canonical-recover"] = {**inputs["canonical-checkpoint"], "outerRecovery": True,
                                   "sequence": [{"text": "Ready."}, {"text": "Ready."}, {"text": "Ready."}]}
    return [{"id": "provider-overflow-" + name, "requirement": REQUIREMENT, "operation": OPERATION,
             "covers": list(POINTS), "input": {**common, **value},
             "driverScope": "Pinned original embedded run with a real transcript, model transport, compaction, "
                            "truncation and an agent-owned read tool. The retained-checkpoint case invokes original "
                            "embedded prompt preflight with an official OpenAI Responses checkpoint. The SDK uses "
                            "the public host's model and summary callbacks with durable session storage.",
             "normalizationPolicy": "Compare provider and summary dispatches, recovery actions, exact continuation "
                                    "and terminal outcome, complete protected tool result contents and persisted request "
                                    "admissions. Retain complete backend-specific raw requests, transcript and warnings."}
            for name, value in inputs.items()]


def build_cases():
    cases = _definitions()
    if sha256(wire(cases[:-1])).hexdigest() != INITIAL_SIX or sha256(wire(cases)).hexdigest() != DIGEST:
        raise ValueError("The complete ordered provider overflow inputs changed")
    return cases


def members(rows):
    return [r for r in rows if r.get("operation") == OPERATION or set(POINTS) & set(r.get("covers", ()))]


def validate_registration(rows):
    found = members(rows)
    if found and wire(found) != wire(build_cases()):
        raise ValueError("Provider overflow requires the complete ordered family")


def family_complete(rows):
    cases = build_cases()
    found = members(rows)
    return len(found) == len(cases) and all(row.get("status") == "matched" and row.get("runtimeEvidenceValidated") is True
        and all(row.get(k) == v for k, v in case.items()) for row, case in zip(found, cases, strict=True))
