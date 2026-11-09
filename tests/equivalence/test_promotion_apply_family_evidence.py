"""Challenge validators with sealed actual captures, never replay as an oracle."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.promotion_apply_family import differences
from equivalence.promotion_apply_family_evidence import validate_pair

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/promotion-apply-family-protected.json.gz"


@pytest.fixture(scope="module")
def captures():
    compressed = FIXTURE.read_bytes()
    manifest = json.loads(FIXTURE.with_suffix(FIXTURE.suffix + ".manifest.json").read_text())
    assert manifest["acceptanceCredit"] is False
    assert hashlib.sha256(compressed).hexdigest() == manifest["sha256"]
    decoded = gzip.decompress(compressed)
    assert len(decoded) == manifest["decodedBytes"]
    assert hashlib.sha256(decoded).hexdigest() == manifest["decodedSha256"]
    packet = json.loads(decoded)
    assert packet["producer"] == manifest["producer"]
    return packet["cases"]


def check(row):
    validate_pair(row["case"], row["native"], row["sdk"], row["native"]["output"], row["sdk"]["output"])


@pytest.mark.parametrize("index", range(3))
def test_sealed_original_and_sdk_observations_validate_without_executing_owners(captures, index):
    check(captures[index])


@pytest.mark.parametrize("mutation", ["candidate-field", "public-error", "physical-row", "document-bytes", "clock", "normalizer-input", "retention-return"])
def test_original_channel_corruption_cannot_receive_acceptance_credit(captures, mutation):
    row = deepcopy(captures[0])
    raw = row["native"]
    if mutation == "candidate-field":
        apply = next(c for c in raw["calls"] if c["operation"] == "applyShortTermPromotions")
        del apply["result"]["appliedCandidates"][0]["recallCount"]
    elif mutation == "public-error":
        raw["output"]["outcome"] = {"error": {"name": "InventedError", "message": "changed"}}
    elif mutation == "physical-row":
        database = next(d for d in raw["snapshots"][1]["physical"] if d["path"] == raw["databasePath"])
        table = next(t for t in database["tables"] if t["name"] == "plugin_state_entries")
        table["rows"].pop()
    elif mutation == "document-bytes":
        document = next(d for d in raw["output"]["after"]["documents"] if d["path"] == "MEMORY.md")
        document["text"] = "rewritten result"
    elif mutation == "clock":
        raw["clock"]["setTimeoutUnchanged"] = False
    elif mutation == "normalizer-input":
        call = next(c for c in raw["calls"] if c["operation"] == "normalizeShortTermRecallStore")
        call["input"]["entries"] = {}
    else:
        call = next(c for c in raw["calls"] if c["operation"] == "enforceShortTermRecallStoreRetention")
        del call["returned"]
    with pytest.raises((ValueError, KeyError)):
        check(row)


@pytest.mark.parametrize("mutation", ["missing-host-call", "missing-return", "wrong-publication", "sdk-return", "sdk-physical", "sdk-request"])
def test_live_journal_and_sdk_extensions_cannot_be_omitted_or_reassigned(captures, mutation):
    row = deepcopy(captures[-1])
    if mutation == "missing-host-call":
        row["native"]["completions"] = []
    elif mutation == "missing-return":
        row["native"]["ioReceipts"].pop()
    elif mutation == "wrong-publication":
        call = next(r for r in row["native"]["ioReceipts"] if r["operation"] == "fs.rename" and r["when"] == "before")
        call["arguments"][1] = "/unowned/MEMORY.md"
    elif mutation == "sdk-return":
        row["sdk"]["richSdkResult"]["fields"]["appended"] += 1
    elif mutation == "sdk-physical":
        entry = next(e for e in row["sdk"]["snapshots"][1]["filesystem"] if e["path"].endswith("/MEMORY.md"))
        entry["hex"] = "00"
    else:
        row["sdk"]["completions"][0]["request"]["fields"]["message"] = "changed actual request"
    with pytest.raises((ValueError, KeyError)):
        check(row)


def test_genuine_different_callback_messages_remain_comparison_data(captures):
    row = deepcopy(captures[-1])
    sdk = row["sdk"]
    message = "A different complete model request"
    sdk["completions"][0]["request"]["fields"]["message"] = message
    sdk["completions"][0]["publicRequest"]["message"] = message
    call = next(r for r in sdk["receipts"] if r["operation"] == "host.complete" and r["when"] == "before")
    call["arguments"][0]["fields"]["message"] = message
    for envelope in (sdk["output"], sdk["unmappedOutput"]):
        envelope["completionCalls"][0]["request"]["message"] = message
    check(row)
    delta = differences(row["native"]["output"], sdk["output"])
    assert [d["path"] for d in delta] == ["$.completionCalls[0].request.message"]
