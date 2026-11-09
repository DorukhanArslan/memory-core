"""Actual preload and inherited worker reject authority/case substitution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence.host_restart import CASE_HASHES, build_cases, case_wire
from equivalence.host_restart_native import LOCAL, digest
from equivalence.model_runtime_authority import prepare_model_node_authority

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def authority():
    node = Path(os.environ.get("MEMORY_EQ_NODE", ROOT / "work/node-v24.16.0-linux-x64/bin/node"))
    if not node.is_file():
        pytest.skip("The approved Node executable is required for actual preload transport guards")
    return prepare_model_node_authority(node)


def setup(tmp_path, authority):
    case = build_cases()[0]
    (tmp_path / "traces").mkdir()
    context = {"schemaVersion": 1, "kind": "release-oracle-execution", "runtime": {"packages": []},
        "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
        "hostRestartProfile": {"kind": "host-restart-recall-development", "operation": case["operation"],
            "caseId": case["id"], "caseWireSha256": CASE_HASHES[case["id"]],
            "nodeRuntime": authority, "acceptancePointsAwarded": 0},
        "allowedLocal": [{"path": str(ROOT / "equivalence" / name), "sha256": digest(ROOT / "equivalence" / name)} for name in LOCAL],
        "traceDirectory": str(tmp_path / "traces"), "evidenceDirectory": str(tmp_path / "evidence"),
        "stateDirectory": str(tmp_path / "state"), "configPath": str(tmp_path / "openclaw.json"),
        "approvedReferenceSources": [], "fixtureSourceCaptures": []}
    return case, context


def invoke(tmp_path, authority, context, *arguments, stdin=""):
    filename = tmp_path / "context.json"
    filename.write_text(json.dumps(context))
    env = {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC", "MEMORY_EQ_RELEASE_CONTEXT": str(filename),
           "NODE_OPTIONS": f'--import={ROOT / "equivalence/host-restart-preload.mjs"}'}
    return subprocess.run([authority["execPath"], *arguments], input=stdin, env=env, capture_output=True, text=True, timeout=15)


@pytest.mark.parametrize("field", ["promotionApplyFamilyProfile", "entryProvenanceProfile", "atomicCaseBinding",
                                   "approvedReferenceSources", "fixtureSourceCaptures", "casePath", "extraBackend"])
def test_preload_rejects_other_profiles_sources_and_full_case_carriers(tmp_path, authority, field):
    _, context = setup(tmp_path, authority)
    context[field] = [{}] if field.endswith("Sources") or field.endswith("Captures") else {}
    result = invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')")
    assert result.returncode != 0 and result.stdout == ""
    assert "Restart capability cannot borrow" in result.stderr
    assert not list((tmp_path / "traces").iterdir())


def test_a_changed_case_and_changed_digest_cannot_widen_the_capability(tmp_path, authority):
    case, context = setup(tmp_path, authority)
    case["input"]["phases"][1]["recall"]["prompt"] += " Other operation."
    wire = case_wire(case)
    context["hostRestartProfile"]["caseWireSha256"] = hashlib.sha256(wire).hexdigest()
    result = invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')", stdin=wire.decode())
    assert result.returncode != 0 and result.stdout == ""
    assert not list((tmp_path / "traces").iterdir())


def test_entry_rejects_changed_stdin_before_original_imports(tmp_path, authority):
    case, context = setup(tmp_path, authority)
    case["input"]["phases"][0]["write"]["text"] += " Other fact."
    result = invoke(tmp_path, authority, context, str(ROOT / "equivalence/host-restart-entry.mjs"), stdin=case_wire(case).decode())
    assert result.returncode != 0
    returned = json.loads(result.stdout)
    assert returned["ok"] is False and "protected input binding" in returned["error"]["message"]
    rows = [json.loads(line) for p in (tmp_path / "traces").glob("*.jsonl") for line in p.read_text().splitlines()]
    assert not any(row.get("kind") == "release" for row in rows)


def test_the_same_independent_preload_is_inherited_by_a_real_worker(tmp_path, authority):
    _, context = setup(tmp_path, authority)
    entry = str(ROOT / "equivalence/model-runtime-observation.mjs")
    script = "const {Worker}=require('node:worker_threads'); const w=new Worker(" + json.dumps(entry) + "); w.on('error',e=>{throw e;});"
    result = invoke(tmp_path, authority, context, "--eval", script)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for p in (tmp_path / "traces").glob("*.jsonl") for line in p.read_text().splitlines()]
    receipts = [row for row in rows if row["event"] == "host-restart-bootstrap"]
    assert len(receipts) == 2
    assert len({row["pid"] for row in receipts}) == 1
    assert len({row["threadId"] for row in receipts}) == 2
    assert all(row["profile"] == context["hostRestartProfile"] for row in receipts)
