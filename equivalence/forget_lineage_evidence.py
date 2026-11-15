"""Bind this zero-credit baseline's observations to complete retained originals."""
import hashlib
import json
from pathlib import Path

from equivalence.forget_lineage_profile import canonical


def _same(left, right):
    return canonical(left) == canonical(right)


def _bytes(record):
    data = bytes.fromhex(record["hex"])
    if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError("A retained physical byte record changed")
    return data


def validate_native(case, public, snapshots, evidence):
    if len(snapshots) != 1 or not isinstance(snapshots[0], dict):
        raise ValueError("One complete original forget/lineage capture is required")
    raw = snapshots[0]
    base = Path(raw["fixtureBase"])
    if (not base.is_absolute() or base.parent != Path(evidence)
            or not base.name.startswith("native-forget-lineage-")
            or not _same(raw["input"], case["input"]) or raw.get("closed") is not True):
        raise ValueError("The original capture lost its owned identity, exact input or completion")
    expected_clock = {"owner": "node:test", "apis": ["Date"], "nowMs": case["input"]["nowMs"],
                      "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True}
    if raw["clock"] != expected_clock:
        raise ValueError("Only the explicit original Date fixture may control the clock")
    operations, observations = raw["operations"], public["observations"]
    if len(operations) != len(case["input"]["operations"]) or len(observations) != len(operations):
        raise ValueError("Every driven forget/lineage operation needs its complete observation")
    for request, captured, observed in zip(case["input"]["operations"], operations, observations, strict=True):
        if not _same(request, captured["operation"]) or not _same(captured["observed"], observed):
            raise ValueError("A public operation differs from the complete original observation")
        if request["op"] == "forget":
            if captured.get("originalWriteJsonUnchanged") is not True:
                raise ValueError("The original JSON report writer was replaced")
            stdout = _bytes(captured["stdout"])
            if stdout.decode("utf8") != captured["stdout"]["text"]:
                raise ValueError("The complete CLI stdout carrier changed")
            _bytes(captured["stderr"])
            if observed["report"] is not None and not _same(json.loads(stdout), observed["report"]):
                raise ValueError("The public report differs from the whole actual CLI JSON")
            if observed["error"] is not None and "returnValue" in captured:
                raise ValueError("The adapter failed after the original CLI returned; this is not a business mismatch")
    if len(raw["physical"]) != len(operations) + 1:
        raise ValueError("Every operation must retain its complete physical state")
    for captured in raw["physical"]:
        physical = captured["snapshot"]
        for root in (physical["fixture"], physical["state"]):
            for record in root["files"].values():
                _bytes(record)
        _bytes(physical["config"])


def validate_sdk(case, public, directory):
    directory = Path(directory).resolve()
    raw = json.loads((directory / "python-raw.json").read_text())
    clock = raw["clock"]
    if (clock["requestedNowMs"] != case["input"]["nowMs"]
            or clock["actualNowMs"] != case["input"]["nowMs"]
            or clock["clockFunctionReplaced"] is not True or clock["originalClockRestored"] is not True):
        raise ValueError("The SDK host clock was not controlled and restored")
    if not _same(raw["input"], case["input"]) or len(raw["operations"]) != len(case["input"]["operations"]):
        raise ValueError("SDK evidence lost the exact common input or an operation")
    if not _same([row["observed"] for row in raw["operations"]], public["observations"]):
        raise ValueError("SDK results differ from their complete recorded observations")
    if len(raw["physical"]) != len(raw["operations"]) + 1:
        raise ValueError("SDK evidence omitted a physical state")
    for reference in raw["physical"]:
        path = Path(reference["path"]).resolve()
        if not path.is_relative_to(directory) or hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
            raise ValueError("An SDK physical capture escaped ownership or changed")
        for record in json.loads(path.read_text())["files"].values():
            _bytes(record)
