"""Four literal formatter and genuine memory-tool failure scenarios."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import quote

from equivalence.trust_error_probe import _cases


ROOT = Path(__file__).resolve().parents[1]
OPERATION = "model-tool-error-runtime"
DECLARED_SECRETS = frozenset(secret for case in _cases() for secret in case["input"].get("registeredSecrets", []))
DECLARED_SURFACES = frozenset(surface for secret in DECLARED_SECRETS for surface in (
    secret, quote(secret, safe="-_.!~*'()"), json.dumps(secret, ensure_ascii=False)[1:-1]))


def build_tool_error_cases():
    return [{"id": "model-tool-" + case["id"], "requirement": "trust.secret-redaction", "covers": [],
             "operation": OPERATION, "input": deepcopy(case["input"]),
             "driverScope": (
                 "Actual shared error formatter and complete memory_get/memory_search factory execution over "
                 "real RegisteredMemoryCorpusSupplement callbacks throwing the declared recursive errors. "
                 "Fresh synthetic-only processes, genuine empty SQLite store and provider-none host config; "
                 "no fake manager, provider execution, reset hook or alternate error owner."
             ), "normalizationPolicy": (
                 "Complete formatter text and ordered tool name, original complete wire envelope, and verified "
                 "decoded envelope. Every content/detail/outer field, warning, error and JSON carrier string "
                 "is compared unchanged. No error rewriting, field projection, secret repair or cause removal. "
                 "Complete original causes/stacks, configuration, registry revisions and callback requests stay raw."
             )} for case in _cases()]


def validate_tool_error_input(value):
    if type(value) is not dict or not any(value == case["input"] for case in _cases()):
        raise ValueError("Only the four declared synthetic formatter/tool error inputs are admitted")


def assert_synthetic_error_registry(values):
    if not isinstance(values, (list, tuple)) or any(type(value) is not str or value not in DECLARED_SURFACES for value in values):
        raise ValueError("Undeclared error registry member; sensitive snapshot was not recorded")


def run_tool_error_profile(arguments, *, evidence_directory=None):
    validate_tool_error_input(arguments)
    value = deepcopy(arguments)
    with tempfile.TemporaryDirectory(prefix="python-model-tool-error-") as temporary:
        root = Path(temporary)
        request = {"input": value, "directory": str(root / "fixture")}
        request_json = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        argv = [sys.executable, "-m", "equivalence.tool_error_profile_phase"]
        environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                       "PYTHONPATH": str(ROOT), "LANG": "en_US.UTF-8", "TZ": "UTC",
                       "OPENCLAW_STATE_DIR": str(root / "fixture/state"),
                       "OPENCLAW_CONFIG_PATH": str(root / "fixture/openclaw.json"),
                       "OPENCLAW_HOME": str(root / "fixture")}
        raw = {"kind": "model-tool-error", "fixtureBase": str(root), "coordinatorPid": os.getpid(), "input": value,
               "child": {"request": request, "requestJson": request_json,
                         "requestSha256": hashlib.sha256(request_json.encode()).hexdigest(),
                         "argv": argv, "environmentKeys": sorted(environment)}}
        try:
            with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, cwd=ROOT, env=environment) as child:
                raw["child"]["pid"] = child.pid
                try:
                    stdout, stderr = child.communicate(request_json, timeout=60)
                except subprocess.TimeoutExpired:
                    child.kill()
                    stdout, stderr = child.communicate()
                    raw["child"].update(stdout=stdout, stderr=stderr, exit={"code": child.returncode})
                    raise RuntimeError("The actual SDK formatter/tool process exceeded its bound") from None
                raw["child"].update(stdout=stdout, stderr=stderr, exit={"code": child.returncode})
            if child.returncode != 0:
                raise RuntimeError("The actual SDK formatter/tool process failed; complete streams were retained")
            observation = json.loads(stdout)
            raw["child"]["observation"] = observation
            return observation["result"]
        finally:
            if evidence_directory is not None:
                evidence_directory = Path(evidence_directory)
                evidence_directory.mkdir(parents=True, exist_ok=True)
                (evidence_directory / "python-raw.json").write_text(
                    json.dumps([raw], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
