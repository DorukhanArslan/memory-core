"""One clock and one sequence of independent writers for the two existing lock conditions."""

from copy import deepcopy
import hashlib
import json

REQUIREMENT = "concurrency.workspace-locks"
POINTS = (REQUIREMENT + ".outcomes", REQUIREMENT + ".boundaries")
OPERATION = "workspace-lock-process-runtime"
EPOCH = 1_780_001_000_000

# Each holder first enters a real lease and appends a line in its critical section.
# Killing a holder leaves the lease where the original owner wrote it.
DRIVES = {
    "ordered-writers": ("same", "release", 1, "wait"),
    "different-workspaces": ("other", "release", 1, "independent"),
    "fresh-owner-timeout": ("same", "hold", 1, "timeout"),
    "old-live-owner": ("same", "hold", 60_001, "timeout"),
    "dead-owner-at-threshold": ("same", "kill", 60_000, "at-threshold"),
    "dead-owner-past-threshold": ("same", "kill", 60_001, "takeover"),
    "live-reused-process-id": ("same", "replace-start-time", 60_001, "takeover"),
}


def build_cases():
    return [{
        "id": "workspace-lock-" + label,
        "requirement": REQUIREMENT, "operation": OPERATION, "covers": list(POINTS),
        "input": {"epochMs": EPOCH, "workspace": workspace, "holder": action,
                  "ageMs": age, "drive": drive, "lines": ["first writer\n", "second writer\n"]},
    } for label, (workspace, action, age, drive) in DRIVES.items()]


def _wire(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


DEFINITION_SHA256 = 'febb264f8b7b0c4dc8354f61ea491a1c9fe5f12b3a926655181cf1e73b1c1595'


def validate_registration(cases):
    definitions = build_cases()
    if hashlib.sha256(_wire(definitions)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("Workspace lock drives changed")
    family = [row for row in cases if row["operation"] == OPERATION or row["requirement"] == REQUIREMENT
              or set(row["covers"]).intersection(POINTS)]
    if family and _wire(family) != _wire(definitions):
        raise ValueError("Both workspace lock conditions require every independent process drive")


def family_complete(rows):
    family = [row for row in rows if row["operation"] == OPERATION or row["requirement"] == REQUIREMENT
              or set(row["covers"]).intersection(POINTS)]
    if not family or any(row.get("status") != "matched" or row.get("workspaceLockEvidenceValidated") is not True
                         for row in family):
        return False
    try:
        validate_registration([{key: deepcopy(row[key]) for key in definition}
                               for row, definition in zip(family, build_cases(), strict=True)])
    except (ValueError, KeyError, TypeError):
        return False
    return True
