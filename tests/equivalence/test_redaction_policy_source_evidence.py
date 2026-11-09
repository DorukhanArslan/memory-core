"""Replay one unmodified genuine source execution; reject forged authority/results."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.redaction_policy_evidence import (
    REFERENCE_COMMIT, SOURCE_HASHES, RedactionPolicyEvidenceError,
    validate_redaction_policy_source_execution,
)


def _capture():
    path = Path(__file__).parents[1] / "fixtures/redaction-policy-source-actual.json.gz"
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    compressed = path.read_bytes()
    assert len(compressed) == manifest["gzipBytes"]
    assert hashlib.sha256(compressed).hexdigest() == manifest["gzipSha256"]
    raw = gzip.decompress(compressed)
    assert len(raw) == manifest["rawBytes"]
    assert hashlib.sha256(raw).hexdigest() == manifest["rawSha256"]
    response = json.loads(raw)
    case = deepcopy(response["sourceExecution"]["requestCase"])
    caller = deepcopy(manifest["caller"])
    caller["fixture_root"] = Path(caller["fixture_root"])
    return response, case, caller, manifest


def _validate(response, case, caller):
    validate_redaction_policy_source_execution(response, case, **caller)


def _sync_public(response):
    frame, = response["sourceExecution"]["observations"]
    public = response["results"][0]["result"]
    frame["output"] = deepcopy(public)
    frame["registry"] = deepcopy(public["registry"])


def test_actual_unmodified_source_capture_and_complete_thirteen_owner_binding_are_valid():
    response, case, caller, manifest = _capture()
    assert manifest["rawSha256"] == "5d5e4c235ce1efa742b83f324e790ab8887819dcd83067fc70fbbc0dec6f19a5"
    assert caller["node_authority"] == {
        "execPath": "/workspace/openclaw-memory-bridge/node_modules/node/bin/node", "nodeVersion": "v24.16.0",
        "icuVersion": "78.3", "unicodeVersion": "17.0",
        "sha256": "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"}
    bindings = manifest["bindings"]
    assert bindings["referenceCommit"] == REFERENCE_COMMIT
    assert len(bindings["sourceBindings"]) == len(SOURCE_HASHES) == 13
    assert {row["path"]: row["sha256"] for row in bindings["sourceBindings"]} == SOURCE_HASHES
    assert len(bindings["sourceImportLinks"]) == 12
    assert bindings["compiledModulesAllowed"] is bindings["sourceFallbackAllowed"] is False
    assert bindings["sameModuleGraphRequired"] is bindings["freshOrdinaryProcessRequired"] is True
    assert bindings["testRegistryResetAllowed"] is False
    _validate(response, case, caller)


@pytest.mark.parametrize("tamper", [
    "fallback", "compiled-module", "missing-owner", "changed-owner", "pid", "ppid", "runtime-unicode",
    "private-marker", "host-config", "logging-owner-path", "revision", "initial-revision", "call-output",
    "public-drop", "missing-call", "undeclared-registry", "ordinary-process", "different-case",
])
def test_original_source_authority_private_state_and_complete_returns_cannot_be_rewritten(tamper):
    response, case, caller, _ = _capture()
    execution = response["sourceExecution"]
    frame, = execution["observations"]
    public = response["results"][0]["result"]
    if tamper == "fallback":
        execution["compiledFallbackAllowed"] = True
    elif tamper == "compiled-module":
        response["sources"].append({"path": "dist/redact-BCoakatc.mjs", "sha256": "a" * 64})
    elif tamper == "missing-owner":
        response["sources"] = [row for row in response["sources"] if row["path"] != "src/logging/redact-internal-state.ts"]
    elif tamper == "changed-owner":
        next(row for row in response["sources"] if row["path"] == "src/logging/redact.ts")["sha256"] = "a" * 64
    elif tamper in {"pid", "ppid"}:
        execution[tamper] += 1
    elif tamper == "runtime-unicode":
        execution["unicodeVersion"] = "16.0"
    elif tamper == "private-marker":
        public["result"]["policy"]["fullContext"] = False
        next(row for row in frame["calls"] if row["name"] == "captureModelVisibleRedactionPolicy")["result"] = deepcopy(public["result"]["policy"])
        _sync_public(response)
    elif tamper == "host-config":
        frame["logging"]["json"]["redactPatterns"] = []
    elif tamper == "logging-owner-path":
        frame["logging"]["json"]["file"] = "/different-owned-root/native.log"
    elif tamper == "revision":
        public["registry"]["after"]["revision"] = 1
        _sync_public(response)
    elif tamper == "initial-revision":
        public["registry"]["before"]["revision"] = 1
        _sync_public(response)
    elif tamper == "call-output":
        frame["calls"][0]["result"] = "rewritten"
    elif tamper == "public-drop":
        del public["result"]["structuredModel"]
        _sync_public(response)
    elif tamper == "missing-call":
        frame["calls"].pop()
    elif tamper == "undeclared-registry":
        public["registry"]["after"]["values"] = ["undeclared-synthetic-value"]
        _sync_public(response)
    elif tamper == "ordinary-process":
        execution["ordinaryProcess"] = False
    else:
        execution["requestCase"]["id"] = "another-case"
    with pytest.raises(RedactionPolicyEvidenceError):
        _validate(response, case, caller)
