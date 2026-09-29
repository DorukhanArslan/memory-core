"""The literal parsers of scripts/extract_upstream_constants.py on inline TypeScript snippets.

Offline: the set-equality check against the checkout is
tests/integration/test_extracted_upstream_constants.py; these cover the parser helpers the
generated modules rely on (template literals with ternaries, nested templates, string arrays,
regex literals).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location(
        "extract_upstream_constants_unit", ROOT / "scripts" / "extract_upstream_constants.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_ternary_inside_a_template_becomes_a_field_and_its_literals(script):
    source = (
        "const guidance = hasSearch\n"
        "  ? `Run memory_search${\n"
        '      hasGet ? "; then memory_get" : ""\n'
        "    }. Say you checked.`\n"
        '  : "fallback";\n'
    )

    template, condition, consequent, alternate = script.ts_template_ternary_at(
        source, "Run memory_search", "clause"
    )

    assert template == "Run memory_search{clause}. Say you checked."
    assert (condition, consequent, alternate) == ("hasGet", "; then memory_get", "")
    assert template.format(clause=consequent) == "Run memory_search; then memory_get. Say you checked."


def test_a_ternary_branch_may_be_a_nested_template_with_mapped_fields(script):
    source = (
        "const action = overrides?.agentId\n"
        "  ? `Retry: run status --agent ${overrides.agentId}, then index --agent ${overrides.agentId}`\n"
        "  : \"Retry after a short wait; inspect this agent's index.\";\n"
        "const text = `Outer ${flag ? `inner ${name} {x}` : 'it\\'s plain'} end`;\n"
    )

    consequent, alternate = script.ts_ternary_at(
        source, "overrides?.agentId", {"overrides.agentId": "agent_id"}
    )
    template, condition, inner, plain = script.ts_template_ternary_at(
        source, "Outer ", "part", {"name": "name"}
    )

    assert consequent == "Retry: run status --agent {agent_id}, then index --agent {agent_id}"
    assert alternate == "Retry after a short wait; inspect this agent's index."
    assert (template, condition) == ("Outer {part} end", "flag")
    # Template branches keep format fields; literal braces are doubled in both branch kinds.
    assert inner == "inner {name} {{x}}"
    assert plain == "it's plain"


def test_template_parsing_still_refuses_an_unmapped_expression(script):
    source = "const text = `a ${unknown} b`;"

    with pytest.raises(ValueError, match="unmapped template expression 'unknown'"):
        script.ts_template_at(source, "a ${", {})


def test_a_template_with_no_or_two_ternaries_is_refused(script):
    none = "const text = `plain ${value}`;"
    two = 'const text = `two ${a ? "x" : "y"} and ${b ? "z" : "w"}`;'

    with pytest.raises(ValueError, match="0 ternaries"):
        script.ts_template_ternary_at(none, "plain", "field", {"value": "value"})
    with pytest.raises(ValueError, match="not a ternary expression: 'value'"):
        script.ts_template_ternary_at(none, "plain", "field")
    with pytest.raises(ValueError, match="2 ternaries"):
        script.ts_template_ternary_at(two, "two", "field")


def test_optional_chaining_and_nullish_coalescing_are_not_ternaries(script):
    source = 'const text = `n ${params.max ?? 10} ${a?.b ? "yes" : "no"}`;'

    template, condition, consequent, alternate = script.ts_template_ternary_at(
        source, "n ", "flag", {"params.max ?? 10": "max"}
    )

    assert template == "n {max} {flag}"
    assert (condition, consequent, alternate) == ("a?.b", "yes", "no")


def test_string_arrays_regex_literals_and_numbers_after_an_anchor(script):
    source = (
        'const CODES = new Set(["EAGAIN", "EWOULDBLOCK",\n  "EDEADLK"]);\n'
        "const MESSAGE = /Unknown system error -11\\b/i;\n"
        "const ERRNO = -11;\n"
        "retry({ attempts: 3, minDelayMs: 25 });\n"
    )

    assert script.ts_string_array_at(source, "const CODES = new Set(") == (
        "EAGAIN",
        "EWOULDBLOCK",
        "EDEADLK",
    )
    assert script.ts_regex_literal_at(source, "MESSAGE") == ("Unknown system error -11\\b", "i")
    assert script.ts_signed_integer_constant(source, "ERRNO") == -11
    assert script.ts_number_after(source, "attempts:") == 3
    with pytest.raises(ValueError, match="0 occurrences"):
        script.ts_number_after(source, "maxDelayMs:")


def test_inline_regex_tests_and_identity_code_sets(script):
    source = (
        "const isQuotaError = /insufficient_quota|quota|429/.test(normalizedReason);\n"
        "export function resolveMemoryIndexIdentityDiagnostic(\n"
        "  status: Status,\n"
        "): Diagnostic | undefined {\n"
        "  if (\n"
        '    identity.owner === "openclaw" &&\n'
        '    (identity.code === "provenance_version" || identity.code === "chunking_version")\n'
        "  ) {\n"
        '    return { code: identity.code, owner: "openclaw" };\n'
        "  }\n"
        '  if (identity.owner === "configuration" && (identity.code === "model")) {\n'
        '    return { code: identity.code, owner: "configuration" };\n'
        "  }\n"
        "  return undefined;\n"
        "}\n"
    )

    assert script.ts_regex_literal_at(source, "isQuotaError") == ("insufficient_quota|quota|429", "")
    assert script._identity_codes(source, "openclaw") == ("provenance_version", "chunking_version")
    assert script._identity_codes(source, "configuration") == ("model",)
    with pytest.raises(ValueError):
        script._identity_codes(source, "nobody")
