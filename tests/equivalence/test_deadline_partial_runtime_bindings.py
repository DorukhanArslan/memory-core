"""Labelled controlled-manager provenance fixtures grant no deadline behavior credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from equivalence import deadline_partial_runtime_bindings as bindings
from equivalence.runtime_oracle import ReleaseOracleExecution, ROOT, RuntimeOracleError, _OPERATIONS
from test_runtime_oracle_transport import (
    _bootstrap, _evidence, _load, _trace, transport as transport,
)


_TOOL = "extensions/memory-core/src/tools.ts"
_CORPUS = "extensions/memory-core/src/memory-corpus.ts"
_SHARED = "extensions/memory-core/src/tools.shared.ts"
_TOOL_RUNTIME = "extensions/memory-core/src/tools.runtime.ts"
_MANAGER_RUNTIME = "extensions/memory-core/src/memory/manager-runtime.ts"
_SDK_FILES = "src/plugin-sdk/memory-core-host-runtime-files.ts"
_RUNTIME_FILES = "packages/memory-host-sdk/src/runtime-files.ts"
_READ = "packages/memory-host-sdk/src/host/read-file.ts"
_COMPILED_TOOL = "dist/tools-DotaQGXh.mjs"
_COMPILED_MANAGER = "dist/extensions/memory-core/manager-runtime.js"
_COMPILED_CONTROL = "dist/search-deadline-control-CvwcTLrz.mjs"
_COMPILED_READ = "dist/read-file-CH8NQLbp.mjs"


_LINKS = (
    (_TOOL, "./memory-corpus.js", "attemptMemoryCorpus", "import"),
    (_TOOL, "./memory-search-tool-query.js", "buildPausedMemoryIndexUnavailableResult", "import"),
    (_TOOL, "./memory/search-deadline.js", "DEFAULT_MEMORY_SEARCH_TIMEOUT_MS", "import"),
    (_TOOL, "./tools.shared.js", "buildMemorySearchUnavailableResult", "import"),
    (_CORPUS, "./memory/search-deadline.js", "createMemorySearchDeadlineError", "import"),
    (_SHARED, "./memory/search-deadline.js", "DEFAULT_MEMORY_SEARCH_TIMEOUT_MS", "import"),
    (_TOOL_RUNTIME, "./memory/index.js", "getMemorySearchManager", "export"),
    (_MANAGER_RUNTIME, "./manager.js", "getMemoryIndexManagerRegistry", "import"),
    (_TOOL, "./memory-read-tool.js", "executeMemoryReadResult", "import"),
    (_TOOL_RUNTIME, "openclaw/plugin-sdk/memory-core-host-runtime-files", "readAgentMemoryFile", "export"),
    (_SDK_FILES, "../../packages/memory-host-sdk/src/runtime-files.js", "listMemoryFiles", "export"),
    (_RUNTIME_FILES, "./host/read-file.js", "readAgentMemoryFile", "export"),
    (_READ, "./read-file-shared.js", "buildMemoryReadResult", "import"),
)


@pytest.fixture
def sources():
    result = {
        name: "// Labelled native owner, never executed.\n" + "\n".join(anchors)
        for name, anchors in bindings.SOURCE_ANCHORS.items()
    }
    result[_TOOL] = (
        'import { attemptMemoryCorpus, composeMemoryCorpusMetadata, runMemoryCorpusDeadline, '
        'searchMemoryCorpusSupplements, unavailableMemoryCorpus } from "./memory-corpus.js";\n'
        'import { buildPausedMemoryIndexUnavailableResult, executeMemorySearchToolQuery } '
        'from "./memory-search-tool-query.js";\n'
        'import { DEFAULT_MEMORY_SEARCH_TIMEOUT_MS, resolveMemorySearchAbortError, '
        'runMemorySearchWithDeadline } from "./memory/search-deadline.js";\n'
        'import { buildMemorySearchUnavailableResult, createMemoryTool, '
        'getMemoryManagerContextWithPurpose, loadMemoryToolRuntime } from "./tools.shared.js";\n'
        'import { executeMemoryReadResult, executeWikiMemoryReadResult } from "./memory-read-tool.js";\n'
        + result[_TOOL]
    )
    result[_CORPUS] = (
        'import { createMemorySearchDeadlineError, DEFAULT_MEMORY_SEARCH_TIMEOUT_MS, '
        'isMemorySearchDeadlineError, resolveMemorySearchAbortError } '
        'from "./memory/search-deadline.js";\n' + result[_CORPUS]
    )
    result[_SHARED] = (
        'import { DEFAULT_MEMORY_SEARCH_TIMEOUT_MS } from "./memory/search-deadline.js";\n'
        + result[_SHARED]
    )
    result[_TOOL_RUNTIME] = (
        'export { getMemorySearchManager } from "./memory/index.js";\n'
        'export {\n  readAgentMemoryFile,\n  resolveMemoryBackendConfig,\n} '
        'from "openclaw/plugin-sdk/memory-core-host-runtime-files";\n'
    )
    result[_MANAGER_RUNTIME] = (
        'import { getMemoryIndexManagerRegistry, MemoryIndexManager } from "./manager.js";\n'
        + result[_MANAGER_RUNTIME]
    )
    result[_SDK_FILES] = (
        'export {\n  listMemoryFiles,\n  normalizeExtraMemoryPaths,\n  readAgentMemoryFile,\n'
        '  resolveMemoryBackendConfig,\n} '
        'from "../../packages/memory-host-sdk/src/runtime-files.js";\n'
    )
    result[_READ] = (
        'import { buildMemoryReadResult, DEFAULT_MEMORY_READ_LINES } from "./read-file-shared.js";\n'
        + result[_READ]
    )
    return result


@pytest.fixture
def compiled_sources():
    return {
        name: "// Labelled official artifact, never executed.\n" + "\n".join(anchors)
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
        "commit", "-qm", "Labelled controlled deadline runtime owner fixture")
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


def test_controlled_profile_discloses_constructor_override_and_genuine_timer_owner(trees, sources):
    before = deepcopy(sources)
    result = bindings.prepare_deadline_partial_runtime_bindings(*trees)
    assert sources == before
    assert result["kind"] == "official-release-memory-deadline-partial-tool-owner"
    assert result["referenceCommit"] == bindings.REFERENCE_COMMIT
    assert result["sourceBuildReproduced"] is False
    assert result["constructorSkipped"] is result["managerFixture"] is True
    assert result["fullManagerExecutionVerified"] is False
    assert result["fullHostOrchestrationVerified"] is False
    assert result["workerRequired"] is False
    assert {row["path"] for row in result["sourceBindings"]} == set(bindings.SOURCE_HASHES)
    assert {row["path"] for row in result["compiledBindings"]} == set(bindings.COMPILED_HASHES)
    assert result["requiredLoadedArtifacts"] == list(bindings.SEARCH_REQUIRED_LOADED_ARTIFACTS)
    assert result["requiredLoadedArtifactsByProfile"] == {
        "deadline-partial-runtime": list(bindings.SEARCH_REQUIRED_LOADED_ARTIFACTS),
        "deadline-partial-get-runtime": list(bindings.GET_REQUIRED_LOADED_ARTIFACTS),
    }
    assert result["entrypoints"] == {
        "tool": {"path": _COMPILED_TOOL, "export": "createMemorySearchTool"},
        "manager": {"path": _COMPILED_MANAGER, "export": "MemoryIndexManager",
                    "overriddenMethod": "get", "constructorSkipped": True},
        "deadlineControl": {"path": _COMPILED_CONTROL, "export": "n",
                            "originalBinding": "createMemorySearchDeadlineControl"},
        "getTool": {"path": _COMPILED_TOOL, "export": "createMemoryGetTool"},
        "getRead": {"path": _COMPILED_READ, "export": "t", "originalBinding": "readAgentMemoryFile"},
    }
    override, = result["overriddenMethods"]
    assert override["path"] == _COMPILED_MANAGER
    assert override["method"] == "get"
    assert override["static"] is override["controlledFixture"] is True
    assert "static get body do not execute" in override["behavior"]
    assert result["timingProfile"] == {
        "owner": "node:test", "timers": "mock.timers", "apis": ["Date", "setTimeout"],
        "performanceClock": "mock.method(performance, 'now', () => Date.now())",
        "customTimerImplementation": False,
    }
    assert result["profiles"]["deadline-partial-get-runtime"] == {
        "constructorSkipped": False, "managerFixture": False, "workerRequired": False,
        "realFileIO": True, "overriddenMethods": [], "indexManagerConstructed": False,
        "fullManagerExecutionVerified": False, "managerAcquisition": "not-required",
    }
    assert _COMPILED_MANAGER not in bindings.GET_REQUIRED_LOADED_ARTIFACTS
    assert [row["path"] for row in result["sourceImportLinks"]] == [
        row[0] for row in _LINKS
    ]
    for row in result["sourceBindings"] + result["compiledBindings"]:
        assert len(row["sha256"]) == 64
        assert all(anchor["line"] > 0 for anchor in row["anchors"])


@pytest.mark.parametrize("tree,name", [
    *(('source', name) for name in bindings.SOURCE_HASHES),
    *(('compiled', name) for name in bindings.COMPILED_HASHES),
])
def test_reviewed_fixture_bytes_require_every_deadline_cooldown_and_query_owner(
    tmp_path, monkeypatch, sources, compiled_sources, tree, name,
):
    values, anchors = (
        (sources, bindings.SOURCE_ANCHORS) if tree == "source"
        else (compiled_sources, bindings.COMPILED_ANCHORS)
    )
    values[name] = values[name].replace(anchors[name][0], "// missing original owner")
    with pytest.raises(bindings.DeadlinePartialRuntimeBindingError):
        bindings.prepare_deadline_partial_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize("module,specifier,name,kind", _LINKS)
@pytest.mark.parametrize("mutation", ["alias", "type", "owner"])
def test_reviewed_fixture_bytes_cannot_replace_native_tool_deadline_import_links(
    tmp_path, monkeypatch, sources, compiled_sources, module, specifier, name, kind, mutation,
):
    if mutation == "alias":
        sources[module] = sources[module].replace(name, "Other as " + name, 1)
    elif mutation == "owner":
        sources[module] = sources[module].replace(specifier, "./unreviewed.js", 1)
    else:
        end = sources[module].index('from "' + specifier + '"')
        start = sources[module].rfind(kind + " {", 0, end)
        sources[module] = sources[module][:start] + sources[module][start:].replace(
            kind + " {", kind + " type {", 1,
        )
    with pytest.raises(bindings.DeadlinePartialRuntimeBindingError):
        bindings.prepare_deadline_partial_runtime_bindings(
            *_trees(tmp_path, monkeypatch, sources, compiled_sources),
        )


@pytest.mark.parametrize("mutation", [
    "source-dirty", "source-digest", "commit", "nested-root", "source-symlink",
    "source-ancestor-symlink", "committed-bytes", "compiled-digest", "compiled-symlink",
    "compiled-ancestor-symlink", "compiled-missing",
])
def test_changed_source_or_unowned_artifact_cannot_authenticate_controlled_deadline_execution(
    trees, monkeypatch, mutation,
):
    checkout, runtime = trees
    if mutation == "source-dirty":
        (checkout / _CORPUS).write_text("// changed\n")
    elif mutation == "source-digest":
        monkeypatch.setattr(bindings, "SOURCE_HASHES", {**bindings.SOURCE_HASHES, _CORPUS: "0" * 64})
    elif mutation == "commit":
        monkeypatch.setattr(bindings, "REFERENCE_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "extensions"
    elif mutation in {
        "source-symlink", "source-ancestor-symlink", "compiled-symlink", "compiled-ancestor-symlink",
    }:
        file = checkout / _CORPUS if mutation.startswith("source") else runtime / _COMPILED_TOOL
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
        (runtime / _COMPILED_TOOL).write_text("// changed compiled artifact\n")
    else:
        (runtime / _COMPILED_MANAGER).unlink()
    with pytest.raises(bindings.DeadlinePartialRuntimeBindingError):
        bindings.prepare_deadline_partial_runtime_bindings(checkout, runtime)


@pytest.mark.parametrize("missing", ["source", "runtime"])
def test_missing_tree_supplies_no_controlled_deadline_owner_evidence(trees, tmp_path, missing):
    checkout, runtime = trees
    if missing == "source":
        checkout = tmp_path / "absent-source"
    else:
        runtime = tmp_path / "absent-runtime"
    with pytest.raises(bindings.DeadlinePartialRuntimeBindingError):
        bindings.prepare_deadline_partial_runtime_bindings(checkout, runtime)


@pytest.fixture
def deadline_transport(transport):
    previous, original, case, result = transport
    config = deepcopy(original)
    package = config["packages"][0]
    existing = {row["path"] for row in package["files"]}
    for relative in bindings.COMPILED_HASHES:
        if relative in existing:
            continue
        raw = ("// Labelled controlled deadline artifact: " + relative + "\n").encode()
        file = Path(config["runtimeRoot"]) / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(raw)
        package["files"].append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest()})
    case["operation"] = "deadline-partial-runtime"
    case["input"] = {"kind": "tool", "startMs": 1000, "supplements": [{"pluginId": "alpha"}],
                     "commands": [
                         {"op": "call", "id": "first", "params": {"query": "tea", "corpus": "all"}},
                         {"op": "barrier", "dispatches": {"memory": 1, "wiki:alpha": 1}},
                         {"op": "tick", "ms": 30_000},
                         {"op": "resolve", "lane": "memory", "invocation": 1, "value": []},
                         {"op": "resolve", "lane": "wiki:alpha", "invocation": 1, "value": []},
                         {"op": "barrier", "finished": {"memory": 1, "wiki:alpha": 1},
                          "settled": ["first"]},
                     ]}
    with ReleaseOracleExecution(config, previous.adapter_hashes) as execution:
        yield execution, config, case, result


def _deadline_trace(execution, config):
    local = [
        {"event": "load", "pid": 111, "threadId": 0, "kind": "oracle",
         "path": str((ROOT / "equivalence" / name).resolve()),
         "sha256": execution._locals[str((ROOT / "equivalence" / name).resolve())]}
        for name in ("release-oracle.mjs", "deadline-partial-runtime.mjs",
                     "deadline-partial.mjs", "search-contract-runtime.mjs")
    ]
    return [_bootstrap(execution, 0), *local,
            *[_load(config, relative, 0) for relative in bindings.COMPILED_HASHES]]


def _controlled_results(case, result):
    """Build labelled protocol evidence only; these values never establish timer parity."""
    memory_args = {"query": "tea", "options": {"signalPresent": True}}
    wiki_args = {"query": "tea"}
    reason = {"name": "Error", "message": "memory_search timed out after 30s"}
    memory = [
        {"event": "start", "invocation": 1, "time": 1000, "args": memory_args},
        {"event": "abort", "invocation": 1, "time": 31_000, "reason": reason},
        {"event": "fulfilled", "invocation": 1, "time": 31_000, "value": []},
    ]
    wiki = [
        {"event": "start", "invocation": 1, "time": 1000, "args": wiki_args},
        {"event": "fulfilled", "invocation": 1, "time": 31_000, "value": []},
    ]
    events = [
        {"lane": "memory", **memory[0]}, {"lane": "wiki:alpha", **wiki[0]},
        {"lane": "memory", **memory[1]}, {"lane": "memory", **memory[2]},
        {"lane": "wiki:alpha", **wiki[1]},
    ]
    details = {"results": [], "timedOut": True, "timeoutMs": 30_000,
               "opaque": {"values": [None, False, 0]}}
    envelope = {"content": [{"type": "text", "text": json.dumps(details, indent=2)}],
                "details": details, "opaqueEnvelopeMetadata": [None, "keep"]}
    public_envelope = deepcopy(envelope)
    public_envelope["content"][0]["text"] = deepcopy(details)
    steps = []
    for index, command in enumerate(case["input"]["commands"]):
        step = {**deepcopy(command), "time": 1000 if index < 2 else 31_000}
        if index in {1, 2, 5}:
            step.update(
                dispatchCounts={"memory": 1, "wiki:alpha": 1},
                activeCounts={"memory": 0 if index == 5 else 1,
                              "wiki:alpha": 0 if index == 5 else 1},
                abortCounts={"memory": 0 if index == 1 else 1, "wiki:alpha": 0},
                settledCalls=[] if index == 1 else ["first"],
            )
        steps.append(step)
    raw = [{
        "managerFixture": True, "constructorSkipped": True, "managerGetRestoredBeforeExit": True,
        "timerDriver": {"kind": "node-test-mock-timers", "apis": ["Date", "setTimeout"],
                        "dateReplaced": True, "setTimeoutReplaced": True, "clearTimeoutReplaced": True,
                        "initialDateNow": 1000, "initialPerformanceNow": 1000,
                        "performanceNowMatchesDateNow": True},
        "globalEvents": deepcopy(events),
        "nativeEnvelopes": [{"id": "first", "time": 31_000, "result": deepcopy(envelope)}],
        "managerGets": [], "statusReads": [], "closes": [],
        "clockSteps": deepcopy(steps), "clockObservationCuts": [2, 2, 3, 4, 5, 5],
        "clockOutcomeCuts": [0, 0, 1, 1, 1, 1], "timerClears": [], "clockClearCuts": [0] * 6,
    }]
    result["results"][0]["result"] = {
        "provider": "none", "calls": [{"id": "first", "result": public_envelope}],
        "memoryDispatches": [deepcopy(memory_args)], "wikiDispatches": {"alpha": [deepcopy(wiki_args)]},
        "lanes": {"memory": deepcopy(memory), "wiki:alpha": deepcopy(wiki)},
        "clockSteps": deepcopy(steps),
    }
    return raw


def test_controlled_deadline_transport_retains_full_calls_causal_counts_and_actual_timer_profile(
    deadline_transport,
):
    execution, config, case, result = deadline_transport
    raw = _controlled_results(case, result)
    _trace(execution, 0, _deadline_trace(execution, config))
    _evidence(execution, case, raw)
    observed = execution.collect(result, [case])
    assert observed["runtimeDiagnostics"][0]["rawSnapshots"] == raw
    assert observed["results"] == result["results"]
    assert observed["releaseTrace"]["protectedWorkerThreads"] == 0
    assert observed["releaseTrace"]["networkFetchDenied"] is True
    assert set(bindings.COMPILED_HASHES) <= {row["path"] for row in observed["releaseSources"]}
    # A declared controlled manager never relaxes genuine indexed-search proof.
    assert _OPERATIONS["search-contract-runtime"][2] is True
    assert _OPERATIONS["deadline-partial-runtime"][2] is False


@pytest.mark.parametrize("missing", [
    *bindings.SEARCH_REQUIRED_LOADED_ARTIFACTS, "adapter", "timer-owner", "carrier-owner", "bootstrap",
])
def test_controlled_execution_requires_every_native_owner_and_observed_timer_transport(
    deadline_transport, missing,
):
    execution, config, case, result = deadline_transport
    raw = _controlled_results(case, result)
    events = _deadline_trace(execution, config)
    if missing in bindings.COMPILED_HASHES:
        events = [event for event in events if event.get("path") != missing]
    elif missing == "bootstrap":
        events = events[1:]
    else:
        filename = {"adapter": "deadline-partial-runtime.mjs", "timer-owner": "deadline-partial.mjs",
                    "carrier-owner": "search-contract-runtime.mjs"}[missing]
        events = [event for event in events if not event.get("path", "").endswith("/" + filename)]
    _trace(execution, 0, events)
    _evidence(execution, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


@pytest.mark.parametrize("mutation", [
    "no-raw", "no-manager-fixture", "constructor-claim", "manager-not-restored",
    "custom-timers", "date-not-replaced", "settimeout-not-replaced", "cleartimeout-not-replaced",
    "wrong-performance-origin", "no-performance-coupling", "missing-call", "wrong-call-id",
    "duplicate-call", "wire-mismatch", "dropped-envelope-metadata", "missing-global-event",
    "changed-public-event", "changed-memory-args", "changed-wiki-args", "unknown-lane",
    "missing-clock-step", "wrong-command", "future-event-cut", "future-outcome-cut",
    "nonmonotone-event-cut", "forged-active-count", "forged-abort-count", "forged-settled-call",
])
def test_manufactured_timer_results_or_causal_provider_observations_are_rejected(
    deadline_transport, mutation,
):
    execution, config, case, result = deadline_transport
    raw = _controlled_results(case, result)
    public = result["results"][0]["result"]
    snapshot = raw[0]
    if mutation == "no-raw":
        raw = []
    elif mutation == "no-manager-fixture":
        snapshot["managerFixture"] = False
    elif mutation == "constructor-claim":
        snapshot["constructorSkipped"] = False
    elif mutation == "manager-not-restored":
        snapshot["managerGetRestoredBeforeExit"] = False
    elif mutation == "custom-timers":
        snapshot["timerDriver"]["kind"] = "hand-written-timeout-result"
    elif mutation in {"date-not-replaced", "settimeout-not-replaced", "cleartimeout-not-replaced"}:
        key = {"date-not-replaced": "dateReplaced", "settimeout-not-replaced": "setTimeoutReplaced",
               "cleartimeout-not-replaced": "clearTimeoutReplaced"}[mutation]
        snapshot["timerDriver"][key] = False
    elif mutation == "wrong-performance-origin":
        snapshot["timerDriver"]["initialPerformanceNow"] += 1
    elif mutation == "no-performance-coupling":
        snapshot["timerDriver"]["performanceNowMatchesDateNow"] = False
    elif mutation == "missing-call":
        snapshot["nativeEnvelopes"] = []
    elif mutation == "wrong-call-id":
        snapshot["nativeEnvelopes"][0]["id"] = "unrequested"
    elif mutation == "duplicate-call":
        snapshot["nativeEnvelopes"].append(deepcopy(snapshot["nativeEnvelopes"][0]))
    elif mutation == "wire-mismatch":
        snapshot["nativeEnvelopes"][0]["result"]["content"][0]["text"] = "{}"
    elif mutation == "dropped-envelope-metadata":
        public["calls"][0]["result"].pop("opaqueEnvelopeMetadata")
    elif mutation == "missing-global-event":
        snapshot["globalEvents"].pop(2)
    elif mutation == "changed-public-event":
        public["lanes"]["memory"][0]["time"] += 1
    elif mutation == "changed-memory-args":
        public["memoryDispatches"][0]["query"] = "different"
    elif mutation == "changed-wiki-args":
        public["wikiDispatches"]["alpha"][0]["query"] = "different"
    elif mutation == "unknown-lane":
        snapshot["globalEvents"][0]["lane"] = "unknown-provider"
    elif mutation == "missing-clock-step":
        snapshot["clockSteps"].pop()
    elif mutation == "wrong-command":
        snapshot["clockSteps"][2]["ms"] += 1
        public["clockSteps"][2]["ms"] += 1
    elif mutation == "future-event-cut":
        snapshot["clockObservationCuts"][2] = 99
    elif mutation == "future-outcome-cut":
        snapshot["clockOutcomeCuts"][2] = 99
    elif mutation == "nonmonotone-event-cut":
        snapshot["clockObservationCuts"][2] = 1
    else:
        key, value = {
            "forged-active-count": ("activeCounts", {"memory": 0, "wiki:alpha": 0}),
            "forged-abort-count": ("abortCounts", {"memory": 0, "wiki:alpha": 0}),
            "forged-settled-call": ("settledCalls", []),
        }[mutation]
        snapshot["clockSteps"][2][key] = deepcopy(value)
        public["clockSteps"][2][key] = deepcopy(value)
    _trace(execution, 0, _deadline_trace(execution, config))
    _evidence(execution, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


@pytest.mark.parametrize("kind", ["definition", "deadline", "control", "provenance"])
def test_controlled_manager_profile_cannot_substitute_for_direct_source_owners(deadline_transport, kind):
    execution, _, case, result = deadline_transport
    case["input"]["kind"] = kind
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


def _clear_barrier_results(case, result):
    case["input"]["commands"][-1]["timerClears"] = 2
    raw = _controlled_results(case, result)
    raw[0]["timerClears"] = [
        {"time": 1000, "handleType": "number", "handle": 1},
        {"time": 31_000, "handleType": "number", "handle": 2},
    ]
    raw[0]["clockClearCuts"] = [0, 0, 0, 0, 0, 2]
    raw[0]["clockSteps"][-1]["timerClearCount"] = 2
    result["results"][0]["result"]["clockSteps"][-1]["timerClearCount"] = 2
    return raw


def test_owner_settlement_barrier_uses_actual_timer_cancellation_observations(deadline_transport):
    execution, config, case, result = deadline_transport
    raw = _clear_barrier_results(case, result)
    _trace(execution, 0, _deadline_trace(execution, config))
    _evidence(execution, case, raw)
    observed = execution.collect(result, [case])
    assert observed["runtimeDiagnostics"][0]["rawSnapshots"] == raw
    assert observed["results"][0]["result"]["clockSteps"][-1]["timerClearCount"] == 2


@pytest.mark.parametrize("mutation", [
    "missing-clears", "missing-cuts", "future-cut", "nonmonotone-cut",
    "forged-count", "barrier-before-clear", "undeclared-count",
])
def test_provider_finish_cannot_replace_genuine_deadline_owner_cancellation_evidence(
    deadline_transport, mutation,
):
    execution, config, case, result = deadline_transport
    raw = _clear_barrier_results(case, result)
    public = result["results"][0]["result"]
    if mutation == "missing-clears":
        raw[0].pop("timerClears")
    elif mutation == "missing-cuts":
        raw[0].pop("clockClearCuts")
    elif mutation == "future-cut":
        raw[0]["clockClearCuts"][-1] = 3
    elif mutation == "nonmonotone-cut":
        raw[0]["clockClearCuts"][0] = 1
    elif mutation == "forged-count":
        raw[0]["clockSteps"][-1]["timerClearCount"] = 1
        public["clockSteps"][-1]["timerClearCount"] = 1
    elif mutation == "barrier-before-clear":
        raw[0]["clockClearCuts"][-1] = 1
    else:
        case["input"]["commands"][-1].pop("timerClears")
        raw[0]["clockSteps"][-1].pop("timerClears")
        public["clockSteps"][-1].pop("timerClears")
    _trace(execution, 0, _deadline_trace(execution, config))
    _evidence(execution, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


def _get_results(execution, case, result):
    """Labelled protocol fixture for a real-reader profile, never file-read parity proof."""
    case["operation"] = "deadline-partial-get-runtime"
    case["input"] = {
        "kind": "tool", "toolName": "memory_get", "startMs": 1000,
        "files": {"MEMORY.md": "A real-file fixture."},
        "commands": [{"op": "call", "id": "first", "params": {"path": "MEMORY.md"}},
                     {"op": "barrier", "settled": ["first"]}],
    }
    details = {"status": "ok", "path": "MEMORY.md", "text": "A real-file fixture.",
               "from": 1, "lines": 1}
    wire = {"content": [{"type": "text", "text": json.dumps(details)}], "details": details}
    decoded = deepcopy(wire)
    decoded["content"][0]["text"] = deepcopy(details)
    steps = [
        {**case["input"]["commands"][0], "time": 1000},
        {**case["input"]["commands"][1], "time": 1000, "dispatchCounts": {"memory": 0},
         "activeCounts": {"memory": 0}, "abortCounts": {"memory": 0}, "settledCalls": ["first"]},
    ]
    base = execution.evidence_directory / hashlib.sha256(case["id"].encode()).hexdigest()
    raw = [{
        "toolName": "memory_get", "managerFixture": False, "constructorSkipped": False,
        "managerAcquisition": "not-required", "indexManagerConstructed": False,
        "fixtureBase": str(base / "deadline-get-fixture-labelled_123"),
        "managerGets": [], "statusReads": [], "closes": [], "globalEvents": [],
        "nativeEnvelopes": [{"id": "first", "time": 1000, "result": wire}],
        "timerDriver": {"kind": "node-test-mock-timers", "apis": ["Date", "setTimeout"],
                        "dateReplaced": True, "setTimeoutReplaced": True, "clearTimeoutReplaced": True,
                        "initialDateNow": 1000, "initialPerformanceNow": 1000,
                        "performanceNowMatchesDateNow": True},
        "clockSteps": deepcopy(steps), "clockObservationCuts": [0, 0],
        "clockOutcomeCuts": [0, 1], "timerClears": [], "clockClearCuts": [0, 0],
    }]
    result["results"][0]["result"] = {
        "provider": "none", "calls": [{"id": "first", "result": decoded}],
        "memoryDispatches": [], "wikiDispatches": {}, "lanes": {"memory": []},
        "clockSteps": deepcopy(steps),
    }
    return raw


def _get_trace(execution, config):
    return [event for event in _deadline_trace(execution, config)
            if event.get("kind") != "release" or event["path"] in bindings.GET_REQUIRED_LOADED_ARTIFACTS]


def test_get_deadline_profile_uses_real_read_owners_without_controlled_manager_claim(deadline_transport):
    execution, config, case, result = deadline_transport
    raw = _get_results(execution, case, result)
    _trace(execution, 0, _get_trace(execution, config))
    _evidence(execution, case, raw)
    observed = execution.collect(result, [case])
    assert observed["releaseTrace"]["protectedWorkerThreads"] == 0
    assert _COMPILED_MANAGER not in {row["path"] for row in observed["releaseSources"]}
    assert observed["runtimeDiagnostics"][0]["rawSnapshots"] == raw


@pytest.mark.parametrize("missing", bindings.GET_REQUIRED_LOADED_ARTIFACTS)
def test_real_get_deadlines_require_every_actual_read_corpus_and_timer_owner(deadline_transport, missing):
    execution, config, case, result = deadline_transport
    raw = _get_results(execution, case, result)
    _trace(execution, 0, [event for event in _get_trace(execution, config) if event.get("path") != missing])
    _evidence(execution, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


@pytest.mark.parametrize("mutation", [
    "manager-fixture", "constructor-skip", "index-constructor", "manager-acquisition",
    "manager-get", "manager-status", "manager-close", "root-base", "other-case-base",
    "bad-base-leaf", "synthetic-memory-provider",
])
def test_real_get_deadline_profile_cannot_substitute_a_manager_or_unowned_files(
    deadline_transport, mutation,
):
    execution, config, case, result = deadline_transport
    raw = _get_results(execution, case, result)
    public = result["results"][0]["result"]
    snapshot = raw[0]
    if mutation == "manager-fixture":
        snapshot["managerFixture"] = True
    elif mutation == "constructor-skip":
        snapshot["constructorSkipped"] = True
    elif mutation == "index-constructor":
        snapshot["indexManagerConstructed"] = True
    elif mutation == "manager-acquisition":
        snapshot["managerAcquisition"] = "controlled-fixture"
    elif mutation in {"manager-get", "manager-status", "manager-close"}:
        key = {"manager-get": "managerGets", "manager-status": "statusReads", "manager-close": "closes"}[mutation]
        snapshot[key] = [{}]
    elif mutation == "root-base":
        snapshot["fixtureBase"] = "/tmp"
    elif mutation == "other-case-base":
        snapshot["fixtureBase"] = str(execution.evidence_directory / "other-case"
                                      / "deadline-get-fixture-labelled_123")
    elif mutation == "bad-base-leaf":
        snapshot["fixtureBase"] = str(Path(snapshot["fixtureBase"]).with_name("unowned"))
    else:
        args = {"query": "synthetic manager substitute"}
        event = {"lane": "memory", "event": "start", "invocation": 1, "time": 1000, "args": args}
        snapshot["globalEvents"] = [event]
        snapshot["clockObservationCuts"] = [1, 1]
        public["memoryDispatches"] = [deepcopy(args)]
        public["lanes"]["memory"] = [{key: value for key, value in event.items() if key != "lane"}]
        for steps in (snapshot["clockSteps"], public["clockSteps"]):
            steps[-1]["dispatchCounts"]["memory"] = 1
            steps[-1]["activeCounts"]["memory"] = 1
    _trace(execution, 0, _get_trace(execution, config))
    _evidence(execution, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])
