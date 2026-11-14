"""Labelled isolated replay/authority doubles; these are not original evidence.

The default CLI mode and real file/source admission run unchanged. Only the
trusted decoder/reference probes and independent guard are isolated here; no
command-line switch can select a fake guard or bypass production admission.
"""
from copy import deepcopy
import hashlib
from importlib import import_module, util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from equivalence.forget_index_fence_v2 import CASE_HASHES, POINTS
from equivalence.promotion_apply_family import differences


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/replay_forget_index_fence.py"


@pytest.fixture
def packet(monkeypatch, tmp_path, request):
    version = getattr(request, "param", "v2")
    frozen = import_module(f"equivalence.forget_index_fence_{version}")
    spec = util.spec_from_file_location("labelled_forget_replay_cli", SCRIPT)
    cli = util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    program = tmp_path / "labelled-program"
    (program / "equivalence").mkdir(parents=True)
    guard_path = program / "equivalence/forget_index_fence_evidence.py"
    guard_path.write_text("# Labelled isolated guard; never genuine engine evidence.\n")
    node = tmp_path / "labelled-node"
    node.write_bytes(b"labelled approved decoder fixture, never executed")
    reference = tmp_path / "labelled-reference"
    reference.mkdir()
    (reference / "package.json").write_text('{"version":"2026.9.9"}\n')
    sdk = tmp_path / "independently-chosen-sdk"
    (sdk / "memory_core").mkdir(parents=True)
    (sdk / "memory_core/__init__.py").write_text("# labelled SDK source snapshot\n")
    (sdk / "memory_core/owner.py").write_text("IDENTITY = 'original labelled source'\n")
    monkeypatch.setattr(cli, "ROOT", program)

    def node_authority(path):
        assert path == node
        return {"execPath": str(node), "nodeVersion": "v24.16.0", "icuVersion": "78.3",
                "unicodeVersion": "17.0", "sha256": cli._seal(node)["sha256"]}

    def reference_authority(path, selected_node):
        assert path == reference and selected_node == node
        return {"tag": "v2026.9.9", "commit": "b" * 40, "tree": "c" * 40,
                "nodeVersion": "v24.16.0", "packageVersion": "2026.9.9",
                "packageSha256": cli._seal(reference / "package.json")["sha256"]}

    monkeypatch.setattr(cli, "_node_authority", node_authority)
    monkeypatch.setattr(cli, "_reference_authority", reference_authority)
    node_info, ref_info = node_authority(node), reference_authority(reference, node)
    sdk_info = cli._sdk_identity(sdk)
    roots = [tmp_path / "labelled-004", tmp_path / "labelled-005"]
    for root in roots:
        root.mkdir()
    calls, hook = [], {"function": None}
    guard = ModuleType("equivalence.forget_index_fence_evidence")
    guard.__file__ = str(guard_path)

    def replay(case, native_directory, sdk_directory, **kwargs):
        calls.append((case["id"], native_directory, sdk_directory, kwargs))
        assert kwargs == {"approved_node": node, "approved_reference": reference,
                          "approved_sdk_root": sdk, "include_results": True}
        native = json.loads((native_directory / "evidence/native-raw.json").read_text())[0]
        dispatch = json.loads((sdk_directory / "python-raw.json").read_text())[0]
        stdout = json.loads((native_directory / "stdout.json").read_text())
        if (native["caseId"] != case["id"] or native["input"] != case["input"]
                or dispatch["input"] != case["input"] or native["completed"] is not True
                or dispatch["observation"]["complete"] is not True
                or stdout["ok"] is not True or stdout["result"] != native["result"]):
            raise ValueError("Labelled strict guard rejected an incomplete original transport")
        native_result, sdk_result = native["result"], dispatch["observation"]["result"]
        if hook["function"] is not None:
            hook["function"](case)
        return {"validated": True, "publicMatch": not differences(native_result, sdk_result),
                "nativeSnapshots": len(native_result["snapshots"]),
                "sdkSnapshots": len(sdk_result["snapshots"]), "acceptancePointsAwarded": 0,
                "nativeResult": native_result, "sdkResult": sdk_result}

    guard.replay_case = replay
    monkeypatch.setitem(sys.modules, guard.__name__, guard)
    cases = frozen.build_cases()
    for index, case in enumerate(cases):
        root = roots[0] if index == 4 else roots[1]
        directory = root / case["id"]
        (directory / "native/evidence").mkdir(parents=True)
        (directory / "sdk/evidence").mkdir(parents=True)
        native_result = {"provider": "none", "calls": {"labelled": {"whole": [False, 0, None],
                          "side": "native", "value": index}}, "snapshots": {}}
        sdk_result = deepcopy(native_result)
        sdk_result["calls"]["labelled"]["side"] = "sdk"
        (directory / "native/evidence/native-raw.json").write_text(json.dumps([{
            "caseId": case["id"], "input": case["input"], "completed": True,
            "result": native_result}]) + "\n")
        (directory / "native/stdout.json").write_text(json.dumps({
            "id": case["id"], "ok": True, "result": native_result}) + "\n")
        (directory / "sdk/evidence/python-raw.json").write_text(json.dumps([{
            "input": case["input"], "observation": {"complete": True, "result": sdk_result}}]) + "\n")
        (directory / "sdk-output.json").write_text(json.dumps(sdk_result, indent=2) + "\n")
    for root in roots:
        rows = []
        for case in cases:
            directory = root / case["id"]
            if not directory.exists():
                continue
            artifacts = []
            for relative, _ in cli.FILES.values():
                filename = directory / relative
                sealed = cli._seal(filename)
                artifacts.append({"path": filename.relative_to(root).as_posix(), "kind": "file",
                                  "bytes": sealed["bytes"], "sha256": sealed["sha256"]})
            row = {"id": case["id"], "covers": [], "candidateCoverage": list(POINTS),
                   "status": "blocked", "artifacts": artifacts}
            if root == roots[0]:
                row["custodyError"] = {"name": "ValueError", "message": "old labelled observer projection"}
            else:
                row["custodyPending"] = True
            rows.append(row)
        source = {"kind": f"forget-index-fence-{version}-comparison", "finalAuthenticationPassed": True,
                  "errors": [], "acceptancePointsAwarded": 0, "covers": [],
                  "candidateCoverage": list(POINTS), "fullScopePassed": False,
                  "literalManifestSha256": frozen.MANIFEST_SHA256, "collectorSha256": "d" * 64,
                  "adapterHashes": {"labelled-adapter.py": "e" * 64},
                  "implementationIdentity": {"gitCommit": "f" * 40, "trackedWorkingTreeDirty": False,
                      "sourceSha256": sdk_info["sourceSha256"], "sourceFiles": sdk_info["sourceFiles"]},
                  "node": node_info, "reference": {key: ref_info[key] for key in ("tag", "commit")},
                  "execution": {"caseOrder": list(frozen.CASE_HASHES),
                                **({"inputVersion": version} if version == "v3" else {})}, "cases": rows}
        (root / "report.json").write_text(json.dumps(source, indent=2) + "\n")

    def argv(output, selected_roots=None, *, selected_version="fixture"):
        if selected_version == "fixture":
            selected_version = version if version == "v3" else None
        args = [part for root in (roots if selected_roots is None else selected_roots)
                for part in ("--capture-root", str(root))]
        return [*args, *(["--version", selected_version] if selected_version is not None else []),
                "--reference", str(reference), "--node", str(node),
                "--sdk-source-root", str(sdk), "--output", str(output)]

    return {"cli": cli, "roots": roots, "node": node, "reference": reference, "sdk": sdk,
            "guard": guard, "guard_path": guard_path, "calls": calls, "hook": hook,
            "argv": argv, "tmp": tmp_path, "version": version, "frozen": frozen}


def _report(root):
    return json.loads((root / "report.json").read_text())


def _replace_report(root, value):
    (root / "report.json").write_text(json.dumps(value, indent=2) + "\n")


def _refresh_artifact(packet, root, identifier, relative):
    source = _report(root)
    row = next(row for row in source["cases"] if row["id"] == identifier)
    filename = root / identifier / relative
    sealed = packet["cli"]._seal(filename)
    item = next(item for item in row["artifacts"] if item["path"] == identifier + "/" + relative)
    item.update(bytes=sealed["bytes"], sha256=sealed["sha256"])
    _replace_report(root, source)


def test_default_mode_replays_exact_union_and_accepts_an_all_mismatch_baseline_without_credit(packet):
    before = {str(root): (root / "report.json").read_bytes() for root in packet["roots"]}
    output = packet["tmp"] / "independent.json"
    code = packet["cli"].main(packet["argv"](output))
    report = json.loads(output.read_text())
    assert code == 1
    assert report["validCompleteBaseline"] is True and report["finalAuthenticationPassed"] is True
    assert report["summary"] == {"match": 0, "mismatch": 13, "blocked": 0}
    assert report["acceptancePointsAwarded"] == 0 and report["covers"] == []
    assert report["fullScopePassed"] is False and report["candidateFamilyMatched"] is False
    assert [row["id"] for row in report["cases"]] == list(CASE_HASHES)
    assert [call[0] for call in packet["calls"]] == list(CASE_HASHES)
    assert all(row["structuralReplay"]["validated"] is True and row["differences"]
               for row in report["cases"])
    assert all("nativeResult" not in row["structuralReplay"] and "sdkResult" not in row["structuralReplay"]
               for row in report["cases"])
    assert len(report["sourceReports"]) == 2
    assert report["authority"]["sdk"]["root"] == str(packet["sdk"])
    assert report["authority"]["guard"]["sha256"] == hashlib.sha256(packet["guard_path"].read_bytes()).hexdigest()
    for root in packet["roots"]:
        assert (root / "report.json").read_bytes() == before[str(root)]
    assert _report(packet["roots"][0])["cases"][0]["status"] == "blocked"
    assert all(row["custodyPending"] is True for row in _report(packet["roots"][1])["cases"])


@pytest.mark.parametrize("attack", [
    "missing-auth", "false-auth", "report-errors", "wrong-manifest", "foreign-coverage",
    "wrong-sdk", "dirty-sdk", "missing-adapters", "missing-collector", "wrong-reference", "wrong-node",
    "native-error", "sdk-error", "duplicate-id", "missing-id", "extra-id", "duplicate-artifact",
])
def test_invalid_source_reports_are_rejected_before_any_guard_call(packet, attack):
    root = packet["roots"][1]
    source = _report(root)
    if attack == "missing-auth":
        del source["finalAuthenticationPassed"]
    elif attack == "false-auth":
        source["finalAuthenticationPassed"] = False
    elif attack == "report-errors":
        source["errors"] = [{"name": "genuine collector failure"}]
    elif attack == "wrong-manifest":
        source["literalManifestSha256"] = "0" * 64
    elif attack == "foreign-coverage":
        source["covers"] = list(POINTS)
    elif attack == "wrong-sdk":
        source["implementationIdentity"]["sourceSha256"] = "0" * 64
    elif attack == "dirty-sdk":
        source["implementationIdentity"]["trackedWorkingTreeDirty"] = True
    elif attack == "missing-adapters":
        del source["adapterHashes"]
    elif attack == "missing-collector":
        del source["collectorSha256"]
    elif attack == "wrong-reference":
        source["reference"]["commit"] = "0" * 40
    elif attack == "wrong-node":
        source["node"]["sha256"] = "0" * 64
    elif attack in {"native-error", "sdk-error"}:
        source["cases"][0]["nativeError" if attack == "native-error" else "sdkError"] = {"message": "real failure"}
    elif attack == "duplicate-id":
        source["cases"].append(deepcopy(_report(packet["roots"][0])["cases"][0]))
    elif attack == "missing-id":
        source["cases"].pop()
    elif attack == "extra-id":
        source["cases"][0]["id"] = "not-an-original-frozen-case"
    else:
        source["cases"][0]["artifacts"].append(deepcopy(source["cases"][0]["artifacts"][0]))
    _replace_report(root, source)
    output = packet["tmp"] / "rejected.json"
    assert packet["cli"].main(packet["argv"](output)) == 2
    report = json.loads(output.read_text())
    assert packet["calls"] == []
    assert report["validCompleteBaseline"] is False and report["errors"]
    assert report["acceptancePointsAwarded"] == 0 and report["covers"] == [] and report["fullScopePassed"] is False


@pytest.mark.parametrize("selected", ["duplicate-root", "subset-only"])
def test_root_selection_never_silently_duplicates_or_credits_a_subset(packet, selected):
    roots = packet["roots"] * 2 if selected == "duplicate-root" else packet["roots"][:1]
    output = packet["tmp"] / "selection.json"
    assert packet["cli"].main(packet["argv"](output, roots)) == 2
    report = json.loads(output.read_text())
    assert report["validCompleteBaseline"] is False and report["acceptancePointsAwarded"] == 0
    assert packet["calls"] == []


@pytest.mark.parametrize("flag", ["--reference", "--node", "--sdk-source-root"])
def test_missing_independently_selected_source_inputs_fail_before_replay(packet, flag):
    output = packet["tmp"] / "missing-input.json"
    argv = packet["argv"](output)
    argv[argv.index(flag) + 1] = str(packet["tmp"] / "missing-source-input")
    assert packet["cli"].main(argv) == 2
    report = json.loads(output.read_text())
    assert report["validCompleteBaseline"] is False and report["errors"]
    assert packet["calls"] == []


@pytest.mark.parametrize("attack", ["edited-raw", "incomplete-engine", "wrong-small-sdk-output"])
def test_actual_engine_files_and_small_sdk_output_are_bound_to_raw_observations(packet, attack):
    root = packet["roots"][1]
    identifier = list(CASE_HASHES)[0]
    if attack == "wrong-small-sdk-output":
        filename = root / identifier / "sdk-output.json"
        result = json.loads(filename.read_text())
        result["calls"]["labelled"]["side"] = "replaced output"
        filename.write_text(json.dumps(result) + "\n")
        _refresh_artifact(packet, root, identifier, "sdk-output.json")
    else:
        filename = root / identifier / "sdk/evidence/python-raw.json"
        if attack == "edited-raw":
            filename.write_bytes(filename.read_bytes() + b" ")
        else:
            value = json.loads(filename.read_text())
            value[0]["observation"]["complete"] = False
            filename.write_text(json.dumps(value) + "\n")
            _refresh_artifact(packet, root, identifier, "sdk/evidence/python-raw.json")
    output = packet["tmp"] / "bad-engine.json"
    assert packet["cli"].main(packet["argv"](output)) == 2
    report = json.loads(output.read_text())
    assert report["validCompleteBaseline"] is False and report["summary"]["blocked"] >= 1
    assert report["acceptancePointsAwarded"] == 0 and report["errors"]


@pytest.mark.parametrize("attack", ["guard", "sdk-source", "collector-report", "raw-file"])
def test_final_authentication_rejects_inputs_changed_after_valid_replay(packet, attack):
    def change(case):
        packet["hook"]["function"] = None
        if attack == "guard":
            filename = packet["guard_path"]
        elif attack == "sdk-source":
            filename = packet["sdk"] / "memory_core/owner.py"
        elif attack == "collector-report":
            filename = packet["roots"][1] / "report.json"
        else:
            filename = packet["roots"][1] / case["id"] / "sdk/evidence/python-raw.json"
        filename.write_bytes(filename.read_bytes() + b"\n")

    packet["hook"]["function"] = change
    output = packet["tmp"] / "changed.json"
    assert packet["cli"].main(packet["argv"](output)) == 2
    report = json.loads(output.read_text())
    assert report["validCompleteBaseline"] is False and report["errors"]
    assert report["acceptancePointsAwarded"] == 0 and report["fullScopePassed"] is False


def test_output_is_exclusive_and_never_rewrites_a_source_report(packet):
    output = packet["roots"][0] / "report.json"
    original = output.read_bytes()
    assert packet["cli"].main(packet["argv"](output)) == 2
    assert output.read_bytes() == original and packet["calls"] == []


def test_progress_updates_are_complete_atomic_json_and_no_trusted_fake_mode_is_exposed(packet, monkeypatch):
    snapshots = []
    original = packet["cli"].AtomicOutput.write

    def observed(self, report):
        original(self, report)
        snapshots.append(json.loads(self.path.read_text()))

    monkeypatch.setattr(packet["cli"].AtomicOutput, "write", observed)
    output = packet["tmp"] / "progress.json"
    assert packet["cli"].main(packet["argv"](output)) == 1
    assert len(snapshots) >= 15 and snapshots[0]["validCompleteBaseline"] is False
    assert [len(row["cases"]) for row in snapshots] == sorted(len(row["cases"]) for row in snapshots)
    assert all(row["acceptancePointsAwarded"] == 0 and row["covers"] == [] and row["fullScopePassed"] is False
               for row in snapshots)


@pytest.mark.parametrize("packet", ["v2", "v3"], indirect=True)
def test_explicit_version_replays_only_its_own_complete_family(packet):
    output = packet["tmp"] / "selected-version.json"
    args = packet["argv"](output, selected_version=packet["version"])
    assert packet["cli"].main(args) == 1
    report = json.loads(output.read_text())
    assert report["kind"] == f"forget-index-fence-{packet['version']}-independent-replay"
    assert report["validCompleteBaseline"] is True
    assert report["summary"] == {"match": 0, "mismatch": 13, "blocked": 0}
    assert [row["id"] for row in report["cases"]] == list(packet["frozen"].CASE_HASHES)
    assert report["authority"]["manifest"]["sha256"] == packet["frozen"].MANIFEST_SHA256
    assert report["authority"]["literalModule"]["path"] == packet["frozen"].__file__
    assert report["acceptancePointsAwarded"] == 0 and report["covers"] == []
    assert report["fullScopePassed"] is False


@pytest.mark.parametrize("packet", ["v2", "v3"], indirect=True)
def test_wrong_explicit_version_cannot_relabel_a_complete_packet(packet):
    other = "v3" if packet["version"] == "v2" else "v2"
    output = packet["tmp"] / "wrong-version.json"
    assert packet["cli"].main(packet["argv"](output, selected_version=other)) == 2
    report = json.loads(output.read_text())
    assert report["kind"] == f"forget-index-fence-{other}-independent-replay"
    assert packet["calls"] == [] and report["validCompleteBaseline"] is False
    assert report["errors"] and report["acceptancePointsAwarded"] == 0
    assert report["covers"] == [] and report["fullScopePassed"] is False


@pytest.mark.parametrize("packet", ["v3"], indirect=True)
def test_v3_is_never_implicitly_selected_from_capture_contents(packet):
    output = packet["tmp"] / "no-version.json"
    assert packet["cli"].main(packet["argv"](output, selected_version=None)) == 2
    report = json.loads(output.read_text())
    assert report["kind"] == "forget-index-fence-v2-independent-replay"
    assert packet["calls"] == [] and report["validCompleteBaseline"] is False
    assert report["acceptancePointsAwarded"] == 0 and report["fullScopePassed"] is False


@pytest.mark.parametrize("packet", ["v3"], indirect=True)
@pytest.mark.parametrize("attack", ["report-kind", "manifest", "missing-version", "wrong-version"])
def test_v3_report_must_declare_its_frozen_version_and_scope(packet, attack):
    root = packet["roots"][0]
    source = _report(root)
    if attack == "report-kind":
        source["kind"] = "forget-index-fence-v2-comparison"
    elif attack == "manifest":
        source["literalManifestSha256"] = import_module("equivalence.forget_index_fence_v2").MANIFEST_SHA256
    elif attack == "missing-version":
        del source["execution"]["inputVersion"]
    else:
        source["execution"]["inputVersion"] = "v2"
    _replace_report(root, source)
    output = packet["tmp"] / "foreign-scope.json"
    assert packet["cli"].main(packet["argv"](output)) == 2
    report = json.loads(output.read_text())
    assert packet["calls"] == [] and report["validCompleteBaseline"] is False
    assert report["acceptancePointsAwarded"] == 0 and report["covers"] == []
    assert report["fullScopePassed"] is False and report["errors"]


@pytest.mark.parametrize("packet", ["v2", "v3"], indirect=True)
def test_mixed_version_members_cannot_borrow_the_selected_family_scope(packet):
    root = packet["roots"][1]
    source = _report(root)
    other = import_module("equivalence.forget_index_fence_" + ("v2" if packet["version"] == "v3" else "v3"))
    source["cases"][0]["id"] = next(iter(other.CASE_HASHES))
    _replace_report(root, source)
    output = packet["tmp"] / "mixed-members.json"
    assert packet["cli"].main(packet["argv"](output)) == 2
    report = json.loads(output.read_text())
    assert packet["calls"] == [] and report["validCompleteBaseline"] is False
    assert report["acceptancePointsAwarded"] == 0 and report["fullScopePassed"] is False
    assert any("foreign case" in error["message"] for error in report["errors"])
