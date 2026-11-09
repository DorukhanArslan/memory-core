"""The exact executable capability for fixed heartbeat scratch diagnostics only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

APPROVED_NODE = {
    "nodeVersion": "v24.16.0", "icuVersion": "78.3", "unicodeVersion": "17.0",
    "sha256": "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd",
}
PROFILES = frozenset({"heartbeat-scratch-store", "heartbeat-scratch-doctor"})


def validate_heartbeat_node_authority(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"kind", "profile", "node"}
            or value["kind"] != "heartbeat-scratch-node-capability"
            or value["profile"] not in PROFILES):
        raise ValueError("Only the fixed heartbeat scratch profiles have this capability")
    node = value["node"]
    if (not isinstance(node, dict) or set(node) != {"execPath", *APPROVED_NODE}
            or not isinstance(node.get("execPath"), str) or not Path(node["execPath"]).is_absolute()
            or any(node.get(key) != expected for key, expected in APPROVED_NODE.items())):
        raise ValueError("Heartbeat scratch requires its exact approved Node, ICU and Unicode binary")
    return {"kind": value["kind"], "profile": value["profile"], "node": dict(node)}


def prepare_heartbeat_node_authority(executable: Path, profile: str) -> dict:
    if profile not in PROFILES:
        raise ValueError("An unrelated profile cannot borrow heartbeat scratch authority")
    executable = executable.resolve(strict=True)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    if digest != APPROVED_NODE["sha256"]:
        raise ValueError("The selected executable is not the approved heartbeat scratch Node binary")
    observed = subprocess.run(
        [str(executable), "--eval", "process.stdout.write(JSON.stringify({execPath:require('node:fs').realpathSync(process.execPath),nodeVersion:process.version,icuVersion:process.versions.icu,unicodeVersion:process.versions.unicode}))"],
        check=True, capture_output=True, text=True, timeout=10,
        env={"PATH": str(executable.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"},
    )
    node = {**json.loads(observed.stdout), "sha256": digest}
    if node.get("execPath") != str(executable) or hashlib.sha256(executable.read_bytes()).hexdigest() != digest:
        raise ValueError("The heartbeat scratch executable changed during authentication")
    return validate_heartbeat_node_authority({"kind": "heartbeat-scratch-node-capability", "profile": profile, "node": node})
