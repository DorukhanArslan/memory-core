"""Explicit scheduled memory tasks for the original automation boundary."""
from hashlib import sha256
import json

OPERATION = "automation-job-state-runtime"
REQUIREMENT = "automation.job-state"
POINT = REQUIREMENT + ".boundaries"
CASE_ID = "automation-job-state-explicit-memory-task"
NOW = 1_767_225_600_000
INTERVAL = 60_000
NOTICE = "memory/notice.md"
TASKS = "memory/tasks.md"
DIGEST = "7bd09fb0b101b477d1288128993ab5b30c618e8e0925811432bbb2141ef904e3"


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _definition():
    def job(job_id, name, text, enabled=True):
        return {
            "id": job_id, "name": name, "enabled": enabled, "agentId": "main",
            "declarationKey": "heartbeat-task:main:" + job_id,
            "schedule": {"kind": "every", "everyMs": INTERVAL, "anchorMs": NOW + INTERVAL},
            "payload": {"kind": "systemEvent", "text": text},
        }

    def step(job_id, delta, writes=None):
        return {"jobId": job_id, "atMs": NOW + delta, "writes": writes or {}}

    left, right, disabled, missing = "job-cedar", "job-birch", "job-pine", "job-ash"
    return {
        "id": CASE_ID, "requirement": REQUIREMENT, "operation": OPERATION, "covers": [POINT],
        "input": {
            "nowMs": NOW,
            "files": {NOTICE: "Release board\nCedar moves on Thursday.", TASKS: "Birch has two follow-ups."},
            "jobs": [
                job(left, "notice", "Read the second line of the release board."),
                job(right, "tasks", "Read today's follow-ups."),
                job(disabled, "paused", "Read the paused checklist.", False),
                job(missing, "archive", "Look up an archived note."),
            ],
            "toolCalls": {
                left: {"path": NOTICE, "from": 2, "lines": 1},
                right: {"path": TASKS, "from": 1, "lines": 1},
                disabled: {"path": NOTICE, "from": 1, "lines": 1},
                missing: {"path": "memory/archive.md", "from": 1, "lines": 1},
            },
            "steps": [
                step(left, INTERVAL - 1), step(left, INTERVAL), step(left, INTERVAL + 1),
                step(right, INTERVAL + 1), step(disabled, INTERVAL + 1), step(missing, INTERVAL + 1),
                step(left, 2 * INTERVAL, {NOTICE: "Release board\nCedar moves on Friday."}),
            ],
        },
        "driverScope": "Explicit due-mode execution of stored recurring main-agent heartbeat tasks. "
                       "Each step reopens the store and invokes the actual memory reader on a delivered task. "
                       "No operating-system scheduler or language model participates.",
        "normalizationPolicy": "Compare every scheduled task wake, memory-read argument and complete result, "
                               "plus the full supplied workspace file contents after each drive. "
                               "Retain side-specific run receipts and persisted job state separately.",
    }


def build_cases():
    case = _definition()
    if sha256(wire(case)).hexdigest() != DIGEST:
        raise ValueError("The scheduled memory task definition changed")
    return [case]


def validate_case(case):
    if wire(case) != wire(build_cases()[0]):
        raise ValueError("An explicit scheduled memory task must use the complete frozen scenario")


def _family(rows):
    return [row for row in rows if row.get("id") == CASE_ID or row.get("operation") == OPERATION
            or POINT in row.get("covers", ())]


def validate_registration(cases):
    family = _family(cases)
    if family and wire(family) != wire(build_cases()):
        raise ValueError("The scheduled memory task condition requires its complete unchanged scenario")


def family_complete(rows):
    family = _family(rows)
    if len(family) != 1:
        return False
    row = family[0]
    try:
        validate_case({key: row[key] for key in build_cases()[0]})
        return row.get("status") == "matched" and row.get("runtimeEvidenceValidated") is True
    except (KeyError, ValueError, TypeError):
        return False
