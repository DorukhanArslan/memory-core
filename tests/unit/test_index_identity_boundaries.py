"""Stored JSON versions must not bypass the native identity gate by coercion."""

from copy import deepcopy

import pytest

from equivalence.index_identity import build_index_identity_cases, run_index_identity


def _matching_params():
    case = next(case for case in build_index_identity_cases()
                if case["id"] == "identity-matching-vector")
    return deepcopy(case["input"])


@pytest.mark.parametrize(("field", "value", "code", "order"), [
    ("provenanceVersion", "0x0", "provenance_version", "older"),
    ("provenanceVersion", "0b10", "provenance_version", "newer"),
    ("chunkingVersion", "0o0", "chunking_version", "older"),
    ("chunkingVersion", [], "chunking_version", "older"),
    ("chunkingVersion", [["0"]], "chunking_version", "older"),
    ("chunkingVersion", [None], "chunking_version", "older"),
    ("chunkingVersion", [False], None, None),
    ("provenanceVersion", "inf", None, None),
    ("provenanceVersion", "0_0", None, None),
    ("provenanceVersion", "٠", None, None),
    ("provenanceVersion", "+0x0", None, None),
    ("provenanceVersion", "\u00850\u0085", None, None),
    ("provenanceVersion", "\ufeff0\u00a0", "provenance_version", "older"),
    ("provenanceVersion", "1e309", "provenance_version", "newer"),
])
def test_json_version_coercion_preserves_native_diagnostics(field, value, code, order):
    arguments = _matching_params()
    arguments["params"]["meta"][field] = value
    result = run_index_identity(arguments)

    if code is None:
        # Native relational comparisons with NaN are false, so these malformed
        # values continue through configuration checks rather than version gates.
        assert result == {"status": "valid"}
    else:
        assert result["status"] == "mismatched"
        assert result["code"] == code
        assert result["owner"] == "openclaw"
        assert result["versionOrder"] == order


def test_newer_version_still_takes_precedence_over_an_older_dimension():
    arguments = _matching_params()
    arguments["params"]["meta"].update(provenanceVersion="0x0", chunkingVersion="0b110")
    result = run_index_identity(arguments)
    assert result["code"] == "chunking_version"
    assert result["versionOrder"] == "newer"
