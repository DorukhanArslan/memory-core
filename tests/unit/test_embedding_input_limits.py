"""Actual original byte-limit captures and real pre-embedding publication flow."""
from dataclasses import asdict
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from equivalence.entry_provenance_fixtures import embedding_byte_limit_inputs
from memory_core.bootstrap._js import js_utf8_encode
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.embedding_limits import (
    enforce_embedding_max_input_tokens, resolve_embedding_max_input_tokens, split_text_to_utf8_byte_limit,
)
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


_CAPTURE = json.loads((Path(__file__).parents[1] / "fixtures/embedding-byte-limit-native.json").read_text())


def _units(text):
    data = text.encode("utf-16-le", "surrogatepass")
    return [int.from_bytes(data[index:index + 2], "little") for index in range(0, len(data), 2)]


@pytest.mark.parametrize("observation", _CAPTURE["observations"], ids=lambda row: row["input"]["id"])
def test_byte_splits_preserve_every_original_unit_and_pinned_boundary(observation):
    value = observation["input"]
    text = "".join(map(chr, value["units"]))
    parts = split_text_to_utf8_byte_limit(text, value["limit"])
    assert [_units(part) for part in parts] == observation["partUnits"]
    assert _units("".join(parts)) == value["units"]


def test_original_capture_uses_all_common_inputs_without_generated_expectations():
    assert [row["input"] for row in _CAPTURE["observations"]] == embedding_byte_limit_inputs()
    assert _CAPTURE["node"]["version"] == "v24.16.0"
    assert _CAPTURE["artifacts"]["dist/manager-index-preparation-wXpJtJiU.mjs"] == "6f9e0930cb49dfe7ba14ea851dde17a56ebebe66e3dabdab525854f90f179867"


@pytest.mark.parametrize("provider,expected", [
    (SimpleNamespace(provider_id="local"), 2048),
    (SimpleNamespace(provider_id="remote"), 8192),
    (SimpleNamespace(provider_id="remote", max_input_tokens=16), 16),
    (SimpleNamespace(provider_id="remote", max_input_tokens=0), 0),
    (SimpleNamespace(provider_id="local", max_input_tokens=True), 2048),
])
def test_generic_optional_provider_metadata_and_original_defaults(provider, expected):
    assert resolve_embedding_max_input_tokens(provider) == expected


def test_openai_compatible_provider_exposes_optional_real_host_limit_without_a_request():
    from memory_core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider

    default = OpenAICompatibleEmbeddingProvider(api_key="fixture-only", model="fixture-model")
    limited = OpenAICompatibleEmbeddingProvider(api_key="fixture-only", model="fixture-model", max_input_tokens=16)
    assert resolve_embedding_max_input_tokens(default) == 8192
    assert resolve_embedding_max_input_tokens(limited) == 16
    assert default.cache_key_data() == limited.cache_key_data()


def test_real_provider_cap_fragments_keep_entry_provenance_annotations_and_canonical_rows(tmp_path, monkeypatch):
    reference = _CAPTURE["providerPreparation"]
    path = tmp_path / "MEMORY.md"
    path.write_text(reference["input"]["content"])
    os.utime(path, ns=(1700000000000000000, 1700000000000000000))

    class Provider:
        provider_id = "fixture"
        model = "fixture-limit"
        max_input_tokens = 16

        def __init__(self):
            self.calls = []

        def embed_documents(self, texts):
            self.calls.append(list(texts))
            return [[1.0, 0.0] for _ in texts]

        def embed_query(self, text):
            return [1.0, 0.0]

    provider = Provider()
    fragments = []

    def observe(actual_provider, chunks):
        result = enforce_embedding_max_input_tokens(actual_provider, chunks)
        fragments.extend(asdict(chunk) for chunk in result)
        return result

    monkeypatch.setattr("memory_core.index.sqlite_store.enforce_embedding_max_input_tokens", observe)
    store = SQLiteMemoryStore(MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=True)), provider)
    store.reindex(MemoryWorkspace(tmp_path))
    native = reference["withProvider"]["chunks"]
    assert len(fragments) == len(native) == 7
    assert [row["text"] for row in fragments] == [row["text"] for row in native]
    assert [(row["start_line"], row["end_line"], row["entry_start_line"], row["entry_end_line"]) for row in fragments] == [
        (row["startLine"], row["endLine"], row["entryStartLine"], row["entryEndLine"]) for row in native]
    assert all(len(js_utf8_encode(text)) <= 16 for call in provider.calls for text in call)
    state = store.read_published_index()
    assert {row["hash"] for row in state["chunks"]} == {row["hash"] for row in native}
    assert all(row["provenance"] == {"originClass": "agent", "sessionKind": "unknown", "observedAt": 1700000000000,
                                      "supersedesKey": None} for row in state["chunks"])
    assert all(row["recall"] == {"importance": 7, "triggers": None, "projectKey": None} for row in state["chunks"])
    assert len(state["chunks"]) == len(state["fts"]) == len(state["provenance"]) == len(state["recall"])
