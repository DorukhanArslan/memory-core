"""Gate controls use a labelled local command fixture, not an OpenClaw model."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from equivalence.harness import run_suite


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def suite(tmp_path):
    checkout = tmp_path / "reference"
    checkout.mkdir()
    _git(checkout, "init", "-q")
    (checkout / "package.json").write_text(json.dumps({
        "version": "2026.9.9", "engines": {"node": ">=24.16.0 <25 || >=26.1.0"},
    }))
    (checkout / "probe.ts").write_text("export const fixture = true;\n")
    _git(checkout, "add", ".")
    _git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "Labelled reference-command fixture")
    commit = _git(checkout, "rev-parse", "HEAD")
    target = tmp_path / "reference.json"
    target.write_text(json.dumps({"tag": "v2026.9.9", "commit": commit,
                                  "nodeMin": "24.16.0", "nodeRanges": ">=24.16.0 <25 || >=26.1.0"}))
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"schemaVersion": 1, "requirements": [
        {"id": "storage", "required": True, "acceptance": [
            {"id": "storage.write", "description": "A real saved write is visible."},
            {"id": "storage.restart", "description": "The write survives restart."},
        ]},
    ]}))
    node = tmp_path / "node"
    node.write_text("#!" + sys.executable + "\n" + '''
import hashlib,json,os,pathlib,sys,time
if sys.argv[1:]==['--version']:
    print('v24.16.0')
    raise SystemExit
runner=pathlib.Path(sys.argv[1])
root=pathlib.Path(sys.argv[2])
mode=runner.read_text().strip()
payload=json.load(sys.stdin)
with (runner.parent/'dispatches').open('a') as f: f.write('dispatch\\n')
if mode=='sleep': time.sleep(2)
if mode=='error':
    print('SECRET_FIXTURE_VALUE',file=sys.stderr)
    raise SystemExit(1)
if mode=='invalid':
    print('not JSON')
    raise SystemExit
rows=[{'id':case['id'],'ok':True,'result':case['input']} for case in payload['cases']]
if mode=='mismatch': rows[0]['result']='Different actual result'
if mode=='duplicate': rows.append(rows[0])
if mode=='omitted': rows=[]
if mode=='skip': rows[0]['status']='skipped'
if mode=='failed': rows[0]={'id':rows[0]['id'],'ok':False,'error':'SECRET_FIXTURE_VALUE'}
if mode=='environment':
    assert 'EQUIVALENCE_PRIVATE_FIXTURE' not in os.environ
    assert 'OPENROUTER_API_KEY' not in os.environ
    assert 'NODE_OPTIONS' not in os.environ
source={'path':'probe.ts','sha256':hashlib.sha256((root/'probe.ts').read_bytes()).hexdigest()}
if mode=='bad-source': source['sha256']='0'*64
if mode=='untracked-source':
    (root/'untracked.ts').write_text('untracked')
    source={'path':'untracked.ts','sha256':hashlib.sha256(b'untracked').hexdigest()}
if mode=='mutate-reference': (root/'probe.ts').write_text('changed during dispatch')
print(json.dumps({'results':rows,'sources':[] if mode=='no-sources' else [source]}))
''')
    node.chmod(0o700)
    oracle = tmp_path / "oracle.mjs"
    oracle.write_text("match")
    cases = [{"id": "write-fixture", "requirement": "storage", "operation": "echo",
              "input": {"saved": True}, "covers": ["storage.write"]}]
    return {"checkout": checkout, "node": node, "reference_path": target,
            "scope_path": scope, "oracle_path": oracle, "cases": cases,
            "python_runner": lambda case: case["input"]}


def test_full_gate_rejects_uncovered_acceptance_even_when_registered_cases_match(suite):
    report, code = run_suite(**suite)
    assert code == 1
    assert report["status"] == "incomplete"
    assert report["summary"] == {"matched": 1, "mismatched": 0, "blocked": 0,
                                  "uncoveredAcceptance": 1}
    assert report["uncoveredAcceptance"] == ["storage.restart"]
    assert report["fullScopePassed"] is False


def test_explicit_smoke_is_not_a_full_equivalence_claim(suite):
    report, code = run_suite(**suite, smoke=True)
    assert code == 0
    assert report["status"] == "passed"
    assert report["mode"] == "smoke"
    assert report["fullScopePassed"] is False
    assert "no full-equivalence claim" in report["claim"]
    assert report["reference"]["commit"]
    assert report["sources"][0]["path"] == "probe.ts"


def test_full_gate_passes_only_after_every_declared_point_has_a_passing_case(suite):
    case = deepcopy(suite["cases"][0])
    case.update(id="restart-fixture", covers=["storage.restart"])
    suite["cases"].append(case)
    report, code = run_suite(**suite)
    assert code == 0
    assert report["summary"]["matched"] == 2
    assert report["fullScopePassed"] is True
    assert report["uncoveredAcceptance"] == []


def test_difference_is_retained_and_never_xfailed(suite):
    suite["oracle_path"].write_text("mismatch")
    report, code = run_suite(**suite, smoke=True)
    assert code == 1
    assert report["status"] == "mismatched"
    assert report["cases"][0] == {
        "id": "write-fixture", "requirement": "storage", "covers": ["storage.write"],
        "status": "mismatched", "operation": "echo", "input": {"saved": True},
        "python": {"saved": True}, "openclaw": "Different actual result",
    }


@pytest.mark.parametrize("change,expected", [
    ("wrong-commit", "reference-commit-mismatch"),
    ("missing", "reference-missing"),
    ("dirty", "reference-dirty"),
    ("wrong-version", "reference-version-mismatch"),
    ("wrong-node", "node-unsupported"),
])
def test_invalid_reference_never_dispatches_or_passes(suite, change, expected):
    if change == "wrong-commit":
        target = json.loads(suite["reference_path"].read_text())
        target["commit"] = "0" * 40
        suite["reference_path"].write_text(json.dumps(target))
    elif change == "missing":
        suite["checkout"] = suite["checkout"] / "absent"
    elif change == "dirty":
        (suite["checkout"] / "probe.ts").write_text("changed")
    elif change == "wrong-version":
        package = suite["checkout"] / "package.json"
        package.write_text(json.dumps({"version": "2026.9.6"}))
        _git(suite["checkout"], "add", "package.json")
        _git(suite["checkout"], "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-qm", "Wrong reference version fixture")
        target = json.loads(suite["reference_path"].read_text())
        target["commit"] = _git(suite["checkout"], "rev-parse", "HEAD")
        suite["reference_path"].write_text(json.dumps(target))
    else:
        suite["node"].write_text(suite["node"].read_text().replace("v24.16.0", "v25.0.0"))
    report, code = run_suite(**suite, smoke=True)
    assert code == 2
    assert report["status"] == "blocked"
    assert report["errors"][0]["code"] == expected
    assert not (suite["oracle_path"].parent / "dispatches").exists()


@pytest.mark.parametrize("mode,expected", [
    ("duplicate", "oracle-protocol"), ("omitted", "oracle-protocol"),
    ("skip", "oracle-protocol"), ("invalid", "oracle-protocol"),
    ("bad-source", "oracle-source-mismatch"), ("no-sources", "oracle-protocol"),
    ("untracked-source", "oracle-source-mismatch"), ("mutate-reference", "oracle-source-mismatch"),
])
def test_invalid_or_mutated_evidence_blocks_acceptance(suite, mode, expected):
    suite["oracle_path"].write_text(mode)
    report, code = run_suite(**suite, smoke=True)
    assert code == 2
    assert report["status"] == "blocked"
    assert report["errors"][0]["code"] == expected


@pytest.mark.parametrize("mode", ["error", "failed"])
def test_runner_failures_are_private_not_successful_cases(suite, mode):
    suite["oracle_path"].write_text(mode)
    report, code = run_suite(**suite, smoke=True)
    assert code == 2
    assert report["status"] == "blocked"
    assert "SECRET_FIXTURE_VALUE" not in json.dumps(report)
    assert (suite["oracle_path"].parent / "dispatches").read_text().count("dispatch") == 1


def test_timeout_does_not_retry_the_reference_process(suite):
    suite["oracle_path"].write_text("sleep")
    report, code = run_suite(**suite, smoke=True, timeout_seconds=0.05)
    assert code == 2
    assert report["errors"][0]["code"] == "oracle-timeout"
    assert (suite["oracle_path"].parent / "dispatches").read_text().count("dispatch") == 1


def test_secrets_and_node_options_do_not_cross_to_oracle(suite, monkeypatch):
    suite["oracle_path"].write_text("environment")
    monkeypatch.setenv("EQUIVALENCE_PRIVATE_FIXTURE", "SECRET_FIXTURE_VALUE")
    monkeypatch.setenv("OPENROUTER_API_KEY", "SECRET_FIXTURE_VALUE")
    monkeypatch.setenv("NODE_OPTIONS", "SECRET_FIXTURE_VALUE")
    report, code = run_suite(**suite, smoke=True)
    assert code == 0
    assert "SECRET_FIXTURE_VALUE" not in json.dumps(report)


def test_storage_cases_require_authenticated_dependencies_before_dispatch(suite, monkeypatch):
    from equivalence.dependencies import DependencyError

    def unavailable(*args, **kwargs):
        raise DependencyError("Untrusted archive fixture; do not forward diagnostic details.")

    monkeypatch.setattr("equivalence.dependencies.prepare_dependencies", unavailable)
    suite["cases"][0]["operation"] = "storage-discovery"
    report, code = run_suite(**suite, smoke=True)
    assert code == 2
    assert report["errors"][0]["code"] == "reference-dependencies-unavailable"
    assert "Untrusted archive fixture" not in json.dumps(report)
    assert not (suite["oracle_path"].parent / "dispatches").exists()


def test_storage_cannot_pass_without_loaded_dependency_evidence(suite, monkeypatch):
    config = {"schemaVersion": 1, "kind": "labelled-package-fixture", "packages": []}
    monkeypatch.setattr("equivalence.dependencies.prepare_dependencies", lambda *a, **k: config)
    monkeypatch.setattr("equivalence.reference_bindings.prepare_reference_bindings", lambda *a: {})
    suite["cases"][0]["operation"] = "storage-discovery"
    report, code = run_suite(**suite, smoke=True)
    assert code == 2
    assert report["errors"][0]["code"] == "oracle-dependency-mismatch"
    assert (suite["oracle_path"].parent / "dispatches").read_text().count("dispatch") == 1


def test_python_adapter_mutation_invalidates_the_report(suite, monkeypatch, tmp_path):
    from equivalence import harness

    adapter = tmp_path / "labelled_adapter.py"
    adapter.write_text("original adapter fixture")
    monkeypatch.setattr(harness, "_adapter_identity",
                        lambda: {adapter.name: harness._digest(adapter)})

    def mutate(case):
        adapter.write_text("changed during the Python half")
        return case["input"]

    suite["python_runner"] = mutate
    report, code = run_suite(**suite, smoke=True)
    assert code == 2
    assert report["errors"][0]["code"] == "adapter-changed"
    assert report["fullScopePassed"] is False


def test_json_booleans_do_not_match_numbers_and_no_float_tolerance_is_implied(suite):
    suite["cases"][0]["input"] = {"value": True}
    suite["python_runner"] = lambda case: {"value": 1}
    report, code = run_suite(**suite, smoke=True)
    assert code == 1
    assert report["status"] == "mismatched"
    suite["cases"][0]["input"] = {"value": 0.6}
    suite["python_runner"] = lambda case: {"value": 0.6000000000000001}
    report, code = run_suite(**suite, smoke=True)
    assert code == 1
    assert report["status"] == "mismatched"


@pytest.mark.parametrize("corruption", ["duplicate-case", "unknown-point", "duplicate-point", "unknown-requirement"])
def test_invalid_coverage_claims_never_run_oracle(suite, corruption):
    if corruption == "duplicate-case":
        suite["cases"].append(deepcopy(suite["cases"][0]))
    elif corruption == "unknown-point":
        suite["cases"][0]["covers"] = ["storage.unregistered"]
    elif corruption == "duplicate-point":
        suite["cases"][0]["covers"] = ["storage.write", "storage.write"]
    else:
        suite["cases"][0]["requirement"] = "unknown"
    report, code = run_suite(**suite)
    assert code == 2
    assert report["errors"][0]["code"] == "cases-invalid"
    assert not (suite["oracle_path"].parent / "dispatches").exists()


@pytest.mark.parametrize("corruption", ["duplicate-acceptance", "no-required-scope", "empty-acceptance"])
def test_invalid_scope_cannot_create_an_empty_green_full_gate(suite, corruption):
    scope = json.loads(suite["scope_path"].read_text())
    requirement = scope["requirements"][0]
    if corruption == "duplicate-acceptance":
        requirement["acceptance"].append(deepcopy(requirement["acceptance"][0]))
    elif corruption == "no-required-scope":
        requirement["required"] = False
    else:
        requirement["acceptance"] = []
    suite["scope_path"].write_text(json.dumps(scope))
    report, code = run_suite(**suite)
    assert code == 2
    assert report["errors"][0]["code"] == "scope-invalid"
    assert not (suite["oracle_path"].parent / "dispatches").exists()
