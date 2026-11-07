"""Provenance guards for real native index owner imports, not parity fixtures."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import index_bindings as bindings


@pytest.fixture
def sources():
    names = ", ".join(bindings._PUBLICATION_SCHEMA_NAMES)
    all_names = (*bindings._PUBLICATION_SCHEMA_NAMES, "MEMORY_INDEX_META_TABLE", "MEMORY_INDEX_VECTOR_TABLE")
    result = {
        bindings._PUBLICATION: (
            f'import {{ {names} }} from "{bindings._SCHEMA_SPECIFIER}";\n'
            f'import {{ runSqliteImmediateTransactionSync }} from "{bindings._SQL_SPECIFIER}";\n'
        ),
        bindings._VECTOR_STATE: (
            f'import {{ MEMORY_INDEX_META_TABLE }} from "{bindings._SCHEMA_SPECIFIER}";\n'
        ),
        bindings._SCHEMA_FACADE: (
            f'export {{ {", ".join(all_names)} }} from '
            '"../../packages/memory-host-sdk/src/host/memory-schema.js";\n'
        ),
        bindings._SQL_FACADE: (
            'export { runSqliteImmediateTransactionSync } from "../infra/sqlite-transaction.js";\n'
        ),
        bindings._SCHEMA: "",
        bindings._TRANSACTION: "export function runSqliteImmediateTransactionSync<T>() {}\n",
    }
    for owner in dict.fromkeys(bindings._SCHEMA_OWNERS.values()):
        owned = [name for name, target in bindings._SCHEMA_OWNERS.items() if target == owner]
        result[bindings._SCHEMA] += f'export {{ {", ".join(owned)} }} from "./{Path(owner).stem}.js";\n'
        result[owner] = "\n".join(
            f'export const {name} = "fixture";' if name.startswith("MEMORY_")
            else f"export function {name}() {{}}"
            for name in owned
        ) + "\n"
    assert set(result) == set(bindings._SOURCE_SHA256)
    return result


def test_publication_imports_keep_original_schema_and_transaction_owners(sources):
    before = deepcopy(sources)
    result = bindings._trace_index_projections(sources)
    assert len(result) == 3
    assert {(item["resolution"]["parent"], item["resolution"]["target"]) for item in result} == {
        (bindings._PUBLICATION, bindings._SCHEMA_FACADE),
        (bindings._PUBLICATION, bindings._SQL_FACADE),
        (bindings._VECTOR_STATE, bindings._SCHEMA_FACADE),
    }
    assert result[0]["resolution"]["bindings"] == list(bindings._PUBLICATION_SCHEMA_NAMES)
    assert all(item["chain"][0]["kind"] == "import" for item in result)
    assert sources == before


@pytest.mark.parametrize("change", [
    "facade-alias", "facade-target", "facade-type-only", "owner-alias", "owner-target",
    "missing-declaration", "duplicate-declaration", "runtime-extra", "runtime-alias",
    "transaction-owner", "transaction-missing", "duplicate-reexport",
])
def test_modified_or_ambiguous_index_bindings_are_rejected(sources, change):
    if change == "facade-alias":
        sources[bindings._SCHEMA_FACADE] = sources[bindings._SCHEMA_FACADE].replace(
            "dropMemoryChunkFtsTriggers", "other as dropMemoryChunkFtsTriggers")
    elif change == "facade-target":
        sources[bindings._SCHEMA_FACADE] = sources[bindings._SCHEMA_FACADE].replace("memory-schema.js", "other.js")
    elif change == "facade-type-only":
        sources[bindings._SCHEMA_FACADE] = sources[bindings._SCHEMA_FACADE].replace("export {", "export type {")
    elif change == "owner-alias":
        sources[bindings._SCHEMA] = sources[bindings._SCHEMA].replace(
            "ensureMemoryChunkProvenance", "other as ensureMemoryChunkProvenance")
    elif change == "owner-target":
        sources[bindings._SCHEMA] = sources[bindings._SCHEMA].replace("memory-schema-fts.js", "replacement.js")
    elif change == "missing-declaration":
        sources[bindings._PROVENANCE] = ""
    elif change == "duplicate-declaration":
        sources[bindings._TRANSACTION] *= 2
    elif change == "runtime-extra":
        sources[bindings._PUBLICATION] = sources[bindings._PUBLICATION].replace(
            "rebuildMemoryChunkFts }", "rebuildMemoryChunkFts, unreviewedRuntime }")
    elif change == "runtime-alias":
        sources[bindings._VECTOR_STATE] = sources[bindings._VECTOR_STATE].replace(
            "MEMORY_INDEX_META_TABLE", "MEMORY_INDEX_META_TABLE as other")
    elif change == "transaction-owner":
        sources[bindings._SQL_FACADE] = sources[bindings._SQL_FACADE].replace("sqlite-transaction", "other")
    elif change == "transaction-missing":
        sources[bindings._TRANSACTION] = "function runSqliteImmediateTransactionSync() {}\n"
    else:
        sources[bindings._SCHEMA_FACADE] *= 2
    with pytest.raises(bindings.IndexBindingError):
        bindings._trace_index_projections(sources)


@pytest.fixture
def checkout(tmp_path, monkeypatch, sources):
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


def test_prepared_provenance_is_explicitly_scoped_without_manager_claim(checkout):
    result = bindings.prepare_index_bindings(checkout)
    assert result["kind"] == "native-index-bindings"
    assert len(result["allowedResolutions"]) == 3
    assert all(item["scope"] == "native-index-publication" for item in result["projectionEvidence"])
    assert all(item["facadeExecutionVerified"] is False and item["fullManagerExecutionVerified"] is False
               for item in result["projectionEvidence"])
    assert all(item["facadeInitializationBypassed"] is False for item in result["projectionEvidence"])
    assert all(item["requiredFacadeSource"]["path"] == item["target"] for item in result["projectionEvidence"])
    assert all(item["chain"] and item["sources"] for item in result["projectionEvidence"])


def test_index_binding_modified_source_is_rejected(checkout):
    (checkout / bindings._SCHEMA).write_text("export const replaced = true;\n")
    with pytest.raises(bindings.IndexBindingError, match="unmodified"):
        bindings.prepare_index_bindings(checkout)


def test_index_binding_reviewed_digest_is_required(checkout, monkeypatch):
    changed = {**bindings._SOURCE_SHA256, bindings._TRANSACTION: "0" * 64}
    monkeypatch.setattr(bindings, "_SOURCE_SHA256", changed)
    with pytest.raises(bindings.IndexBindingError, match="reviewed release"):
        bindings.prepare_index_bindings(checkout)


def test_index_binding_wrong_commit_or_nested_root_is_rejected(checkout, monkeypatch):
    with pytest.raises(bindings.IndexBindingError, match="exact pinned"):
        bindings.prepare_index_bindings(checkout / "packages")
    monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    with pytest.raises(bindings.IndexBindingError, match="exact pinned"):
        bindings.prepare_index_bindings(checkout)


def test_absent_reference_never_creates_index_binding_evidence(tmp_path):
    with pytest.raises(bindings.IndexBindingError):
        bindings.prepare_index_bindings(tmp_path / "absent")


def test_original_facade_execution_requires_actual_source_hash_evidence(checkout):
    config = bindings.prepare_index_bindings(checkout)
    before = deepcopy(config)
    with pytest.raises(bindings.IndexBindingError, match="did not execute"):
        bindings.attest_index_facades(config, [])
    loaded = [item["requiredFacadeSource"] for item in config["projectionEvidence"]]
    result = bindings.attest_index_facades(config, loaded)
    assert all(item["facadeExecutionVerified"] for item in result["projectionEvidence"])
    assert config == before
    corrupted = [dict(item) for item in loaded]
    corrupted[0]["sha256"] = "0" * 64
    # Corrupt every occurrence; duplicate allowlist users do not supply new
    # independent execution evidence for the same original facade file.
    corrupted = [item for item in corrupted if item["path"] != loaded[0]["path"]]
    corrupted.append({"path": loaded[0]["path"], "sha256": "0" * 64})
    with pytest.raises(bindings.IndexBindingError, match="did not execute"):
        bindings.attest_index_facades(config, corrupted)


@pytest.fixture
def kernel_sources(sources):
    result = deepcopy(sources)
    result[bindings._SOURCE_KERNEL] = (
        f'import {{ hashText, type MemorySource }} from "{bindings._INDEX_SPECIFIER}";\n'
        f'import {{ MEMORY_INDEX_VECTOR_TABLE }} from "{bindings._SCHEMA_SPECIFIER}";\n'
        'import { executeSqliteQuerySync, executeSqliteQueryTakeFirstSync, getNodeSqliteKysely, '
        f'runSqliteImmediateTransactionSync }} from "{bindings._SQL_SPECIFIER}";\n'
    )
    result[bindings._CHUNK_WRITER] = (
        f'import {{ encodeMemoryEmbedding, type MemoryChunk }} from "{bindings._INDEX_SPECIFIER}";\n'
        f'import {{ compileSqliteQueryBindings, getNodeSqliteKysely }} from "{bindings._SQL_SPECIFIER}";\n'
    )
    result[bindings._INDEX_FACADE] = (
        f'export {{ hashText }} from "../../{bindings._HASH[:-3]}.js";\n'
        f'export {{ encodeMemoryEmbedding }} from "../../{bindings._CODEC[:-3]}.js";\n'
    )
    result[bindings._HASH] = "export function hashText() {}\n"
    result[bindings._CODEC] = "export function encodeMemoryEmbedding() {}\n"
    queries = ("compileSqliteQueryBindings", "executeSqliteQuerySync",
               "executeSqliteQueryTakeFirstSync", "getNodeSqliteKysely")
    result[bindings._SQL_FACADE] += (
        f'export {{ {", ".join(queries)} }} from "../infra/kysely-sync.js";\n'
    )
    result[bindings._QUERIES] = "\n".join(f"export function {name}<T>() {{}}" for name in queries)
    return result


def test_source_kernel_uses_complete_original_facades_without_synthetic_bridge(kernel_sources):
    items = bindings._trace_index_projections(kernel_sources, include_source_kernel=True)
    assert len(items) == 8
    assert {item["resolution"]["target"] for item in items} == {
        bindings._SCHEMA_FACADE, bindings._SQL_FACADE, bindings._INDEX_FACADE,
    }
    kernel = [item for item in items if item["resolution"]["parent"] == bindings._SOURCE_KERNEL]
    assert len(kernel) == 3
    sql = next(item for item in kernel if item["resolution"]["specifier"] == bindings._SQL_SPECIFIER)
    assert {edge["path"] for edge in sql["chain"]} == {
        bindings._SOURCE_KERNEL, bindings._SQL_FACADE, bindings._QUERIES, bindings._TRANSACTION,
    }


@pytest.mark.parametrize("module", ["_SOURCE_KERNEL", "_CHUNK_WRITER", "_INDEX_FACADE", "_QUERIES"])
def test_source_kernel_must_keep_all_original_bindings(kernel_sources, module):
    kernel_sources[getattr(bindings, module)] = "export const replaced = true;\n"
    with pytest.raises(bindings.IndexBindingError):
        bindings._trace_index_projections(kernel_sources, include_source_kernel=True)


def test_prepared_source_kernel_retains_original_facades_and_attests_only_loaded_bytes(
    checkout, kernel_sources, monkeypatch,
):
    for relative, content in kernel_sources.items():
        path = checkout / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                    "commit", "-qm", "kernel provenance fixture"], cwd=checkout, check=True)
    monkeypatch.setattr(bindings, "_COMMIT", subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout).decode().strip())
    for mapping in ("_SOURCE_SHA256", "_KERNEL_SOURCE_SHA256"):
        monkeypatch.setattr(bindings, mapping, {
            relative: hashlib.sha256(kernel_sources[relative].encode()).hexdigest()
            for relative in getattr(bindings, mapping)
        })
    config = bindings.prepare_index_bindings(checkout, include_source_kernel=True)
    assert len(config["allowedResolutions"]) == 8
    assert {item["target"] for item in config["allowedResolutions"]} == {
        bindings._SCHEMA_FACADE, bindings._SQL_FACADE, bindings._INDEX_FACADE,
    }
    loaded = [item["requiredFacadeSource"] for item in config["projectionEvidence"]]
    result = bindings.attest_index_facades(config, loaded)
    assert all(item["facadeExecutionVerified"] and not item["facadeInitializationBypassed"]
               for item in result["projectionEvidence"])
