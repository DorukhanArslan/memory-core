"""Labelled provenance/transport fixtures establish no exact-path behavioral parity."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import exact_path_runtime_bindings as bindings
from equivalence.runtime_oracle import ROOT, RuntimeOracleError
from test_runtime_oracle_transport import (
    _bootstrap, _evidence, _load, _trace, transport as transport,
)


@pytest.fixture
def sources():
    return {
        bindings._KEYWORD: (
            "export abstract class MemoryKeywordRetrieval extends MemoryProviderLifecycle {\n"
            "  private mergeKeywordSearchHits(\n    values: unknown[]\n  ) { return values; }\n"
            "  private limitKeywordSearchHits(\n    values: unknown[]\n  ) { return values; }\n}\n"
        ),
        bindings._ORCHESTRATION: (
            'import { MemoryKeywordRetrieval } from "./manager-keyword-retrieval.js";\n'
            "export abstract class MemorySearchOrchestration extends MemoryKeywordRetrieval {\n}\n"
        ),
        bindings._MANAGER: (
            'import { MemorySearchOrchestration } from "./manager-search-orchestration.js";\n'
            "export class MemoryIndexManager extends MemorySearchOrchestration "
            "implements MemorySearchManager {\n}\n"
        ),
        bindings._RUNTIME: (
            'import { getMemoryIndexManagerRegistry, MemoryIndexManager } from "./manager.js";\n'
            "export { MemoryIndexManager };\n"
        ),
    }


@pytest.fixture
def compiled_sources():
    return {name: "// Labelled compiled-owner fixture, never executed.\n" + "\n".join(anchors)
            for name, anchors in bindings.COMPILED_ANCHORS.items()}


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
        "commit", "-qm", "Labelled exact-path runtime owner fixture")
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


def test_exact_path_method_owner_keeps_source_and_compiled_identities_separate(trees, sources):
    before = deepcopy(sources)
    result = bindings.prepare_exact_path_runtime_bindings(*trees)
    assert before == sources
    assert result["kind"] == "official-release-exact-path-method-owner"
    assert result["referenceCommit"] == bindings.REFERENCE_COMMIT
    assert result["sourceBuildReproduced"] is False
    assert result["constructorSkipped"] is True
    assert result["fullManagerExecutionVerified"] is False
    assert result["fullHostOrchestrationVerified"] is False
    assert {row["path"] for row in result["sourceBindings"]} == set(bindings.SOURCE_HASHES)
    assert {row["path"] for row in result["compiledBindings"]} == set(bindings.COMPILED_HASHES)
    assert [row["path"] for row in result["sourceClassLinks"]] == [
        bindings._ORCHESTRATION, bindings._MANAGER, bindings._RUNTIME,
    ]
    assert result["entrypoint"] == {
        "path": bindings._COMPILED, "export": "MemoryIndexManager",
        "owner": "MemoryKeywordRetrieval",
        "methods": ["mergeKeywordSearchHits", "limitKeywordSearchHits"],
    }
    for row in result["sourceBindings"] + result["compiledBindings"]:
        assert len(row["sha256"]) == 64
        assert all(anchor["line"] > 0 for anchor in row["anchors"])


@pytest.mark.parametrize("mutation", [
    "keyword-method-absent", "keyword-method-duplicate", "keyword-parent",
    "orchestration-alias", "orchestration-type-only", "orchestration-extra-import",
    "manager-import-owner", "manager-parent", "runtime-import-owner", "runtime-export",
    "compiled-method-absent", "compiled-method-duplicate", "compiled-parent", "compiled-export",
])
def test_even_reviewed_bytes_require_unique_methods_and_original_class_links(
    tmp_path, monkeypatch, sources, compiled_sources, mutation,
):
    if mutation.startswith("keyword-method"):
        needle = "  private mergeKeywordSearchHits(\n"
        sources[bindings._KEYWORD] = sources[bindings._KEYWORD].replace(
            needle, "  private changed(\n" if mutation.endswith("absent") else needle * 2,
        )
    elif mutation == "keyword-parent":
        sources[bindings._KEYWORD] = sources[bindings._KEYWORD].replace(
            "extends MemoryProviderLifecycle", "extends UnreviewedParent",
        )
    elif mutation == "orchestration-alias":
        sources[bindings._ORCHESTRATION] = sources[bindings._ORCHESTRATION].replace(
            "{ MemoryKeywordRetrieval }", "{ Other as MemoryKeywordRetrieval }",
        )
    elif mutation == "orchestration-type-only":
        sources[bindings._ORCHESTRATION] = sources[bindings._ORCHESTRATION].replace(
            "import {", "import type {",
        )
    elif mutation == "orchestration-extra-import":
        sources[bindings._ORCHESTRATION] = sources[bindings._ORCHESTRATION].replace(
            "{ MemoryKeywordRetrieval }", "{ MemoryKeywordRetrieval, Unreviewed }",
        )
    elif mutation == "manager-import-owner":
        sources[bindings._MANAGER] = sources[bindings._MANAGER].replace(
            "./manager-search-orchestration.js", "./unreviewed.js",
        )
    elif mutation == "manager-parent":
        sources[bindings._MANAGER] = sources[bindings._MANAGER].replace(
            "extends MemorySearchOrchestration", "extends UnreviewedParent",
        )
    elif mutation == "runtime-import-owner":
        sources[bindings._RUNTIME] = sources[bindings._RUNTIME].replace("./manager.js", "./other.js")
    elif mutation == "runtime-export":
        sources[bindings._RUNTIME] = sources[bindings._RUNTIME].replace(
            "export { MemoryIndexManager };", "export { Other };",
        )
    else:
        compiled = bindings._COMPILED
        needle = "\tmergeKeywordSearchHits(resultSets, exactPathQuery) {"
        if mutation == "compiled-method-absent":
            compiled_sources[compiled] = compiled_sources[compiled].replace(needle, "changed() {")
        elif mutation == "compiled-method-duplicate":
            compiled_sources[compiled] += "\n" + needle
        elif mutation == "compiled-parent":
            compiled_sources[compiled] = compiled_sources[compiled].replace(
                "class extends MemoryKeywordRetrieval", "class extends Other",
            )
        else:
            compiled_sources[compiled] = compiled_sources[compiled].replace(
                "export { MemoryIndexManager,", "export { Other,",
            )
    trees = _trees(tmp_path, monkeypatch, sources, compiled_sources)
    with pytest.raises(ValueError):
        bindings.prepare_exact_path_runtime_bindings(*trees)


@pytest.mark.parametrize("mutation", [
    "source-dirty", "source-digest", "commit", "nested-checkout", "source-symlink",
    "committed-bytes", "compiled-digest", "compiled-symlink", "compiled-missing",
])
def test_changed_or_unowned_source_and_artifact_bytes_cannot_authenticate_methods(
    trees, monkeypatch, mutation,
):
    checkout, runtime = trees
    if mutation == "source-dirty":
        (checkout / bindings._KEYWORD).write_text("// changed\n")
    elif mutation == "source-digest":
        monkeypatch.setattr(bindings, "SOURCE_HASHES", {
            **bindings.SOURCE_HASHES, bindings._KEYWORD: "0" * 64,
        })
    elif mutation == "commit":
        monkeypatch.setattr(bindings, "REFERENCE_COMMIT", "0" * 40)
    elif mutation == "nested-checkout":
        checkout = checkout / "extensions"
    elif mutation in {"source-symlink", "compiled-symlink"}:
        file = checkout / bindings._KEYWORD if mutation == "source-symlink" else runtime / bindings._COMPILED
        saved = file.with_name("saved-owner")
        saved.write_bytes(file.read_bytes())
        file.unlink()
        file.symlink_to(saved)
    elif mutation == "committed-bytes":
        original = bindings._git

        def changed_git(root, *args):
            return b"changed committed bytes" if args[0] == "show" else original(root, *args)

        monkeypatch.setattr(bindings, "_git", changed_git)
    elif mutation == "compiled-digest":
        (runtime / bindings._COMPILED).write_text("// changed compiled owner\n")
    else:
        (runtime / bindings._COMPILED).unlink()
    with pytest.raises(ValueError):
        bindings.prepare_exact_path_runtime_bindings(checkout, runtime)


@pytest.mark.parametrize("missing", ["reference", "runtime"])
def test_missing_tree_yields_no_exact_path_runtime_owner(trees, tmp_path, missing):
    checkout, runtime = trees
    if missing == "reference":
        checkout = tmp_path / "absent-reference"
    else:
        runtime = tmp_path / "absent-runtime"
    with pytest.raises(ValueError):
        bindings.prepare_exact_path_runtime_bindings(checkout, runtime)


def _exact_trace(execution, config):
    local = [{"event": "load", "pid": 111, "threadId": 0, "kind": "oracle",
              "path": str((ROOT / "equivalence" / name).resolve()),
              "sha256": execution._locals[str((ROOT / "equivalence" / name).resolve())]}
             for name in ("release-oracle.mjs", "exact-path-runtime.mjs")]
    return [_bootstrap(execution, 0), *local,
            _load(config, "dist/extensions/memory-core/manager-runtime.js", 0)]


def test_exact_path_runtime_requires_its_actual_owner_but_no_unrelated_worker(transport):
    execution, config, case, result = transport
    case["operation"] = "exact-path-runtime"
    _trace(execution, 0, _exact_trace(execution, config))
    _evidence(execution, case, [{"method": "labelled prototype transport"}])
    enriched = execution.collect(result, [case])
    assert enriched["releaseTrace"]["protectedWorkerThreads"] == 0
    assert enriched["releaseSources"][0]["path"] == "dist/extensions/memory-core/manager-runtime.js"


@pytest.mark.parametrize("missing", ["adapter", "owner", "bootstrap"])
def test_exact_path_runtime_cannot_borrow_another_operation_or_omit_protection(transport, missing):
    execution, config, case, result = transport
    case["operation"] = "exact-path-runtime"
    events = _exact_trace(execution, config)
    if missing == "adapter":
        events = [event for event in events
                  if not str(event.get("path", "")).endswith("exact-path-runtime.mjs")]
    elif missing == "owner":
        events = [event for event in events
                  if not str(event.get("path", "")).endswith("manager-runtime.js")]
    else:
        events.pop(0)
    _trace(execution, 0, events)
    _evidence(execution, case)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])
