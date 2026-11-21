"""Register the fixed STORE and Doctor inputs and compare both protected batches once."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from equivalence import heartbeat_doctor_probe as doctor
from equivalence import heartbeat_scratch_probe as store
from equivalence.heartbeat_dependency import prepare_heartbeat_dependency
from equivalence.heartbeat_scratch_review import review_packets

OPERATION = "heartbeat-scratch-outcomes-runtime"
POINT = "heartbeat.scratch.outcomes"
SHA256 = re.compile(r"[0-9a-f]{64}")
STORE_DIGEST = "79ebb2a265c09022a743abaaea0485219b071076c2a8e467f80ae3a8e9d23725"
DOCTOR_DIGEST = "1c544112e9034ac4dd018e5afb70019b6945cc1f239a9304f81aa9764bc7053f"


def _digest(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def build_cases():
    cases = []
    for kind, corpus, expected in (("store", store.build_cases(), STORE_DIGEST),
                                   ("doctor", doctor.build_doctor_cases(), DOCTOR_DIGEST)):
        if _digest(corpus) != expected:
            raise ValueError(f"Heartbeat {kind} fixture corpus changed")
        for original in corpus:
            cases.append({"id": "heartbeat-scratch-outcomes-" + original["id"], "requirement": "heartbeat.scratch",
                          "operation": OPERATION, "covers": [POINT],
                          "input": {"profile": kind, "fixture": original["id"], "sha256": _digest(original),
                                    "phases": len(original["phases"])}})
    return cases


def validate_registration(cases):
    members = [row for row in cases if row["operation"] == OPERATION or POINT in row["covers"]]
    if members and members != build_cases():
        raise ValueError("Heartbeat scratch outcomes require every pinned STORE and Doctor fixture")


def family_complete(rows):
    members = [row for row in rows if row.get("operation") == OPERATION or POINT in row["covers"]]
    if not members:
        return False
    cases = build_cases()
    if len(cases) != len(members):
        return False
    for case, row in zip(cases, members, strict=True):
        evidence = row.get("heartbeatScratchEvidence", {})
        stdout = evidence.get("stdoutSha256", ())
        if (any(row.get(key) != value for key, value in case.items())
                or row.get("status") != "matched" or row.get("runtimeEvidenceValidated") is not True
                or evidence.get("matches") is not True or evidence.get("id") != case["input"]["fixture"]
                or evidence.get("nativeSha256") != evidence.get("sdkSha256")
                or not SHA256.fullmatch(str(evidence.get("nativeSha256")))
                or not isinstance(stdout, list) or len(stdout) != case["input"]["phases"]
                or any(not isinstance(pair, dict) or set(pair) != {"native", "sdk"}
                       or not all(isinstance(digest, str) and SHA256.fullmatch(digest) for digest in pair.values())
                       for pair in stdout)):
            return False
    return True


def _report_row(case, observation):
    evidence = observation.copy()
    row = {**case, "status": "matched" if evidence["matches"] else "mismatched",
           "referenceMode": "authenticated-official-release", "runtimeEvidenceValidated": True,
           "heartbeatScratchEvidence": evidence}
    if not evidence["matches"]:
        for field, checksum in (("openclaw", "nativeSha256"), ("python", "sdkSha256")):
            row[field] = evidence.pop(field)
            if _digest(row[field]) != evidence[checksum]:
                raise ValueError("Heartbeat scratch mismatch values differ from their reviewed projections")
    return row


def run_batch(checkout, node, runtime, directory):
    """Create and review fresh original and SDK observations in a unique attempt."""
    store.run(checkout, runtime, node, directory / "store")
    # Doctor loads one extra dependency. Leave the authenticated base installation
    # intact for the remainder of the suite and validate the private copy in run().
    with tempfile.TemporaryDirectory(prefix="heartbeat-doctor-runtime-") as temporary:
        private = Path(temporary) / "release-runtime"
        shutil.copytree(runtime, private, symlinks=True)
        archive = doctor.ROOT / ".reference/heartbeat-dependencies/archives/croner-10.0.1.tgz"
        prepare_heartbeat_dependency(checkout, private, archive, install=True)
        doctor.run(checkout, private, node, directory / "doctor", configured_state=True)
        review = review_packets(directory / "doctor", directory / "store")
    cases = build_cases()
    if [row["id"] for row in review["cases"]] != [case["input"]["fixture"] for case in cases]:
        raise ValueError("Heartbeat scratch review omitted or reordered a fixture")
    (directory / "review.json").write_text(json.dumps(review, indent=2, ensure_ascii=True) + "\n")
    return {case["id"]: _report_row(case, observation)
            for case, observation in zip(cases, review["cases"], strict=True)}
