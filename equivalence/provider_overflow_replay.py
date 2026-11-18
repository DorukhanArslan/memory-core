"""Independently reconstruct every admitted request, summary, tool result and terminal from disk."""
from __future__ import annotations

import json
from pathlib import Path

from equivalence.provider_overflow_cases import build_cases, wire
from equivalence.provider_overflow_native import digest, read_native


def review_pair(case, native_record, original, sdk, directory, sdk_sha, implementation):
    native = Path(native_record["evidenceDirectory"])
    if native_record["validationStatus"] != "verified" or directory.parent != native.parent:
        raise ValueError("Original and SDK overflow attempts must be retained separately under the family")
    packet = {"id": case["id"], "nativeDirectory": native.name, "sdkDirectory": directory.name,
              "nativeRawSha256": native_record["sha256"], "sdkRawSha256": sdk_sha, "implementation": implementation,
              "original": original, "sdk": sdk}
    (directory / "review.json").write_bytes(wire(packet))
    replay(packet, directory.parent)


def replay(packet, root):
    from equivalence.provider_overflow_sdk import read_sdk

    [case] = [c for c in build_cases() if c["id"] == packet["id"]]
    root = Path(root).resolve()
    actual = {}
    for side, loader, key, filename in (("native", read_native, "original", "native-raw.json"),
                                        ("sdk", read_sdk, "sdk", "python-raw.json")):
        name = packet[side + "Directory"]
        if not name.startswith(side + "-attempt-") or Path(name).name != name:
            raise ValueError("Unexpected retained overflow attempt directory")
        path = root / name
        raw_file = path / filename
        if raw_file.resolve(strict=True) != raw_file or not raw_file.is_file():
            raise ValueError("Overflow evidence file escapes its owner")
        data = raw_file.read_bytes()
        if digest(data) != packet[side + "RawSha256"]:
            raise ValueError("Corrupt overflow producer stream")
        [capture] = json.loads(data)
        observed = loader(case, capture, path)
        if wire(observed) != wire(packet[key]):
            raise ValueError("Overflow public output differs from its physical producer")
        actual[key] = observed
    # Distinct valid results must remain visible to the harness as mismatches.
    return actual
