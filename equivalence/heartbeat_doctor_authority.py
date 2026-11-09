"""Mutually exclusive exact Node authority for original heartbeat Doctor calls."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

NODE = {"nodeVersion": "v24.16.0", "icuVersion": "78.3", "unicodeVersion": "17.0",
        "sha256": "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"}


def validate_doctor_authority(value):
    if (not isinstance(value, dict) or set(value) != {"kind", "profile", "node"}
            or value["kind"] != "heartbeat-doctor-node-capability" or value["profile"] != "heartbeat-scratch-doctor"):
        raise ValueError("Only original heartbeat Doctor execution has this capability")
    actual = value["node"]
    if (not isinstance(actual, dict) or set(actual) != {"execPath", *NODE}
            or not isinstance(actual.get("execPath"), str) or not Path(actual["execPath"]).is_absolute()
            or any(actual.get(key) != expected for key, expected in NODE.items())):
        raise ValueError("Doctor requires the exact approved Node, ICU and Unicode executable")
    return {"kind": value["kind"], "profile": value["profile"], "node": dict(actual)}


def prepare_doctor_authority(executable: Path):
    if os.environ.get("MEMORY_EQ_HEARTBEAT_CONTEXT") or os.environ.get("MEMORY_EQ_RELEASE_CONTEXT"):
        raise ValueError("Doctor authority cannot run inside STORE or release execution contexts")
    executable = executable.resolve(strict=True)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    if digest != NODE["sha256"]:
        raise ValueError("Doctor executable differs from its fixed approved bytes")
    result = subprocess.run([str(executable), "--eval", "process.stdout.write(JSON.stringify({execPath:require('node:fs').realpathSync(process.execPath),nodeVersion:process.version,icuVersion:process.versions.icu,unicodeVersion:process.versions.unicode}))"],
        capture_output=True, text=True, check=True, timeout=10,
        env={"PATH": str(executable.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"})
    observed = {**json.loads(result.stdout), "sha256": digest}
    if observed.get("execPath") != str(executable) or hashlib.sha256(executable.read_bytes()).hexdigest() != digest:
        raise ValueError("Doctor executable changed during authentication")
    return validate_doctor_authority({"kind": "heartbeat-doctor-node-capability", "profile": "heartbeat-scratch-doctor", "node": observed})
