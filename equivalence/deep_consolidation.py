"""Literal model decisions for the original whole deep consolidation operation."""
from copy import deepcopy
import hashlib
import json

from equivalence.promotion_apply_family import build_cases as build_apply_cases, case_wire

OPERATION = "deep-consolidation-runtime"
REQUIREMENT = "promotion.deep-consolidation"
POINTS = tuple(f"{REQUIREMENT}.{kind}" for kind in ("outcomes", "boundaries"))
SCOPE = (
    "One genuine apply over a live daily file and a persisted recall store per case. "
    "Compare the complete caller result, actual model request and literal reply, both "
    "memory files, recall state, host events, saved preimages and per-agent origin rows "
    "before and after settlement. Only the owned temporary fixture root is mapped. "
    "The unchanged eight-case promotion apply family has separate coverage."
)
ACTION_CASES = ("added", "merged", "superseded", "unsafe-loss", "unrelated-prior",
                "invalid-reply", "concurrent-edit")
OLD_KEY = "memory:memory/2026-05-01.md:7:7"
LINEAGE = "preferred-exercise"
OLD_FACT = "- The preferred exercise is swimming before breakfast."
FACT = "- The preferred exercise is running before breakfast."
KEPT = ("- The existing bus pass is blue.", "- The saved map is in the pantry.",
        "- The bicycle has a silver bell.")


def build_cases():
    template = build_apply_cases()[-1]["input"]
    rows = []
    for name in ACTION_CASES:
        value = deepcopy(template)
        candidate = value["candidates"][0]
        key = candidate["key"]
        entry = value["recall"]["entries"][key]
        has_lineage = name == "superseded"
        prior = OLD_FACT if has_lineage else FACT
        memory = ["# Personal notes", "", *KEPT]
        if name not in {"added", "concurrent-edit"}:
            if has_lineage:
                memory.append(f"<!-- openclaw-memory-lineage:{LINEAGE} -->")
            memory.extend((f"<!-- openclaw-memory-promotion:{OLD_KEY} -->", prior))
        value["files"] = {"MEMORY.md": "\n".join(memory) + "\n",
                          candidate["path"]: "# Source facts\n\n" + FACT + "\n"}
        for observed in (entry, candidate):
            observed["snippet"] = FACT
            if has_lineage:
                observed["provenance"]["supersedesKey"] = LINEAGE
        value["kind"] = "deep-consolidation"
        value["originSeeds"] = [
            {"entryKey": parent_key, "agentId": "main", "sessionId": session,
             "sessionKey": f"agent:main:{session}", "originClass": "agent",
             "observedAt": value["nowMs"] - offset}
            for parent_key, session, offset in (
                (OLD_KEY, "prior-session", 2000), (key, "current-session", 1000))]
        action = {"added": "added", "concurrent-edit": "added", "superseded": "superseded"}.get(name, "merged")
        prior_entries = [] if action == "added" else [KEPT[1] if name == "unrelated-prior" else prior]
        plan = {"operations": [{"candidateKey": key, "action": action, "priorEntries": prior_entries}]}
        completion = value["completion"]
        completion["text"] = "not a JSON plan" if name == "invalid-reply" else json.dumps(plan, separators=(",", ":"))
        if name == "unsafe-loss":
            value["options"]["maxPriorEntryLossFraction"] = 0.24  # one out of four
        if name == "concurrent-edit":
            completion["mutationsBeforeReturn"] = [{"operation": "append-file", "path": "MEMORY.md",
                                                    "text": "- The live edit must survive.\n"}]
        rows.append({"id": f"deep-consolidation-{name}", "operation": OPERATION,
                     "requirement": REQUIREMENT, "covers": list(POINTS), "input": value, "driverScope": SCOPE})
    return rows


CASE_HASHES = {'deep-consolidation-added': 'f74f8724207fdb9a113b842254c7b8e878396a2dc5d6b8ed2c14c643e66e969f',
 'deep-consolidation-merged': 'c3fc863aac8d05cc72d5c595ea8037b09de9e337076ce2ff3183e965ab4c54bf',
 'deep-consolidation-superseded': 'badeb3ed9089f4618f04f0479ecb51284b54c63ecd2453db6f9b995ae8ba2ff1',
 'deep-consolidation-unsafe-loss': 'be64165bc04667a425e963f279ac9797c56e40ddf8d6fb1d4492654b34bece4b',
 'deep-consolidation-unrelated-prior': 'dd90f9559aacaf1fed226c0e699ab97cd184aef6136abff3d84f6a6b0777566f',
 'deep-consolidation-invalid-reply': '1a4794ac86ad14d7357b7058d63b5ecc82160a9c9781d7d6a2229b663e2a93ea',
 'deep-consolidation-concurrent-edit': 'bd5da515f2cd84573b1942f8d0eb9c68d8293f45d950d9b010b0c94778193275'}


def validate_case(case):
    if (case.get("requirement") != REQUIREMENT or case.get("operation") != OPERATION
            or case.get("covers") != list(POINTS) or case.get("driverScope") != SCOPE
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES.get(case.get("id"))):
        raise ValueError("Unregistered deep consolidation input, scope or coverage")
    return case


def _members(cases):
    return [case for case in cases if case.get("operation") == OPERATION
            or case.get("id") in CASE_HASHES or set(POINTS).intersection(case.get("covers", ()))]


def validate_registration(cases):
    family = _members(cases)
    if family and [row["id"] for row in family] != list(CASE_HASHES):
        raise ValueError("Deep consolidation requires its whole ordered family")
    for case in family:
        validate_case(case)


def family_complete(rows):
    members = _members(rows)
    if [row["id"] for row in members] != list(CASE_HASHES):
        return False
    try:
        for row in members:
            validate_case(row)
            if row.get("status") != "matched" or row.get("runtimeEvidenceValidated") is not True:
                return False
    except (ValueError, KeyError, TypeError):
        return False
    return True
