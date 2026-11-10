"""Private custody encoding preserves genuine SDK result semantics."""
from copy import deepcopy
from dataclasses import fields
import json

import pytest

from equivalence.index_identity_boundaries_sdk import _search_result_custody
from memory_core.host.managed_index import _ManagedSearchResults
from memory_core.index.hybrid import HYBRID_METADATA_MISSING, HybridResult
from memory_core.tools.search_factory import serialize_search_tool_result


MISSING = {"$sdkPrivate": "HYBRID_METADATA_MISSING"}


def _result(**annotations):
    return HybridResult(path="MEMORY.md", start_line=1, end_line=4, score=0.5,
        vector_score=0.0, text_score=0.1, snippet="Actual SDK result codec fixture.",
        source="memory", **annotations)


def test_actual_default_hybrid_result_retains_every_private_field_and_serializes():
    result = _result()
    encoded = _search_result_custody([result])
    assert json.loads(json.dumps(encoded, allow_nan=False)) == encoded
    assert set(encoded[0]) == {field.name for field in fields(result)}
    for name in ("importance", "triggers", "project_key", "provenance", "source_mtime", "_vector_id"):
        assert getattr(result, name) is HYBRID_METADATA_MISSING
        assert encoded[0][name] == MISSING
    assert encoded[0]["_retrieval_mode"] == result._retrieval_mode
    assert result.to_payload().get("importance", HYBRID_METADATA_MISSING) is HYBRID_METADATA_MISSING


@pytest.mark.parametrize("annotation", [HYBRID_METADATA_MISSING, None, 0, 0.0])
def test_missing_null_and_zero_keep_their_distinct_actual_public_meanings(annotation):
    result = _result(importance=annotation)
    original = deepcopy(result.to_payload())
    envelope = serialize_search_tool_result(result.to_payload())

    encoded = _search_result_custody(result)
    json.dumps(encoded, allow_nan=False)

    if annotation is HYBRID_METADATA_MISSING:
        assert encoded["importance"] == MISSING
        assert "importance" not in original
        assert result.importance is HYBRID_METADATA_MISSING
    else:
        assert encoded["importance"] == annotation
        assert type(encoded["importance"]) is type(annotation)
        assert "importance" in original and original["importance"] == annotation
        assert result.importance is annotation
    assert result.to_payload() == original
    assert serialize_search_tool_result(result.to_payload()) == envelope
    assert json.loads(envelope["content"][0]["text"]) == envelope["details"]


def test_unknown_private_object_is_not_stringified_or_dropped_to_hide_failure():
    unknown = object()
    result = _result(provenance=unknown)
    encoded = _search_result_custody(result)
    assert encoded["provenance"] is unknown
    with pytest.raises(TypeError, match="not JSON serializable"):
        json.dumps(encoded, allow_nan=False)
    assert result.provenance is unknown


def test_actual_managed_list_pinned_status_is_retained_without_mutating_live_objects():
    row = _result(importance=None, triggers=0)
    status = {"custom": {"indexIdentity": {"status": "valid"},
                         "automaticRebuildNotice": {"sequence": 0, "warning": ""}}}
    returned = _ManagedSearchResults([row], status)
    original_payload = deepcopy(row.to_payload())

    receipt = {"result": _search_result_custody(returned),
               "returnAttributes": _search_result_custody(vars(returned))}
    json.dumps(receipt, allow_nan=False)

    assert receipt["result"][0]["importance"] is None
    assert receipt["result"][0]["triggers"] == 0
    assert receipt["result"][0]["_vector_id"] == MISSING
    assert receipt["returnAttributes"]["_memory_search_status"] == status
    assert returned._memory_search_status is status
    assert returned[0] is row and row.to_payload() == original_payload
    receipt["returnAttributes"]["_memory_search_status"]["custom"]["indexIdentity"]["status"] = "tampered-copy"
    assert status["custom"]["indexIdentity"] == {"status": "valid"}
