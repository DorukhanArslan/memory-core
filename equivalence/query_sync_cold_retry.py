"""Frozen input-only, zero-credit probes of cold automatic retry.

This standalone development packet is not registered as acceptance evidence.
Original query-sync boundaries remain unverified until their whole policy is
covered; these two schedules cannot borrow coverage from the outcome family.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "query-sync-boundary-development-runtime"
REQUIREMENT = "indexing.query-sync"
MANIFEST = Path(__file__).resolve().parents[1] / "docs/query_sync_cold_retry_development_literals.json"
MANIFEST_SHA256 = "1a374d6f1f54a3b59d033bf56014b21e6d8c0bde268277f64d030104b6a3fa1f"
CASE_HASHES = {
    "query-sync-boundary-development-cold-clean-control":
        "632c3a2cde15ebe5aafb4bdd0396ad2dd59e35e3732814d24661acc57cb1958f",
    "query-sync-boundary-development-cold-refusal-recovery":
        "37119fa8ece9b513e7766252aa6691374fd0a8bcfd1a1cfe5cda21d12c75c9af",
}


def case_wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def validate_case(case):
    if (not isinstance(case, dict)
            or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION or case.get("requirement") != REQUIREMENT
            or case.get("covers") != [] or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Cold retry development requires an exact frozen zero-credit input")
    return deepcopy(case)


def build_cases():
    payload = MANIFEST.read_bytes()
    if hashlib.sha256(payload).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Cold retry development manifest changed after input freeze")
    manifest = json.loads(payload)
    if (manifest["kind"] != "query-sync-cold-retry-development-literals"
            or manifest["acceptancePointsAwarded"] != 0 or manifest["registered"] is not False
            or [case.get("id") for case in manifest["cases"]] != list(CASE_HASHES)):
        raise ValueError("Cold retry development requires its complete two-input packet")
    return [validate_case(case) for case in manifest["cases"]]


def query_labels(value):
    """Use the ordered steps; JSON object member order does not schedule work."""
    labels = [step["label"] for step in value["steps"]
              if step["operation"] == "public-memory-search"]
    if len(labels) != len(set(labels)) or set(labels) != set(value["queries"]):
        raise ValueError("Each frozen public query must occur once in the ordered steps")
    return labels
