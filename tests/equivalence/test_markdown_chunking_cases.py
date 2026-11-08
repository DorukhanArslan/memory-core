"""Cheap fixture/adapter guards; real equivalence uses the pinned native runner."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from equivalence.markdown_chunking import build_markdown_chunking_cases, run_markdown_chunking


def test_chunk_cases_are_reproducible_and_cover_both_fixed_contracts():
    cases = build_markdown_chunking_cases()
    assert cases == build_markdown_chunking_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert len([case for case in cases if "-legacy-" in case["id"]]) == 13
    assert {case["requirement"] for case in cases} == {
        "chunking.markdown-boundaries", "chunking.utf16-cjk-budget",
    }


def test_chunk_adapter_preserves_input_and_reads_every_chunk_and_entry_range():
    def units(value):
        raw = value.encode("utf-16-le", "surrogatepass")
        return [int.from_bytes(raw[index:index + 2], "little") for index in range(0, len(raw), 2)]

    for case in build_markdown_chunking_cases():
        before = deepcopy(case)
        value = case["input"]
        content = ("".join(chr(unit) for unit in value["contentUnits"])
                   if "contentUnits" in value else value["content"])
        source = content.split("\n")
        result = run_markdown_chunking(value)
        json.dumps(result, allow_nan=False)
        assert case == before
        for chunk in result.get("chunks", []):
            assert 1 <= chunk["startLine"] <= chunk["endLine"] <= len(source)
            assert chunk["sourceLineCodeUnits"] == [
                units(line) for line in source[chunk["startLine"] - 1:chunk["endLine"]]]
            if chunk["entryStartLine"] is not None:
                assert chunk["entryStartLine"] <= chunk["startLine"]
                assert chunk["endLine"] <= chunk["entryEndLine"]
                assert chunk["entrySourceLineCodeUnits"] == [units(line) for line in source[
                    chunk["entryStartLine"] - 1:chunk["entryEndLine"]]]
            assert len(chunk["hash"]) == 64


def test_chunk_fixtures_include_literal_surrogates_and_exact_budget_neighbors():
    cases = {case["id"]: case for case in build_markdown_chunking_cases()}
    assert cases["markdown-chunking-literal-pair"]["input"]["contentUnits"] == [0xD840, 0xDC00] * 5
    for name in ("lone-high", "lone-low", "pair-across-edge", "weighted-tail",
                 "heading-bom", "heading-nel", "whitespace-bom", "whitespace-nel"):
        assert f"markdown-chunking-{name}" in cases
    assert all(f"markdown-chunking-ascii-budget-{length}" in cases for length in (31, 32, 33))


def test_raw_chunker_preserves_empty_and_whitespace_chunks():
    from memory_core.index.chunking import chunk_markdown

    for content in ("", "\n\n\n", " \t\n\r\n", "\ufeff", "\u0085\n\u001c"):
        chunks = chunk_markdown("MEMORY.md", content)
        assert len(chunks) == 1
        assert (chunks[0].text, chunks[0].start_line, chunks[0].end_line) == (
            content, 1, len(content.split("\n")),
        )


def test_per_entry_headings_use_ecmascript_whitespace():
    from memory_core.index.chunking import chunk_markdown

    chunks = chunk_markdown(
        "USER.md", "intro\n#\ufeffheading\n#\u0085continuation\n#\u001ccontinuation\n- entry",
        per_entry=True,
    )
    assert [(chunk.start_line, chunk.end_line) for chunk in chunks] == [(1, 1), (2, 4), (5, 5)]
    assert (chunks[-1].entry_start_line, chunks[-1].entry_end_line) == (5, 5)


def test_literal_surrogate_pairs_have_the_same_budget_and_text_as_astral_characters():
    from memory_core.index.chunking import chunk_markdown

    for literal in ("\ud840\udc00" * 5, "a" * 31 + "\ud83d\ude00b"):
        scalar = literal.encode("utf-16-le", "surrogatepass").decode("utf-16-le")
        assert chunk_markdown("MEMORY.md", literal, target_tokens=8, overlap_tokens=3) == (
            chunk_markdown("MEMORY.md", scalar, target_tokens=8, overlap_tokens=3))


def test_direct_cjk_helpers_weight_literal_pairs_and_never_split_them():
    from memory_core.index.cjk_chars import estimate_string_chars, truncate_utf16_safe

    assert estimate_string_chars("\ud840\udc00") == 16
    assert estimate_string_chars("\ud83d\ude00") == 2
    assert truncate_utf16_safe("a\ud840\udc00b", 2) == "a"
    assert truncate_utf16_safe("a\ud840\udc00b", 3) == "a𠀀"
    assert truncate_utf16_safe("a\ud800b", 2) == "a\ud800"


@pytest.mark.parametrize(("content", "expected"), [
    ("\ufeff\nretained", [(2, 2, "retained")]),
    ("retained\n\ufeff", [(1, 1, "retained")]),
    ("\u0085\nretained", [(1, 1, "\u0085"), (2, 2, "retained")]),
])
def test_reset_preparation_filters_both_sides_with_javascript_trim_and_keeps_source_lines(
    content, expected,
):
    from memory_core.index.sqlite_store import IndexSourceSnapshot, SQLiteMemoryStore

    entry = IndexSourceSnapshot(
        path="session.jsonl", source="sessions", text=content, hash="fixture", mtime=0, size=0,
        index_entry=SimpleNamespace(
            reset_recall_cutoff={"state": "valid", "cutoffLine": 2}, line_map=[1, 2],
        ),
    )
    chunks = SQLiteMemoryStore._prepare_source_chunks(entry, tokens=400, overlap=80)
    assert [(chunk.start_line, chunk.end_line, chunk.text) for chunk in chunks] == expected
