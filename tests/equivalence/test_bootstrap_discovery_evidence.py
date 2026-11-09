"""Replay unchanged actual Native observations, not generated Native expectations."""

from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.bootstrap_discovery_evidence import validate_bootstrap_discovery_raw
from equivalence.bootstrap_discovery_fixtures import build_bootstrap_discovery_cases
from equivalence import runtime_oracle


FIXTURES = Path(__file__).parents[1] / "fixtures"
CASE_IDS = [case["id"] for case in build_bootstrap_discovery_cases()]


@pytest.fixture(scope="module")
def captured():
    source = FIXTURES / "bootstrap-discovery-protected-transport.json.gz"
    manifest = json.loads(
        (FIXTURES / "bootstrap-discovery-protected-transport.json.manifest.json").read_text()
    )
    packed = source.read_bytes()
    assert hashlib.sha256(packed).hexdigest() == manifest["gzipSha256"]
    raw = gzip.decompress(packed)
    assert len(raw) == manifest["bytes"]
    assert hashlib.sha256(raw).hexdigest() == manifest["sha256"]
    value = json.loads(raw)
    assert value["implementation"]["gitCommit"] == manifest["sourceCommit"]
    assert value["implementation"]["trackedWorkingTreeDirty"] is False
    assert value["summary"] == {
        "matched": 4,
        "mismatched": 7,
        "blocked": 0,
        "uncoveredAcceptance": 128,
    }
    assert value["packageSelection"]["newConditionCredit"] == 0
    return value


def _arguments(captured, case_id):
    transport = next(
        item["bootstrapDiscoveryTransport"]
        for item in captured["releaseTraces"]
        if item["id"] == case_id
    )
    diagnostic = next(
        item["rawSnapshots"]
        for item in captured["runtimeDiagnostics"]
        if item["id"] == case_id and item["side"] == "native"
    )
    return {
        "row": deepcopy(transport["row"]),
        "case": deepcopy(transport["case"]),
        "diagnostic": deepcopy(diagnostic),
        "evidence_directory": Path(diagnostic[0]["fixtureBase"]).parent,
        "runtime_root": transport["runtimeRoot"],
        "bootstrap": deepcopy(transport["bootstrap"]),
        "release_by_pid": {
            int(pid): set(paths) for pid, paths in transport["releaseByPid"].items()
        },
        "local_by_pid": {int(pid): set(paths) for pid, paths in transport["localByPid"].items()},
        "process_parents": {
            int(pid): parent for pid, parent in transport["processParents"].items()
        },
    }, transport


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_actual_complete_native_rows_replay_without_path_or_pid_rewriting(
    captured, case_id, monkeypatch
):
    arguments, transport = _arguments(captured, case_id)
    # Historical path identity is an explicit validator dependency. The stored
    # row, raw file bytes and all original trace facts remain unchanged.
    monkeypatch.setattr(runtime_oracle, "ROOT", Path(transport["adapterRoot"]))
    validate_bootstrap_discovery_raw(**arguments)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_actual_caller_maps_are_derived_from_the_retained_original_trace_bytes(captured, case_id):
    _, transport = _arguments(captured, case_id)
    release, local, parents, bootstrap = {}, {}, {}, []
    hashes = {
        (item["package"], item["path"]): item["sha256"] for item in captured["releaseSources"]
    }
    for trace in transport["rawProcessWorkerTraces"]:
        raw = trace["text"].encode("utf-8")
        assert len(raw) == trace["bytes"] and hashlib.sha256(raw).hexdigest() == trace["sha256"]
        assert raw.endswith(b"\n")
        events = [json.loads(line) for line in raw.splitlines()]
        first = events[0]
        pid, thread = map(int, trace["name"].removesuffix(".jsonl").split("-"))
        assert first["event"] == "bootstrap" and first["pid"] == pid and first["threadId"] == thread
        assert first["fetchDenied"] is True and first["providerMode"] == "none"
        bootstrap.append(
            {
                "pid": pid,
                "threadId": thread,
                "isMainThread": thread == 0,
                "runtime": first["runtime"],
                "bootstrapProfile": first["bootstrapProfile"],
            }
        )
        if thread == 0:
            parents[str(pid)] = first["ppid"]
        for event in events[1:]:
            assert event["pid"] == pid and event["threadId"] == thread
            assert event["event"] in {"load", "resolve-native"}
            assert event["kind"] in {"oracle", "release"}
            if event["event"] != "load":
                continue
            if event["kind"] == "release":
                assert hashes[event["package"], event["path"]] == event["sha256"]
                if event["package"] == "node_modules/openclaw":
                    release.setdefault(str(pid), set()).add(event["path"])
            elif thread == 0:
                local.setdefault(str(pid), set()).add(event["path"])
    assert bootstrap == transport["bootstrap"]
    assert parents == transport["processParents"]
    assert {pid: sorted(paths) for pid, paths in release.items()} == transport["releaseByPid"]
    assert {pid: sorted(paths) for pid, paths in local.items()} == transport["localByPid"]
    # Package archive authentication and required owner execution are the
    # collector's responsibility; this test replays its actual recorded maps.


@pytest.mark.parametrize(
    "mutation",
    [
        "runtime",
        "bootstrap-runtime",
        "parent",
        "input",
        "clock",
        "locals",
        "release",
        "template",
        "template-path",
        "template-loss",
        "call-loss",
        "call-args",
        "call-return-flag",
        "public-ensure",
        "public-body",
        "public-order",
        "warnings",
        "state",
        "file-bytes",
        "stat-field",
        "stat-type",
        "filesystem-row",
        "enumeration",
        "writes",
        "close",
    ],
)
def test_real_evidence_rejects_channel_loss_and_execution_or_payload_drift(
    captured, mutation, monkeypatch
):
    args, transport = _arguments(captured, "bootstrap-discovery-initial-whole-exports")
    monkeypatch.setattr(runtime_oracle, "ROOT", Path(transport["adapterRoot"]))
    raw = args["diagnostic"][0]
    if mutation == "runtime":
        raw["runtime"]["sha256"] = "0" * 64
    elif mutation == "bootstrap-runtime":
        args["bootstrap"][0]["runtime"]["nodeVersion"] = "v24.16.1"
    elif mutation == "parent":
        args["process_parents"][raw["pid"]] = raw["pid"]
    elif mutation == "input":
        raw["input"]["layout"] = "memory-core"
    elif mutation == "clock":
        raw["clock"]["performanceNowUnchanged"] = False
    elif mutation == "locals":
        args["local_by_pid"][raw["pid"]] = set()
    elif mutation == "release":
        args["release_by_pid"][raw["pid"]] = set()
    elif mutation == "template":
        raw["packagedTemplates"]["AGENTS.md"]["content"] += "Changed"
    elif mutation == "template-path":
        raw["packagedTemplates"]["AGENTS.md"]["path"] = "/another/AGENTS.md"
    elif mutation == "template-loss":
        raw["packagedTemplates"].pop("SOUL.md")
    elif mutation == "call-loss":
        raw["calls"].pop()
    elif mutation == "call-args":
        raw["calls"][0]["request"]["ensureBootstrapFiles"] = 1
    elif mutation == "call-return-flag":
        raw["calls"][0]["returnedUndefined"] = True
    elif mutation == "public-ensure":
        args["row"]["result"]["steps"][0]["ensure"]["bootstrapPending"] = False
    elif mutation == "public-body":
        args["row"]["result"]["steps"][0]["loaded"][0]["content"] = "Replaced"
    elif mutation == "public-order":
        args["row"]["result"]["steps"][0]["runs"][0]["files"].reverse()
    elif mutation == "warnings":
        next(item for item in raw["calls"] if item["owner"] == "resolveBootstrapFilesForRun")[
            "warnings"
        ].append("Changed")
    elif mutation == "state":
        raw["snapshots"][0]["state"]["setupExists"] = False
    elif mutation == "file-bytes":
        next(item for item in raw["snapshots"][0]["workspace"] if item["kind"] == "file")["bytes"][
            "hex"
        ] = ""
    elif mutation == "stat-field":
        raw["snapshots"][0]["workspace"][0]["stat"].pop("uid")
    elif mutation == "stat-type":
        raw["snapshots"][0]["workspace"][0]["stat"]["ino"] = True
    elif mutation == "filesystem-row":
        raw["snapshots"][0]["workspace"].pop()
    elif mutation == "enumeration":
        raw["snapshots"][0]["workspaceEntries"].pop()
    elif mutation == "writes":
        raw["writes"] = []
    elif mutation == "close":
        raw["close"]["returnedUndefined"] = False
    with pytest.raises(runtime_oracle.RuntimeOracleError):
        validate_bootstrap_discovery_raw(**args)
