"""Real preload rejects mixed authority and changed literals before original imports."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.promotion_apply_family import CASE_HASHES, build_cases
from equivalence.promotion_apply_family_native import LOCAL

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def authority():
    node = Path(os.environ.get("MEMORY_EQ_NODE", ROOT / "work/node-v24.16.0-linux-x64/bin/node"))
    if not node.is_file():
        pytest.skip("The exact approved binary is required for the family preload transport guard")
    return prepare_model_node_authority(node)


def setup(tmp_path, authority):
    case = build_cases()[0]
    request = tmp_path / "case.json"
    request.write_text(json.dumps(case))
    traces = tmp_path / "traces"
    traces.mkdir()
    context = {"schemaVersion": 1, "kind": "release-oracle-execution", "runtime": {"packages": []},
        "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
        "promotionApplyFamilyProfile": {"kind": "promotion-apply-family-development", "operation": case["operation"],
            "casePath": str(request), "caseFileSha256": hashlib.sha256(request.read_bytes()).hexdigest(),
            "caseWireSha256": CASE_HASHES[case["id"]], "nodeRuntime": authority, "acceptancePointsAwarded": 0},
        "allowedLocal": [{"path": str(ROOT / "equivalence" / name),
                          "sha256": hashlib.sha256((ROOT / "equivalence" / name).read_bytes()).hexdigest()} for name in LOCAL],
        "traceDirectory": str(traces), "evidenceDirectory": str(tmp_path / "evidence"),
        "stateDirectory": str(tmp_path / "state"), "configPath": str(tmp_path / "openclaw.json"),
        "approvedReferenceSources": [], "fixtureSourceCaptures": []}
    return case, request, context


def invoke(tmp_path, authority, context, *arguments):
    filename = tmp_path / "context.json"
    filename.write_text(json.dumps(context))
    env = {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC", "MEMORY_EQ_RELEASE_CONTEXT": str(filename),
           "NODE_OPTIONS": f'--import={ROOT / "equivalence/promotion-apply-family-preload.mjs"}'}
    return subprocess.run([authority["execPath"], *arguments], env=env, capture_output=True, text=True, timeout=15)


@pytest.mark.parametrize("field", ["promotionApplyProfile", "entryProvenanceProfile", "atomicCaseBinding",
                                   "approvedReferenceSources", "fixtureSourceCaptures", "extraBackend"])
def test_family_preload_refuses_other_profiles_sources_or_backend_fields(tmp_path, authority, field):
    _, _, context = setup(tmp_path, authority)
    context[field] = [{}] if field.endswith("Sources") or field.endswith("Captures") else {}
    result = invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Family capability cannot borrow" in result.stderr
    assert not list((tmp_path / "traces").iterdir())


@pytest.mark.parametrize("field", ["operation", "input", "id"])
def test_changed_case_cannot_import_an_original_even_with_a_changed_carrier_hash(tmp_path, authority, field):
    case, request, context = setup(tmp_path, authority)
    if field == "input":
        case["input"]["options"]["limit"] += 1
    else:
        case[field] += "-different"
    request.write_text(json.dumps(case))
    context["promotionApplyFamilyProfile"]["caseFileSha256"] = hashlib.sha256(request.read_bytes()).hexdigest()
    result = invoke(tmp_path, authority, context, str(ROOT / "equivalence/promotion-apply-family-entry.mjs"))
    assert result.returncode != 0
    returned = json.loads(result.stdout)
    assert returned["ok"] is False
    assert "exact reviewed literal" in returned["error"]["message"]
    rows = [json.loads(line) for p in (tmp_path / "traces").glob("*.jsonl") for line in p.read_text().splitlines()]
    assert not any(row.get("kind") == "release" for row in rows)
