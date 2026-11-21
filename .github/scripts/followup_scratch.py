"""Replay the captured scratch family from the same original suite process."""
from pathlib import Path

from equivalence.heartbeat_scratch_review import review_packets
from equivalence.harness import _same_json


def replay_scratch(data, cases, args, runtime):
    if data.get("heartbeatScratchError") is not None:
        raise ValueError("Heartbeat scratch batch raised an error")
    root = (args.report.resolve().parent / "heartbeat-scratch-outcomes").resolve(strict=True)
    attempt = Path(data["heartbeatScratchEvidenceDirectory"]).resolve(strict=True)
    if list(root.iterdir()) != [attempt] or not attempt.is_dir() or not attempt.name.startswith("attempt-"):
        raise ValueError("Missing or ambiguous scratch evidence from this suite")
    review = review_packets(attempt / "doctor", attempt / "store")
    if review["total"] != 39 or len(cases) != review["total"] or review["acceptancePointsAwarded"] != 0:
        raise ValueError("Unexpected scratch fixture count or diagnostic credit")
    receipts = []
    for case, observed in zip(cases, review["cases"], strict=True):
        row = data["followupRows"][case["id"]]["case"]
        compact = {key: value for key, value in observed.items() if key not in {"openclaw", "python"}}
        if not observed["matches"] and not all(
                side in observed and _same_json(observed[side], row[side]) for side in ("openclaw", "python")):
            raise ValueError("Reopened scratch discrepancy differs from the stored whole outputs")
        if (observed["id"] != case["input"]["fixture"]
                or not _same_json(row["heartbeatScratchEvidence"], compact)
                or row["status"] != ("matched" if observed["matches"] else "mismatched")):
            raise ValueError("Physical scratch observations differ from the complete suite row")
        receipts.append({"id": case["id"], "publicMatch": observed["matches"], "receipt": compact})
    return receipts
