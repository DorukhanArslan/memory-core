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
from types import ModuleType, SimpleNamespace

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
    adapter_path = program / "equivalence/labelled_actor.py"
    adapter_path.write_text("# Labelled adapter source; never original engine evidence.\n")
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
                          "approved_sdk_root": sdk, "include_results": True,
                          **({"approved_adapter_root": program} if version != "v2" or hook.get("explicitAdapter") else {})}
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
                                **({"inputVersion": version} if version in {"v3", "v4", "v5"} else {})}, "cases": rows}
        (root / "report.json").write_text(json.dumps(source, indent=2) + "\n")

    def argv(output, selected_roots=None, *, selected_version="fixture"):
        if selected_version == "fixture":
            selected_version = version if version in {"v3", "v4", "v5"} else None
        args = [part for root in (roots if selected_roots is None else selected_roots)
                for part in ("--capture-root", str(root))]
        return [*args, *(["--version", selected_version] if selected_version is not None else []),
                "--reference", str(reference), "--node", str(node),
                "--sdk-source-root", str(sdk), "--output", str(output)]

    return {"cli": cli, "roots": roots, "node": node, "reference": reference, "sdk": sdk,
            "guard": guard, "guard_path": guard_path, "calls": calls, "hook": hook,
            "argv": argv, "tmp": tmp_path, "version": version, "frozen": frozen,
            "program": program, "adapter_path": adapter_path}


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


@pytest.mark.parametrize("packet", ["v2", "v3", "v4", "v5"], indirect=True)
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


@pytest.mark.parametrize("packet", ["v2", "v3", "v4", "v5"], indirect=True)
def test_wrong_explicit_version_cannot_relabel_a_complete_packet(packet):
    other = "v4" if packet["version"] != "v4" else "v3"
    output = packet["tmp"] / "wrong-version.json"
    assert packet["cli"].main(packet["argv"](output, selected_version=other)) == 2
    report = json.loads(output.read_text())
    assert report["kind"] == f"forget-index-fence-{other}-independent-replay"
    assert packet["calls"] == [] and report["validCompleteBaseline"] is False
    assert report["errors"] and report["acceptancePointsAwarded"] == 0
    assert report["covers"] == [] and report["fullScopePassed"] is False


@pytest.mark.parametrize("packet", ["v3", "v4", "v5"], indirect=True)
def test_later_version_is_never_implicitly_selected_from_capture_contents(packet):
    output = packet["tmp"] / "no-version.json"
    assert packet["cli"].main(packet["argv"](output, selected_version=None)) == 2
    report = json.loads(output.read_text())
    assert report["kind"] == "forget-index-fence-v2-independent-replay"
    assert packet["calls"] == [] and report["validCompleteBaseline"] is False
    assert report["acceptancePointsAwarded"] == 0 and report["fullScopePassed"] is False


@pytest.mark.parametrize("packet", ["v3", "v4", "v5"], indirect=True)
@pytest.mark.parametrize("attack", ["report-kind", "manifest", "missing-version", "wrong-version"])
def test_later_report_must_declare_its_frozen_version_and_scope(packet, attack):
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


@pytest.mark.parametrize("packet", ["v2", "v3", "v4", "v5"], indirect=True)
def test_mixed_version_members_cannot_borrow_the_selected_family_scope(packet):
    root = packet["roots"][1]
    source = _report(root)
    other = import_module("equivalence.forget_index_fence_" + ("v2" if packet["version"] != "v2" else "v4"))
    source["cases"][0]["id"] = next(iter(other.CASE_HASHES))
    _replace_report(root, source)
    output = packet["tmp"] / "mixed-members.json"
    assert packet["cli"].main(packet["argv"](output)) == 2
    report = json.loads(output.read_text())
    assert packet["calls"] == [] and report["validCompleteBaseline"] is False
    assert report["acceptancePointsAwarded"] == 0 and report["fullScopePassed"] is False
    assert any("foreign case" in error["message"] for error in report["errors"])


@pytest.mark.parametrize("packet", ["v2", "v3", "v4", "v5"], indirect=True)
def test_explicit_adapter_source_is_independent_and_sealed(packet):
    packet["hook"]["explicitAdapter"] = True
    output = packet["tmp"] / "explicit-adapter.json"
    args = [*packet["argv"](output), "--adapter-root", str(packet["program"])]
    assert packet["cli"].main(args) == 1
    report = json.loads(output.read_text())
    assert report["validCompleteBaseline"] is True
    assert report["authority"]["adapters"]["root"] == str(packet["program"])
    assert any(row["path"] == "equivalence/labelled_actor.py" for row in report["authority"]["adapters"]["files"])
    assert all(call[3]["approved_adapter_root"] == packet["program"] for call in packet["calls"])
    assert report["acceptancePointsAwarded"] == 0 and report["fullScopePassed"] is False


@pytest.mark.parametrize("packet", ["v3", "v4", "v5"], indirect=True)
def test_changed_actor_source_after_replay_invalidates_complete_baseline(packet):
    def change(case):
        packet["hook"]["function"] = None
        packet["adapter_path"].write_text("# CHANGED labelled actor; never genuine evidence\n")

    packet["hook"]["function"] = change
    output = packet["tmp"] / "changed-adapter.json"
    assert packet["cli"].main(packet["argv"](output)) == 2
    report = json.loads(output.read_text())
    assert report["errors"] and report["validCompleteBaseline"] is False
    assert report["acceptancePointsAwarded"] == 0 and report["fullScopePassed"] is False


@pytest.mark.parametrize("packet", ["v4", "v5"], indirect=True)
def test_missing_explicit_adapter_source_is_rejected_before_guard(packet):
    output = packet["tmp"] / "missing-adapter.json"
    args = [*packet["argv"](output), "--adapter-root", str(packet["tmp"] / "absent-actor-source")]
    assert packet["cli"].main(args) == 2
    report = json.loads(output.read_text())
    assert packet["calls"] == [] and report["validCompleteBaseline"] is False and report["errors"]
    assert report["acceptancePointsAwarded"] == 0 and report["fullScopePassed"] is False


@pytest.fixture
def suite_packet(packet, monkeypatch):
    """Labelled real-shaped full report; isolated guard, never original evidence."""
    import shutil
    from equivalence.cases import build_cases as registered

    assert packet["version"] == "v5"
    cli, program = packet["cli"], packet["program"]
    production_program = SCRIPT.parents[1]
    for name in ("scope.json", "reference.json"):
        (program / "equivalence" / name).write_bytes((production_program / "equivalence" / name).read_bytes())
    (program / "equivalence/cases.py").write_text("# UNIT_REGISTERED_FACTORY_ONLY\n")
    definitions = registered()[:1452] + packet["frozen"].build_cases()
    monkeypatch.setattr(cli, "_registered_cases", lambda: deepcopy(definitions))
    adapter_hashes = {"UNIT_ONLY.py": "e" * 64}
    monkeypatch.setattr(cli, "_suite_adapter_hashes", lambda: dict(adapter_hashes))
    native_root, sdk_root = (packet["tmp"] / name for name in ("suite-native", "suite-sdk"))
    native_root.mkdir()
    sdk_root.mkdir()
    captures = {}
    for identifier in packet["frozen"].CASE_HASHES:
        source = next(root / identifier for root in packet["roots"] if (root / identifier).exists())
        native_dir, sdk_dir = native_root / identifier, sdk_root / identifier
        shutil.move(str(source / "native"), native_dir)
        shutil.move(str(source / "sdk/evidence"), sdk_dir)
        (source / "sdk-output.json").unlink()
        captures[identifier] = native_dir, sdk_dir
    for root in packet["roots"]:
        (root / "report.json").unlink()  # Suite mode must not need a collector surrogate.
    rows, diagnostics = [], []
    for definition in definitions:
        row = {key: deepcopy(definition[key]) for key in ("id", "operation", "input", "requirement", "covers")}
        row.update({key: deepcopy(definition[key]) for key in
                    ("normalizationPolicy", "driverScope", "declaredDeviation") if key in definition})
        row["status"] = "matched"
        if definition["id"] in captures:
            native_dir, sdk_dir = captures[definition["id"]]
            row.update(runtimeEvidenceValidated=True,
                       openclaw=json.loads((native_dir / "stdout.json").read_text())["result"],
                       python=json.loads((sdk_dir / "python-raw.json").read_text())[0]["observation"]["result"])
            row["status"] = "mismatched"
            for side, directory, filename in (("native", native_dir, "evidence/native-raw.json"),
                                              ("python", sdk_dir, "python-raw.json")):
                sealed = cli._seal(directory / filename)
                diagnostics.append({"id": definition["id"], "side": side, "sha256": sealed["sha256"],
                                    "evidenceDirectory": str(directory), "validationStatus": "verified",
                                    "rawSnapshotReference": {"directory": str(directory), "file": filename,
                                                             "bytes": sealed["bytes"], "sha256": sealed["sha256"]}})
        rows.append(row)
    scope = json.loads((program / "equivalence/scope.json").read_text())
    requirements, uncovered = [], []
    for requirement in scope["requirements"]:
        acceptance = []
        for point in requirement["acceptance"]:
            identifiers = [case["id"] for case in definitions if point["id"] in case["covers"]]
            if not identifiers:
                uncovered.append(point["id"])
            acceptance.append({"id": point["id"], "caseIds": identifiers, "matchedCaseIds": []})
        requirements.append({"id": requirement["id"], "required": requirement["required"], "acceptance": acceptance,
                             "registeredCases": sum(case["requirement"] == requirement["id"] for case in definitions)})
    report = {"schemaVersion": 1, "kind": "pinned-differential-acceptance", "mode": "full", "status": "mismatched",
              "reference": cli._reference_authority(packet["reference"], packet["node"]),
              "manifestSha256": {"reference": cli._seal(program / "equivalence/reference.json")["sha256"],
                                 "scope": cli._seal(program / "equivalence/scope.json")["sha256"]},
              "implementation": {**cli._sdk_identity(packet["sdk"]), "trackedWorkingTreeDirty": False},
              "adapterSha256": adapter_hashes, "casesSha256": cli._seal(program / "equivalence/cases.py")["sha256"],
              "forgetIndexFenceNode": cli._node_authority(packet["node"]),
              "forgetIndexFenceBindings": {"sourceBuildReproduced": False, "sourceFallbackAllowed": False},
              "summary": {"matched": 1452, "mismatched": 13, "blocked": 0, "uncoveredAcceptance": len(uncovered)},
              "fullScopePassed": False, "startedAt": "2026-11-14T00:00:00+00:00", "finishedAt": "2026-11-14T00:01:00+00:00",
              "durationSeconds": 60.0, "referenceExecution": {"trackedTypeScriptCaseIds": [],
                                                            "compiledReleaseCaseIds": [case["id"] for case in definitions]},
              "cases": rows, "runtimeDiagnostics": diagnostics, "requirements": requirements,
              "uncoveredAcceptance": uncovered, "errors": []}
    path = packet["tmp"] / "full-1465.json"
    def save():
        path.write_text(json.dumps(report, ensure_ascii=True, allow_nan=False) + "\n")
    save()
    def args(output):
        return ["--version", "v5", "--suite-report", str(path), "--native-capture-root", str(native_root),
                "--sdk-capture-root", str(sdk_root), "--reference", str(packet["reference"]), "--node", str(packet["node"]),
                "--sdk-source-root", str(packet["sdk"]), "--adapter-root", str(program), "--output", str(output)]
    return {**packet, "suite": report, "suite_path": path, "save_suite": save, "suite_args": args,
            "captures": captures, "native_root": native_root, "sdk_root": sdk_root}


@pytest.mark.parametrize("packet", ["v5"], indirect=True)
def test_suite_mode_streams_exact_full_registered_scope_without_collector_or_small_sdk_files(suite_packet, monkeypatch):
    packet, cli = suite_packet, suite_packet["cli"]
    before = packet["suite_path"].read_bytes()
    original = cli._read_json
    def no_whole_report(path, **kwargs):
        assert Path(path) != packet["suite_path"], "The large suite must be streamed, never whole-loaded"
        return original(path, **kwargs)
    monkeypatch.setattr(cli, "_read_json", no_whole_report)
    output = packet["tmp"] / "suite-replay.json"
    assert cli.main(packet["suite_args"](output)) == 1
    result = json.loads(output.read_text())
    assert result["validCompleteBaseline"] is True and result["summary"] == {"match": 0, "mismatch": 13, "blocked": 0}
    assert result["suiteAuthority"]["registeredCases"] == 1465
    assert result["sourceReports"][0]["fixedAcceptancePoints"] == 128
    assert [call[0] for call in packet["calls"]] == list(packet["frozen"].CASE_HASHES)
    assert all(set(row["files"]) == {"nativeRaw", "sdkRaw", "nativeStdout"} for row in result["cases"])
    assert all("sdkOutput" not in row["files"] for row in result["cases"])
    assert result["acceptancePointsAwarded"] == 0 and result["covers"] == [] and result["fullScopePassed"] is False
    assert packet["suite_path"].read_bytes() == before


@pytest.mark.parametrize("packet", ["v5"], indirect=True)
@pytest.mark.parametrize("attack", [
    "missing-payload", "missing-input", "wrong-old-definition", "omitted-old-row", "duplicated-v5-row",
    "scope-hash", "source-hash", "dirty-source", "node", "case-source", "missing-side", "duplicate-side",
    "unverified-side", "wrong-file", "reference-hash", "boolean-custody", "scope-denominator", "errors",
    "foreign-runtime-record",
])
def test_suite_admission_rejects_incomplete_or_foreign_global_and_v5_claims_before_guard(suite_packet, attack):
    packet = suite_packet
    report = packet["suite"]
    row = report["cases"][1452]
    if attack == "missing-payload":
        del row["python"]
    elif attack == "missing-input":
        del row["input"]
    elif attack == "wrong-old-definition":
        report["cases"][0]["input"] = {"changed": True}
    elif attack == "omitted-old-row":
        report["cases"].pop(0)
    elif attack == "duplicated-v5-row":
        report["cases"].append(deepcopy(row))
    elif attack == "scope-hash":
        report["manifestSha256"]["scope"] = "0" * 64
    elif attack == "source-hash":
        report["implementation"]["sourceSha256"] = "0" * 64
    elif attack == "dirty-source":
        report["implementation"]["trackedWorkingTreeDirty"] = True
    elif attack == "node":
        report["forgetIndexFenceNode"]["sha256"] = "0" * 64
    elif attack == "case-source":
        report["casesSha256"] = "0" * 64
    elif attack == "missing-side":
        report["runtimeDiagnostics"].pop()
    elif attack == "duplicate-side":
        report["runtimeDiagnostics"].append(deepcopy(report["runtimeDiagnostics"][0]))
    elif attack == "unverified-side":
        report["runtimeDiagnostics"][0]["validationStatus"] = "unverified"
    elif attack == "wrong-file":
        report["runtimeDiagnostics"][0]["rawSnapshotReference"]["file"] = "../other.json"
    elif attack == "reference-hash":
        report["runtimeDiagnostics"][0]["rawSnapshotReference"]["sha256"] = "0" * 64
    elif attack == "boolean-custody":
        row["runtimeEvidenceValidated"] = 1
    elif attack == "scope-denominator":
        report["requirements"].pop()
    elif attack == "foreign-runtime-record":
        report["runtimeDiagnostics"].append({"id": "unregistered-evidence", "side": "native"})
    else:
        report["errors"].append({"code": "actual-final-check-failure"})
    packet["save_suite"]()
    output = packet["tmp"] / "bad-suite.json"
    assert packet["cli"].main(packet["suite_args"](output)) == 2
    result = json.loads(output.read_text())
    assert packet["calls"] == [] and result["validCompleteBaseline"] is False and result["errors"]
    assert result["acceptancePointsAwarded"] == 0 and result["fullScopePassed"] is False


@pytest.mark.parametrize("packet", ["v5"], indirect=True)
@pytest.mark.parametrize("attack", ["native-root", "sdk-root", "bytes", "symlink", "report-payload", "post-replay-change"])
def test_suite_roots_original_bytes_whole_payloads_and_final_seals_are_independent(suite_packet, attack):
    packet = suite_packet
    output = packet["tmp"] / "tampered-suite.json"
    args = packet["suite_args"](output)
    identifier = next(iter(packet["frozen"].CASE_HASHES))
    native_dir, sdk_dir = packet["captures"][identifier]
    if attack in {"native-root", "sdk-root"}:
        root = packet["tmp"] / "unselected-physical-root"
        root.mkdir()
        flag = "--native-capture-root" if attack == "native-root" else "--sdk-capture-root"
        args[args.index(flag) + 1] = str(root)
    elif attack == "bytes":
        path = sdk_dir / "python-raw.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif attack == "symlink":
        path = sdk_dir / "python-raw.json"
        original = path.with_name("original.json")
        path.rename(original)
        path.symlink_to(original)
    elif attack == "report-payload":
        packet["suite"]["cases"][1452]["python"]["calls"]["labelled"]["side"] = "altered-full-payload"
        packet["save_suite"]()
    else:
        def change(case):
            packet["hook"]["function"] = None
            path = native_dir / "stdout.json"
            path.write_bytes(path.read_bytes() + b" ")
        packet["hook"]["function"] = change
    assert packet["cli"].main(args) == 2
    result = json.loads(output.read_text())
    assert result["errors"] and result["validCompleteBaseline"] is False
    assert result["acceptancePointsAwarded"] == 0 and result["fullScopePassed"] is False


@pytest.mark.parametrize("packet", ["v5"], indirect=True)
def test_suite_selector_is_v5_only_explicit_and_mutually_exclusive(suite_packet):
    packet = suite_packet
    args = packet["suite_args"](packet["tmp"] / "never-created.json")
    invalid = [args + ["--capture-root", str(packet["roots"][0])],
               ["v4" if part == "v5" else part for part in args],
               [part for index, part in enumerate(args) if index not in (args.index("--native-capture-root"), args.index("--native-capture-root") + 1)]]
    for value in invalid:
        with pytest.raises(SystemExit) as error:
            packet["cli"].main(value)
        assert error.value.code == 2
    assert packet["calls"] == []


@pytest.mark.parametrize("packet", ["v5"], indirect=True)
def test_suite_mode_authenticates_matched_whole_payloads_without_awarding_acceptance(suite_packet):
    packet = suite_packet
    for row in packet["suite"]["cases"][1452:]:
        _, sdk_dir = packet["captures"][row["id"]]
        dispatch = json.loads((sdk_dir / "python-raw.json").read_text())
        dispatch[0]["observation"]["result"] = deepcopy(row["openclaw"])
        (sdk_dir / "python-raw.json").write_text(json.dumps(dispatch) + "\n")
        row["python"] = deepcopy(row["openclaw"])
        row["status"] = "matched"
        diagnostic = next(item for item in packet["suite"]["runtimeDiagnostics"]
                          if item["id"] == row["id"] and item["side"] == "python")
        sealed = packet["cli"]._seal(sdk_dir / "python-raw.json")
        diagnostic["sha256"] = sealed["sha256"]
        diagnostic["rawSnapshotReference"].update(bytes=sealed["bytes"], sha256=sealed["sha256"])
    for requirement in packet["suite"]["requirements"]:
        if requirement["id"] == "forget.index-fence":
            for point in requirement["acceptance"]:
                point["matchedCaseIds"] = list(packet["frozen"].CASE_HASHES)
    packet["suite"]["status"] = "incomplete" if packet["suite"]["uncoveredAcceptance"] else "passed"
    packet["suite"]["fullScopePassed"] = packet["suite"]["status"] == "passed"
    packet["suite"]["summary"].update(matched=1465, mismatched=0)
    packet["save_suite"]()
    output = packet["tmp"] / "all-match-suite.json"
    assert packet["cli"].main(packet["suite_args"](output)) == 0
    report = json.loads(output.read_text())
    assert report["validCompleteBaseline"] is True and report["candidateFamilyMatched"] is True
    assert report["summary"] == {"match": 13, "mismatch": 0, "blocked": 0}
    assert report["acceptancePointsAwarded"] == 0 and report["covers"] == [] and report["fullScopePassed"] is False


@pytest.mark.parametrize("packet", ["v5"], indirect=True)
@pytest.mark.parametrize("suffix", [',"ignored":{"duplicate":1,"duplicate":2}}', ',"ignored":1e4000}', '} {}'])
def test_suite_stream_validates_even_discarded_fields_and_trailing_data(suite_packet, suffix):
    packet = suite_packet
    wire = packet["suite_path"].read_text().rstrip()
    packet["suite_path"].write_text(wire[:-1] + suffix)
    output = packet["tmp"] / "bad-stream.json"
    assert packet["cli"].main(packet["suite_args"](output)) == 2
    result = json.loads(output.read_text())
    assert packet["calls"] == [] and result["validCompleteBaseline"] is False
    assert result["errors"] and result["acceptancePointsAwarded"] == 0


@pytest.mark.parametrize("packet", ["v5"], indirect=True)
def test_suite_reader_and_discarded_wire_are_released_before_any_raw_capture_access(suite_packet, monkeypatch):
    import weakref
    from equivalence import strict_report_reader

    packet = suite_packet
    packet["suite"]["runtimeDiagnostics"].insert(0, {
        "id": packet["suite"]["cases"][0]["id"], "side": "native", "rawSnapshots": [{"UNIT_LEGACY_DISCARDED": "x" * 1024 * 1024}]})
    packet["save_suite"]()
    references = []
    original_reader = strict_report_reader.Reader
    class ObservedReader(original_reader):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            references.append(weakref.ref(self))
    monkeypatch.setattr(strict_report_reader, "Reader", ObservedReader)
    original_reference = packet["cli"]._suite_reference
    def checked_reference(*args, **kwargs):
        assert references and all(reference() is None for reference in references)
        return original_reference(*args, **kwargs)
    monkeypatch.setattr(packet["cli"], "_suite_reference", checked_reference)
    output = packet["tmp"] / "bounded-replay.json"
    assert packet["cli"].main(packet["suite_args"](output)) == 1
    report = json.loads(output.read_text())
    assert report["validCompleteBaseline"] is True
    assert "UNIT_LEGACY_DISCARDED" not in output.read_text()


@pytest.mark.parametrize("packet", ["v5"], indirect=True)
@pytest.mark.parametrize("size_offset", [-1, 0, 1])
def test_suite_stream_admission_enforces_its_exact_byte_boundary(suite_packet, monkeypatch, size_offset):
    packet, cli = suite_packet, suite_packet["cli"]
    path = packet["suite_path"]
    wire = path.read_bytes()
    assert wire.endswith(b"\n")
    limit = len(wire)
    monkeypatch.setattr(cli, "SUITE_REPORT_LIMIT", limit)
    path.write_bytes(wire[:-1] if size_offset == -1 else wire + b" " * size_offset)
    assert path.stat().st_size == limit + size_offset
    output = packet["tmp"] / "suite-byte-boundary.json"

    assert cli.main(packet["suite_args"](output)) == (2 if size_offset > 0 else 1)
    result = json.loads(output.read_text())
    if size_offset > 0:
        assert packet["calls"] == [] and result["validCompleteBaseline"] is False
        assert any("bounded" in error["message"] for error in result["errors"])
    else:
        assert result["validCompleteBaseline"] is True
        assert result["summary"] == {"match": 0, "mismatch": 13, "blocked": 0}
    assert result["acceptancePointsAwarded"] == 0 and result["fullScopePassed"] is False


@pytest.mark.parametrize("size_offset", [-1, 0, 1])
def test_real_suite_ceiling_is_two_gib_before_any_report_read(packet, monkeypatch, size_offset):
    cli, root = packet["cli"], packet["tmp"]
    path = root / "sparse-suite.json"
    with path.open("wb") as stream:
        stream.truncate(2 * 1024 * 1024 * 1024 + size_offset)
    monkeypatch.setattr(cli, "_suite_authority", lambda frozen: ([], {"requirements": []}, {}))
    args = SimpleNamespace(suite_report=path, native_capture_root=root, sdk_capture_root=root)
    seal_limits = []

    class BeforeReportRead(Exception):
        pass

    def observe_seal(selected, *, limit):
        assert selected == path
        seal_limits.append(limit)
        raise BeforeReportRead

    monkeypatch.setattr(cli, "_seal", observe_seal)
    if size_offset > 0:
        with pytest.raises(ValueError, match="bounded"):
            cli._admit_suite_report(args, {}, {}, packet["frozen"])
        assert seal_limits == []
    else:
        with pytest.raises(BeforeReportRead):
            cli._admit_suite_report(args, {}, {}, packet["frozen"])
        assert seal_limits == [2 * 1024 * 1024 * 1024]


@pytest.mark.parametrize("kind,limit", [
    ("collector", 1024 * 1024 * 1024),
    ("native", 128 * 1024 * 1024),
    ("python", 512 * 1024 * 1024),
])
def test_suite_ceiling_does_not_expand_collector_or_engine_packet_limits(packet, monkeypatch, kind, limit):
    cli, root = packet["cli"], packet["tmp"]
    directory = root / "oversized-packet"
    filename = "evidence/native-raw.json" if kind == "native" else "python-raw.json"
    path = directory / filename
    path.parent.mkdir(parents=True)
    with path.open("wb") as stream:
        stream.truncate(limit + 1)
    original_open = Path.open

    def reject_packet_read(selected, *args, **kwargs):
        assert selected != path, "An oversized packet must be rejected before any read"
        return original_open(selected, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_packet_read)
    with pytest.raises(ValueError, match="bounded"):
        if kind == "collector":
            cli._read_json(path)
        else:
            cli._suite_reference({
                "id": "UNIT_OVERSIZED_PACKET", "side": kind, "sha256": "0" * 64,
                "evidenceDirectory": str(directory), "validationStatus": "verified",
                "rawSnapshotReference": {"directory": str(directory), "file": filename,
                                         "bytes": limit + 1, "sha256": "0" * 64},
            }, kind, root)
