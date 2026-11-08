"""Labelled direct-source fixtures authenticate owners, never memory-get behavior."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import get_contract_bindings as bindings


@pytest.fixture
def sources():
    return {
        bindings._COMMON: (
            'import { asPositiveSafeInteger, asSafeIntegerInRange, parseStrictFiniteNumber } '
            'from "@openclaw/normalization-core/number-coercion";\n'
            'import { asNonArrayRecord } from "@openclaw/normalization-core/record-coerce";\n'
            'import { readSnakeCaseParamRaw } from "../../param-key.js";\n'
            'import { ToolAuthorizationError, ToolInputError } from "../tool-input-error.js";\n'
            'export function asToolParamsRecord() {}\n'
            'export function readNumberParam() {}\n'
            'export function readPositiveIntegerParam() {}\n'
            'export function readToolStringParam(value: string): string;\n'
            'export function readToolStringParam(value: unknown): unknown;\n'
            'export function readToolStringParam(value: unknown) {}\n'
        ),
        bindings._ERRORS: (
            'export class ToolInputError {}\n'
            'export class ToolAuthorizationError {}\n'
        ),
        bindings._PARAM_KEY: (
            'import { lowercasePreservingWhitespace } '
            'from "@openclaw/normalization-core/string-coerce";\n'
            'export function readSnakeCaseParamRaw() {}\n'
        ),
        bindings._NUMBERS: (
            'import { normalizeOptionalString } from "./string-coerce.ts";\n'
            'export function asPositiveSafeInteger() {}\n'
            'export function asSafeIntegerInRange() {}\n'
            'export function parseStrictFiniteNumber() {}\n'
            'export function resolveIntegerOption() {}\n'
        ),
        bindings._RECORDS: 'export function asNonArrayRecord() {}\n',
        bindings._STRINGS: (
            'export function lowercasePreservingWhitespace() {}\n'
            'export function normalizeOptionalString() {}\n'
        ),
        bindings._UTF16: (
            'export function truncateUtf16Safe() {}\n'
            'export function sliceUtf16Safe() {}\n'
        ),
        bindings._READ_SHARED: (
            'import { resolveIntegerOption } from "@openclaw/normalization-core/number-coercion";\n'
            'import { truncateUtf16Safe } from "@openclaw/normalization-core/utf16-slice";\n'
            'export const DEFAULT_MEMORY_READ_LINES = 120;\n'
            'export const DEFAULT_MEMORY_READ_MAX_CHARS = 12000;\n'
            'export function buildMemoryReadResult() {}\n'
            'export function buildMemoryReadResultFromSlice() {}\n'
        ),
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
        "commit", "-qm", "Labelled memory-get source owner fixture")
    monkeypatch.setattr(bindings, "_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "_HASHES", {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()
    })
    return root


@pytest.fixture
def checkout(tmp_path, monkeypatch, sources):
    assert set(sources) == set(bindings._HASHES)
    return _checkout(tmp_path, monkeypatch, sources)


def test_direct_get_owners_have_no_projection_and_make_no_whole_tool_claim(checkout, sources):
    before = deepcopy(sources)
    result = bindings.prepare_get_contract_bindings(checkout)
    assert sources == before
    assert result["kind"] == "native-get-contract-source-owners"
    assert result["reference"] == {"tag": "v2026.9.9", "commit": bindings._COMMIT}
    assert result["allowedResolutions"] == []
    assert result["projectionEvidence"] == []
    parser, excerpt = result["sourceOwnerEvidence"]
    assert parser["module"] == bindings._COMMON
    assert parser["bindings"] == [
        "asToolParamsRecord", "readPositiveIntegerParam", "readToolStringParam",
    ]
    assert excerpt["module"] == bindings._READ_SHARED
    assert excerpt["bindings"] == [
        "buildMemoryReadResult", "buildMemoryReadResultFromSlice",
        "DEFAULT_MEMORY_READ_LINES", "DEFAULT_MEMORY_READ_MAX_CHARS",
    ]
    for owner in (parser, excerpt):
        assert owner["originalOwnerExecutionRequired"] is True
        assert owner["facadeInitializationBypassed"] is False
        assert owner["fullToolExecutionVerified"] is False
        assert owner["fullManagerExecutionVerified"] is False
        assert owner["fullHostOrchestrationVerified"] is False
    assert {row["path"] for owner in (parser, excerpt) for row in owner["sources"]} == set(sources)
    overload, = [row for row in parser["chain"] if row["kind"] == "overload-declarations"]
    assert len(overload["lines"]) == 3
    assert {row.get("binding") for row in excerpt["chain"]} >= {
        "resolveIntegerOption", "truncateUtf16Safe", "sliceUtf16Safe",
        "normalizeOptionalString",
    }


@pytest.mark.parametrize("mutation", [
    "parser-alias", "parser-type", "parser-extra", "parser-owner", "parser-duplicate",
    "parser-declaration-missing", "overload-missing", "overload-duplicate",
    "error-not-exported", "key-owner", "number-declaration-duplicate", "number-string-owner",
    "excerpt-number-owner", "excerpt-utf16-alias", "excerpt-utf16-type", "excerpt-utf16-extra",
    "excerpt-builder-missing", "excerpt-default-not-exported", "excerpt-default-duplicate",
    "utf16-slice-missing",
])
def test_even_reviewed_fixture_bytes_must_keep_native_parser_and_excerpt_owner_chains(
    tmp_path, monkeypatch, sources, mutation,
):
    common, read = bindings._COMMON, bindings._READ_SHARED
    if mutation == "parser-alias":
        sources[common] = sources[common].replace(
            "asPositiveSafeInteger,", "Other as asPositiveSafeInteger,", 1,
        )
    elif mutation == "parser-type":
        sources[common] = sources[common].replace("import {", "import type {", 1)
    elif mutation == "parser-extra":
        sources[common] = sources[common].replace(
            "asPositiveSafeInteger,", "asPositiveSafeInteger, Unreviewed,", 1,
        )
    elif mutation == "parser-owner":
        sources[common] = sources[common].replace("number-coercion", "unreviewed", 1)
    elif mutation == "parser-duplicate":
        sources[common] += sources[common].splitlines()[0] + "\n"
    elif mutation == "parser-declaration-missing":
        sources[common] = sources[common].replace(
            "export function readPositiveIntegerParam", "function other",
        )
    elif mutation == "overload-missing":
        sources[common] = sources[common].replace(
            'export function readToolStringParam(value: string): string;\n', "",
        )
    elif mutation == "overload-duplicate":
        sources[common] += 'export function readToolStringParam(value: number): number;\n'
    elif mutation == "error-not-exported":
        sources[bindings._ERRORS] = sources[bindings._ERRORS].replace(
            "export class ToolInputError", "class ToolInputError",
        )
    elif mutation == "key-owner":
        sources[bindings._PARAM_KEY] = sources[bindings._PARAM_KEY].replace("string-coerce", "other")
    elif mutation == "number-declaration-duplicate":
        sources[bindings._NUMBERS] += 'export function resolveIntegerOption() {}\n'
    elif mutation == "number-string-owner":
        sources[bindings._NUMBERS] = sources[bindings._NUMBERS].replace("string-coerce.ts", "other.ts")
    elif mutation == "excerpt-number-owner":
        sources[read] = sources[read].replace("number-coercion", "other")
    elif mutation == "excerpt-utf16-alias":
        sources[read] = sources[read].replace(
            "{ truncateUtf16Safe }", "{ Other as truncateUtf16Safe }",
        )
    elif mutation == "excerpt-utf16-type":
        sources[read] = sources[read].replace(
            "import { truncateUtf16Safe }", "import type { truncateUtf16Safe }",
        )
    elif mutation == "excerpt-utf16-extra":
        sources[read] = sources[read].replace(
            "{ truncateUtf16Safe }", "{ truncateUtf16Safe, Unreviewed }",
        )
    elif mutation == "excerpt-builder-missing":
        sources[read] = sources[read].replace("export function buildMemoryReadResult(", "function other(")
    elif mutation == "excerpt-default-not-exported":
        sources[read] = sources[read].replace("export const DEFAULT_MEMORY_READ_LINES", "const other")
    elif mutation == "excerpt-default-duplicate":
        sources[read] += 'export const DEFAULT_MEMORY_READ_MAX_CHARS = 12000;\n'
    else:
        sources[bindings._UTF16] = sources[bindings._UTF16].replace(
            "export function sliceUtf16Safe", "function other",
        )
    with pytest.raises(bindings.GetContractBindingError):
        bindings.prepare_get_contract_bindings(_checkout(tmp_path, monkeypatch, sources))


@pytest.mark.parametrize("mutation", [
    "dirty", "digest", "commit", "nested-root", "symlink", "ancestor-symlink", "committed-bytes",
])
def test_changed_or_unowned_sources_supply_no_get_helper_evidence(checkout, monkeypatch, mutation):
    if mutation == "dirty":
        (checkout / bindings._READ_SHARED).write_text("// changed\n")
    elif mutation == "digest":
        monkeypatch.setattr(bindings, "_HASHES", {
            **bindings._HASHES, bindings._READ_SHARED: "0" * 64,
        })
    elif mutation == "commit":
        monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    elif mutation == "nested-root":
        checkout = checkout / "packages"
    elif mutation in {"symlink", "ancestor-symlink"}:
        file = checkout / bindings._READ_SHARED
        target = file.parent if mutation == "ancestor-symlink" else file
        saved = target.with_name("saved-owner")
        target.rename(saved)
        target.symlink_to(saved, target_is_directory=mutation == "ancestor-symlink")
    else:
        original = bindings._git

        def forged_git(root, *args):
            return b"forged committed bytes" if args[0] == "show" else original(root, *args)

        monkeypatch.setattr(bindings, "_git", forged_git)
    with pytest.raises(bindings.GetContractBindingError):
        bindings.prepare_get_contract_bindings(checkout)


def test_missing_reference_supplies_no_get_helper_evidence(tmp_path):
    with pytest.raises(bindings.GetContractBindingError):
        bindings.prepare_get_contract_bindings(tmp_path / "absent")
