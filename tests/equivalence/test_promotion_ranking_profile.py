"""Independent capability guards; labelled transport is not native evidence."""
from copy import deepcopy
import hashlib

import pytest

from equivalence.entry_provenance_profile import ENTRY_PROVENANCE_PROFILES
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.promotion_ranking_bindings import (
    PROMOTION_RANKING_OPERATION,
    prepare_promotion_ranking_profile,
    validate_promotion_ranking_profile,
)
from equivalence.runtime_oracle import (
    MODEL_RUNTIME_OPERATIONS,
    ROOT,
    ReleaseOracleExecution,
    RuntimeOracleError,
)


def _profile():
    return {"kind": "approved-promotion-ranking-profile", "operation": PROMOTION_RANKING_OPERATION,
            "inputKind": "promotion-ranking", "nodeRuntime": {"execPath": "/reviewed/node", **APPROVED_NODE_RUNTIME}}


def _transport(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    raw = b"// Labelled transport fixture, never native execution evidence.\n"
    (root / "manager.mjs").write_bytes(raw)
    config = {"runtimeRoot": str(root), "packages": [{"location": "node_modules/openclaw", "directory": str(root),
              "files": [{"path": "manager.mjs", "sha256": hashlib.sha256(raw).hexdigest()}]}]}
    adapters = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (ROOT / "equivalence").glob("*.mjs")}
    return config, adapters


def _case(operation=PROMOTION_RANKING_OPERATION, input_kind="promotion-ranking"):
    return {"id": "labelled-promotion-ranking", "operation": operation, "input": {"kind": input_kind}}


def _unsuccessful_transport(case):
    return {"kind": "official-release-runtime-comparison", "sources": [], "results": [
        {"id": case["id"], "ok": False, "error": "Labelled transport fixture; no native execution occurred."}]}


def test_promotion_profile_keeps_its_independent_operation_kind_and_binary_authority():
    value = _profile()
    validated = validate_promotion_ranking_profile(value)
    assert validated == value
    assert PROMOTION_RANKING_OPERATION == "promotion-ranking-runtime"
    assert PROMOTION_RANKING_OPERATION not in ENTRY_PROVENANCE_PROFILES
    assert PROMOTION_RANKING_OPERATION not in MODEL_RUNTIME_OPERATIONS
    validated["nodeRuntime"]["sha256"] = "changed-copy"
    assert value["nodeRuntime"]["sha256"] == APPROVED_NODE_RUNTIME["sha256"]


@pytest.mark.parametrize("field", ("sha256", "nodeVersion", "icuVersion", "unicodeVersion", "execPath"))
def test_promotion_binary_authority_cannot_be_forged(field):
    profile = _profile()
    profile["nodeRuntime"][field] = "unreviewed"
    with pytest.raises(ValueError, match="exact approved"):
        validate_promotion_ranking_profile(profile)


@pytest.mark.parametrize("mutation", ("kind", "operation", "inputKind", "extra", "missing"))
def test_promotion_profile_rejects_unrelated_or_extended_contracts(mutation):
    profile = _profile()
    if mutation == "extra":
        profile["sourceCapability"] = True
    elif mutation == "missing":
        del profile["nodeRuntime"]
    else:
        profile[mutation] = "unreviewed"
    with pytest.raises(ValueError, match="exact independent"):
        validate_promotion_ranking_profile(profile)


@pytest.mark.parametrize("value", (None, [], False, "unreviewed"))
def test_promotion_profile_requires_an_explicit_mapping(value):
    with pytest.raises(ValueError):
        validate_promotion_ranking_profile(value)


def test_profile_preparation_cannot_authenticate_an_absent_node_binary(tmp_path):
    with pytest.raises(FileNotFoundError):
        prepare_promotion_ranking_profile(tmp_path / "absent-node")


@pytest.mark.parametrize("capability", ("entry", "model", "source", "capture"))
def test_promotion_profile_cannot_combine_other_execution_capabilities(tmp_path, capability):
    config, adapters = _transport(tmp_path)
    options = {"promotion_profile": _profile()}
    if capability == "entry":
        operation = "entry-memory-publication-runtime"
        options["entry_profile"] = {"kind": "approved-entry-provenance-profile", "operation": operation,
            "inputKind": ENTRY_PROVENANCE_PROFILES[operation], "nodeRuntime": _profile()["nodeRuntime"]}
    elif capability == "model":
        options["model_node_runtime"] = _profile()["nodeRuntime"]
    elif capability == "source":
        options["turn_taint_source"] = {"unreviewed": True}
    else:
        options["fixture_captures"] = True
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution(config, adapters, **options):
            pass


def test_promotion_context_retains_exact_scope_without_source_or_capture_permission(tmp_path):
    config, adapters = _transport(tmp_path)
    profile = _profile()
    expected = deepcopy(profile)
    with ReleaseOracleExecution(config, adapters, promotion_profile=profile) as execution:
        profile["operation"] = "caller-mutated"
        assert execution._context["promotionRankingProfile"] == expected
        assert execution._context["approvedNodeRuntime"] == expected["nodeRuntime"]
        assert execution._context["approvedReferenceSources"] == []
        assert execution._context["fixtureSourceCaptures"] == []
        assert "entryProvenanceProfile" not in execution._context
        assert execution.entry_profile is None and execution.model_node_runtime is None


@pytest.mark.parametrize("operation", (
    "entry-memory-publication-runtime", "model-tool-result-runtime", "turn-trust-runtime", "search-contract-runtime",
))
def test_promotion_capability_cannot_impersonate_another_operation(tmp_path, operation):
    config, adapters = _transport(tmp_path)
    case = _case(operation=operation)
    with ReleaseOracleExecution(config, adapters, promotion_profile=_profile()) as execution:
        with pytest.raises(RuntimeOracleError, match="restricted to its exact compiled operation"):
            execution.collect(_unsuccessful_transport(case), [case])


@pytest.mark.parametrize("input_kind", ("published-memory", "model-helper", "turn-trust", "flow", None))
def test_promotion_capability_cannot_impersonate_another_input_kind(tmp_path, input_kind):
    config, adapters = _transport(tmp_path)
    case = _case(input_kind=input_kind)
    with ReleaseOracleExecution(config, adapters, promotion_profile=_profile()) as execution:
        with pytest.raises(RuntimeOracleError, match="cannot impersonate"):
            execution.collect(_unsuccessful_transport(case), [case])


def test_ranking_operation_cannot_run_without_its_independent_profile(tmp_path):
    config, adapters = _transport(tmp_path)
    case = _case()
    with ReleaseOracleExecution(config, adapters) as execution:
        with pytest.raises(RuntimeOracleError, match="restricted to its exact compiled operation"):
            execution.collect(_unsuccessful_transport(case), [case])


def test_valid_profile_does_not_turn_labelled_transport_into_native_success(tmp_path):
    config, adapters = _transport(tmp_path)
    case = _case()
    with ReleaseOracleExecution(config, adapters, promotion_profile=_profile()) as execution:
        with pytest.raises(RuntimeOracleError, match="did not complete"):
            execution.collect(_unsuccessful_transport(case), [case])
