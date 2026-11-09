"""Exact executable authority for the reviewed model/redaction observations."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess


APPROVED_NODE_RUNTIME = {
    "nodeVersion": "v24.16.0", "icuVersion": "78.3", "unicodeVersion": "17.0",
    "sha256": "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd",
}


def validate_model_node_authority(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"execPath", *APPROVED_NODE_RUNTIME}
            or not isinstance(value.get("execPath"), str) or not Path(value["execPath"]).is_absolute()
            or any(value.get(key) != expected for key, expected in APPROVED_NODE_RUNTIME.items())):
        raise ValueError("Model boundary authority requires the exact approved Node/ICU/Unicode binary")
    return dict(value)


def prepare_model_node_authority(node: Path) -> dict:
    executable = Path(node).resolve(strict=True)
    before = hashlib.sha256(executable.read_bytes()).hexdigest()
    process = subprocess.run([str(executable), "--eval", "process.stdout.write(JSON.stringify({execPath:require('node:fs').realpathSync(process.execPath),nodeVersion:process.version,icuVersion:process.versions.icu,unicodeVersion:process.versions.unicode}))"],
        capture_output=True, text=True, check=True, timeout=10,
        env={"PATH": str(executable.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"})
    value = {**json.loads(process.stdout), "sha256": before}
    if value.get("execPath") != str(executable) or hashlib.sha256(executable.read_bytes()).hexdigest() != before:
        raise ValueError("The selected model boundary executable changed during authentication")
    return validate_model_node_authority(value)
