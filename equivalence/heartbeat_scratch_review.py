"""Replay two complete heartbeat packets in their capture directories without running engines."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from equivalence import heartbeat_doctor_probe as doctor
from equivalence import heartbeat_scratch_probe as store
from equivalence.heartbeat_runtime_bindings import REFERENCE_COMMIT
from equivalence.heartbeat_scratch_outcomes import compare_doctor_outcomes


def _read(path):
    return json.loads(path.read_bytes())


def _require(satisfied, reason):
    if not satisfied:
        raise ValueError(reason)


def _digest(value):
    data = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def _differences(native, sdk, path=()):
    if type(native) is not type(sdk):
        yield path, native, sdk
    elif isinstance(native, dict):
        for key in sorted(native.keys() | sdk.keys()):
            if key not in native or key not in sdk:
                yield (*path, key), native.get(key), sdk.get(key)
            else:
                yield from _differences(native[key], sdk[key], (*path, key))
    elif isinstance(native, list):
        if len(native) != len(sdk):
            yield (*path, "length"), len(native), len(sdk)
        for index, (left, right) in enumerate(zip(native, sdk)):
            yield from _differences(left, right, (*path, index))
    elif native != sdk:
        yield path, native, sdk


def _check_doctor_sdk(raw, fixture, root):
    host = fixture["host"]
    store_path = root / ("custom-cron/jobs.json" if fixture["customStore"] else "state/automation.json")
    _require(raw["fixtureDirectory"] == str(root) and raw["hostMapping"] == host
             and raw["storeConfiguration"] == {"root": str(root / "workspace"), "store_path": str(store_path)}
             and raw["clock"]["nowMs"] == fixture["nowMs"], "unexpected SDK migration host")
    for call in raw["calls"]:
        _require(call["clockMs"] == fixture["nowMs"], "unexpected SDK phase clock")
        _require(call.get("openclawHome") == str(root / "home"), "unexpected SDK fixture home")
        operation = call["operation"]["op"]
        if operation in {"repair", "preview"}:
            _require(call["request"] == {"root": str(root / "workspace"), "agent_ids": host["agentIds"],
                     "retain_source": host["retainSource"], "now_ms": fixture["nowMs"],
                     "monitor_agent_ids": [agent["id"] for agent in fixture["agents"]],
                     "should_repair": operation == "repair", "state_dir": str(root / "state")},
                     "SDK did not execute the declared configured migration")


def _review(directory, *, is_doctor):
    expected = doctor.build_doctor_cases() if is_doctor else store.build_cases()
    _require(store._same_json_wire(_read(directory / "cases.json"), expected), "incomplete or changed cases")
    auth = _read(directory / "authentication-before.json")
    _require(auth == _read(directory / "authentication-after.json"), "capture authentication changed")
    owned = (*doctor.ADAPTERS, *doctor.SDK_FILES, *doctor.STORE_ISOLATION_FILES) if is_doctor else (*store.LOCAL_FILES, *store.SDK_FILES)
    identities = doctor._identity(owned)
    _require(auth["ownedFiles"] == identities, "local producer differs from capture")
    _require(auth["runtime"]["reference"]["commit"] == REFERENCE_COMMIT, "unexpected OpenClaw reference")
    report = _read(directory / "report.json")
    _require(not (directory / "capture-rejection.json").exists() and report["acceptancePointsAwarded"] == 0
             and report["covers"] == [], "rejected or relabelled diagnostic packet")
    _require([row["id"] for row in report["observations"]] == [case["id"] for case in expected],
             "report missing complete case family")
    if is_doctor:
        _require(report.get("sdkStateDirectory") == "<FIXTURE>/state", "capture lacks configured host state")
    results = []
    for case, row in zip(expected, report["observations"], strict=True):
        root = directory / case["id"]
        native, sdk, stdout_hashes = [], [], []
        claim_pids = None
        for n, (fixture, prior) in enumerate(zip(case["phases"], row["phases"], strict=True)):
            phase = root / str(n)
            context = _read(phase / "context.json")
            path = phase / "native-input.json"
            _require(context["runtime"] == auth["runtime"] and context["capability"] == auth["capability"]
                     and context["requestPath"] == str(path) and context["traceDirectory"] == str(phase / "traces")
                     and context["requestSha256"] == hashlib.sha256(path.read_bytes()).hexdigest(),
                     "unexpected capture authority or request")
            digests = {}
            for lane, observations in (("native", native), ("sdk", sdk)):
                request = _read(phase / f"{lane}-input.json")
                fixture_root = root / f"{lane}-fixture"
                _require(store._same_json_wire(request, {
                    "kind": "heartbeat-doctor-sequence" if is_doctor else case["kind"],
                    "phase": n, "input": fixture, "fixtureDirectory": str(fixture_root),
                }), "unexpected input to capture")
                packed = (phase / f"{lane}.stdout.json").read_bytes()
                digests[lane] = hashlib.sha256(packed).hexdigest()
                observed = json.loads(packed)
                compared = doctor._root_comparison(observed["result"], fixture_root) if is_doctor else observed["result"]
                _require(store._same_json_wire(prior[lane], compared), "raw result differs from capture report")
                observations.append(observed)
            stdout_hashes.append(digests)
            if is_doctor:
                _check_doctor_sdk(sdk[-1]["raw"], fixture, root / "sdk-fixture")
                _require(native[-1]["raw"]["env"].get("OPENCLAW_HOME") == str(root / "native-fixture" / "home"),
                         "unexpected OpenClaw fixture home")
                execution = doctor.validate_execution(phase, context, native[-1])
                _require(execution == prior["execution"], "Doctor execution traces differ")
                for cut in ("before", "after"):
                    statuses = _read(phase / f"claim-processes-{cut}.json")
                    pids = [record["pid"] for record in statuses]
                    count = 2 if case.get("claim") == "multiple" else int("claim" in case)
                    _require(len(pids) == len(set(pids)) == count and (claim_pids is None or claim_pids == pids),
                             "missing or changed claim PIDs")
                    claim_pids = pids
                    doctor._require_claim_role(case.get("claim"), statuses)
            else:
                events = store._validate_trace(phase, context, auth["runtime"], auth["capability"])
                _require(len(events) == prior["traceEvents"], "STORE execution trace differs")
                observations = [{"step": step, "value": value} for step, value in
                                zip(fixture["steps"], native[-1]["result"], strict=True)]
                _require(store._same_json_wire(observations, native[-1]["raw"]["observations"]),
                         "STORE native calls differ from capture")
                _require(store._same_json_wire(fixture["steps"], [c["step"] for c in sdk[-1]["raw"]["calls"]]),
                         "STORE SDK calls differ from capture")
        if is_doctor:
            outcome = compare_doctor_outcomes(case, native, sdk)
        else:
            outcome = {"native": [r["result"] for r in native], "sdk": [r["result"] for r in sdk]}
            for pids in ([r["raw"]["process"]["pid"] for r in native], [r["process"]["pid"] for r in sdk]):
                _require(len(set(pids)) == len(pids), "reused STORE phase process")
            outcome["matches"] = store._same_json_wire(outcome["native"], outcome["sdk"])
        item = {"id": case["id"], "matches": outcome["matches"], "stdoutSha256": stdout_hashes,
                "nativeSha256": _digest(outcome["native"]), "sdkSha256": _digest(outcome["sdk"])}
        if not item["matches"]:
            item.update(openclaw=outcome["native"], python=outcome["sdk"])
            # Keep a first difference alongside both complete compared values.
            differences = list(_differences(outcome["native"], outcome["sdk"]))
            item["differenceCount"] = len(differences)
            if differences:
                path, left, right = next((d for d in differences if "returns" in d[0]), differences[0])
                item["firstDifference"] = {"path": path, "native": left, "sdk": right}
        results.append(item)
    return results


def review_packets(doctor_packet: Path, store_packet: Path) -> dict:
    """Verify the complete captured STORE and Doctor families and return compact receipts."""
    rows = _review(store_packet.resolve(), is_doctor=False) + _review(doctor_packet.resolve(), is_doctor=True)
    return {"matches": sum(row["matches"] for row in rows), "total": len(rows),
            "acceptancePointsAwarded": 0, "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doctor", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    reviewed = review_packets(args.doctor, args.store)
    print(json.dumps(reviewed, ensure_ascii=True, indent=2))
    return int(reviewed["matches"] != reviewed["total"])


if __name__ == "__main__":
    raise SystemExit(main())
