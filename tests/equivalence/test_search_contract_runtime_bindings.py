"""Labelled owner/artifact fixtures authenticate provenance, never tool behavior."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import search_contract_runtime_bindings as bindings
from equivalence.runtime_oracle import ReleaseOracleExecution, ROOT, RuntimeOracleError
from test_runtime_oracle_transport import (
    _bootstrap, _evidence, _load, _trace, transport as transport,
)


_TOOL = "extensions/memory-core/src/tools.ts"
_RUNTIME = "extensions/memory-core/src/memory/manager-runtime.ts"
_COMPILED_TOOL = "dist/tools-DotaQGXh.mjs"
_COMPILED_CONTRACT = "dist/memory-tool-contract-DOz26L8b.mjs"
_COMPILED_MANAGER = "dist/extensions/memory-core/manager-runtime.js"


@pytest.fixture
def sources():
    result = {
        name: "// Labelled owner fixture, never executed.\n" + "\n".join(anchors)
        for name, anchors in bindings.SOURCE_ANCHORS.items()
    }
    result[_TOOL] = (
        'import { MEMORY_GET_TOOL_CONTRACT, MEMORY_SEARCH_TOOL_CONTRACT } '
        'from "./memory-tool-contract.js";\n'
        'import { buildMemorySearchPresentation, resolveMemoryCitationsMode, shouldIncludeCitations } '
        'from "./tools.citations.js";\n'
        'import { buildMemorySearchUnavailableResult, createMemoryTool, '
        'getMemoryManagerContextWithPurpose, loadMemoryToolRuntime } from "./tools.shared.js";\n'
        + result[_TOOL]
    )
    result[_RUNTIME] = (
        'import { getMemoryIndexManagerRegistry, MemoryIndexManager } from "./manager.js";\n'
        + result[_RUNTIME]
    )
    return result


@pytest.fixture
def compiled_sources():
    return {
        name: "// Labelled compiled fixture, never executed.\n" + "\n".join(anchors)
        for name, anchors in bindings.COMPILED_ANCHORS.items()
    }


def _trees(root: Path, monkeypatch, sources, compiled):
    checkout = root / "reference"
    checkout.mkdir()

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=checkout).decode().strip()

    git("init", "-q")
    for name, source in sources.items():
        file = checkout / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source)
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Labelled search-contract runtime owner fixture")
    runtime = root / "runtime"
    for name, source in compiled.items():
        file = runtime / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source)
    monkeypatch.setattr(bindings, "REFERENCE_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "SOURCE_HASHES", {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()
    })
    monkeypatch.setattr(bindings, "COMPILED_HASHES", {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in compiled.items()
    })
    return checkout, runtime


@pytest.fixture
def trees(tmp_path, monkeypatch, sources, compiled_sources):
    return _trees(tmp_path, monkeypatch, sources, compiled_sources)


def test_tool_provenance_separates_official_exports_from_source_build_and_execution(trees, sources):
    before = deepcopy(sources)
    result = bindings.prepare_search_contract_runtime_bindings(*trees)
    assert sources == before
    assert result["kind"] == "official-release-memory-search-tool-owner"
    assert result["referenceCommit"] == bindings.REFERENCE_COMMIT
    assert result["sourceBuildReproduced"] is False
    assert result["constructorSkipped"] is False
    assert result["fullManagerExecutionVerified"] is False
    assert result["fullHostOrchestrationVerified"] is False
    assert {row["path"] for row in result["sourceBindings"]} == set(bindings.SOURCE_HASHES)
    assert {row["path"] for row in result["compiledBindings"]} == set(bindings.COMPILED_HASHES)
    assert result["entrypoints"] == {
        "tool": {"path": _COMPILED_TOOL, "export": "createMemorySearchTool"},
        "contract": {"path": _COMPILED_CONTRACT, "export": "n",
                     "originalBinding": "MEMORY_SEARCH_TOOL_CONTRACT"},
        "manager": {"path": _COMPILED_MANAGER, "export": "MemoryIndexManager",
                    "methods": ["get", "sync", "search", "close"]},
    }
    assert result["requiredLoadedArtifactsByProfile"] == {
        "search-contract-helper-runtime": list(bindings.HELPER_ARTIFACTS),
        "search-contract-runtime": list(bindings.COMPILED_HASHES),
    }
    assert result["workerRequiredByProfile"] == {
        "search-contract-helper-runtime": False, "search-contract-runtime": True,
    }
    assert _COMPILED_MANAGER not in bindings.HELPER_ARTIFACTS
    assert set(bindings.HELPER_ARTIFACTS) < set(bindings.TOOL_ARTIFACTS)
    assert [row["path"] for row in result["sourceImportLinks"]] == [_TOOL] * 3 + [_RUNTIME]
    for row in result["sourceBindings"] + result["compiledBindings"]:
        assert len(row["sha256"]) == 64
        assert all(anchor["line"] > 0 for anchor in row["anchors"])


@pytest.mark.parametrize("tree,name", [
    *(('source', name) for name in bindings.SOURCE_HASHES),
    *(('compiled', name) for name in bindings.COMPILED_HASHES),
])
def test_reviewed_fixture_bytes_still_require_every_tool_owner_declaration(
    tmp_path, monkeypatch, sources, compiled_sources, tree, name,
):
    values, anchors = (
        (sources, bindings.SOURCE_ANCHORS) if tree == "source"
        else (compiled_sources, bindings.COMPILED_ANCHORS)
    )
    values[name] = values[name].replace(anchors[name][0], "// missing original declaration")
    with pytest.raises(bindings.SearchContractRuntimeBindingError):
        bindings.prepare_search_contract_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize("mutation", [
    "contract-alias", "contract-type", "contract-extra", "contract-owner",
    "citations-alias", "citations-type", "citations-owner", "shared-alias", "shared-owner",
    "manager-alias", "manager-type", "manager-extra", "manager-owner", "duplicate-compiled-tool",
])
def test_reviewed_fixture_bytes_cannot_replace_native_tool_bindings_or_public_exports(
    tmp_path, monkeypatch, sources, compiled_sources, mutation,
):
    if mutation.startswith("contract-"):
        source, name, specifier = _TOOL, "MEMORY_GET_TOOL_CONTRACT", "memory-tool-contract.js"
    elif mutation.startswith("citations-"):
        source, name, specifier = _TOOL, "buildMemorySearchPresentation", "tools.citations.js"
    elif mutation.startswith("shared-"):
        source, name, specifier = _TOOL, "buildMemorySearchUnavailableResult", "tools.shared.js"
    else:
        source, name, specifier = _RUNTIME, "getMemoryIndexManagerRegistry", "manager.js"
    if mutation.endswith("-alias"):
        sources[source] = sources[source].replace(name, "Other as " + name, 1)
    elif mutation.endswith("-type"):
        start = sources[source].index("import { " + name)
        sources[source] = sources[source][:start] + sources[source][start:].replace(
            "import {", "import type {", 1,
        )
    elif mutation.endswith("-extra"):
        sources[source] = sources[source].replace(name + ",", name + ", Unreviewed,", 1)
    elif mutation.endswith("-owner"):
        sources[source] = sources[source].replace(specifier, "unreviewed.js", 1)
    else:
        compiled_sources[_COMPILED_TOOL] += "\n" + bindings.COMPILED_ANCHORS[_COMPILED_TOOL][0]
    with pytest.raises(bindings.SearchContractRuntimeBindingError):
        bindings.prepare_search_contract_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize("mutation", [
    "source-dirty", "source-digest", "commit", "nested-root", "source-symlink",
    "source-ancestor-symlink", "committed-bytes", "compiled-digest", "compiled-symlink",
    "compiled-ancestor-symlink", "compiled-missing",
])
def test_unowned_or_changed_source_and_release_artifact_bytes_supply_no_tool_identity(
    trees, monkeypatch, mutation,
):
    checkout, runtime = trees
    if mutation == "source-dirty":
        (checkout / _TOOL).write_text("// changed\n")
    elif mutation == "source-digest":
        monkeypatch.setattr(bindings, "SOURCE_HASHES", {
            **bindings.SOURCE_HASHES, _TOOL: "0" * 64,
        })
    elif mutation == "commit":
        monkeypatch.setattr(bindings, "REFERENCE_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "extensions"
    elif mutation in {
        "source-symlink", "source-ancestor-symlink", "compiled-symlink", "compiled-ancestor-symlink",
    }:
        file = checkout / _TOOL if mutation.startswith("source") else runtime / _COMPILED_TOOL
        target = file.parent if "ancestor" in mutation else file
        saved = target.with_name("saved-owner")
        target.rename(saved)
        target.symlink_to(saved, target_is_directory="ancestor" in mutation)
    elif mutation == "committed-bytes":
        original = bindings._git

        def forged_git(root, *args):
            return b"forged committed bytes" if args[0] == "show" else original(root, *args)

        monkeypatch.setattr(bindings, "_git", forged_git)
    elif mutation == "compiled-digest":
        (runtime / _COMPILED_TOOL).write_text("// changed compiled bytes\n")
    else:
        (runtime / _COMPILED_CONTRACT).unlink()
    with pytest.raises(bindings.SearchContractRuntimeBindingError):
        bindings.prepare_search_contract_runtime_bindings(checkout, runtime)


@pytest.mark.parametrize("missing", ["source", "runtime"])
def test_missing_tree_supplies_no_search_contract_runtime_evidence(trees, tmp_path, missing):
    checkout, runtime = trees
    if missing == "source":
        checkout = tmp_path / "absent-source"
    else:
        runtime = tmp_path / "absent-runtime"
    with pytest.raises(bindings.SearchContractRuntimeBindingError):
        bindings.prepare_search_contract_runtime_bindings(checkout, runtime)


@pytest.fixture
def search_transport(transport):
    previous, original, case, result = transport
    config = deepcopy(original)
    package = config["packages"][0]
    existing = {item["path"] for item in package["files"]}
    for relative in bindings.COMPILED_HASHES:
        if relative in existing:
            continue
        raw = ("// Labelled search-tool transport fixture: " + relative + "\n").encode()
        file = Path(config["runtimeRoot"]) / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(raw)
        package["files"].append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest()})
    case["operation"] = "search-contract-runtime"
    case["input"] = {"kind": "tool"}
    with ReleaseOracleExecution(config, previous.adapter_hashes) as execution:
        yield execution, config, case, result


def _search_trace(execution, config, artifacts):
    local = [
        {"event": "load", "pid": 111, "threadId": 0, "kind": "oracle",
         "path": str((ROOT / "equivalence" / name).resolve()),
         "sha256": execution._locals[str((ROOT / "equivalence" / name).resolve())]}
        for name in ("release-oracle.mjs", "search-contract-runtime.mjs")
    ]
    return [_bootstrap(execution, 0), *local,
            *[_load(config, relative, 0) for relative in artifacts]]


def _search_worker(execution, config):
    return [_bootstrap(execution, 1),
            _load(config, "dist/extensions/memory-core/memory-index.worker.js", 1)]


def test_whole_tool_transport_keeps_raw_envelopes_and_requires_protected_real_search_owner(
    search_transport,
):
    execution, config, case, result = search_transport
    _trace(execution, 0, _search_trace(execution, config, bindings.TOOL_ARTIFACTS))
    _trace(execution, 1, _search_worker(execution, config))
    raw = [{"labelledTransportFixture": True, "nativeEnvelopes": [
        {"index": 0, "result": {
            "content": [{"type": "text", "text": '{\n  "results": []\n}'}],
            "details": {"results": []},
        }},
        {"index": 1, "error": {"name": "ToolInputError", "status": 400,
                                 "message": "query required"}},
    ]}]
    _evidence(execution, case, raw)
    observed = execution.collect(result, [case])
    assert observed["releaseTrace"]["protectedWorkerThreads"] == 1
    assert observed["releaseTrace"]["networkFetchDenied"] is True
    assert set(bindings.TOOL_ARTIFACTS) <= {row["path"] for row in observed["releaseSources"]}
    assert observed["runtimeDiagnostics"][0]["rawSnapshots"] == raw


@pytest.mark.parametrize("missing", [
    *bindings.TOOL_ARTIFACTS, "worker", "adapter", "bootstrap",
])
def test_whole_tool_transport_cannot_drop_any_owner_or_worker_authority(search_transport, missing):
    execution, config, case, result = search_transport
    events = _search_trace(execution, config, bindings.TOOL_ARTIFACTS)
    if missing in bindings.TOOL_ARTIFACTS:
        events = [event for event in events if event.get("path") != missing]
    elif missing == "adapter":
        events = [event for event in events if not event.get("path", "").endswith(
            "/search-contract-runtime.mjs",
        )]
    elif missing == "bootstrap":
        events = events[1:]
    _trace(execution, 0, events)
    if missing != "worker":
        _trace(execution, 1, _search_worker(execution, config))
    _evidence(execution, case, [{"labelledTransportFixture": True}])
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


def test_factory_only_helper_transport_does_not_claim_manager_dispatch_or_need_a_worker(
    search_transport,
):
    execution, config, case, result = search_transport
    case["operation"] = "search-contract-helper-runtime"
    case["input"] = {"kind": "definition"}
    _trace(execution, 0, _search_trace(execution, config, bindings.HELPER_ARTIFACTS))
    raw = [{"labelledTransportFixture": True, "kind": "definition",
            "nativeEnvelopes": [], "dispatches": [], "result": {"definition": None}}]
    _evidence(execution, case, raw)
    observed = execution.collect(result, [case])
    assert observed["releaseTrace"]["protectedWorkerThreads"] == 0
    assert _COMPILED_MANAGER not in {row["path"] for row in observed["releaseSources"]}
    assert set(bindings.HELPER_ARTIFACTS) <= {row["path"] for row in observed["releaseSources"]}
    assert observed["runtimeDiagnostics"][0]["rawSnapshots"] == raw


@pytest.mark.parametrize("missing", bindings.HELPER_ARTIFACTS)
def test_worker_free_helper_transport_still_requires_every_actual_definition_owner(
    search_transport, missing,
):
    execution, config, case, result = search_transport
    case["operation"] = "search-contract-helper-runtime"
    case["input"] = {"kind": "prepare-arguments"}
    events = _search_trace(execution, config, bindings.HELPER_ARTIFACTS)
    _trace(execution, 0, [event for event in events if event.get("path") != missing])
    _evidence(execution, case, [{"labelledTransportFixture": True}])
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


@pytest.mark.parametrize("operation,kind", [
    ("search-contract-helper-runtime", "tool"),
    ("search-contract-runtime", "definition"),
    ("search-contract-runtime", "prepare-arguments"),
])
def test_whole_tool_fixtures_cannot_select_the_worker_free_helper_profile(
    search_transport, operation, kind,
):
    execution, _, case, result = search_transport
    case["operation"] = operation
    case["input"] = {"kind": kind}
    with pytest.raises(RuntimeOracleError, match="declared helper or whole-tool profile"):
        execution.collect(result, [case])
