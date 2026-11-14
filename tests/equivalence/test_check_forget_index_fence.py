"""Labelled collector routing/authority doubles; no original engine or credit."""
from copy import deepcopy
from importlib import import_module, util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_forget_index_fence.py"


@pytest.fixture
def collector(monkeypatch, tmp_path):
    spec = util.spec_from_file_location("labelled_forget_collector", SCRIPT)
    cli = util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    program = tmp_path / "labelled-program"
    program.mkdir()
    node, reference, runtime = (tmp_path / name for name in ("node", "reference", "runtime"))
    calls = {"native": [], "sdk": [], "replay": []}
    control = {"replay": None}
    state = {}
    monkeypatch.setattr(cli, "ROOT", program)
    monkeypatch.setattr(cli, "prepare_model_node_authority", lambda path: {"label": "UNIT_NODE", "path": str(path)})
    monkeypatch.setattr(cli, "prepare_release_runtime", lambda ref, root: {
        "runtimeRoot": str(runtime), "reference": {"tag": "UNIT_REFERENCE", "commit": "1" * 40}})
    monkeypatch.setattr(cli, "prepare_forget_index_fence_bindings", lambda ref, root: {
        "label": "UNIT_SOURCE_AUTHORITY", "sourceBuildReproduced": False})
    monkeypatch.setattr(cli, "_implementation_identity", lambda: {"label": "UNIT_SDK_SOURCE"})
    monkeypatch.setattr(cli, "_adapter_identity", lambda: {"labelled-adapter": "2" * 64})

    def native(case, approved_node, release, directory, *, timeout, checkout):
        calls["native"].append((deepcopy(case), approved_node, directory, timeout, checkout))
        state["case"] = case
        result = {"provider": "none", "calls": {"UNIT_ONLY": {"value": [False, 0, None]}}, "snapshots": {}}
        (directory / "evidence").mkdir(parents=True)
        (directory / "evidence/native-raw.json").write_text('[{"label":"UNIT_NATIVE_ONLY"}]\n')
        (directory / "stdout.json").write_text(json.dumps({"id": case["id"], "result": result}) + "\n")
        return {"results": [{"id": case["id"], "result": result}],
                "releaseTrace": {"label": "UNIT_NATIVE_SOURCE_TRACE"}}

    def sdk(value, *, evidence_directory):
        calls["sdk"].append((deepcopy(value), evidence_directory))
        assert value == state["case"]["input"]
        evidence_directory.mkdir(parents=True)
        (evidence_directory / "python-raw.json").write_text('[{"label":"UNIT_SDK_ONLY"}]\n')
        return {"provider": "none", "calls": {"UNIT_ONLY": {"value": [False, 0, None]}}, "snapshots": {}}

    def replay(case, native_directory, sdk_directory, **kwargs):
        calls["replay"].append((case, native_directory, sdk_directory, kwargs))
        if control["replay"] is not None:
            return control["replay"]
        return {"validated": True, "publicMatch": True, "acceptancePointsAwarded": 0,
                "nativeSnapshots": 0, "sdkSnapshots": 0}

    monkeypatch.setattr(cli, "run_native_case", native)
    monkeypatch.setattr(cli, "run_forget_index_fence_sdk_case", sdk)
    monkeypatch.setattr(cli, "replay_case", replay)

    def args(output, version=None, extra=()):
        return ["--reference", str(reference), "--node", str(node), "--release-runtime", str(runtime),
                "--output", str(output), *(["--version", version] if version else []), *extra]

    return {"cli": cli, "program": program, "node": node, "reference": reference, "runtime": runtime,
            "calls": calls, "control": control, "args": args, "tmp": tmp_path}


@pytest.mark.parametrize("version", [None, "v2", "v3", "v4", "v5"])
def test_complete_selected_family_has_explicit_isolated_routes_and_zero_credit(collector, version):
    chosen = version or "v2"
    frozen = import_module(f"equivalence.forget_index_fence_{chosen}")
    output = collector["tmp"] / "packet"
    assert collector["cli"].main(collector["args"](output, version)) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["kind"] == f"forget-index-fence-{chosen}-comparison"
    assert report["execution"]["inputVersion"] == chosen
    assert [row["id"] for row in report["cases"]] == list(frozen.CASE_HASHES)
    assert report["literalManifestSha256"] == frozen.MANIFEST_SHA256
    assert report["summary"] == {"match": 13, "mismatch": 0, "blocked": 0}
    assert report["candidateFamilyMatched"] is True and report["finalAuthenticationPassed"] is True
    assert report["acceptancePointsAwarded"] == 0 and report["covers"] == [] and report["fullScopePassed"] is False
    assert report["initialOwnerBindings"]["sourceBuildReproduced"] is False
    assert len(collector["calls"]["native"]) == len(collector["calls"]["sdk"]) == len(collector["calls"]["replay"]) == 13
    for case, native_dir, sdk_dir, kwargs in collector["calls"]["replay"]:
        assert native_dir == output / case["id"] / "native"
        assert sdk_dir == output / case["id"] / "sdk/evidence"
        assert native_dir != sdk_dir
        assert kwargs == {"approved_node": collector["node"], "approved_sdk_root": collector["program"],
                          "approved_reference": collector["reference"],
                          **({"approved_adapter_root": collector["program"]} if chosen != "v2" else {})}


@pytest.mark.parametrize("selection", ["foreign", "mixed", "duplicate"])
def test_v5_rejects_wrong_or_repeated_members_before_any_dispatch(collector, selection):
    v4 = import_module("equivalence.forget_index_fence_v4")
    v5 = import_module("equivalence.forget_index_fence_v5")
    selected = ([next(iter(v4.CASE_HASHES))] if selection == "foreign" else
                [next(iter(v5.CASE_HASHES)), next(iter(v4.CASE_HASHES))] if selection == "mixed" else
                [next(iter(v5.CASE_HASHES))] * 2)
    output = collector["tmp"] / "rejected"
    extra = [part for case_id in selected for part in ("--case", case_id)]
    with pytest.raises(SystemExit) as failure:
        collector["cli"].main(collector["args"](output, "v5", extra))
    assert failure.value.code == 2 and not output.exists()
    assert all(not calls for calls in collector["calls"].values())


def test_v5_capture_only_remains_blocked_and_uncredited(collector):
    frozen = import_module("equivalence.forget_index_fence_v5")
    output = collector["tmp"] / "pending"
    extra = ["--case", next(iter(frozen.CASE_HASHES)), "--defer-custody"]
    assert collector["cli"].main(collector["args"](output, "v5", extra)) == 2
    report = json.loads((output / "report.json").read_text())
    assert report["cases"][0]["custodyPending"] is True and report["cases"][0]["status"] == "blocked"
    assert report["candidateFamilyMatched"] is False and collector["calls"]["replay"] == []
    assert report["acceptancePointsAwarded"] == 0 and report["fullScopePassed"] is False


@pytest.mark.parametrize("value", [
    {"validated": False, "publicMatch": True, "acceptancePointsAwarded": 0},
    {"validated": 1, "publicMatch": True, "acceptancePointsAwarded": 0},
    {"validated": True, "publicMatch": 1, "acceptancePointsAwarded": 0},
    {"validated": True, "publicMatch": True, "acceptancePointsAwarded": True},
    {"validated": True, "publicMatch": False, "acceptancePointsAwarded": 0},
])
def test_v5_requires_actual_affirmative_custody_and_consistent_whole_parity(collector, value):
    collector["control"]["replay"] = value
    case_id = next(iter(import_module("equivalence.forget_index_fence_v5").CASE_HASHES))
    output = collector["tmp"] / "guard-refused"
    assert collector["cli"].main(collector["args"](output, "v5", ["--case", case_id])) == 2
    report = json.loads((output / "report.json").read_text())
    assert report["cases"][0]["status"] == "blocked" and "custodyError" in report["cases"][0]
    assert report["candidateFamilyMatched"] is False and report["acceptancePointsAwarded"] == 0
    assert report["fullScopePassed"] is False
