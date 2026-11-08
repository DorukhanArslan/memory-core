"""Labelled owner fixtures grant no deadline, cooldown or recovery behavior credit."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import deadline_partial_bindings as bindings


def _functions(*names):
    return "".join(f"export function {name}() {{}}\n" for name in names)


@pytest.fixture
def sources():
    return {
        bindings._DEADLINE: (
            'export const DEFAULT_MEMORY_SEARCH_TIMEOUT_MS = 30000;\n'
            + _functions("resolveMemorySearchAbortError", "createMemorySearchDeadlineError",
                         "isMemorySearchDeadlineError", "runMemorySearchWithDeadline")
        ),
        bindings._CONTROL: (
            'export const MEMORY_SEARCH_DEADLINE_CONTROL = Symbol("labelled");\n'
            + _functions("createMemorySearchDeadlineControl")
        ),
        bindings._CORPUS: (
            'import { createMemorySearchDeadlineError, DEFAULT_MEMORY_SEARCH_TIMEOUT_MS, '
            'isMemorySearchDeadlineError, resolveMemorySearchAbortError } '
            'from "./memory/search-deadline.js";\n'
            'import { createMemorySearchDeadlineControl } '
            'from "openclaw/plugin-sdk/memory-core-host-engine-storage";\n'
            'import { listMemoryCorpusSupplements } '
            'from "openclaw/plugin-sdk/memory-core-host-runtime-core";\n'
            'import { runTasksWithConcurrency } from "openclaw/plugin-sdk/concurrency-runtime";\n'
            'import { extractErrorCode, formatErrorMessage } from "openclaw/plugin-sdk/error-runtime";\n'
            + _functions("unavailableMemoryCorpus", "attemptMemoryCorpus", "runMemoryCorpusDeadline",
                         "composeMemoryCorpusMetadata", "searchMemoryCorpusSupplements",
                         "readMemoryCorpusSupplements")
        ),
        bindings._SHARED: (
            'import { DEFAULT_MEMORY_SEARCH_TIMEOUT_MS } from "./memory/search-deadline.js";\n'
            'import { normalizeLowercaseStringOrEmpty } '
            'from "openclaw/plugin-sdk/string-coerce-runtime";\n'
            + _functions("buildMemorySearchUnavailableResult")
        ),
        bindings._STORAGE_SDK: (
            'export { createMemorySearchDeadlineControl } '
            'from "../../packages/memory-host-sdk/src/engine-storage.js";\n'
        ),
        bindings._STORAGE: (
            'export { createMemorySearchDeadlineControl } from "./host/search-deadline-control.js";\n'
        ),
        bindings._RUNTIME_SDK: (
            'export { listMemoryCorpusSupplements } from "../plugins/memory-state.js";\n'
        ),
        bindings._STATE: _functions("listMemoryCorpusSupplements"),
        bindings._CONCURRENCY_SDK: (
            'export { runTasksWithConcurrency } from "../utils/run-with-concurrency.js";\n'
        ),
        bindings._CONCURRENCY: _functions("runTasksWithConcurrency"),
        bindings._ERROR_SDK: (
            'export { extractErrorCode, formatErrorMessage } from "../infra/errors.js";\n'
        ),
        bindings._ERRORS: (
            'import { extractErrorCode, formatErrorMessage as formatSharedErrorMessage } '
            'from "@openclaw/normalization-core/error-coercion";\n'
            'export { extractErrorCode } from "@openclaw/normalization-core/error-coercion";\n'
            'import { redactSensitiveText } from "../logging/redact.js";\n'
            + _functions("formatErrorMessage")
        ),
        bindings._ERROR_COERCION: _functions("extractErrorCode", "formatErrorMessage"),
        bindings._REDACT: _functions("redactSensitiveText"),
        bindings._STRING_SDK: (
            'export { normalizeLowercaseStringOrEmpty } '
            'from "../../packages/normalization-core/src/string-coerce.js";\n'
        ),
        bindings._STRINGS: _functions("normalizeLowercaseStringOrEmpty"),
    }


def _checkout(root: Path, monkeypatch, sources):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root).decode().strip()

    git("init", "-q")
    for relative, source in sources.items():
        file = root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source)
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Labelled deadline and recovery source owner fixture")
    monkeypatch.setattr(bindings, "_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "_HASHES", {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()
    })
    return root


@pytest.fixture
def checkout(tmp_path, monkeypatch, sources):
    assert set(sources) == set(bindings._HASHES)
    return _checkout(tmp_path, monkeypatch, sources)


def test_direct_deadline_owners_never_turn_formatting_provenance_into_timing_credit(
    checkout, sources,
):
    before = deepcopy(sources)
    result = bindings.prepare_deadline_partial_bindings(checkout)
    assert sources == before
    assert result["kind"] == "native-deadline-partial-source-owners"
    assert result["reference"] == {"tag": "v2026.9.9", "commit": bindings._COMMIT}
    assert result["allowedResolutions"] == result["projectionEvidence"] == []
    owners = result["sourceOwnerEvidence"]
    assert [row["module"] for row in owners] == [
        bindings._DEADLINE, bindings._CONTROL, bindings._CORPUS, bindings._SHARED,
    ]
    assert {source["path"] for row in owners for source in row["sources"]} == set(sources)
    for owner in owners:
        assert owner["originalOwnerExecutionRequired"] is True
        assert owner["facadeInitializationBypassed"] is False
        for flag in ("deadlineExecutionVerified", "cooldownStateExecutionVerified",
                     "fullToolExecutionVerified", "fullManagerExecutionVerified",
                     "fullHostOrchestrationVerified"):
            assert owner[flag] is False
    assert owners[1]["bindings"] == [
        "MEMORY_SEARCH_DEADLINE_CONTROL", "createMemorySearchDeadlineControl",
    ]
    alias, = [row for row in owners[2]["chain"] if "localBindings" in row]
    assert alias["bindings"] == ["extractErrorCode", "formatErrorMessage"]
    assert alias["localBindings"] == ["extractErrorCode", "formatSharedErrorMessage"]
    assert "does not establish timer" in owners[3]["note"]


@pytest.mark.parametrize("mutation", [
    "deadline-creator-not-exported", "deadline-classifier-duplicate", "control-symbol-missing",
    "corpus-owner-missing", "deadline-import-alias", "deadline-import-type", "deadline-import-extra",
    "storage-reexport-owner", "registry-reexport-owner", "concurrency-import-owner",
    "concurrency-owner-not-exported", "error-import-alias", "error-facade-owner",
    "error-normalizer-owner", "error-wrapper-alias", "error-wrapper-duplicate",
    "redactor-import-owner", "redactor-owner-missing", "shared-timeout-owner",
    "shared-string-alias", "string-facade-owner", "warning-owner-duplicate",
])
def test_even_reviewed_bytes_require_the_genuine_timer_control_registry_and_error_chains(
    tmp_path, monkeypatch, sources, mutation,
):
    deadline, corpus, errors, shared = (
        bindings._DEADLINE, bindings._CORPUS, bindings._ERRORS, bindings._SHARED,
    )
    if mutation == "deadline-creator-not-exported":
        sources[deadline] = sources[deadline].replace(
            "export function createMemorySearchDeadlineError", "function createMemorySearchDeadlineError",
        )
    elif mutation == "deadline-classifier-duplicate":
        sources[deadline] += _functions("isMemorySearchDeadlineError")
    elif mutation == "control-symbol-missing":
        sources[bindings._CONTROL] = sources[bindings._CONTROL].replace(
            "export const MEMORY_SEARCH_DEADLINE_CONTROL", "const other",
        )
    elif mutation == "corpus-owner-missing":
        sources[corpus] = sources[corpus].replace("export function attemptMemoryCorpus", "function other")
    elif mutation == "deadline-import-alias":
        sources[corpus] = sources[corpus].replace(
            "{ createMemorySearchDeadlineError,", "{ Other as createMemorySearchDeadlineError,",
        )
    elif mutation == "deadline-import-type":
        sources[corpus] = sources[corpus].replace("import {", "import type {", 1)
    elif mutation == "deadline-import-extra":
        sources[corpus] = sources[corpus].replace(
            "{ createMemorySearchDeadlineError,", "{ createMemorySearchDeadlineError, Unreviewed,",
        )
    elif mutation == "storage-reexport-owner":
        sources[bindings._STORAGE] = sources[bindings._STORAGE].replace("search-deadline-control.js", "other.js")
    elif mutation == "registry-reexport-owner":
        sources[bindings._RUNTIME_SDK] = sources[bindings._RUNTIME_SDK].replace("memory-state.js", "other.js")
    elif mutation == "concurrency-import-owner":
        sources[corpus] = sources[corpus].replace("concurrency-runtime", "other-runtime")
    elif mutation == "concurrency-owner-not-exported":
        sources[bindings._CONCURRENCY] = sources[bindings._CONCURRENCY].replace("export function", "function")
    elif mutation == "error-import-alias":
        sources[corpus] = sources[corpus].replace("{ extractErrorCode,", "{ Other as extractErrorCode,")
    elif mutation == "error-facade-owner":
        sources[bindings._ERROR_SDK] = sources[bindings._ERROR_SDK].replace("../infra/errors.js", "./other.js")
    elif mutation == "error-normalizer-owner":
        sources[errors] = sources[errors].replace("error-coercion", "other-coercion")
    elif mutation == "error-wrapper-alias":
        sources[errors] = sources[errors].replace("as formatSharedErrorMessage", "as Other")
    elif mutation == "error-wrapper-duplicate":
        sources[errors] += sources[errors].splitlines()[0] + "\n"
    elif mutation == "redactor-import-owner":
        sources[errors] = sources[errors].replace("logging/redact.js", "logging/other.js")
    elif mutation == "redactor-owner-missing":
        sources[bindings._REDACT] = "// missing redactor owner\n"
    elif mutation == "shared-timeout-owner":
        sources[shared] = sources[shared].replace("search-deadline.js", "other.js")
    elif mutation == "shared-string-alias":
        sources[shared] = sources[shared].replace(
            "{ normalizeLowercaseStringOrEmpty }", "{ Other as normalizeLowercaseStringOrEmpty }",
        )
    elif mutation == "string-facade-owner":
        sources[bindings._STRING_SDK] = sources[bindings._STRING_SDK].replace("string-coerce.js", "other.js")
    else:
        sources[shared] += _functions("buildMemorySearchUnavailableResult")
    with pytest.raises(bindings.DeadlinePartialBindingError):
        bindings.prepare_deadline_partial_bindings(_checkout(tmp_path, monkeypatch, sources))


@pytest.mark.parametrize("mutation", [
    "dirty", "digest", "commit", "nested-root", "symlink", "ancestor-symlink", "committed-bytes",
])
def test_changed_or_unowned_timer_source_supplies_no_deadline_recovery_evidence(
    checkout, monkeypatch, mutation,
):
    if mutation == "dirty":
        (checkout / bindings._DEADLINE).write_text("// changed\n")
    elif mutation == "digest":
        monkeypatch.setattr(bindings, "_HASHES", {**bindings._HASHES, bindings._CONTROL: "0" * 64})
    elif mutation == "commit":
        monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "extensions"
    elif mutation in {"symlink", "ancestor-symlink"}:
        file = checkout / bindings._CONTROL
        target = file.parent if mutation == "ancestor-symlink" else file
        saved = target.with_name("saved-owner")
        target.rename(saved)
        target.symlink_to(saved, target_is_directory=mutation == "ancestor-symlink")
    else:
        original = bindings._git

        def forged_git(root, *args):
            return b"forged committed bytes" if args[0] == "show" else original(root, *args)

        monkeypatch.setattr(bindings, "_git", forged_git)
    with pytest.raises(bindings.DeadlinePartialBindingError):
        bindings.prepare_deadline_partial_bindings(checkout)


def test_missing_reference_supplies_no_timer_or_recovery_provenance(tmp_path):
    with pytest.raises(bindings.DeadlinePartialBindingError):
        bindings.prepare_deadline_partial_bindings(tmp_path / "absent")
