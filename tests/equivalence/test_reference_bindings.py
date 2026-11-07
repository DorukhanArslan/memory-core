"""Source-provenance regressions; these are not native behavior comparisons."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import reference_bindings as bindings


@pytest.fixture
def sources():
    names = ", ".join(bindings._BINDINGS)
    return {
        bindings._PARENT: (
            f'import {{ {names}, type MemorySource }} from "{bindings._SPECIFIER}";\n'
        ),
        bindings._FACADE: (
            f'export {{ {names} }} from "../../packages/memory-host-sdk/src/engine-storage.js";\n'
        ),
        bindings._ENGINE: f'export {{ {names} }} from "./host/internal.js";\n',
        bindings._TARGET: (
            'export { hashText } from "./hash.js";\n'
            'export { MEMORY_CHUNKING_VERSION } from "./markdown-chunks.js";\n'
            'export function normalizeExtraMemoryPathEntries() {}\n'
        ),
        bindings._HASH: 'export function hashText() {}\n',
        bindings._CHUNKS: 'export const MEMORY_CHUNKING_VERSION = 1;\n',
    }


def test_direct_export_chain_retains_names_without_claiming_execution(sources):
    before = deepcopy(sources)
    chain = bindings._trace_projection(sources)

    assert len(chain) == 8
    assert chain[0]["bindings"] == list(bindings._BINDINGS)
    assert chain[0]["kind"] == "import"
    assert chain[1]["specifier"] == "../../packages/memory-host-sdk/src/engine-storage.js"
    assert sources == before


@pytest.mark.parametrize("change", [
    "facade-alias", "facade-target", "facade-type-only", "engine-alias",
    "engine-target", "owner-alias", "missing-declaration", "duplicate-declaration",
    "extra-runtime-import", "aliased-runtime-import", "duplicate-export-block",
])
def test_altered_or_ambiguous_export_provenance_fails(sources, change):
    if change == "facade-alias":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace("hashText", "other as hashText")
    elif change == "facade-target":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace("engine-storage", "other-owner")
    elif change == "facade-type-only":
        sources[bindings._FACADE] = sources[bindings._FACADE].replace("export {", "export type {")
    elif change == "engine-alias":
        sources[bindings._ENGINE] = sources[bindings._ENGINE].replace("hashText", "hashText as renamed")
    elif change == "engine-target":
        sources[bindings._ENGINE] = sources[bindings._ENGINE].replace("internal", "replacement")
    elif change == "owner-alias":
        sources[bindings._TARGET] = sources[bindings._TARGET].replace("{ hashText }", "{ other as hashText }")
    elif change == "missing-declaration":
        sources[bindings._HASH] = "function hashText() {}\n"
    elif change == "duplicate-declaration":
        sources[bindings._HASH] *= 2
    elif change == "extra-runtime-import":
        sources[bindings._PARENT] = sources[bindings._PARENT].replace("type MemorySource", "unreviewedRuntime")
    elif change == "aliased-runtime-import":
        sources[bindings._PARENT] = sources[bindings._PARENT].replace("hashText", "hashText as renamed")
    else:
        sources[bindings._FACADE] *= 2

    with pytest.raises(bindings.ReferenceBindingError):
        bindings._trace_projection(sources)


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch, sources):
    # This temporary Git tree exercises provenance checks only. It is never
    # offered to the native oracle or represented as the pinned release.
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path).decode().strip()

    git("init", "-q")
    for relative, content in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture")
    monkeypatch.setattr(bindings, "_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "_SOURCE_SHA256", {
        relative: hashlib.sha256(content.encode()).hexdigest()
        for relative, content in sources.items()
    })
    return tmp_path


def test_prepared_projection_is_parent_scoped_and_limits_its_claim(checkout):
    result = bindings.prepare_reference_bindings(checkout)

    resolution, = result["allowedResolutions"]
    assert resolution == {
        "parent": bindings._PARENT,
        "specifier": bindings._SPECIFIER,
        "target": bindings._TARGET,
        "bindings": list(bindings._BINDINGS),
    }
    evidence, = result["projectionEvidence"]
    assert evidence["scope"] == "identity-kernel-only"
    assert evidence["facadeExecutionVerified"] is False
    assert evidence["fullManagerExecutionVerified"] is False
    assert len(evidence["sources"]) == 6
    assert len(evidence["chain"]) == 8


def test_modified_native_source_is_rejected(checkout):
    (checkout / bindings._FACADE).write_text("export const replacement = true;\n")
    with pytest.raises(bindings.ReferenceBindingError, match="unmodified"):
        bindings.prepare_reference_bindings(checkout)


def test_committed_native_source_must_match_reviewed_digest(checkout, monkeypatch):
    expected = dict(bindings._SOURCE_SHA256)
    expected[bindings._ENGINE] = "0" * 64
    monkeypatch.setattr(bindings, "_SOURCE_SHA256", expected)
    with pytest.raises(bindings.ReferenceBindingError, match="pinned Git source"):
        bindings.prepare_reference_bindings(checkout)


def test_wrong_native_commit_is_rejected(checkout, monkeypatch):
    monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    with pytest.raises(bindings.ReferenceBindingError, match="exact pinned"):
        bindings.prepare_reference_bindings(checkout)


def test_reference_root_cannot_be_a_nested_directory(checkout):
    with pytest.raises(bindings.ReferenceBindingError, match="exact pinned"):
        bindings.prepare_reference_bindings(checkout / "packages")


def test_missing_reference_is_not_projection_evidence(tmp_path):
    with pytest.raises(bindings.ReferenceBindingError):
        bindings.prepare_reference_bindings(tmp_path / "missing")


@pytest.fixture
def cache_sources(sources):
    sources = deepcopy(sources)
    vectors = ", ".join(bindings._CACHE_BINDINGS)
    sql = ", ".join(bindings._SQL_BINDINGS)
    for module in (bindings._FACADE, bindings._ENGINE):
        sources[module] = sources[module].replace(" } from", f", {vectors} }} from")
    sources[bindings._TARGET] += f'export {{ {vectors} }} from "./embedding-vector.js";\n'
    sources[bindings._CACHE_PARENT] = (
        f'import {{ {vectors}, type MemoryChunk }} from "{bindings._SPECIFIER}";\n'
        f'import {{ {sql}, type Generated }} from "openclaw/plugin-sdk/sqlite-runtime";\n'
    )
    sources[bindings._VECTOR] = "\n".join(
        f"export function {name}() {{}}" for name in bindings._CACHE_BINDINGS)
    sources[bindings._SQL_FACADE] = f'export {{ {sql} }} from "../infra/kysely-sync.js";\n'
    sources[bindings._SQL_TARGET] = "\n".join(
        f"export function {name}<T>() {{}}" for name in bindings._SQL_BINDINGS)
    return sources


def test_cache_sql_and_codec_imports_trace_to_original_declarations(cache_sources):
    before = deepcopy(cache_sources)
    projections = bindings._trace_cache_projections(cache_sources)
    assert len(projections) == 2
    assert {item["resolution"]["target"] for item in projections} == {
        bindings._VECTOR, bindings._SQL_TARGET,
    }
    assert all(item["resolution"]["parent"] == bindings._CACHE_PARENT for item in projections)
    assert all(len(item["chain"]) == 6 for item in projections)
    assert cache_sources == before


@pytest.mark.parametrize("change", [
    "codec-alias", "codec-type-only", "codec-owner", "sql-alias", "sql-owner",
    "sql-extra-import", "sql-missing-declaration", "codec-duplicate-declaration",
])
def test_changed_cache_binding_provenance_is_rejected(cache_sources, change):
    if change == "codec-alias":
        cache_sources[bindings._TARGET] = cache_sources[bindings._TARGET].replace(
            "decodeMemoryEmbedding", "other as decodeMemoryEmbedding")
    elif change == "codec-type-only":
        cache_sources[bindings._TARGET] = cache_sources[bindings._TARGET].replace(
            "export { decodeMemoryEmbedding", "export type { decodeMemoryEmbedding")
    elif change == "codec-owner":
        cache_sources[bindings._TARGET] = cache_sources[bindings._TARGET].replace("embedding-vector", "other")
    elif change == "sql-alias":
        cache_sources[bindings._SQL_FACADE] = cache_sources[bindings._SQL_FACADE].replace(
            "getNodeSqliteKysely", "other as getNodeSqliteKysely")
    elif change == "sql-owner":
        cache_sources[bindings._SQL_FACADE] = cache_sources[bindings._SQL_FACADE].replace("kysely-sync", "other")
    elif change == "sql-extra-import":
        cache_sources[bindings._CACHE_PARENT] = cache_sources[bindings._CACHE_PARENT].replace(
            "type Generated", "unreviewedRuntime")
    elif change == "sql-missing-declaration":
        cache_sources[bindings._SQL_TARGET] = ""
    else:
        cache_sources[bindings._VECTOR] *= 2
    with pytest.raises(bindings.ReferenceBindingError):
        bindings._trace_cache_projections(cache_sources)


def test_prepared_cache_bindings_exclude_manager_and_facade_execution(checkout, cache_sources, monkeypatch):
    for relative, content in cache_sources.items():
        path = checkout / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                    "commit", "-qm", "cache provenance fixture"], cwd=checkout, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout).decode().strip()
    monkeypatch.setattr(bindings, "_COMMIT", commit)
    for mapping in ("_SOURCE_SHA256", "_CACHE_SOURCE_SHA256"):
        monkeypatch.setattr(bindings, mapping, {
            relative: hashlib.sha256(cache_sources[relative].encode()).hexdigest()
            for relative in getattr(bindings, mapping)
        })
    result = bindings.prepare_reference_bindings(checkout, include_cache=True)
    assert len(result["allowedResolutions"]) == 3
    assert [item["scope"] for item in result["projectionEvidence"]] == [
        "identity-kernel-only", "embedding-cache-kernel-only", "embedding-cache-kernel-only",
    ]
    assert all(not item["facadeExecutionVerified"] and not item["fullManagerExecutionVerified"]
               for item in result["projectionEvidence"])
