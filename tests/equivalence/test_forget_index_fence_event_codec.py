"""Lossless event storage tests; no original engine or public golden executes."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zlib

import pytest

from equivalence import forget_index_fence_native as native


HELPER = Path(__file__).resolve().parents[2] / "equivalence/forget-index-fence-source-clock.mjs"


def _frame(raw):
    compressor = zlib.compressobj(wbits=-15)
    data = compressor.compress(raw) + compressor.flush()
    return {"codec": native.PASSIVE_EVENT_CODEC, "rawBytes": len(raw),
            "rawSha256": hashlib.sha256(raw).hexdigest(), "dataBase64": base64.b64encode(data).decode()}


def test_node_framing_roundtrips_exact_json_bytes_through_independent_python_decoder():
    node = os.environ.get("MEMORY_EQ_NODE") or shutil.which("node")
    if node is None:
        pytest.skip("A local Node runtime is required for this builtin-only codec test")
    value = {"event": "labelled-storage-only", "text": "Actual 🦊 UTF8\n\u0000 source", "nested": [None, True, 1.25]}
    code = f"""
import {{encodePassiveEvent}} from {json.dumps(HELPER.as_uri())};
const value={json.dumps(value)};process.stdout.write(encodePassiveEvent(value));
"""
    environment = {key: value for key, value in os.environ.items()
                   if key != "NODE_OPTIONS" and not key.startswith("MEMORY_EQ_")}
    result = subprocess.run([node, "--input-type=module", "--eval", code], env=environment,
                            capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    decoded, size = native.decode_passive_event(result.stdout.strip())
    assert decoded == value
    frame = json.loads(result.stdout)
    raw = zlib.decompress(base64.b64decode(frame["dataBase64"]), wbits=-15)
    assert len(raw) == size == frame["rawBytes"]
    assert hashlib.sha256(raw).hexdigest() == frame["rawSha256"]
    assert raw.decode() == json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@pytest.mark.parametrize("attack", ["codec", "extra", "length-bool", "length-small", "length-large", "length-negative",
                                  "hash", "hash-upper", "base64", "base64-whitespace", "truncated", "trailing",
                                  "concatenated", "wrong-stream", "noncanonical-padding"])
def test_codec_rejects_tampered_truncated_or_noncanonical_frames(attack):
    raw = b'{"event":"labelled-only","payload":"exact original bytes"}'
    frame = _frame(raw)
    compressed = base64.b64decode(frame["dataBase64"])
    if attack == "codec":
        frame["codec"] = "unapproved"
    elif attack == "extra":
        frame["normalized"] = True
    elif attack == "length-bool":
        frame["rawBytes"] = True
    elif attack == "length-small":
        frame["rawBytes"] -= 1
    elif attack == "length-large":
        frame["rawBytes"] += 1
    elif attack == "length-negative":
        frame["rawBytes"] = -1
    elif attack == "hash":
        frame["rawSha256"] = "0" * 64
    elif attack == "hash-upper":
        frame["rawSha256"] = frame["rawSha256"].upper()
    elif attack == "base64":
        frame["dataBase64"] = "not_base64!"
    elif attack == "base64-whitespace":
        frame["dataBase64"] += "\n"
    elif attack == "truncated":
        frame["dataBase64"] = base64.b64encode(compressed[:-1]).decode()
    elif attack == "trailing":
        frame["dataBase64"] = base64.b64encode(compressed + b"trailing data").decode()
    elif attack == "concatenated":
        frame["dataBase64"] = base64.b64encode(compressed + compressed).decode()
    elif attack == "wrong-stream":
        frame["dataBase64"] = base64.b64encode(zlib.compress(raw)).decode()
    else:
        frame["dataBase64"] += "="
    with pytest.raises(ValueError):
        native.decode_passive_event(json.dumps(frame))


@pytest.mark.parametrize("raw", [b'{"event":"one","event":"two"}', b'{"value":NaN}', b'{"value":Infinity}',
                                 b'{"value":"\xff"}', b'[]'])
def test_codec_never_hides_invalid_or_ambiguous_original_json(raw):
    with pytest.raises(ValueError):
        native.decode_passive_event(json.dumps(_frame(raw)))


def test_decoded_bomb_and_total_bounds_are_separate_from_wire_capacity(tmp_path, monkeypatch):
    raw = json.dumps({"event": "labelled-only", "text": "x" * 100_000}).encode()
    frame = _frame(raw)
    assert len(frame["dataBase64"]) < 4096
    with pytest.raises(ValueError):
        native.decode_passive_event(json.dumps(frame), max_raw_bytes=4096)
    smaller_claim = deepcopy(frame)
    smaller_claim["rawBytes"] = 2
    with pytest.raises(ValueError):
        native.decode_passive_event(json.dumps(smaller_claim))
    rows = [{"event": "labelled-only", "pid": 123, "ppid": 1, "threadId": 0, "actor": "labelled", "instance": 1,
             "sequence": sequence, "atNs": str(sequence)} for sequence in (1, 2)]
    bodies = [json.dumps(row).encode() for row in rows]
    (tmp_path / "123-0-events.jsonl").write_text("".join(json.dumps(_frame(body)) + "\n" for body in bodies))
    monkeypatch.setattr(native, "PASSIVE_RAW_TOTAL_LIMIT", sum(map(len, bodies)) - 1)
    with pytest.raises(ValueError):
        native._original_children({"evidenceDirectory": str(tmp_path)}, {}, {
            123: {"actor": "labelled", "ppid": 1, "instance": 1},
        })


def test_plain_records_are_explicitly_diagnostic_only():
    raw = b'{"event":"labelled-legacy-only"}'
    with pytest.raises(ValueError, match="storage codec"):
        native.decode_passive_event(raw)
    assert native.decode_passive_event(raw, allow_legacy_plain=True) == (json.loads(raw), len(raw))


def test_codec_envelope_duplicate_keys_are_rejected_before_decoding():
    frame = json.dumps(_frame(b'{"event":"labelled-only"}'))
    with pytest.raises(ValueError, match="duplicate"):
        native.decode_passive_event('{"codec":"duplicate",' + frame[1:])
