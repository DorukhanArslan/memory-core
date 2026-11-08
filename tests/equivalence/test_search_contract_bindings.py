"""Labelled source-provenance fixtures give no search-tool behavioral credit."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import search_contract_bindings as bindings


@pytest.fixture
def sources():
    result = {
        bindings._CITATIONS: (
            'import { stripMemoryAnnotationCarriers } from '
            '"openclaw/plugin-sdk/memory-core-host-engine-storage";\n'
            'import { parseAgentSessionKey } from '
            '"openclaw/plugin-sdk/memory-core-host-runtime-core";\n'
            'export function buildMemorySearchPresentation() {}\n'
            'export function resolveMemoryCitationsMode() {}\n'
            'export function shouldIncludeCitations() {}\n'
        ),
        bindings._STORAGE_SDK: (
            'export { stripMemoryAnnotationCarriers } from '
            '"../../packages/memory-host-sdk/src/engine-storage.js";\n'
        ),
        bindings._STORAGE: 'export { stripMemoryAnnotationCarriers } from "./host/internal.js";\n',
        bindings._INTERNAL: (
            'export { stripMemoryAnnotationCarriers } from "./curated-annotations.js";\n'
        ),
        bindings._ANNOTATIONS: 'export function stripMemoryAnnotationCarriers() {}\n',
        bindings._RUNTIME_SDK: 'export { parseAgentSessionKey } from "../routing/session-key.js";\n',
        bindings._ROUTING: 'export { parseAgentSessionKey } from "../sessions/session-key-utils.js";\n',
        bindings._SESSION_UTILS: (
            'export { parseAgentSessionKey } from '
            '"@openclaw/session-url-contract/session-key-normalization";\n'
        ),
        bindings._SESSION_NORMALIZATION: 'export function parseAgentSessionKey() {}\n',
        bindings._COMMON: (
            'import { asPositiveSafeInteger, asSafeIntegerInRange, parseStrictFiniteNumber } '
            'from "@openclaw/normalization-core/number-coercion";\n'
            'import { asNonArrayRecord } from "@openclaw/normalization-core/record-coerce";\n'
            'import { normalizeSingleOrTrimmedStringList } '
            'from "@openclaw/normalization-core/string-normalization";\n'
            'import { readSnakeCaseParamRaw } from "../../param-key.js";\n'
            'import { ToolAuthorizationError, ToolInputError } from "../tool-input-error.js";\n'
            'export function asToolParamsRecord() {}\n'
            'export function readNumberParam() {}\n'
            'export function readPositiveIntegerParam() {}\n'
            'export function readFiniteNumberParam() {}\n'
            'export function readToolStringParam(value: string): string;\n'
            'export function readToolStringParam(value: unknown): unknown;\n'
            'export function readToolStringParam(value: unknown) {}\n'
        ),
        bindings._NUMBERS: (
            'export function asPositiveSafeInteger() {}\n'
            'export function asSafeIntegerInRange() {}\n'
            'export function parseStrictFiniteNumber() {}\n'
        ),
        bindings._RECORDS: 'export function asNonArrayRecord() {}\n',
        bindings._STRING_LIST: 'export function normalizeSingleOrTrimmedStringList() {}\n',
        bindings._STRINGS: 'export function lowercasePreservingWhitespace() {}\n',
        bindings._PARAM_KEY: (
            'import { lowercasePreservingWhitespace } '
            'from "@openclaw/normalization-core/string-coerce";\n'
            'export function readSnakeCaseParamRaw() {}\n'
        ),
        bindings._ERRORS: (
            'export class ToolInputError {}\n'
            'export class ToolAuthorizationError {}\n'
        ),
        bindings._SHARED: (
            'import { DEFAULT_MEMORY_SEARCH_TIMEOUT_MS } from "./memory/search-deadline.js";\n'
            'export function buildMemorySearchUnavailableResult() {}\n'
        ),
        bindings._DEADLINE: 'export const DEFAULT_MEMORY_SEARCH_TIMEOUT_MS = 30000;\n',
    }
    assert set(result) == set(bindings._HASHES)
    return result


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
        "commit", "-qm", "Labelled search-contract binding fixture")
    monkeypatch.setattr(bindings, "_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "_HASHES", {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()
    })
    return root


@pytest.fixture
def checkout(tmp_path, monkeypatch, sources):
    return _checkout(tmp_path, monkeypatch, sources)


def test_projections_are_exact_and_direct_parsers_do_not_claim_whole_tool_execution(
    checkout, sources,
):
    before = deepcopy(sources)
    result = bindings.prepare_search_contract_bindings(checkout)
    assert sources == before
    assert result["kind"] == "native-search-contract-binding-projection"
    assert result["reference"] == {"tag": "v2026.9.9", "commit": bindings._COMMIT}
    assert result["allowedResolutions"] == [
        {"parent": bindings._CITATIONS,
         "specifier": "openclaw/plugin-sdk/memory-core-host-engine-storage",
         "target": bindings._ANNOTATIONS, "bindings": ["stripMemoryAnnotationCarriers"]},
        {"parent": bindings._CITATIONS,
         "specifier": "openclaw/plugin-sdk/memory-core-host-runtime-core",
         "target": bindings._SESSION_NORMALIZATION, "bindings": ["parseAgentSessionKey"]},
    ]
    assert len(result["projectionEvidence"]) == 2
    for row in result["projectionEvidence"]:
        assert row["facadeInitializationBypassed"] is True
        assert row["facadeExecutionVerified"] is False
        assert row["fullManagerExecutionVerified"] is False
        assert row["fullHostOrchestrationVerified"] is False
        assert row["chain"][0]["kind"] == "import"
        assert row["chain"][-1]["kind"] == "declaration"
    parser, presentation, unavailable = result["sourceOwnerEvidence"]
    assert parser["module"] == bindings._COMMON
    assert parser["facadeInitializationBypassed"] is False
    assert parser["originalOwnerExecutionRequired"] is True
    assert presentation["module"] == bindings._CITATIONS
    assert presentation["originalOwnerExecutionRequired"] is True
    assert unavailable["module"] == bindings._SHARED
    assert unavailable["nativeConstants"] == ["DEFAULT_MEMORY_SEARCH_TIMEOUT_MS"]
    assert unavailable["originalOwnerExecutionRequired"] is True
    assert unavailable["facadeInitializationBypassed"] is False
    assert unavailable["fullHostOrchestrationVerified"] is False
    overload, = [row for row in parser["chain"] if row["kind"] == "overload-declarations"]
    assert overload["binding"] == "readToolStringParam"
    assert len(overload["lines"]) == 3
    observed = {source["path"] for row in (
        *result["projectionEvidence"], *result["sourceOwnerEvidence"],
    ) for source in row["sources"]}
    assert observed == set(sources)


@pytest.mark.parametrize("mutation", [
    "citation-import-alias", "citation-import-type", "citation-import-extra",
    "citation-import-duplicate", "annotation-reexport-owner", "annotation-reexport-type",
    "session-reexport-owner", "session-owner-duplicate", "parser-import-alias",
    "parser-import-type", "parser-import-owner", "parser-declaration-missing",
    "number-declaration-duplicate", "overload-missing", "overload-duplicate",
    "error-class-not-exported", "key-import-owner", "timeout-import-owner",
    "timeout-constant-duplicate", "unavailable-owner-missing",
])
def test_even_reviewed_bytes_must_retain_each_original_owner_and_binding(
    tmp_path, monkeypatch, sources, mutation,
):
    citations, common = bindings._CITATIONS, bindings._COMMON
    if mutation == "citation-import-alias":
        sources[citations] = sources[citations].replace(
            "{ stripMemoryAnnotationCarriers }", "{ Other as stripMemoryAnnotationCarriers }",
        )
    elif mutation == "citation-import-type":
        sources[citations] = sources[citations].replace("import {", "import type {", 1)
    elif mutation == "citation-import-extra":
        sources[citations] = sources[citations].replace(
            "{ stripMemoryAnnotationCarriers }", "{ stripMemoryAnnotationCarriers, Unreviewed }",
        )
    elif mutation == "citation-import-duplicate":
        sources[citations] += sources[citations].splitlines()[0] + "\n"
    elif mutation == "annotation-reexport-owner":
        sources[bindings._INTERNAL] = sources[bindings._INTERNAL].replace(
            "curated-annotations.js", "unreviewed.js",
        )
    elif mutation == "annotation-reexport-type":
        sources[bindings._STORAGE] = sources[bindings._STORAGE].replace("export {", "export type {")
    elif mutation == "session-reexport-owner":
        sources[bindings._SESSION_UTILS] = sources[bindings._SESSION_UTILS].replace(
            "session-key-normalization", "unreviewed",
        )
    elif mutation == "session-owner-duplicate":
        sources[bindings._SESSION_NORMALIZATION] *= 2
    elif mutation == "parser-import-alias":
        sources[common] = sources[common].replace(
            "asPositiveSafeInteger,", "Other as asPositiveSafeInteger,",
        )
    elif mutation == "parser-import-type":
        sources[common] = sources[common].replace("import {", "import type {", 1)
    elif mutation == "parser-import-owner":
        sources[common] = sources[common].replace("number-coercion", "unreviewed")
    elif mutation == "parser-declaration-missing":
        sources[common] = sources[common].replace("export function readFiniteNumberParam", "function other")
    elif mutation == "number-declaration-duplicate":
        sources[bindings._NUMBERS] += 'export function parseStrictFiniteNumber() {}\n'
    elif mutation == "overload-missing":
        sources[common] = sources[common].replace(
            'export function readToolStringParam(value: string): string;\n', "",
        )
    elif mutation == "overload-duplicate":
        sources[common] += 'export function readToolStringParam(value: number): number;\n'
    elif mutation == "error-class-not-exported":
        sources[bindings._ERRORS] = sources[bindings._ERRORS].replace(
            "export class ToolInputError", "class ToolInputError",
        )
    elif mutation == "key-import-owner":
        sources[bindings._PARAM_KEY] = sources[bindings._PARAM_KEY].replace(
            "string-coerce", "unreviewed",
        )
    elif mutation == "timeout-import-owner":
        sources[bindings._SHARED] = sources[bindings._SHARED].replace(
            "search-deadline.js", "unreviewed.js",
        )
    elif mutation == "timeout-constant-duplicate":
        sources[bindings._DEADLINE] *= 2
    else:
        sources[bindings._SHARED] = sources[bindings._SHARED].replace(
            "export function buildMemorySearchUnavailableResult", "function other",
        )
    with pytest.raises(bindings.SearchContractBindingError):
        bindings.prepare_search_contract_bindings(_checkout(tmp_path, monkeypatch, sources))


@pytest.mark.parametrize("mutation", [
    "dirty", "digest", "commit", "nested-root", "symlink", "ancestor-symlink", "committed-bytes",
])
def test_changed_or_unowned_sources_cannot_authenticate_search_helpers(
    checkout, monkeypatch, mutation,
):
    if mutation == "dirty":
        (checkout / bindings._COMMON).write_text("// changed\n")
    elif mutation == "digest":
        monkeypatch.setattr(bindings, "_HASHES", {**bindings._HASHES, bindings._COMMON: "0" * 64})
    elif mutation == "commit":
        monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "packages"
    elif mutation in {"symlink", "ancestor-symlink"}:
        file = checkout / bindings._COMMON
        target = file if mutation == "symlink" else file.parent
        saved = target.with_name("saved-owner")
        target.rename(saved)
        target.symlink_to(saved, target_is_directory=mutation == "ancestor-symlink")
    else:
        original = bindings._git

        def forged_git(root, *args):
            return b"forged committed bytes" if args[0] == "show" else original(root, *args)

        monkeypatch.setattr(bindings, "_git", forged_git)
    with pytest.raises(bindings.SearchContractBindingError):
        bindings.prepare_search_contract_bindings(checkout)


def test_missing_reference_supplies_no_search_helper_evidence(tmp_path):
    with pytest.raises(bindings.SearchContractBindingError):
        bindings.prepare_search_contract_bindings(tmp_path / "absent")
