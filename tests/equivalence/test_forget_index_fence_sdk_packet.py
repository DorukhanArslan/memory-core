"""Lossless V5 packet writer tests only; no engines or capture files are used."""
from copy import deepcopy
import hashlib
import json

import pytest

from equivalence import forget_index_fence_sdk as sdk


def _dispatch(version=5):
    observation = {"complete": True, "provider": "none", "result": {"calls": {
        "search:whole": {"operation": "search", "label": "whole", "outcome": {"status": "fulfilled", "result": {
            "results": [{"snippet": "雪の記憶 🌲\nActual second line", "literalEscapes": r"\n\u000a\t\\", "score": 1.0}],
            "warning": "exact warning: å, 雪, emoji 🌲", "action": "preserve\nall action lines", "count": 7, "flag": False}}},
        "forget:whole": {"operation": "forget", "label": "whole", "outcome": {"status": "fulfilled", "result": {
            "sessionIds": ["whole-session"], "artifacts": {"indexChunks": 3}, "refusals": [], "createdAt": 1794614400000}}}},
        "snapshots": {"whole": {"documents": [{"path": "MEMORY.md", "bytes": "e99baa0a", "sha256": "actual-byte-hash"}],
                                "private": {"nested": [{"rows": [None, True, False, 1, 1.0, {"opaque": "unchanged"}]}]}}}},
        "processes": [{"stdout": "nested original stream\nwith literal \\n", "stderr": "nested error: é\n",
                       "source": {"root": "/independent/SDK root", "sha256": "full-source-hash"}}]}
    stdout = " \n" + json.dumps(observation, ensure_ascii=False, indent=2) + "\n"
    kind = f"forget-index-fence-v{version}" if version > 1 else "forget-index-fence"
    return {"kind": kind + "-sdk-dispatch", "input": {"kind": kind, "independent": ["unchanged", 3]},
            "request": {"input": {"kind": kind}, "adapterRoot": "/adapter/source root", "sdkRoot": "/selected/source root"},
            "stdout": stdout, "stderr": "exact original stderr\n雪\\nend\n", "observation": observation,
            "exit": {"code": 0}, "pid": 202, "argv": ["/python", "-m", "original.driver"],
            "sourceProvenanceBefore": {"root": "/selected/source root", "files": [{"path": "memory_core/source.py",
                "bytes": 31, "sha256": "original-before", "nested": {"sourceBytes": "# original é\n"}}]},
            "sourceProvenanceAfter": {"root": "/selected/source root", "files": [{"path": "memory_core/source.py",
                "bytes": 31, "sha256": "original-after", "nested": {"sourceBytes": "# original é\n"}}]},
            "adapterProvenanceBefore": {"root": "/adapter/source root", "sourceSha256": "adapter-before"},
            "adapterProvenanceAfter": {"root": "/adapter/source root", "sourceSha256": "adapter-after"}}


def test_v5_packet_omits_only_duplicate_observation_and_authenticates_exact_utf8_stdout():
    dispatch = _dispatch()
    original = deepcopy(dispatch)
    observation = dispatch["observation"]
    packet = sdk._capture_dispatch_packet(dispatch)
    stdout_bytes = dispatch["stdout"].encode("utf8")
    assert packet is not dispatch and "observation" not in packet
    assert packet["observationEncoding"] == {"kind": "stdout-json-v1", "field": "stdout",
        "utf8Bytes": len(stdout_bytes), "sha256": hashlib.sha256(stdout_bytes).hexdigest()}
    assert len(stdout_bytes) > len(dispatch["stdout"])
    assert {key: value for key, value in packet.items() if key != "observationEncoding"} == {
        key: value for key, value in original.items() if key != "observation"}
    assert packet["stdout"] == original["stdout"] and packet["stderr"] == original["stderr"]
    assert json.loads(packet["stdout"]) == observation
    assert dispatch == original and dispatch["observation"] is observation
    # This writer removes one duplicate and keeps the remaining in-memory
    # custody shallow; it does not recursively clone the source manifests.
    assert packet["input"] is dispatch["input"]
    assert packet["sourceProvenanceBefore"] is dispatch["sourceProvenanceBefore"]
    assert packet["sourceProvenanceAfter"] is dispatch["sourceProvenanceAfter"]


def test_independent_json_roundtrip_keeps_unicode_newlines_literal_escapes_and_whole_nested_result():
    dispatch = _dispatch()
    packet = sdk._capture_dispatch_packet(dispatch)
    stored = json.loads(json.dumps(packet, ensure_ascii=False, allow_nan=False))
    decoded = json.loads(stored["stdout"])
    assert decoded == dispatch["observation"]
    result = decoded["result"]["calls"]["search:whole"]["outcome"]["result"]
    assert result["results"][0]["snippet"] == "雪の記憶 🌲\nActual second line"
    assert result["results"][0]["literalEscapes"] == r"\n\u000a\t\\"
    assert result["action"] == "preserve\nall action lines"
    assert stored["stdout"].encode("utf8") == dispatch["stdout"].encode("utf8")
    assert stored["sourceProvenanceBefore"] == dispatch["sourceProvenanceBefore"]
    assert stored["sourceProvenanceAfter"] == dispatch["sourceProvenanceAfter"]
    assert stored["adapterProvenanceBefore"] == dispatch["adapterProvenanceBefore"]
    assert stored["adapterProvenanceAfter"] == dispatch["adapterProvenanceAfter"]


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_legacy_dispatches_keep_full_observation_and_all_original_fields_without_marker(version):
    dispatch = _dispatch(version)
    original = deepcopy(dispatch)
    packet = sdk._capture_dispatch_packet(dispatch)
    assert packet == original and dispatch == original
    assert "observationEncoding" not in packet
    assert packet["observation"] == original["observation"]
    assert packet["stdout"] == original["stdout"]


@pytest.mark.parametrize("dispatch_kind,input_kind", [
    ("forget-index-fence-v5-sdk-dispatch", "forget-index-fence-v4"),
    ("forget-index-fence-v4-sdk-dispatch", "forget-index-fence-v5"),
    ("forget-index-fence-v5-sdk-dispatch", "forget-index-fence-v99"),
])
def test_mixed_version_identity_is_rejected_without_mutating_original(dispatch_kind, input_kind):
    dispatch = _dispatch()
    dispatch["kind"], dispatch["input"]["kind"] = dispatch_kind, input_kind
    before = deepcopy(dispatch)
    with pytest.raises(ValueError):
        sdk._capture_dispatch_packet(dispatch)
    assert dispatch == before


@pytest.mark.parametrize("invalid", ["preexisting-marker", "unpaired-surrogate", "nonobject-observation", "invalid-json", "different-observation"])
def test_invalid_v5_payloads_are_rejected_instead_of_discarding_a_distinct_or_undecodable_observation(invalid):
    dispatch = _dispatch()
    if invalid == "preexisting-marker":
        dispatch["observationEncoding"] = {"kind": "stdout-json-v1", "field": "stdout", "utf8Bytes": 0, "sha256": "wrong"}
    elif invalid == "unpaired-surrogate":
        dispatch["observation"]["processes"][0]["stderr"] = "invalid Unicode: \ud800"
        dispatch["stdout"] = json.dumps(dispatch["observation"], ensure_ascii=False)
    elif invalid == "nonobject-observation":
        dispatch["observation"] = [dispatch["observation"]]
        dispatch["stdout"] = json.dumps(dispatch["observation"], ensure_ascii=False)
    elif invalid == "invalid-json":
        dispatch["stdout"] = "not an original JSON observation\n"
    else:
        dispatch["observation"]["result"]["calls"]["search:whole"]["outcome"]["result"]["warning"] += " changed"
    before = deepcopy(dispatch)
    with pytest.raises(ValueError):
        sdk._capture_dispatch_packet(dispatch)
    assert dispatch == before


@pytest.mark.parametrize("original_scalar,different_scalar", [(True, 1), (False, 0), (1.0, 1)])
def test_distinct_json_scalar_types_cannot_be_discarded_as_an_equal_duplicate(original_scalar, different_scalar):
    dispatch = _dispatch()
    result = dispatch["observation"]["result"]["calls"]["search:whole"]["outcome"]["result"]
    result["flag"] = original_scalar
    dispatch["stdout"] = json.dumps(dispatch["observation"], ensure_ascii=False)
    result["flag"] = different_scalar
    before = deepcopy(dispatch)
    with pytest.raises(ValueError):
        sdk._capture_dispatch_packet(dispatch)
    assert dispatch == before


def test_stream_decoder_preserves_valid_unicode_newlines_and_literal_escapes_exactly():
    text = " \r\n{\"unicode\":\"雪🌲\",\"literal\":\"\\\\n\"}\r\n"
    payload = text.encode("utf8")
    dispatch = {"sourceProvenanceBefore": {"root": "/selected/original-root", "sha256": "original"}}
    before = deepcopy(dispatch)
    assert sdk._decode_dispatch_stream(payload, "stdout", dispatch) == text
    assert dispatch == before and payload == text.encode("utf8")


@pytest.mark.parametrize("field", ["stdout", "stderr"])
def test_stream_decoder_retains_every_invalid_byte_and_exact_decode_error_without_replacement(field):
    payload = b"\xff\xfe\nvalid UTF8 suffix: \xc3\xa9\\n"
    dispatch = {"adapterProvenanceAfter": {"root": "/actual/adapter-root", "sha256": "unchanged"}}
    assert sdk._decode_dispatch_stream(payload, field, dispatch) is None
    assert dispatch[field + "BytesHex"] == payload.hex()
    assert bytes.fromhex(dispatch[field + "BytesHex"]) == payload
    error = dispatch[field + "DecodeError"]
    assert error["name"] == "UnicodeDecodeError" and error["message"]
    assert error["args"][1] == {"bytesHex": payload.hex(), "bytes": len(payload)}
    assert dispatch["adapterProvenanceAfter"] == {"root": "/actual/adapter-root", "sha256": "unchanged"}
