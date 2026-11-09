"""Default paired profile over the frozen genuine worker scheduling experiment."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from equivalence.get_contract import map_get_fixture_paths
from equivalence.trust_worker_probe import _cases


ROOT = Path(__file__).resolve().parents[1]
OPERATION = "trust-worker-runtime"
_PROFILE = (
    "Actual registered SQLite transcript projection with the original bounded worker retry owner, "
    "genuine parent registry mutations at successful reply delivery, and the genuine live observer "
    "bypass. All five scheduling inputs run in fresh synthetic-only processes. Complete source "
    "results, errors and persisted raw events are compared. Actual worker/preparation counts, "
    "revision numbers, callbacks and complete scheduling observations remain unchanged in raw "
    "evidence; process-local implementation counters are not a shared JSON output contract. "
    "No source/result/retry replacement, provider execution or arbitrary scheduling is claimed."
)
_POLICY = (
    "Complete source result/error and ordered transcript before/after records. Only the exact "
    "owned fixture-root prefix in JSON string values maps to $FIXTURE; no field removal, score "
    "tolerance, retry/version offsets, redaction repair or source mutation. Missing result/error "
    "from the original experiment is represented by null in the declared shared envelope. "
    "Complete original stdout and the SDK snapshot, including their original absence semantics, "
    "remain raw."
)


def build_trust_worker_cases():
    return [{"id": "trust-worker-" + case["id"], "requirement": "trust.secret-redaction",
             "covers": [], "operation": OPERATION, "input": deepcopy(case["input"]),
             "driverScope": _PROFILE, "normalizationPolicy": _POLICY} for case in _cases()]


def validate_worker_profile_input(value):
    if not any(type(value) is dict and value == case["input"]
               and all(type(value[key]) is type(item) for key, item in case["input"].items())
               for case in _cases()):
        raise ValueError("Only the five declared synthetic worker inputs are admitted")


def worker_profile_public(observation, fixture_base, *, sdk=False):
    before, after = observation["before"], observation["after"]
    if sdk:
        before, after = before["events"], after["events"]
    return map_get_fixture_paths({"provider": "none", "result": observation.get("result"),
                                  "error": observation.get("error"),
                                  "transcript": {"before": before, "after": after}}, fixture_base)


def run_trust_worker(arguments, *, evidence_directory=None):
    """Execute the existing SDK experiment in a fresh minimal-environment process."""
    validate_worker_profile_input(arguments)
    value = deepcopy(arguments)
    with tempfile.TemporaryDirectory(prefix="python-trust-worker-") as temporary:
        root = Path(temporary)
        directory = root / "fixture"
        request = {"input": value, "fixtureDirectory": str(directory)}
        request_json = json.dumps(request, separators=(",", ":"))
        request_path = root / "request.json"
        request_path.write_text(request_json, encoding="utf-8")
        argv = [sys.executable, "-m", "equivalence.trust_worker_probe", "--sdk-case", str(request_path)]
        environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                       "PYTHONPATH": str(ROOT), "LANG": "en_US.UTF-8", "TZ": "UTC",
                       "OPENCLAW_STATE_DIR": str(directory / "state"),
                       "OPENCLAW_CONFIG_PATH": str(directory / "openclaw.json"),
                       "OPENCLAW_HOME": str(directory)}
        raw = {"kind": "worker-profile", "fixtureBase": str(root), "coordinatorPid": os.getpid(),
               "input": value, "child": {"request": request, "requestJson": request_json,
                   "requestSha256": hashlib.sha256(request_json.encode()).hexdigest(),
                   "argv": argv, "environmentKeys": sorted(environment)}}
        try:
            with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  cwd=ROOT, env=environment) as child:
                raw["child"]["pid"] = child.pid
                try:
                    stdout, stderr = child.communicate(timeout=60)
                except subprocess.TimeoutExpired:
                    child.kill()
                    stdout, stderr = child.communicate()
                    raw["child"].update(stdout=stdout, stderr=stderr, exit={"code": child.returncode})
                    raise RuntimeError("The genuine SDK worker experiment exceeded its process bound") from None
                raw["child"].update(stdout=stdout, stderr=stderr, exit={"code": child.returncode})
            if child.returncode != 0:
                raise RuntimeError("The genuine SDK worker experiment failed; complete streams were retained")
            observation = json.loads(stdout)
            raw["child"]["observation"] = observation
            return worker_profile_public(observation, root, sdk=True)
        finally:
            if evidence_directory is not None:
                evidence_directory = Path(evidence_directory)
                evidence_directory.mkdir(parents=True, exist_ok=True)
                (evidence_directory / "python-raw.json").write_text(
                    json.dumps([raw], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
