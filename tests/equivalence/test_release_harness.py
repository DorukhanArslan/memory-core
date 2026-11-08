"""Harness integration controls use labelled transports, not parity evidence."""
from copy import deepcopy
import json
import subprocess
import sys

import pytest

from equivalence import flush_runtime_bindings, harness, release_runtime, runtime_oracle


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def release_suite(tmp_path, monkeypatch):
    checkout = tmp_path / "labelled-reference"
    checkout.mkdir()
    _git(checkout, "init", "-q")
    (checkout / "package.json").write_text(json.dumps({
        "version": "2026.9.9", "engines": {"node": ">=24.16.0 <25 || >=26.1.0"},
    }))
    (checkout / "probe.ts").write_text("// Labelled harness reference, not a memory oracle.\n")
    _git(checkout, "add", ".")
    _git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "Labelled release-harness fixture")
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({
        "tag": "v2026.9.9", "commit": _git(checkout, "rev-parse", "HEAD"),
        "nodeMin": "24.16.0", "nodeRanges": ">=24.16.0 <25 || >=26.1.0",
    }))
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"schemaVersion": 1, "requirements": [{
        "id": "indexing", "required": True, "acceptance": [
            {"id": "indexing.lifecycle", "description": "Labelled lifecycle boundary."},
        ],
    }]}))
    node = tmp_path / "node"
    node.write_text(f"#!{sys.executable}\nprint('v24.16.0')\n")
    node.chmod(0o700)
    cases = [{"id": f"labelled-runtime-{index}", "requirement": "indexing",
              "operation": "index-lifecycle-runtime", "input": {"provider": "none"},
              "covers": ["indexing.lifecycle"]} for index in range(2)]
    config = {"kind": "labelled-runtime-fixture", "runtimeRoot": str(tmp_path / "runtime"),
              "reference": {"tag": "v2026.9.9"},
              "buildAttestation": {"sourceBuildReproduced": False},
              "packages": [{"location": "node_modules/openclaw", "directory": "/owned/fixture",
                            "files": [{"path": "labelled.js", "sha256": "1" * 64}]}]}
    calls = {"prepare": [], "oracle": [], "python": []}

    def prepare(checkout, destination):
        calls["prepare"].append((checkout, destination))
        return deepcopy(config)

    def native(node, script, checkout, selected, timeout, **kwargs):
        calls["oracle"].append((script, deepcopy(selected), kwargs))
        return {"kind": "official-release-runtime-comparison", "sources": [],
                "results": [{"id": case["id"], "ok": True, "result": case["input"]}
                            for case in selected],
                "releaseSources": [{"package": "node_modules/openclaw", "path": "labelled.js",
                                    "sha256": "1" * 64}],
                "releaseTrace": {"kind": "labelled-trace-fixture", "protectedWorkerThreads": 1},
                "runtimeDiagnostics": [{"id": selected[0]["id"], "sha256": "2" * 64,
                                        "rawSnapshots": [{"raw": "labelled native snapshot"}]}]}

    def python(case):
        calls["python"].append(case["id"])
        directory = case["_diagnosticDirectory"]
        directory.mkdir(parents=True)
        (directory / "python-raw.json").write_text(json.dumps([{"raw": "labelled Python snapshot"}]))
        return case["input"]

    monkeypatch.setattr(release_runtime, "prepare_release_runtime", prepare)
    monkeypatch.setattr(harness, "_oracle", native)
    monkeypatch.setattr(flush_runtime_bindings, "prepare_flush_runtime_bindings",
                        lambda *_args: {"kind": "labelled-flush-owner-fixture"})
    return {"checkout": checkout, "node": node, "reference_path": reference,
            "scope_path": scope, "cases": cases, "python_runner": python,
            "release_runtime_root": tmp_path / "runtime"}, calls, config


def test_missing_official_artifacts_block_before_python_and_do_not_fall_back(release_suite, monkeypatch):
    options, calls, _ = release_suite

    def absent(*_args):
        raise release_runtime.ReleaseRuntimeError("Labelled missing-archive failure.")

    monkeypatch.setattr(release_runtime, "prepare_release_runtime", absent)
    report, code = harness.run_suite(**options)
    assert code == 2
    assert report["errors"][0]["code"] == "release-runtime-unavailable"
    assert calls["oracle"] == calls["python"] == []
    assert report["cases"] == []


@pytest.mark.parametrize("operation", ["index-lifecycle-runtime", "flush-trigger-runtime"])
def test_each_native_case_uses_a_fresh_dispatch_and_preserves_truthful_evidence(release_suite, operation):
    options, calls, _ = release_suite
    for case in options["cases"]:
        case["operation"] = operation
    report, code = harness.run_suite(**options)
    assert code == 0, report["errors"]
    assert len(calls["prepare"]) == 2  # Entire runtime authenticated before and after.
    assert [entry[1] for entry in calls["oracle"]] == [[case] for case in options["cases"]]
    assert all(entry[0].name == "release-oracle.mjs" for entry in calls["oracle"])
    assert all(entry[2]["release_runtime"]["kind"] == "labelled-runtime-fixture"
               for entry in calls["oracle"])
    assert report["sources"] == []
    assert report["referenceExecution"] == {
        "trackedTypeScriptCaseIds": [], "compiledReleaseCaseIds": calls["python"],
    }
    assert all(row["referenceMode"] == "authenticated-official-release" for row in report["cases"])
    assert report["releaseRuntime"]["buildAttestation"]["sourceBuildReproduced"] is False
    if operation == "flush-trigger-runtime":
        assert report["flushRuntimeBindings"] == {"kind": "labelled-flush-owner-fixture"}
    else:
        assert "flushRuntimeBindings" not in report
    assert "runtimeRoot" not in report["releaseRuntime"]
    assert all("directory" not in item and "files" not in item
               for item in report["releaseRuntime"]["packages"])
    assert len(report["releaseSources"]) == 1  # Union the shared authenticated imports.
    assert len(report["releaseTraces"]) == 2
    assert [row["side"] for row in report["runtimeDiagnostics"]] == ["native", "native", "python", "python"]
    assert {row["rawSnapshots"][0]["raw"] for row in report["runtimeDiagnostics"]} == {
        "labelled native snapshot", "labelled Python snapshot",
    }


@pytest.mark.parametrize("mutation", ["changed-config", "changed-artifact"])
def test_runtime_mutation_blocks_all_python_comparisons(release_suite, monkeypatch, mutation):
    options, calls, config = release_suite
    preparation_count = 0

    def prepare(*_args):
        nonlocal preparation_count
        preparation_count += 1
        if preparation_count == 2:
            if mutation == "changed-artifact":
                raise release_runtime.ReleaseRuntimeError("Authenticated artifact bytes changed.")
            return {**config, "manifestSha256": "0" * 64}
        return deepcopy(config)

    monkeypatch.setattr(release_runtime, "prepare_release_runtime", prepare)
    report, code = harness.run_suite(**options)
    assert code == 2
    assert report["errors"][0]["code"] == "release-runtime-changed"
    assert calls["python"] == []
    assert len(calls["oracle"]) == 2


def test_failed_native_case_is_not_retried_or_replaced_by_python(release_suite, monkeypatch):
    options, calls, _ = release_suite
    options["cases"] = options["cases"][:1]

    def failed(node, script, checkout, selected, timeout, **kwargs):
        calls["oracle"].append(selected)
        return {"results": [{"id": selected[0]["id"], "ok": False, "error": "fixture failure"}],
                "releaseSources": [], "releaseTrace": {}, "runtimeDiagnostics": []}

    monkeypatch.setattr(harness, "_oracle", failed)
    report, code = harness.run_suite(**options)
    assert code == 2
    assert len(calls["oracle"]) == 1 and calls["python"] == []
    assert report["cases"][0]["code"] == "oracle-case-failed"


@pytest.mark.parametrize("when", ["before", "after"])
def test_unverified_flush_owner_blocks_credit_without_a_source_or_python_fallback(release_suite, monkeypatch, when):
    options, calls, _ = release_suite
    for case in options["cases"]:
        case["operation"] = "flush-trigger-runtime"
    checked = 0

    def owner(*_args):
        nonlocal checked
        checked += 1
        if when == "before":
            raise ValueError("Labelled unverified compiled export.")
        return {"kind": "labelled-flush-owner-fixture", "digest": str(checked)}

    monkeypatch.setattr(flush_runtime_bindings, "prepare_flush_runtime_bindings", owner)
    report, code = harness.run_suite(**options)
    assert code == 2
    assert report["errors"][0]["code"] == (
        "flush-runtime-owner-unavailable" if when == "before" else "release-runtime-changed"
    )
    assert calls["python"] == []
    assert len(calls["oracle"]) == (0 if when == "before" else 2)


@pytest.mark.parametrize("mode", ["valid", "evidence-rejected", "trailing-stdout"])
def test_oracle_context_forwards_only_reviewed_environment_and_requires_exact_protocol(tmp_path, monkeypatch, mode):
    node = tmp_path / "labelled-node"
    node.write_text(f"#!{sys.executable}\n" + '''
import json,os,sys
assert os.environ['NODE_OPTIONS']=='--import=/trusted/preload.mjs'
assert 'OPENROUTER_API_KEY' not in os.environ
assert 'UNREVIEWED_NODE_FLAG' not in os.environ
body=json.load(sys.stdin)
print(json.dumps({'kind':'official-release-runtime-comparison','sources':[],
 'results':[{'id':body['cases'][0]['id'],'ok':True,'result':{'provider':'none'}}]}))
''' + ("print('native trailing output')\n" if mode == "trailing-stdout" else ""))
    node.chmod(0o700)
    runner = tmp_path / "labelled-release-oracle.mjs"
    runner.write_text("// Only the labelled Python command fixture executes this test.\n")
    seen = []

    class Context:
        env = {"NODE_OPTIONS": "--import=/trusted/preload.mjs"}

        def __init__(self, config, hashes):
            assert config == {"fixture": True}
            assert "release-preload.mjs" in hashes

        def __enter__(self):
            seen.append("entered")
            return self

        def __exit__(self, *_args):
            seen.append("closed")

        def collect(self, result, cases):
            seen.append("collected")
            if mode == "evidence-rejected":
                raise runtime_oracle.RuntimeOracleError("Labelled trace rejection.")
            return {**result, "releaseSources": [{"fixture": True}],
                    "releaseTrace": {"protectedWorkerThreads": 2},
                    "runtimeDiagnostics": [{"rawSnapshots": [{"raw": True}]}]}

    monkeypatch.setattr(runtime_oracle, "ReleaseOracleExecution", Context)
    monkeypatch.setenv("NODE_OPTIONS", "UNREVIEWED_NODE_FLAG")
    monkeypatch.setenv("OPENROUTER_API_KEY", "LABELLED_PRIVATE_VALUE")
    case = {"id": "labelled-case", "operation": "index-lifecycle-runtime", "input": {}}
    if mode == "valid":
        result = harness._oracle(node, runner, tmp_path, [case], 5, release_runtime={"fixture": True})
        assert result["sources"] == []
        assert result["runtimeDiagnostics"] == [{"rawSnapshots": [{"raw": True}]}]
        assert result["releaseTrace"]["protectedWorkerThreads"] == 2
        assert seen == ["entered", "collected", "closed"]
    else:
        with pytest.raises(harness.HarnessError) as error:
            harness._oracle(node, runner, tmp_path, [case], 5, release_runtime={"fixture": True})
        assert error.value.code == ("runtime-evidence-invalid" if mode == "evidence-rejected" else "oracle-protocol")
        assert seen == (["entered", "collected", "closed"] if mode == "evidence-rejected"
                        else ["entered", "closed"])
