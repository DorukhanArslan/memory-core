"""Labelled owner/transport fixtures grant no memory-get behavioral credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from equivalence import get_contract_runtime_bindings as bindings
from equivalence.runtime_oracle import ReleaseOracleExecution, ROOT, RuntimeOracleError
from test_runtime_oracle_transport import (
    _bootstrap, _evidence, _load, _trace, transport as transport,
)


_TOOL = "extensions/memory-core/src/tools.ts"
_TOOL_RUNTIME = "extensions/memory-core/src/tools.runtime.ts"
_SDK_RUNTIME = "src/plugin-sdk/memory-core-host-runtime-files.ts"
_RUNTIME_FILES = "packages/memory-host-sdk/src/runtime-files.ts"
_READ = "packages/memory-host-sdk/src/host/read-file.ts"
_COMPILED_TOOL = "dist/tools-DotaQGXh.mjs"
_COMPILED_READ = "dist/read-file-CH8NQLbp.mjs"


@pytest.fixture
def sources():
    result = {
        name: "// Labelled source owner, never executed.\n" + "\n".join(anchors)
        for name, anchors in bindings.SOURCE_ANCHORS.items()
    }
    result[_TOOL] = (
        'import { executeMemoryReadResult, executeWikiMemoryReadResult } '
        'from "./memory-read-tool.js";\n' + result[_TOOL]
    )
    result[_TOOL_RUNTIME] = (
        'export {\n  readAgentMemoryFile,\n  resolveMemoryBackendConfig,\n} '
        'from "openclaw/plugin-sdk/memory-core-host-runtime-files";\n'
    )
    result[_SDK_RUNTIME] = (
        'export {\n  listMemoryFiles,\n  normalizeExtraMemoryPaths,\n  readAgentMemoryFile,\n'
        '  resolveMemoryBackendConfig,\n} '
        'from "../../packages/memory-host-sdk/src/runtime-files.js";\n'
    )
    result[_READ] = (
        'import { buildMemoryReadResult, DEFAULT_MEMORY_READ_LINES } '
        'from "./read-file-shared.js";\n' + result[_READ]
    )
    return result


@pytest.fixture
def compiled_sources():
    return {
        name: "// Labelled compiled artifact, never executed.\n" + "\n".join(anchors)
        for name, anchors in bindings.COMPILED_ANCHORS.items()
    }


def _trees(root: Path, monkeypatch, sources, compiled):
    checkout = root / "reference"
    checkout.mkdir()

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=checkout).decode().strip()

    git("init", "-q")
    for relative, source in sources.items():
        file = checkout / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source)
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Labelled memory-get runtime owner fixture")
    runtime = root / "runtime"
    for relative, source in compiled.items():
        file = runtime / relative
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


def test_get_provenance_uses_actual_read_owners_without_claiming_index_manager_execution(trees):
    result = bindings.prepare_get_contract_runtime_bindings(*trees)
    assert result["kind"] == "official-release-memory-get-tool-owner"
    assert result["referenceCommit"] == bindings.REFERENCE_COMMIT
    assert result["sourceBuildReproduced"] is False
    assert result["constructorSkipped"] is False
    assert result["indexManagerConstructed"] is False
    assert result["fullManagerExecutionVerified"] is False
    assert result["fullHostOrchestrationVerified"] is False
    assert result["workerRequired"] is False
    assert {row["path"] for row in result["sourceBindings"]} == set(bindings.SOURCE_HASHES)
    assert {row["path"] for row in result["compiledBindings"]} == set(bindings.COMPILED_HASHES)
    assert result["entrypoints"] == {
        "tool": {"path": _COMPILED_TOOL, "export": "createMemoryGetTool"},
        "read": {"path": _COMPILED_READ, "export": "t", "originalBinding": "readAgentMemoryFile"},
    }
    assert result["requiredLoadedArtifactsByKind"] == {
        "definition": list(bindings.DEFINITION_ARTIFACTS), "tool": list(bindings.TOOL_ARTIFACTS),
    }
    assert result["requiredLoadedArtifactsByProfile"] == {
        "get-contract-helper-runtime": list(bindings.DEFINITION_ARTIFACTS),
        "get-contract-runtime": list(bindings.TOOL_ARTIFACTS),
    }
    assert result["additionalReadRuntimeArtifactsForReturnedEnvelope"] == list(
        bindings.READ_RUNTIME_ARTIFACTS,
    )
    assert [row["path"] for row in result["sourceImportLinks"]] == [
        _TOOL, _TOOL_RUNTIME, _SDK_RUNTIME, _RUNTIME_FILES, _READ,
    ]
    assert set(bindings.DEFINITION_ARTIFACTS) < set(bindings.TOOL_ARTIFACTS)
    assert set(bindings.TOOL_ARTIFACTS) | set(bindings.READ_RUNTIME_ARTIFACTS) == set(
        bindings.COMPILED_HASHES,
    )
    for owner in result["sourceBindings"] + result["compiledBindings"]:
        assert len(owner["sha256"]) == 64
        assert all(anchor["line"] > 0 for anchor in owner["anchors"])


@pytest.mark.parametrize("tree,name", [
    *(('source', name) for name in bindings.SOURCE_HASHES),
    *(('compiled', name) for name in bindings.COMPILED_HASHES),
])
def test_reviewed_fixture_bytes_still_require_every_get_owner_declaration(
    tmp_path, monkeypatch, sources, compiled_sources, tree, name,
):
    values, anchors = (
        (sources, bindings.SOURCE_ANCHORS) if tree == "source"
        else (compiled_sources, bindings.COMPILED_ANCHORS)
    )
    values[name] = values[name].replace(anchors[name][0], "// removed native declaration")
    with pytest.raises(bindings.GetContractRuntimeBindingError):
        bindings.prepare_get_contract_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize("owner", ["tool", "runtime", "sdk", "final", "reader"])
@pytest.mark.parametrize("mutation", ["alias", "type", "owner", "duplicate"])
def test_even_reviewed_fixture_bytes_cannot_replace_the_public_read_import_chain(
    tmp_path, monkeypatch, sources, compiled_sources, owner, mutation,
):
    module, name, specifier = {
        "tool": (_TOOL, "executeMemoryReadResult", "./memory-read-tool.js"),
        "runtime": (_TOOL_RUNTIME, "readAgentMemoryFile", "openclaw/plugin-sdk/memory-core-host-runtime-files"),
        "sdk": (_SDK_RUNTIME, "readAgentMemoryFile", "../../packages/memory-host-sdk/src/runtime-files.js"),
        "final": (_RUNTIME_FILES, "readAgentMemoryFile", "./host/read-file.js"),
        "reader": (_READ, "buildMemoryReadResult", "./read-file-shared.js"),
    }[owner]
    if mutation == "alias":
        sources[module] = sources[module].replace(name, "Other as " + name, 1)
    elif mutation == "type":
        keyword = "import" if owner in {"tool", "reader"} else "export"
        sources[module] = sources[module].replace(keyword + " {", keyword + " type {", 1)
    elif mutation == "owner":
        sources[module] = sources[module].replace(specifier, "./unreviewed.js", 1)
    else:
        sources[module] += "\n" + sources[module]
    with pytest.raises(bindings.GetContractRuntimeBindingError):
        bindings.prepare_get_contract_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize("mutation", [
    "source-dirty", "source-digest", "commit", "nested-root", "source-symlink",
    "source-ancestor-symlink", "committed-bytes", "compiled-digest", "compiled-symlink",
    "compiled-ancestor-symlink", "compiled-missing",
])
def test_changed_or_unowned_get_source_and_release_artifacts_supply_no_identity(
    trees, monkeypatch, mutation,
):
    checkout, runtime = trees
    if mutation == "source-dirty":
        (checkout / _READ).write_text("// changed\n")
    elif mutation == "source-digest":
        monkeypatch.setattr(bindings, "SOURCE_HASHES", {**bindings.SOURCE_HASHES, _READ: "0" * 64})
    elif mutation == "commit":
        monkeypatch.setattr(bindings, "REFERENCE_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "packages"
    elif mutation in {
        "source-symlink", "source-ancestor-symlink", "compiled-symlink", "compiled-ancestor-symlink",
    }:
        file = checkout / _READ if mutation.startswith("source") else runtime / _COMPILED_READ
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
        (runtime / _COMPILED_READ).write_text("// changed compiled artifact\n")
    else:
        (runtime / _COMPILED_TOOL).unlink()
    with pytest.raises(bindings.GetContractRuntimeBindingError):
        bindings.prepare_get_contract_runtime_bindings(checkout, runtime)


@pytest.mark.parametrize("missing", ["source", "runtime"])
def test_missing_tree_supplies_no_get_runtime_evidence(trees, tmp_path, missing):
    checkout, runtime = trees
    if missing == "source":
        checkout = tmp_path / "absent-source"
    else:
        runtime = tmp_path / "absent-runtime"
    with pytest.raises(bindings.GetContractRuntimeBindingError):
        bindings.prepare_get_contract_runtime_bindings(checkout, runtime)


@pytest.fixture
def get_transport(transport):
    previous, original, case, result = transport
    config = deepcopy(original)
    package = config["packages"][0]
    existing = {item["path"] for item in package["files"]}
    for relative in bindings.COMPILED_HASHES:
        if relative in existing:
            continue
        raw = ("// Labelled memory-get transport artifact: " + relative + "\n").encode()
        file = Path(config["runtimeRoot"]) / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(raw)
        package["files"].append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest()})
    case["operation"] = "get-contract-runtime"
    case["input"] = {"kind": "tool", "steps": [
        {"params": {"path": "memory/a.md"}}, {"params": {}},
    ]}
    with ReleaseOracleExecution(config, previous.adapter_hashes) as execution:
        yield execution, config, case, result


def _get_trace(execution, config, artifacts):
    local = [
        {"event": "load", "pid": 111, "threadId": 0, "kind": "oracle",
         "path": str((ROOT / "equivalence" / name).resolve()),
         "sha256": execution._locals[str((ROOT / "equivalence" / name).resolve())]}
        for name in ("release-oracle.mjs", "get-contract-runtime.mjs", "search-contract-runtime.mjs")
    ]
    return [_bootstrap(execution, 0), *local,
            *[_load(config, relative, 0) for relative in artifacts]]


def _get_results(result):
    details = {"status": "ok", "path": "memory/a.md", "text": "A saved note.",
               "from": 1, "lines": 1, "opaque": {"values": [None, False, 0]}}
    envelope = {"content": [{"type": "text", "text": json.dumps(details, indent=2)}],
                "details": details, "opaqueEnvelopeMetadata": [None, "keep"]}
    error = {"name": "ToolInputError", "status": 400, "message": "path required"}
    requests = [{"pluginId": "labelled", "query": {"lookup": "memory/a.md"}}]
    raw = [{"kind": "tool", "indexManagerConstructed": False,
            "nativeEnvelopes": [{"index": 0, "result": deepcopy(envelope)},
                                {"index": 1, "error": deepcopy(error)}],
            "requests": deepcopy(requests)}]
    public = deepcopy(envelope)
    public["content"][0]["text"] = deepcopy(details)
    result["results"][0]["result"] = {"provider": "none", "steps": [
        {"result": public}, {"error": error},
    ], "requests": requests}
    return raw


def test_actual_get_transport_keeps_complete_raw_envelopes_without_inventing_an_index_worker(
    get_transport,
):
    execution, config, case, result = get_transport
    raw = _get_results(result)
    _trace(execution, 0, _get_trace(execution, config, bindings.COMPILED_HASHES))
    _evidence(execution, case, raw)
    observed = execution.collect(result, [case])
    assert observed["releaseTrace"]["protectedWorkerThreads"] == 0
    assert observed["releaseTrace"]["networkFetchDenied"] is True
    assert set(bindings.COMPILED_HASHES) <= {row["path"] for row in observed["releaseSources"]}
    assert observed["runtimeDiagnostics"][0]["rawSnapshots"] == raw
    assert observed["results"][0]["result"] == result["results"][0]["result"]


@pytest.mark.parametrize("missing", [*bindings.COMPILED_HASHES, "adapter", "bootstrap"])
def test_returned_get_envelope_requires_every_actual_get_and_lazy_read_owner(get_transport, missing):
    execution, config, case, result = get_transport
    raw = _get_results(result)
    events = _get_trace(execution, config, bindings.COMPILED_HASHES)
    if missing in bindings.COMPILED_HASHES:
        events = [event for event in events if event.get("path") != missing]
    elif missing == "adapter":
        events = [event for event in events if not event.get("path", "").endswith(
            "/get-contract-runtime.mjs",
        )]
    else:
        events = events[1:]
    _trace(execution, 0, events)
    _evidence(execution, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


def test_validation_error_before_read_does_not_claim_lazy_runtime_or_index_dispatch(get_transport):
    execution, config, case, result = get_transport
    raw = _get_results(result)
    raw[0]["nativeEnvelopes"] = [{"index": 0, **raw[0]["nativeEnvelopes"][1]}]
    raw[0]["nativeEnvelopes"][0]["index"] = 0
    raw[0]["requests"] = []
    public = result["results"][0]["result"]
    public["steps"] = public["steps"][1:]
    public["requests"] = []
    case["input"]["steps"] = [{"params": {}}]
    _trace(execution, 0, _get_trace(execution, config, bindings.TOOL_ARTIFACTS))
    _evidence(execution, case, raw)
    observed = execution.collect(result, [case])
    assert observed["releaseTrace"]["protectedWorkerThreads"] == 0
    assert not set(bindings.READ_RUNTIME_ARTIFACTS) & {
        row["path"] for row in observed["releaseSources"]
    }
    assert observed["runtimeDiagnostics"][0]["rawSnapshots"] == raw


def test_definition_profile_requires_no_read_runtime_or_index_worker(get_transport):
    execution, config, case, result = get_transport
    case["operation"] = "get-contract-helper-runtime"
    case["input"] = {"kind": "definition"}
    result["results"][0]["result"] = {"provider": "none", "definition": None}
    raw = [{"kind": "definition", "nativeEnvelopes": [], "requests": [],
            "indexManagerConstructed": False, "definition": None}]
    _trace(execution, 0, _get_trace(execution, config, bindings.DEFINITION_ARTIFACTS))
    _evidence(execution, case, raw)
    observed = execution.collect(result, [case])
    assert observed["releaseTrace"]["protectedWorkerThreads"] == 0
    assert _COMPILED_READ not in {row["path"] for row in observed["releaseSources"]}
    assert observed["runtimeDiagnostics"][0]["rawSnapshots"] == raw


@pytest.mark.parametrize("missing", bindings.DEFINITION_ARTIFACTS)
def test_definition_profile_still_requires_all_genuine_factory_owners(get_transport, missing):
    execution, config, case, result = get_transport
    case["operation"] = "get-contract-helper-runtime"
    case["input"] = {"kind": "definition"}
    result["results"][0]["result"] = {"provider": "none", "definition": None}
    events = _get_trace(execution, config, bindings.DEFINITION_ARTIFACTS)
    _trace(execution, 0, [event for event in events if event.get("path") != missing])
    _evidence(execution, case, [{"kind": "definition", "definition": None}])
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


@pytest.mark.parametrize("operation,kind", [
    ("get-contract-helper-runtime", "tool"),
    ("get-contract-runtime", "definition"),
    ("get-contract-runtime", "excerpt"),
    ("get-contract-helper-runtime", "prepare-arguments"),
])
def test_read_operations_cannot_select_the_factory_only_get_profile(get_transport, operation, kind):
    execution, _, case, result = get_transport
    case["operation"] = operation
    case["input"] = {"kind": kind}
    with pytest.raises(RuntimeOracleError, match="declared definition or whole-tool profile"):
        execution.collect(result, [case])


@pytest.mark.parametrize("mutation", [
    "no-snapshots", "no-native-envelopes", "missing-raw-step", "wrong-index", "wrong-error",
    "invalid-json-carrier", "details-differ", "public-omits-metadata", "requests-differ",
    "missing-requested-operation",
])
def test_missing_or_changed_raw_get_envelopes_cannot_authenticate_public_results(
    get_transport, mutation,
):
    execution, config, case, result = get_transport
    raw = _get_results(result)
    public = result["results"][0]["result"]
    if mutation == "no-snapshots":
        raw = []
    elif mutation == "no-native-envelopes":
        raw[0].pop("nativeEnvelopes")
    elif mutation == "missing-raw-step":
        raw[0]["nativeEnvelopes"].pop()
    elif mutation == "wrong-index":
        raw[0]["nativeEnvelopes"][0]["index"] = 1
    elif mutation == "wrong-error":
        raw[0]["nativeEnvelopes"][1]["error"]["name"] = "Error"
    elif mutation == "invalid-json-carrier":
        raw[0]["nativeEnvelopes"][0]["result"]["content"][0]["text"] = "not JSON"
    elif mutation == "details-differ":
        raw[0]["nativeEnvelopes"][0]["result"]["details"].pop("opaque")
    elif mutation == "public-omits-metadata":
        public["steps"][0]["result"].pop("opaqueEnvelopeMetadata")
    elif mutation == "requests-differ":
        raw[0]["requests"] = []
    else:
        raw[0]["nativeEnvelopes"].pop()
        public["steps"].pop()
    _trace(execution, 0, _get_trace(execution, config, bindings.COMPILED_HASHES))
    _evidence(execution, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


def _portable_results(execution, case, result):
    raw = _get_results(result)
    base = execution.evidence_directory / hashlib.sha256(case["id"].encode()).hexdigest()
    base = str(base / "native-get-fixture-labelled_123")
    case["input"]["normalizeFixturePaths"] = True
    raw[0]["fixtureBase"] = base
    envelope = raw[0]["nativeEnvelopes"][0]["result"]
    details = envelope["details"]
    details.update({
        "status": "error", "text": "", "code": "outside-workspace",
        "error": f"file is outside workspace root | Symlink escapes root ({base}/workspace): "
                 f"{base}/workspace/memory/outside",
        "opaque": {"full": base, "path": base + "/outside/file.md",
                   "unrelated": base + "-unrelated/file.md", "values": [None, False, 0]},
    })
    envelope["content"][0]["text"] = json.dumps(details)
    expected = deepcopy(details)
    expected["error"] = (
        "file is outside workspace root | Symlink escapes root ($FIXTURE/workspace): "
        "$FIXTURE/workspace/memory/outside"
    )
    expected["opaque"]["full"] = "$FIXTURE"
    expected["opaque"]["path"] = "$FIXTURE/outside/file.md"
    public = result["results"][0]["result"]
    public["steps"][0]["result"]["details"] = expected
    public["steps"][0]["result"]["content"][0]["text"] = deepcopy(expected)
    raw[0]["requests"][0]["query"]["lookup"] = base + "/workspace/memory/a.md"
    public["requests"][0]["query"]["lookup"] = "$FIXTURE/workspace/memory/a.md"
    return raw, base


def test_portable_get_alias_preserves_complete_diagnostics_and_authenticates_exact_owned_base(
    get_transport,
):
    execution, config, case, result = get_transport
    raw, base = _portable_results(execution, case, result)
    _trace(execution, 0, _get_trace(execution, config, bindings.COMPILED_HASHES))
    _evidence(execution, case, raw)
    observed = execution.collect(result, [case])
    assert observed["runtimeDiagnostics"][0]["rawSnapshots"] == raw
    details = observed["results"][0]["result"]["steps"][0]["result"]["details"]
    assert details["code"] == "outside-workspace"
    assert "Symlink escapes root ($FIXTURE/workspace)" in details["error"]
    assert details["opaque"]["unrelated"] == base + "-unrelated/file.md"
    assert base in raw[0]["nativeEnvelopes"][0]["result"]["content"][0]["text"]


@pytest.mark.parametrize("mutation", [
    "missing", "root", "temporary-parent", "relative", "other-case", "bad-leaf",
    "changed-error-words", "wire-only-matches-after-alias",
])
def test_fixture_identity_alias_cannot_hide_unowned_prefixes_or_changed_get_diagnostics(
    get_transport, mutation,
):
    execution, config, case, result = get_transport
    raw, base = _portable_results(execution, case, result)
    if mutation == "missing":
        raw[0].pop("fixtureBase")
    elif mutation == "root":
        raw[0]["fixtureBase"] = "/"
    elif mutation == "temporary-parent":
        raw[0]["fixtureBase"] = "/tmp"
    elif mutation == "relative":
        raw[0]["fixtureBase"] = "native-get-fixture-relative"
    elif mutation == "other-case":
        raw[0]["fixtureBase"] = str(execution.evidence_directory / "other-case"
                                    / "native-get-fixture-labelled_123")
    elif mutation == "bad-leaf":
        raw[0]["fixtureBase"] = str(Path(base).with_name("unowned-label"))
    elif mutation == "changed-error-words":
        public = result["results"][0]["result"]["steps"][0]["result"]
        public["details"]["error"] = "file is outside workspace root"
        public["content"][0]["text"]["error"] = "file is outside workspace root"
    else:
        # Full raw wire equality must be checked before path aliasing: an
        # actual base and its marker cannot repair a producer text/details mismatch.
        envelope = raw[0]["nativeEnvelopes"][0]["result"]
        envelope["details"]["error"] = envelope["details"]["error"].replace(base, "$FIXTURE")
    _trace(execution, 0, _get_trace(execution, config, bindings.COMPILED_HASHES))
    _evidence(execution, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])
