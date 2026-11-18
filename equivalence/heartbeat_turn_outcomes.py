"""Frozen comparisons of scheduled heartbeat prompts, admission and delivery."""
from __future__ import annotations

from hashlib import sha256
import json

OPERATION = "heartbeat-turn-outcomes-runtime"
REQUIREMENT = "heartbeat.turn-decisions"
POINT = REQUIREMENT + ".outcomes"
NOW = 1_777_824_000_000
DIGEST = "c2d1fd87da4e8afd5c809147edff62c7da29f794ca331a7b04618c5a9bd9c673"


def wire(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _matrix():
    def step(label, *, source="interval", reason="interval", reply="NO_REPLY", **values):
        return {"label": label, "source": source, "reason": reason, "reply": reply, **values}

    def event(text, context):
        return {"text": text, "contextKey": context}

    orchard = "The orchard needs water."
    reminder = event("Reminder: inspect the pear trees.", "cron:pears")
    completion = event("Exec completed (watering, code 0) :: seven trees watered", "exec:watering")
    late = event("Reminder: the second orchard is due.", "cron:second")
    groups = {
        "monitor": [
            step("no-stored-scratch"),
            step("empty-scratch", scratch="# Monitor\n<!-- empty -->\n"),
            step("quiet-ack", scratch="- Inspect the orchard weather.\n", reply="HEARTBEAT_OK"),
            step("configured-prompt", prompt="Read the orchard weather report.", reply="NO_REPLY"),
            step("model-failed", error="orchard model fixture unavailable"),
            step("model-recovered", reply="NO_REPLY"),
            step("busy-lane", busy=True),
            step("disabled-cadence", every="0m"),
        ],
        "deliveries": [
            step("alert-target-none", source="manual", reason="wake", reply=orchard),
            step("alert-received", source="manual", reason="wake", target="local", reply=orchard),
            step("repeat-alert", source="manual", reason="wake", target="local", reply=orchard),
            step("quiet-no-reply", target="local", reply="NO_REPLY"),
            step("quiet-legacy", target="local", reply="HEARTBEAT_OK"),
            step("other-alert", target="local", reply="A different orchard needs water."),
        ],
        "event-queue": [
            step("empty-exec", source="exec-event", reason="exec-event"),
            step("competing-events", source="exec-event", reason="exec-event", events=[reminder, completion], late=[late]),
            step("remaining-reminders", source="cron", reason="cron"),
            step("empty-after-consumption", source="exec-event", reason="exec-event"),
            step("relayable-completion", source="exec-event", reason="exec-event", target="local", events=[completion]),
            step("awareness-ignored", source="exec-event", reason="exec-event",
                 events=[event("A heartbeat delivered this message.", "heartbeat-delivery:previous")]),
        ],
        "tasks": [
            step("two-due-one-future", scratch="# Scratch\n", tasks=[
                {"jobId": "zebra", "name": "Zebra", "prompt": "Check the south orchard.", "due": True},
                {"jobId": "apple", "name": "Apple", "prompt": "Check the north orchard.", "due": True},
                {"jobId": "later", "name": "Later", "prompt": "Check the store tomorrow.", "due": False}],
                 events=[event("HEARTBEAT_OK", "cron:noise")]),
            step("later-tick"),
        ],
    }
    return [{"id": "heartbeat-turn-outcomes-" + name, "requirement": REQUIREMENT,
             "operation": OPERATION, "covers": [POINT], "input": {"nowMs": NOW, "steps": steps},
             "driverScope": "Whole original runHeartbeatOnce with actual queue, channel delivery, model callback, and monitor storage. "
                            "SDK host executes its public heartbeat with the same scheduler observations and scripted replies.",
             "normalizationPolicy": "Compare run status, skip or failure reason, callback body and turn source, "
                                    "observed sends, remaining event occurrences, and completion status. "
                                    "Physical queue IDs retain their raw values and compare by common occurrence positions."}
            for name, steps in groups.items()]


def build_cases():
    cases = _matrix()
    if sha256(wire(cases)).hexdigest() != DIGEST:
        raise ValueError("Heartbeat outcome inputs changed")
    return cases


def members(rows):
    return [row for row in rows if row.get("operation") == OPERATION or POINT in row.get("covers", ())]


def validate_registration(rows):
    matches = members(rows)
    if matches and wire(matches) != wire(build_cases()):
        raise ValueError("Heartbeat outcomes require the complete ordered scenario family")


def family_complete(rows):
    cases = build_cases()
    observed = members(rows)
    return len(observed) == len(cases) and all(row.get("status") == "matched"
        and row.get("runtimeEvidenceValidated") is True and all(row.get(k) == v for k, v in case.items())
        for case, row in zip(cases, observed, strict=True))
