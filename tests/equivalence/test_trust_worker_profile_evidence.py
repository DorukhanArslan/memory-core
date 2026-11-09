"""Non-executing protocol fixtures reject forged worker transport and authority."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.runtime_oracle import ROOT, RuntimeOracleError
from equivalence.trust_worker_profile import worker_profile_public
from equivalence.trust_worker_profile_evidence import (
    PARENT_ARTIFACTS, WORKER_ARTIFACTS, WORKER_PARENT_ARTIFACTS, validate_trust_worker_profile_raw,
)


def _fixture(tmp_path, identifier="registry-changed-once"):
    captures = json.loads((Path(__file__).parents[1] / "fixtures/trust-worker-profile-captures.json").read_text())
    capture, = [row for row in captures["observations"] if row["id"] == identifier]
    base = str(tmp_path / "native-trust-worker-fixture")

    def relocate(value):
        if isinstance(value, str):
            return value.replace("/fixture/workspace", base + "/fixture")
        if isinstance(value, dict):
            return {key: relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        return value

    observation = relocate(capture["native"])
    request = {"input": capture["input"], "runtimeRoot": capture["runtimeRoot"], "fixtureDirectory": base + "/fixture"}
    wire = json.dumps(request)
    child = {"request": request, "requestJson": wire, "requestSha256": hashlib.sha256(wire.encode()).hexdigest(),
             "argv": ["/approved/node", str(ROOT / "equivalence/trust-worker-runtime.mjs"), base + "/request.json"],
             "environmentKeys": ["LANG", "MEMORY_EQ_RELEASE_CONTEXT", "NODE_OPTIONS", "PATH", "TZ"],
             "pid": 102, "exit": {"code": 0, "signal": None}, "stdout": json.dumps(observation), "stderr": "",
             "observation": observation}
    raw = {"kind": "worker-profile", "fixtureBase": base, "coordinatorPid": 101,
           "input": deepcopy(capture["input"]), "child": child}
    row = {"id": "worker", "ok": True, "result": worker_profile_public(observation, base)}
    case = {"id": "worker", "input": deepcopy(capture["input"])}
    kwargs = {"runtime_root": capture["runtimeRoot"],
              "bootstrap": [{"pid": 101, "threadId": 0, "isMainThread": True},
                            {"pid": 102, "threadId": 0, "isMainThread": True},
                            {"pid": 102, "threadId": 1, "isMainThread": False}],
              "release_by_pid": {102: set(PARENT_ARTIFACTS | WORKER_PARENT_ARTIFACTS | WORKER_ARTIFACTS)},
              "local_by_pid": {101: {str(ROOT / ("equivalence/" + file)) for file in (
                  "release-oracle.mjs", "trust-worker-profile-runtime.mjs", "get-contract-runtime.mjs")},
                  102: {str(ROOT / "equivalence/trust-worker-runtime.mjs")}},
              "process_parents": {102: 101},
              "worker_imports": [{"package": "node_modules/openclaw", "path": path, "pid": 102, "threadId": 1}
                                 for path in WORKER_ARTIFACTS]}
    if capture["input"].get("observer"):
        kwargs["bootstrap"].pop()
        kwargs["worker_imports"] = []
        kwargs["release_by_pid"][102] = set(PARENT_ARTIFACTS)
    return row, case, [raw], kwargs


@pytest.mark.parametrize("identifier", ["registry-stable", "registry-changed-once", "registry-changed-twice",
                                        "registry-duplicate-membership", "observer-live-policy"])
def test_actual_captured_owner_results_bind_to_complete_new_public_transport(identifier, tmp_path):
    row, case, diagnostic, kwargs = _fixture(tmp_path, identifier)
    validate_trust_worker_profile_raw(row, case, diagnostic, tmp_path, **kwargs)


@pytest.mark.parametrize("tamper", [
    "public-source", "public-event", "request-bytes", "request-capability", "stdout", "ambient-environment",
    "child-parent", "child-preload", "frozen-owner", "source-owner", "worker-thread", "worker-implementation",
    "mutation-omitted", "result-repaired", "extra-observation", "unknown-secret",
])
def test_changed_worker_results_requests_registry_or_authority_fail_closed(tamper, tmp_path):
    row, case, diagnostic, kwargs = _fixture(tmp_path)
    child = diagnostic[0]["child"]
    observed = child["observation"]
    if tamper == "public-source":
        row["result"]["result"]["hash"] = "forged"
    elif tamper == "public-event":
        row["result"]["transcript"]["before"][1]["message"]["content"] = "forged"
    elif tamper == "request-bytes":
        child["requestJson"] += " "
    elif tamper == "request-capability":
        child["request"]["registry"] = ["worker-fixture-credential"]
    elif tamper == "stdout":
        child["stdout"] = "{}"
    elif tamper == "ambient-environment":
        child["environmentKeys"].append("OPENROUTER_API_KEY")
    elif tamper == "child-parent":
        kwargs["process_parents"][102] = 999
    elif tamper == "child-preload":
        kwargs["bootstrap"].pop(1)
    elif tamper == "frozen-owner":
        kwargs["local_by_pid"][102].clear()
    elif tamper == "source-owner":
        kwargs["release_by_pid"][102].remove(next(iter(PARENT_ARTIFACTS)))
    elif tamper == "worker-thread":
        for item in kwargs["worker_imports"]:
            item["pid"] = 999
    elif tamper == "worker-implementation":
        kwargs["worker_imports"].pop()
    elif tamper == "mutation-omitted":
        observed["mutations"].clear()
    elif tamper == "result-repaired":
        observed["result"]["content"] = "forged"
    elif tamper == "extra-observation":
        observed["invented"] = True
    else:
        case["input"]["secret"] = "not-admitted"
    with pytest.raises(RuntimeOracleError):
        validate_trust_worker_profile_raw(row, case, diagnostic, tmp_path, **kwargs)


def test_mutation_omission_is_rejected_even_with_coherently_rewritten_stream_and_public(tmp_path):
    row, case, diagnostic, kwargs = _fixture(tmp_path)
    child = diagnostic[0]["child"]
    observed = child["observation"]
    # A stream/public rewrite cannot manufacture a stable source acceptance.
    observed["mutations"].clear()
    child["stdout"] = json.dumps(observed)
    row["result"] = worker_profile_public(observed, diagnostic[0]["fixtureBase"])
    with pytest.raises(RuntimeOracleError):
        validate_trust_worker_profile_raw(row, case, diagnostic, tmp_path, **kwargs)


@pytest.mark.parametrize("tamper", ["observer-message", "observer-time", "invented-worker", "wrong-cut"])
def test_live_observer_cannot_drop_callbacks_or_claim_worker_retry(tamper, tmp_path):
    row, case, diagnostic, kwargs = _fixture(tmp_path, "observer-live-policy")
    child = diagnostic[0]["child"]
    observed = child["observation"]
    if tamper == "observer-message":
        observed["callbackObservations"][0]["message"]["content"] = "forged"
    elif tamper == "observer-time":
        observed["callbackObservations"][0]["observedAt"] = 1001
    elif tamper == "invented-worker":
        kwargs["worker_imports"].append({"package": "node_modules/openclaw", "pid": 102,
                                          "threadId": 1, "path": next(iter(WORKER_ARTIFACTS))})
    else:
        observed["mutations"][0]["cut"] = "fabricated-worker-reply"
    child["stdout"] = json.dumps(observed)
    row["result"] = worker_profile_public(observed, diagnostic[0]["fixtureBase"])
    with pytest.raises(RuntimeOracleError):
        validate_trust_worker_profile_raw(row, case, diagnostic, tmp_path, **kwargs)
