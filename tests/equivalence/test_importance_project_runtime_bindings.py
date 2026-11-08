"""Labelled source/artifact fixtures authenticate owners, never ranking outputs."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import importance_project_runtime_bindings as bindings
from equivalence.runtime_oracle import ReleaseOracleExecution, ROOT, RuntimeOracleError
from test_runtime_oracle_transport import (
    _bootstrap, _evidence, _load, _trace, transport as transport,
)


@pytest.fixture
def sources():
    result = {name: "// Labelled owner fixture, never executed.\n" + "\n".join(anchors)
              for name, anchors in bindings.SOURCE_ANCHORS.items()}
    for name, declaration in (
        (bindings._ORCHESTRATION,
         'import { MemoryKeywordRetrieval } from "./manager-keyword-retrieval.js";\n'),
        (bindings._MANAGER,
         'import { MemorySearchOrchestration } from "./manager-search-orchestration.js";\n'),
        (bindings._RUNTIME,
         'import { getMemoryIndexManagerRegistry, MemoryIndexManager } from "./manager.js";\n'),
        (bindings._KEYWORD,
         'import { readMemoryRecallData } from "./manager-retrieval-read.js";\n'),
    ):
        result[name] = declaration + result[name]
    return result


@pytest.fixture
def compiled_sources():
    return {name: "// Labelled compiled fixture, never executed.\n" + "\n".join(anchors)
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
        "commit", "-qm", "Labelled stored importance/project owner fixture")
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


def test_stored_ranking_provenance_keeps_source_build_and_exercised_scope_separate(trees, sources):
    before = deepcopy(sources)
    result = bindings.prepare_importance_project_runtime_bindings(*trees)
    assert sources == before
    assert result["kind"] == "official-release-importance-project-owner"
    assert result["referenceCommit"] == bindings.REFERENCE_COMMIT
    assert result["sourceBuildReproduced"] is False
    assert result["constructorSkipped"] is False
    assert result["fullManagerExecutionVerified"] is False
    assert result["fullHostOrchestrationVerified"] is False
    assert {row["path"] for row in result["sourceBindings"]} == set(bindings.SOURCE_HASHES)
    assert {row["path"] for row in result["compiledBindings"]} == set(bindings.COMPILED_HASHES)
    assert result["requiredLoadedArtifacts"] == list(bindings.COMPILED_HASHES)
    assert [row["path"] for row in result["sourceClassLinks"]] == [
        bindings._ORCHESTRATION, bindings._MANAGER, bindings._RUNTIME, bindings._KEYWORD,
    ]
    assert result["entrypoint"] == {
        "path": bindings._COMPILED, "export": "MemoryIndexManager",
        "methods": ["get", "sync", "search", "close"],
    }
    for row in result["sourceBindings"] + result["compiledBindings"]:
        assert len(row["sha256"]) == 64
        assert all(anchor["line"] > 0 for anchor in row["anchors"])


@pytest.mark.parametrize("mutation", [
    "keyword-finalizer-absent", "keyword-attach-duplicate", "preparation-absent",
    "orchestration-alias", "orchestration-type-only", "orchestration-extra-import",
    "manager-import-owner", "manager-parent", "runtime-import-owner", "runtime-export",
    "recall-import-owner", "compiled-search-absent", "compiled-prepare-absent",
    "compiled-recall-absent", "compiled-retrieval-duplicate", "compiled-parent", "compiled-export",
])
def test_reviewed_ranking_bytes_still_require_each_owner_and_the_real_public_class_chain(
    tmp_path, monkeypatch, sources, compiled_sources, mutation,
):
    if mutation == "keyword-finalizer-absent":
        sources[bindings._KEYWORD] = sources[bindings._KEYWORD].replace(
            "  protected async finalizeKeywordOnlyResults(params: {", "  protected changed(params: {",
        )
    elif mutation == "keyword-attach-duplicate":
        sources[bindings._KEYWORD] += "\n" + bindings.SOURCE_ANCHORS[bindings._KEYWORD][2]
    elif mutation == "preparation-absent":
        sources[bindings._PREPARATION] = "// missing preparation owner\n"
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
    elif mutation == "recall-import-owner":
        sources[bindings._KEYWORD] = sources[bindings._KEYWORD].replace(
            "./manager-retrieval-read.js", "./other.js",
        )
    elif mutation == "compiled-search-absent":
        compiled_sources[bindings._COMPILED] = compiled_sources[bindings._COMPILED].replace(
            "\tasync search(query, opts) {", "\tasync other(query, opts) {",
        )
    elif mutation == "compiled-prepare-absent":
        compiled_sources[bindings._COMPILED_PREPARATION] = "// missing preparation artifact\n"
    elif mutation == "compiled-recall-absent":
        compiled_sources[bindings._COMPILED_RECALL] = "// missing recall artifact\n"
    elif mutation == "compiled-retrieval-duplicate":
        compiled_sources[bindings._COMPILED_RETRIEVAL] += (
            "\n" + bindings.COMPILED_ANCHORS[bindings._COMPILED_RETRIEVAL][0]
        )
    elif mutation == "compiled-parent":
        compiled_sources[bindings._COMPILED] = compiled_sources[bindings._COMPILED].replace(
            "class extends MemoryKeywordRetrieval", "class extends Unreviewed",
        )
    else:
        compiled_sources[bindings._COMPILED] = compiled_sources[bindings._COMPILED].replace(
            "export { MemoryIndexManager,", "export { Other,",
        )
    with pytest.raises(ValueError):
        bindings.prepare_importance_project_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize("mutation", [
    "source-dirty", "source-digest", "commit", "nested-root", "source-symlink",
    "committed-bytes", "compiled-digest", "compiled-symlink", "compiled-missing",
])
def test_changed_or_unowned_ranking_source_and_artifact_bytes_cannot_authenticate(
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
    elif mutation == "nested-root":
        checkout = checkout / "extensions"
    elif mutation in {"source-symlink", "compiled-symlink"}:
        file = (checkout / bindings._KEYWORD if mutation == "source-symlink"
                else runtime / bindings._COMPILED_RECALL)
        saved = file.with_name("saved-owner")
        saved.write_bytes(file.read_bytes())
        file.unlink()
        file.symlink_to(saved)
    elif mutation == "committed-bytes":
        original = bindings._git

        def changed_git(root, *args):
            return b"forged committed bytes" if args[0] == "show" else original(root, *args)

        monkeypatch.setattr(bindings, "_git", changed_git)
    elif mutation == "compiled-digest":
        (runtime / bindings._COMPILED_PREPARATION).write_text("// changed artifact\n")
    else:
        (runtime / bindings._COMPILED_RETRIEVAL).unlink()
    with pytest.raises(ValueError):
        bindings.prepare_importance_project_runtime_bindings(checkout, runtime)


@pytest.mark.parametrize("missing", ["reference", "runtime"])
def test_missing_tree_provides_no_importance_project_runtime_identity(trees, tmp_path, missing):
    checkout, runtime = trees
    if missing == "reference":
        checkout = tmp_path / "absent-reference"
    else:
        runtime = tmp_path / "absent-runtime"
    with pytest.raises(ValueError):
        bindings.prepare_importance_project_runtime_bindings(checkout, runtime)


@pytest.fixture
def project_transport(transport):
    previous, original, case, result = transport
    config = deepcopy(original)
    package = config["packages"][0]
    existing = {item["path"] for item in package["files"]}
    for relative in bindings.COMPILED_HASHES:
        if relative in existing:
            continue
        raw = ("// Labelled project transport fixture: " + relative + "\n").encode()
        file = Path(config["runtimeRoot"]) / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(raw)
        package["files"].append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest()})
    case["operation"] = "importance-project-runtime"
    with ReleaseOracleExecution(config, previous.adapter_hashes) as execution:
        yield execution, config, case, result


def _project_trace(execution, config):
    local = [{"event": "load", "pid": 111, "threadId": 0, "kind": "oracle",
              "path": str((ROOT / "equivalence" / name).resolve()),
              "sha256": execution._locals[str((ROOT / "equivalence" / name).resolve())]}
             for name in ("release-oracle.mjs", "importance-project-runtime.mjs")]
    return [_bootstrap(execution, 0), *local,
            *[_load(config, relative, 0) for relative in bindings.COMPILED_HASHES]]


def _project_worker(execution, config):
    return [_bootstrap(execution, 1),
            _load(config, "dist/extensions/memory-core/memory-index.worker.js", 1)]


def test_stored_ranking_transport_requires_actual_preparation_readers_and_protected_worker(
    project_transport,
):
    execution, config, case, result = project_transport
    _trace(execution, 0, _project_trace(execution, config))
    _trace(execution, 1, _project_worker(execution, config))
    raw = [{"labelledTransportFixture": True, "rows": [], "recall": [], "constructorExecuted": True}]
    _evidence(execution, case, raw)
    observed = execution.collect(result, [case])
    assert observed["releaseTrace"]["protectedWorkerThreads"] == 1
    assert observed["releaseTrace"]["networkFetchDenied"] is True
    assert set(bindings.COMPILED_HASHES) <= {item["path"] for item in observed["releaseSources"]}
    assert observed["runtimeDiagnostics"][0]["rawSnapshots"] == raw


@pytest.mark.parametrize("missing", [
    "manager", "preparation", "retrieval", "recall", "worker", "adapter", "bootstrap",
])
def test_stored_ranking_transport_rejects_missing_real_owner_or_execution_authority(
    project_transport, missing,
):
    execution, config, case, result = project_transport
    events = _project_trace(execution, config)
    missing_file = {
        "manager": bindings._COMPILED,
        "preparation": bindings._COMPILED_PREPARATION,
        "retrieval": bindings._COMPILED_RETRIEVAL,
        "recall": bindings._COMPILED_RECALL,
    }.get(missing)
    if missing_file is not None:
        events = [event for event in events if event.get("path") != missing_file]
    elif missing == "adapter":
        events = [event for event in events if not event.get("path", "").endswith(
            "/importance-project-runtime.mjs")]
    elif missing == "bootstrap":
        events = events[1:]
    _trace(execution, 0, events)
    if missing != "worker":
        _trace(execution, 1, _project_worker(execution, config))
    _evidence(execution, case, [{"labelledTransportFixture": True}])
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])
