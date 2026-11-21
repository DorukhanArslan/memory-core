"""Register the fixed STORE and Doctor inputs and compare both protected batches once."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from equivalence import heartbeat_doctor_probe as doctor
from equivalence import heartbeat_scratch_probe as store
from equivalence.heartbeat_dependency import prepare_heartbeat_dependency
from equivalence.heartbeat_scratch_review import review_packets

OPERATION = "heartbeat-scratch-outcomes-runtime"
POINT = "heartbeat.scratch.outcomes"
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
        if (any(row.get(key) != value for key, value in case.items())
                or row.get("status") != "matched" or row.get("runtimeEvidenceValidated") is not True
                or evidence.get("matches") is not True or evidence.get("id") != case["input"]["fixture"]
                or evidence.get("nativeSha256") != evidence.get("sdkSha256")
                or not evidence.get("nativeSha256")
                or len(evidence.get("stdoutSha256", ())) != case["input"]["phases"]):
            return False
    return True


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
    rows = {}
    for case, observation in zip(cases, review["cases"], strict=True):
        rows[case["id"]] = {**case, "status": "matched" if observation["matches"] else "mismatched",
                            "referenceMode": "authenticated-official-release", "runtimeEvidenceValidated": True,
                            "heartbeatScratchEvidence": observation}
    return rows
