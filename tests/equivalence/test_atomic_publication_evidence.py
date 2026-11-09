"""Real SDK observations challenge the independent protected atomic guards."""
from __future__ import annotations

from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from equivalence.atomic_publication_cases import build_atomic_publication_cases
from equivalence.atomic_publication_evidence import (
    AtomicEvidenceError, SAFE_INTEGER, encode_atomic_public, validate_atomic_publication_raw,
    validate_atomic_return_checkpoint, _read_surviving_tree,
)
from equivalence.atomic_publication_profile import validate_atomic_publication_profile, prepare_atomic_case_binding
from equivalence.atomic_publication_runtime import run_atomic_publication
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.release_runtime import ReleaseRuntimeError, validate_release_sources

ROOT = Path(__file__).resolve().parents[2]
NODE = Path("/workspace/openclaw-memory-bridge/node_modules/node/bin/node")


def _observation(tmp_path, suffix="temp-file-fsync-eio"):
    case = next(case for case in build_atomic_publication_cases() if case["id"].endswith("." + suffix))
    public = run_atomic_publication(case["input"], evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())[0]
    return case, public, raw


def _public(raw):
    snapshots = {when: [{key: value for key, value in entry.items() if key != "stat"} for entry in entries]
                 for when, entries in raw["snapshots"].items()}
    return encode_atomic_public({"provider": "none", "outcomes": raw["outcomes"], "snapshots": snapshots}, raw)


def test_real_sdk_errors_and_surviving_tree_pass_independent_reread(tmp_path):
    case, public, raw = _observation(tmp_path)
    validate_atomic_publication_raw(case, public, raw, evidence_directory=tmp_path, expected_side="sdk", verify_tree=True)


def test_native_collector_rejects_sdk_owner_impersonation(tmp_path):
    case, public, raw = _observation(tmp_path)
    raw["defaultNativeBinding"] = {"available": True, "overrideVariablesAbsent": True,
        "functions": ["createStagedFile", "stagedFileMatches", "removeStagedFile", "closeOwnedFd", "renameReplace", "renameNoReplace"]}
    with pytest.raises(AtomicEvidenceError, match="impersonate"):
        validate_atomic_publication_raw(case, public, raw, expected_side="native")


def test_fault_cannot_borrow_an_ordinary_existing_io_event(tmp_path):
    case, public, raw = _observation(tmp_path)
    ordinary = next(event for event in raw["ioEvents"] if event["operation"] == "open")
    raw["faults"][0]["events"] = [ordinary["seq"]]
    with pytest.raises(AtomicEvidenceError, match="borrow"):
        validate_atomic_publication_raw(case, public, raw)


def test_fault_cannot_claim_a_different_actual_operation_or_occurrence(tmp_path):
    case, public, raw = _observation(tmp_path)
    fault = next(event for event in raw["ioEvents"] if event["operation"] == "fault")
    related = next(event for event in raw["ioEvents"] if event["seq"] == fault["arguments"]["ioEvent"])
    related["operation"] = "close"
    with pytest.raises(AtomicEvidenceError, match="operation"):
        validate_atomic_publication_raw(case, public, raw)


def test_injected_error_must_match_the_literal_facts_even_if_raw_and_public_are_changed_together(tmp_path):
    case, public, raw = _observation(tmp_path)
    fault = next(event for event in raw["ioEvents"] if event["operation"] == "fault")
    fault["error"]["code"] = "ENOSPC"
    fault["rawError"]["properties"]["code"] = "ENOSPC"
    with pytest.raises(AtomicEvidenceError, match="literal code"):
        validate_atomic_publication_raw(case, public, raw)


@pytest.mark.parametrize("field", ["available", "overrideVariablesAbsent"])
def test_native_collector_rejects_missing_or_overridden_default_backend(tmp_path, field):
    case, public, raw = _observation(tmp_path)
    raw["defaultNativeBinding"] = {"available": True, "overrideVariablesAbsent": True,
        "functions": ["createStagedFile", "stagedFileMatches", "removeStagedFile", "closeOwnedFd", "renameReplace", "renameNoReplace"]}
    raw["defaultNativeBinding"][field] = False
    with pytest.raises(AtomicEvidenceError, match="default available"):
        validate_atomic_publication_raw(case, public, raw, expected_side="native")


def test_public_error_must_keep_every_actual_producer_field(tmp_path):
    case, public, raw = _observation(tmp_path)
    raw["outcomes"][0]["error"]["message"] = "category-only replacement"
    raw["requests"][0]["outcome"]["error"]["message"] = "category-only replacement"
    with pytest.raises(AtomicEvidenceError, match="producer field"):
        validate_atomic_publication_raw(case, public, raw)


def test_an_omitted_foreign_stage_is_detected_by_actual_anchored_tree_read(tmp_path):
    case, _, raw = _observation(tmp_path, "bootstrap-foreign-stage-before-cleanup")
    before = len(raw["snapshots"]["after"])
    raw["snapshots"]["after"] = [entry for entry in raw["snapshots"]["after"] if not Path(entry["path"]).name.startswith(".fs-safe-")]
    assert len(raw["snapshots"]["after"]) == before - 1
    forged_public = _public(raw)
    with pytest.raises(AtomicEvidenceError, match="reread"):
        validate_atomic_publication_raw(case, forged_public, raw, verify_tree=True)


def test_receipt_codec_requires_prepared_post_sync_stat_and_correct_fd_generation(tmp_path):
    _, _, raw = _observation(tmp_path, "bootstrap-published-close-fails")
    staged = raw["outcomes"][0]["error"]["details"]["publication"]["staged"]
    encoded = _public(raw)
    assert encoded["outcomes"][0]["error"]["details"]["publication"]["staged"]["identity"]["ctimeNs"] == "$PHYSICAL:stage-0:prepared:ctimeNs"
    allocation = raw["stageAllocations"][0]
    earlier = next(event for event in raw["ioEvents"] if event.get("fd") == allocation["fd"]
                   and event.get("when") == "after" and event.get("operation") == "fstat")
    changed = deepcopy(earlier["stat"])
    changed.update({key: str(staged["identity"][key]) for key in changed})
    changed["mode"] = str(int(changed["mode"]) | 0o100000)
    changed["ctimeNs"] = str(int(changed["ctimeNs"]) - 1)
    earlier["stat"] = changed
    staged["identity"]["ctimeNs"] = int(changed["ctimeNs"])
    encoded = _public(raw)
    assert encoded["outcomes"][0]["error"]["details"]["publication"]["staged"]["identity"]["ctimeNs"] != "$PHYSICAL:stage-0:prepared:ctimeNs"


@pytest.mark.skipif(not NODE.is_file(), reason="The approved local codec verifier binary is unavailable")
def test_javascript_and_python_receipt_codecs_preserve_exact_large_integers_and_phase(tmp_path):
    _, _, raw = _observation(tmp_path, "bootstrap-published-close-fails")
    snapshots = {when: [{key: value for key, value in entry.items() if key != "stat"} for entry in entries]
                 for when, entries in raw["snapshots"].items()}
    public = {"provider": "none", "outcomes": raw["outcomes"], "snapshots": snapshots}

    def transport(value):
        if type(value) is int and abs(value) > SAFE_INTEGER:
            return {"type": "bigint", "decimal": str(value)}
        if isinstance(value, list):
            return [transport(item) for item in value]
        if isinstance(value, dict):
            return {key: transport(item) for key, item in value.items()}
        return value

    program = "import fs from 'node:fs';import {encodeAtomicPublic} from './equivalence/atomic-publication-codec.mjs';const p=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(encodeAtomicPublic(p.public,p.raw)));"
    result = subprocess.run([str(NODE), "--input-type=module", "--eval", program], cwd=ROOT,
                            input=json.dumps(transport({"public": public, "raw": raw}), ensure_ascii=True),
                            capture_output=True, text=True, check=True, timeout=10,
                            env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"})
    assert json.loads(result.stdout) == encode_atomic_public(public, raw)


@pytest.mark.parametrize("operation,kind", [("atomic-commit-runtime", "append"), ("model-session-runtime", "commit")])
def test_atomic_capability_cannot_be_borrowed_by_another_owner(operation, kind):
    with pytest.raises(ValueError):
        validate_atomic_publication_profile({"kind": "approved-atomic-publication-profile", "operation": operation,
            "inputKind": kind, "nodeRuntime": {"execPath": "/owned/node", **APPROVED_NODE_RUNTIME}})


def test_external_entry_allowlist_is_exact_package_and_path():
    approved = ("node_modules/@openclaw/fs-safe", "dist/root.js")
    digest = "1" * 64
    config = {"packages": [{"location": approved[0], "files": [{"path": approved[1], "sha256": digest}]}]}
    sources = [{"package": approved[0], "path": approved[1], "sha256": digest}]
    validate_release_sources(config, sources, required_entry=approved)
    for foreign in ((approved[0], "dist/native.js"), ("node_modules/unreviewed", approved[1]), "dist/arbitrary.mjs"):
        with pytest.raises(ReleaseRuntimeError):
            validate_release_sources(config, sources, required_entry=foreign)


def test_return_checkpoint_keeps_a_separate_real_process_exit_tree(tmp_path):
    case, _, raw = _observation(tmp_path, "replacement-read-cleanup-and-close-fail")
    data = json.dumps([raw], ensure_ascii=True).encode()
    identity = prepare_atomic_case_binding(case)
    common = {"caseId": case["id"], "inputSha256": identity["inputSha256"], "fixtureBase": raw["fixtureBase"],
              "pid": raw["pid"], "threadId": 0}
    request = raw["requests"][0]
    settlement = {"stepId": request["id"], "owner": request["owner"], "arguments": request["arguments"],
                  "outcome": request["outcome"], "rawError": request["rawError"]}
    stage = Path(raw["stageAllocations"][0]["path"])
    stage.unlink()
    actual_exit = _read_surviving_tree(Path(raw["fixtureBase"]))
    events = [
        {**common, "event": "atomic-owner-start", "stepId": request["id"], "owner": request["owner"],
         "arguments": request["arguments"], "beforeTree": raw["snapshots"]["before"]},
        {**common, "event": "atomic-owner-settle", **settlement},
        {**common, "event": "atomic-return-checkpoint", "rawSha256": hashlib.sha256(data).hexdigest(), "rawBytes": len(data),
         "ioEventCount": len(raw["ioEvents"]), "settlements": [settlement], "subjectTree": raw["snapshots"]["after"]},
        {**common, "event": "atomic-exit-start", "checkpointCompleted": True},
        {**common, "event": "atomic-exit-end", "subjectTree": actual_exit},
    ]
    # Synthetic lifecycle carriers challenge only guard logic; the separate
    # protected collector requires actual hash-attested original invocations.
    result = validate_atomic_return_checkpoint(case, raw, events, raw_bytes=data, input_sha256=identity["inputSha256"])
    assert result["operationReturnEqualsProcessExit"] is False
    assert result["postProcessSubjectTree"] == actual_exit
    broken = deepcopy(events)
    broken.insert(3, deepcopy(broken[2]))
    with pytest.raises(AtomicEvidenceError, match="unique"):
        validate_atomic_return_checkpoint(case, raw, broken, raw_bytes=data, input_sha256=identity["inputSha256"])
    broken = deepcopy(events)
    broken[2]["rawSha256"] = "0" * 64
    with pytest.raises(AtomicEvidenceError, match="journal"):
        validate_atomic_return_checkpoint(case, raw, broken, raw_bytes=data, input_sha256=identity["inputSha256"])


@pytest.mark.skipif(not NODE.is_file(), reason="The approved local codec verifier binary is unavailable")
def test_trusted_checkpoint_rejects_unknown_steps_and_unsettled_returns_and_is_immutable(tmp_path):
    case = build_atomic_publication_cases()[0]
    binding = prepare_atomic_case_binding(case)
    evidence = tmp_path / "evidence"
    fixture = evidence / hashlib.sha256(case["id"].encode()).hexdigest() / "native-atomic-test"
    (fixture / "subject").mkdir(parents=True)
    context = {"atomicPublicationProfile": {"operation": case["operation"], "inputKind": "commit"},
               "atomicCaseBinding": binding, "evidenceDirectory": str(evidence), "runtime": {"runtimeRoot": str(tmp_path / "unavailable-runtime")}}
    filename = tmp_path / "context.json"
    filename.write_text(json.dumps(context, ensure_ascii=True))
    program = """
import fs from 'node:fs';
import {installAtomicReturnCheckpoint} from './equivalence/atomic-return-checkpoint.mjs';
const ctx=JSON.parse(fs.readFileSync(process.env.MEMORY_EQ_RELEASE_CONTEXT,'utf8'));
const base=JSON.parse(fs.readFileSync(0,'utf8')).fixture;
installAtomicReturnCheckpoint(ctx,()=>{});
const invoke=Symbol.for('memory.equivalence.atomic.invoke'),checkpoint=Symbol.for('memory.equivalence.atomic.return-checkpoint');
const errors=[];
try{await globalThis[invoke]('unknown',base);}catch(error){errors.push(error.message);}
try{globalThis[checkpoint](base);}catch(error){errors.push(error.message);}
let immutable=false;try{globalThis[invoke]=()=>{};}catch{immutable=true;}
process.stdout.write(JSON.stringify({errors,immutable,configurable:Object.getOwnPropertyDescriptor(globalThis,checkpoint).configurable}));
"""
    result = subprocess.run([str(NODE), "--input-type=module", "--eval", program], cwd=ROOT,
        input=json.dumps({"fixture": str(fixture)}), capture_output=True, text=True, check=True, timeout=10,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC", "MEMORY_EQ_RELEASE_CONTEXT": str(filename)})
    value = json.loads(result.stdout)
    assert value == {"errors": ["atomic-checkpoint-duplicate-or-out-of-phase-owner", "atomic-checkpoint-duplicate-or-unsettled-return"],
                     "immutable": True, "configurable": False}
