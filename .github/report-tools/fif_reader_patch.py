#!/usr/bin/env python3
"""Make an external diagnostic-reader copy; never modify frozen source/report bytes."""
import hashlib
import json
from pathlib import Path
import sys

ORIGINAL_SHA256 = "7df457b0783fbc550558692e37ebb21ad772e5a0d10b910788cc638e4f83a26c"
REPLACEMENTS = [
    ("ROOT = Path(__file__).resolve().parents[1]",
     'ROOT = Path(os.environ.get("MEMORY_CORE_REPLAY_SOURCE_ROOT", str(Path(__file__).resolve().parents[1]))).resolve(strict=True)'),
    ('"registeredCases": 1465, "priorDefinitionsSha256": OLD_DEFINITIONS_SHA256,',
     '"registeredCases": len(cases), "priorDefinitionsSha256": OLD_DEFINITIONS_SHA256,'),
    ("or case_index != 1465 or requirements_index != 64 or len(selected) != 13",
     "or case_index != len(definitions) or requirements_index != 64 or len(selected) != 13"),
    ("or len(groups[0] + groups[1]) != 1465",
     "or len(groups[0] + groups[1]) != len(definitions)"),
    ('or suite["definitionMigration"]["fifVersion"] == "v6"\n            and not _same_json(metadata.get("definitionMigration"), suite["definitionMigration"])',
     'or suite["definitionMigration"]["fifVersion"] == "v6"\n            and "definitionMigration" in metadata\n            and not _same_json(metadata.get("definitionMigration"), suite["definitionMigration"])'),
    ('report["sourceReports"].append({"mode": "registered-suite", "report": sealed, "registeredCases": 1465,',
     'report["sourceReports"].append({"mode": "registered-suite", "report": sealed, "registeredCases": len(definitions),'),
]


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: fif_reader_patch.py ORIGINAL OUTPUT RECEIPT")
    original = Path(sys.argv[1]).resolve(strict=True)
    output = Path(sys.argv[2]).absolute()
    receipt = Path(sys.argv[3]).absolute()
    if len({original, output.resolve(), receipt.resolve()}) != 3:
        raise SystemExit("Original, corrected copy and receipt paths must be distinct")
    if output.exists() or receipt.exists() or output.is_symlink() or receipt.is_symlink():
        raise SystemExit("Output and receipt must be new paths")
    before = original.read_bytes()
    original_sha256 = hashlib.sha256(before).hexdigest()
    if original_sha256 != ORIGINAL_SHA256:
        raise SystemExit("Original reader differs from reviewed source 9669482")
    corrected = before
    counts = []
    for old, new in REPLACEMENTS:
        old_bytes, new_bytes = old.encode(), new.encode()
        observed = corrected.count(old_bytes)
        if observed != 1:
            raise SystemExit("Exact reviewed replacement count differs: " + old)
        corrected = corrected.replace(old_bytes, new_bytes, 1)
        counts.append({"old": old, "new": new, "count": observed})
    if b"1465" in corrected:
        raise SystemExit("A stale reader catalog count remains")
    if original.read_bytes() != before:
        raise SystemExit("Original reader changed during correction")
    with output.open("xb") as stream:
        stream.write(corrected)
    record = {
        "kind": "external-diagnostic-reader-correction",
        "sourceCommit": "9669482d4510b23479c4fe51d99151d40f3e7a68",
        "original": {"path": str(original), "bytes": len(before), "sha256": original_sha256},
        "corrected": {"path": str(output), "bytes": len(corrected), "sha256": hashlib.sha256(corrected).hexdigest()},
        "replacementCount": len(counts),
        "replacements": counts,
        "sourceRootEnvironmentVariable": "MEMORY_CORE_REPLAY_SOURCE_ROOT",
        "frozenSourceUnchanged": original.read_bytes() == before,
        "reportBytesModified": False,
        "metadataOmissionPolicy": "Preserve actual report field absence; if definitionMigration is present require exact equality. The reader still authenticates complete exact streamed definitions, frozen definition_authority, and report/source seals.",
    }
    if not record["frozenSourceUnchanged"]:
        raise SystemExit("Original reader changed before receipt")
    with receipt.open("x") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
