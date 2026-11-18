"""Re-read both redaction callers from the exact archived streams and session database."""
import hashlib
import json
from pathlib import Path

from equivalence.harness import _same_json
from equivalence.secret_boundary_evidence import family_complete, replay_sdk
from equivalence.secret_boundary_inputs import build_cases
from secret_boundary_native import check_native


def replay_secret_boundaries(data, cases, args, runtime):
    parent = (args.report.parent / "secret-redaction").resolve(strict=True)
    receipts = []
    for case in cases:
        capture = data["followupRows"][case["id"]]
        row = capture["case"]
        directory = Path(row["sdkEvidenceDirectory"])
        if directory.parent.name != parent.name or not directory.name.startswith("sdk-attempt-"):
            raise ValueError("Unexpected SDK redaction capture directory")
        folder = parent / directory.name
        path = folder / "python-raw.json"
        if path.resolve(strict=True) != path or not path.is_file() or path.stat().st_size > 16 * 1024**2:
            raise ValueError("Invalid retained SDK redaction file")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        packets = json.loads(raw)
        sdk_trace = capture["python"]
        if (len(packets) != 1 or sdk_trace["side"] != "python" or sdk_trace["sha256"] != digest
                or not _same_json(sdk_trace["rawSnapshots"], packets)):
            raise ValueError("SDK process stream differs from the original report")
        sdk, sdk_receipt = replay_sdk(case, packets[0], folder)
        original = check_native(case, row["openclaw"], source_policy=capture.get("sourcePolicy"),
            native=capture.get("native"), trace=capture.get("trace"), reference=args.reference, node=args.node,
            release_runtime=runtime, release_sources=data["followupReleaseSources"], adapters=data["adapterSha256"])
        if (not row["secretBoundaryEvidenceValidated"] or not _same_json(sdk, row["python"])
                or not _same_json(sdk, row["openclaw"])):
            raise ValueError("Complete public redaction returns differ from the replayed evidence")
        receipts.append({"id": case["id"], "publicMatch": True, "sdkFileSha256": digest,
                         "sdk": sdk_receipt, "native": original})
    return receipts
