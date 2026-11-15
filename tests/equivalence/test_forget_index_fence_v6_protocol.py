"""Immutable V6 frontier and explicit routing; no original engine or credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

import pytest

from equivalence import forget_index_fence_evidence as guard
from equivalence import forget_index_fence_native as native
from equivalence import forget_index_fence_sdk as sdk
from equivalence import forget_index_fence_v5 as old
from equivalence import forget_index_fence_v6 as new
from equivalence.forget_index_fence_sdk_effects_evidence import _closed_effects_case
from equivalence.forget_index_fence_sdk_watch_evidence import _closed_watch_case
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME

ROOT = Path(__file__).resolve().parents[2]


def test_v6_only_moves_existing_keyword_join_and_explicit_version_identities():
    for index, (prior, current) in enumerate(zip(old.build_cases(), new.build_cases(), strict=True)):
        restored = deepcopy(current)
        for owner, key in ((restored, "id"), (restored, "operation"),
                           (restored["input"], "kind"), (restored["input"], "profile")):
            owner[key] = owner[key].replace("forget-index-fence-v6", "forget-index-fence-v5")
        if index == 9:
            steps = restored["input"]["steps"]
            join = steps.pop(18)
            assert join == prior["input"]["steps"][22]
            assert join["label"] == "selectedWatch" and join["afterCalls"] == ["forget:selected"]
            assert steps[17] == {"operation": "original-forget", "actor": "forgetter", "label": "selected"}
            assert steps[18]["label"] == "afterForgetBeforeOriginalEnrichment"
            assert steps[19] == {"operation": "release-gate", "gate": "keywordReply"}
            steps.insert(22, join)
        assert restored == prior
        assert guard._expected_calls(current["input"]) == guard._expected_calls(prior["input"])
        assert current["input"]["observationPolicy"]["watchEffects"]["protocol"] == "original-watch-effects-v5"
        assert current["input"]["observationPolicy"]["searchEffects"]["protocol"] == "original-search-effects-v3"
        assert current["input"]["clock"]["sourceWriteClock"]["protocol"] == "owned-source-write-clock-v2"


@pytest.mark.parametrize("case", new.build_cases(), ids=lambda case: case["id"])
def test_explicit_v6_routes_authenticate_whole_case_and_same_primitive_protocols(case):
    authority = {"execPath": "/labelled/no-engine/node", **APPROVED_NODE_RUNTIME}
    assert native._contract(case["operation"]) is new
    assert native._validated_case(case)[0] == case
    profile = native.prepare_profile(case, authority)
    assert profile["kind"] == "forget-index-fence-v6"
    assert profile["watchEffects"] == case["input"]["observationPolicy"]["watchEffects"]
    assert profile["acceptancePointsAwarded"] == 0
    assert native.validate_profile(profile) == profile
    assert sdk._literal(case["input"]) == case
    assert guard._case(case) == case["input"] and guard._version(case) == 6
    assert guard._native_profile_key(case) == "forgetIndexFenceV3Profile"
    assert guard._native_bootstrap_prefix(case) == "forget-index-fence-v3"
    assert _closed_effects_case(case) == 6 and _closed_watch_case(case) == case


@pytest.mark.parametrize("attack", ["unmoved-v5", "join-after-capture", "skip-actor", "extra-sync", "deadline", "clock", "comparison", "primitive-version"])
def test_v6_never_admits_relabelled_or_weakened_frontier(attack):
    case = deepcopy(new.build_cases()[9])
    value = case["input"]
    if attack == "unmoved-v5":
        value["steps"].insert(22, value["steps"].pop(18))
    elif attack == "join-after-capture":
        value["steps"].insert(19, value["steps"].pop(18))
    elif attack == "skip-actor":
        value["steps"][18]["actors"].pop()
    elif attack == "extra-sync":
        value["steps"].insert(18, {"operation": "original-sync", "actor": "forgetter", "label": "forced"})
    elif attack == "deadline":
        value["observationPolicy"]["watchEffects"]["extraDeadlineSeconds"] = 60
    elif attack == "clock":
        value["clock"]["nowMs"] += 1
    elif attack == "comparison":
        value["comparisonPolicy"]["dropPhysicalIndex"] = True
    else:
        value["observationPolicy"]["watchEffects"]["protocol"] = "original-watch-effects-v6"
    for validate in (new.validate_case, native._validated_case, guard._case, _closed_effects_case, _closed_watch_case):
        with pytest.raises(ValueError):
            validate(case)


def test_v6_registration_is_atomic_and_preload_exact_hash_allowlist_keeps_old_members():
    family = new.build_cases()
    new.validate_registration(family)
    for invalid in (family[:-1], family[::-1], family + [family[0]], old.build_cases()[:1] + family[1:]):
        with pytest.raises(ValueError):
            new.validate_registration(invalid)
    preload = (ROOT / "equivalence/forget-index-fence-preload.mjs").read_text()
    actual = json.loads(re.search(r"const approved=(\{.*?\});", preload)[1])
    assert all(actual[key] == value for key, value in old.CASE_HASHES.items())
    assert all(actual[key] == value for key, value in new.CASE_HASHES.items())
    assert len(actual) == 52
    assert hashlib.sha256(new.MANIFEST.read_bytes()).hexdigest() == new.MANIFEST_SHA256


def test_default_catalog_remains_original_v5_pending_explicit_promotion():
    from equivalence.cases import build_cases
    cases = build_cases()
    assert len(cases) == 1465
    assert cases[-13:] == old.build_cases()
    assert not any(case["operation"] == new.OPERATION for case in cases)


def test_v6_stdout_codec_binds_whole_actual_input_and_rejects_cross_version_host():
    value = new.build_cases()[9]["input"]
    observation = {"kind": "forget-index-fence-v6-sdk-host", "input": value,
                   "result": {"whole": [False, None, 0, "雪\nunchanged"]}}
    dispatch = {"kind": "forget-index-fence-v6-sdk-dispatch", "input": value,
                "stdout": json.dumps(observation, ensure_ascii=False) + "\n", "observation": observation}
    packet = sdk._capture_dispatch_packet(dispatch)
    assert guard.materialize_sdk_dispatch(packet)["observation"] == observation
    observation["kind"] = "forget-index-fence-v5-sdk-host"
    dispatch["stdout"] = json.dumps(observation, ensure_ascii=False) + "\n"
    with pytest.raises(ValueError):
        guard.materialize_sdk_dispatch(sdk._capture_dispatch_packet(dispatch))


def test_v6_native_builtin_admission_retains_same_live_watcher_settings(tmp_path):
    import os
    import subprocess
    from equivalence.model_runtime_authority import prepare_model_node_authority

    node = Path(os.environ.get("MEMORY_EQ_NODE", ROOT / "work/node-v24.16.0-linux-x64/bin/node"))
    if not node.is_file():
        pytest.skip("Pinned Node unavailable; builtin control only, no acceptance credit")
    prepare_model_node_authority(node)
    module = (ROOT / "equivalence/forget-index-fence-runtime.mjs").as_uri()
    body = """
import assert from 'node:assert/strict';
import {assertNativeLiteralVersion,captureResolvedManagerSettings} from MODULE;
const kind='forget-index-fence-v6',id=kind+'-keyword-worker-before-forget-enrichment-after';
assert.equal(assertNativeLiteralVersion({kind},id,kind+'-runtime'),kind);
assert.throws(()=>assertNativeLiteralVersion({kind},'forget-index-fence-v5-keyword-worker-before-forget-enrichment-after',kind+'-runtime'));
const settings={sync:{onSearch:true,onSessionStart:true,watch:true}},owner={settings};
const receipt=captureResolvedManagerSettings(owner,kind,()=> 'labelled-identity');
assert.equal(receipt.modeAdmission.required,true);assert.equal(receipt.modeAdmission.admitted,true);
assert.deepEqual(receipt.value,settings);assert.equal(owner.settings,settings);
assert.equal(captureResolvedManagerSettings({settings:{sync:{onSearch:true,onSessionStart:false,watch:false}}},kind,()=> 'labelled').modeAdmission.admitted,false);
console.log('builtin-only-admission');
""".replace("MODULE", json.dumps(module))
    completed = subprocess.run([str(node), "--input-type=module", "--eval", body], cwd=tmp_path,
                               env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"},
                               capture_output=True, text=True, timeout=10, check=False)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "builtin-only-admission"
