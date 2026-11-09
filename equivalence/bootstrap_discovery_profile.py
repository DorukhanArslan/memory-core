"""Narrow compiled bootstrap caller scope and its exact Node executable."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess


OPERATION = "bootstrap-discovery-runtime"
APPROVED_BOOTSTRAP_NODE = {
    "nodeVersion": "v24.16.0", "icuVersion": "78.3", "unicodeVersion": "17.0",
    "sha256": "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd",
}


def validate_bootstrap_node_authority(value):
    if (not isinstance(value, dict) or set(value) != {"execPath", *APPROVED_BOOTSTRAP_NODE}
            or not isinstance(value.get("execPath"), str) or not Path(value["execPath"]).is_absolute()
            or any(value.get(key) != expected for key, expected in APPROVED_BOOTSTRAP_NODE.items())):
        raise ValueError("Bootstrap discovery requires the exact approved Node/ICU/Unicode binary")
    return deepcopy(value)


def prepare_bootstrap_node_authority(node: Path):
    executable = Path(node).resolve(strict=True)
    before = hashlib.sha256(executable.read_bytes()).hexdigest()
    process = subprocess.run([str(executable), "--eval", "process.stdout.write(JSON.stringify({execPath:require('node:fs').realpathSync(process.execPath),nodeVersion:process.version,icuVersion:process.versions.icu,unicodeVersion:process.versions.unicode}))"],
        capture_output=True, text=True, check=True, timeout=10,
        env={"PATH": str(executable.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"})
    value = {**json.loads(process.stdout), "sha256": before}
    if value.get("execPath") != str(executable) or hashlib.sha256(executable.read_bytes()).hexdigest() != before:
        raise ValueError("The bootstrap executable changed while its identity was observed")
    return validate_bootstrap_node_authority(value)


def validate_bootstrap_discovery_profile(value):
    if (not isinstance(value, dict) or set(value) != {"kind", "operation", "inputKind", "nodeRuntime"}
            or value.get("kind") != "approved-bootstrap-discovery-profile"
            or value.get("operation") != OPERATION or value.get("inputKind") != "workspace-bootstrap"):
        raise ValueError("Only the declared compiled workspace-bootstrap caller may use this capability")
    validate_bootstrap_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_bootstrap_discovery_profile(node: Path):
    return validate_bootstrap_discovery_profile({"kind": "approved-bootstrap-discovery-profile",
        "operation": OPERATION, "inputKind": "workspace-bootstrap", "nodeRuntime": prepare_bootstrap_node_authority(node)})
