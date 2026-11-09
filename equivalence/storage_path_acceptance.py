"""Closed registration for the independently reviewed fixed #2 whole-tool proof.

Both acceptance conditions require every literal reviewed family and all 99
original calls. Historical uncredited packets remain valid diagnostics; they
cannot acquire credit merely by changing their report metadata.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


STORAGE_PATH_ACCEPTANCE_POINTS = (
    "storage.path-safety.outcomes",
    "storage.path-safety.boundaries",
)

# Canonical input digests come from the unchanged corrected11 Native packet,
# d9ffe25b271e06fe961072bf272a314531713ab45ac7c356dd0e1ff923472a0f.
REVIEWED_STORAGE_PATH_FAMILIES = {
    "storage-path-contract-root-relative-and-absolute": (17, "d002004d84388cd5b2c21e9f33098c08a1df1b8490bd19131fca9a464ac82ce0"),
    "storage-path-contract-traversal-and-missing": (17, "35e2d6b810076a81a9112ab57eacad0f31157d6aec735e063d772af049c5c7e3"),
    "storage-path-contract-encoded-literals-and-raw-boundaries": (13, "b3aff20448fbdae24e1c2e6c8407bc3250680406f7c244f7300901d894690dc5"),
    "storage-path-contract-symlink-admission": (13, "a87c78ffbf4bfa951fa446b181357b3a62bee8025a709b746c038546857d3095"),
    "storage-path-contract-symlink-loop-os-errors": (2, "d87836c6a04803e3a35975475c8248214e852ac12d3b109ed26ee38f098abb97"),
    "storage-path-contract-nonregular-and-hardlinks": (4, "9abc4260e194da762b016970d5d302e59cb492769cd514ee62b2a4fe623079f2"),
    "storage-path-contract-missing-workspace": (4, "edf15c683b7029f938d47abe42dc6f13fe1268d73345bfa4822fb1e5cf6c75da"),
    "storage-path-contract-workspace-is-file": (4, "716c2eb02a728731a069db63d65cc1127562c105bdadbfccc8c030c379061d0e"),
    "storage-path-contract-plain-extra-root-authority": (16, "158225da815633479c7c2ca0f4a4526ce321b975d6647b4ddd5e37845778fc9b"),
    "storage-path-contract-patterned-extra-root-admission": (8, "852c32fad5eeab0efc7698b7f52954d72ed23192dfd63bcc5f5a8a0ba4d04f42"),
    "storage-path-read-race-owned-leaf-to-symlink": (1, "7fea697bdb405372c4c3bb4e6eb6789004923224022ef54db7d780c073a490b7"),
}


def reviewed_storage_path_input_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                     separators=(",", ":")).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def validate_storage_path_acceptance_registration(cases: list[dict[str, Any]]) -> None:
    """Reject partial, substituted, helper-only or widened two-point claims."""
    points = set(STORAGE_PATH_ACCEPTANCE_POINTS)
    claiming = [case for case in cases if points.intersection(case.get("covers", []))]
    if not claiming:
        return
    if (len(claiming) != 11 or {case.get("id") for case in claiming} != set(REVIEWED_STORAGE_PATH_FAMILIES)):
        raise ValueError("Both path-safety conditions require all eleven reviewed whole-tool families")
    for case in claiming:
        count, digest = REVIEWED_STORAGE_PATH_FAMILIES[case["id"]]
        value = case.get("input")
        if (case.get("requirement") != "storage.path-safety"
                or case.get("operation") != "get-contract-runtime"
                or case.get("covers") != list(STORAGE_PATH_ACCEPTANCE_POINTS)
                or not isinstance(value, dict) or value.get("kind") != "tool"
                or value.get("observeFilesystem") is not True
                or value.get("normalizeFixturePaths") is not True
                or not isinstance(value.get("steps"), list) or len(value["steps"]) != count
                or reviewed_storage_path_input_sha256(value) != digest):
            raise ValueError("Path-safety credit requires each exact reviewed input, complete snapshots and both point IDs")
