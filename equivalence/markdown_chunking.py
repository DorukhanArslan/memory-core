"""Reused Markdown inputs and thin adapters to the installed chunking owners.

The paired API is the raw chunker. In particular, reference whitespace chunks
are retained: the historical oracle filtered them and therefore could not prove
this API boundary. Content hashes use the store's actual Node-compatible owner;
MemoryChunk.id is a separate internal path/range identity, absent upstream here.
"""

from __future__ import annotations

from typing import Any


def _case(name: str, value: dict[str, Any], *, budget: bool = False) -> dict[str, Any]:
    requirement = "chunking.utf16-cjk-budget" if budget else "chunking.markdown-boundaries"
    return {
        "id": f"markdown-chunking-{name}",
        "operation": "markdown-chunking",
        "requirement": requirement,
        "covers": [f"{requirement}.outcomes", f"{requirement}.boundaries"],
        "input": {"path": "MEMORY.md", "tokens": 400, "overlap": 80, **value},
    }


def build_markdown_chunking_cases() -> list[dict[str, Any]]:
    """Reuse all 13 legacy oracle cases and the unit fixture, then probe edges.

    Inputs are copied from MARKDOWN_CHUNK_CASES in
    tests/integration/test_openclaw_ts_oracle.py and tests/unit/test_chunking.py;
    no historical expected outputs or algorithm implementation are imported.
    """
    legacy = [
        {"content": "# Long-Term Memory\n\n- Glacier storage keeps backups cold.",
         "tokens": 400, "overlap": 80, "perEntry": True},
        {"content": "# Long-Term Memory\n\n- Glacier storage keeps backups cold.",
         "tokens": 400, "overlap": 80},
        {"content": "\n".join(f"line {i} " + "word " * 12 for i in range(60)),
         "tokens": 20, "overlap": 5},
        {"content": "\n".join(f"line {i} " + "word " * 12 for i in range(60)),
         "tokens": 20, "overlap": 0},
        {"content": "x" * 500 + "\nshort\n" + "y" * 130, "tokens": 8, "overlap": 2},
        {"content": "漢字" * 100 + "\nabc\n" + "한국어 텍스트 " * 30,
         "tokens": 10, "overlap": 3},
        {"content": "😀" * 90 + "\nok", "tokens": 5, "overlap": 1},
        {"content": "- a\n- b\ncont\n\n## H\ntext\n- c " + "z" * 300 + "\n#nohead\n- d",
         "tokens": 10, "overlap": 2, "perEntry": True},
        {"content": "intro\n- a\n  more\n\n\n# Title\n- b", "tokens": 400,
         "overlap": 80, "perEntry": True},
        {"content": "", "tokens": 400, "overlap": 80},
        {"content": "\n\n\n", "tokens": 400, "overlap": 80, "perEntry": True},
        {"content": "a\r\nb\r\n- c", "tokens": 400, "overlap": 80, "perEntry": True},
        {"content": "\n".join(f"p{i} " + "w " * 30 for i in range(40)),
         "tokens": 16, "overlap": 4, "perEntry": True},
    ]
    cases = [_case(f"legacy-{index:02d}", value, budget=index in (5, 6))
             for index, value in enumerate(legacy)]
    cases.append(_case("unit-line-ranges", {
        "content": "# Title\none two three\nfour five six\n", "tokens": 3, "overlap": 1,
    }))
    for size in (31, 32, 33):
        cases.append(_case(f"ascii-budget-{size}", {
            "content": "a" * size + "\nb", "tokens": 8, "overlap": 0,
        }, budget=True))
    for name, character, counts in (
        ("common", "漢", (7, 8, 9)),
        ("rare-bmp", "㐀", (2, 3)),
        ("two-token", "ｶ", (3, 4, 5)),
        ("three-token-supplementary", "\U0001d360", (2, 3)),
        ("supplementary", "\U00020000", (1, 2, 3)),
    ):
        for count in counts:
            cases.append(_case(f"{name}-budget-{count}", {
                "content": character * count + "\ntail", "tokens": 8, "overlap": 2,
            }, budget=True))
    for name, content in (
        ("pair-before-edge", "a" * 30 + "😀" + "tail\nnext"),
        ("pair-across-edge", "a" * 31 + "😀" + "tail\nnext"),
        ("pair-after-edge", "a" * 32 + "😀" + "tail\nnext"),
        ("weighted-tail", "漢字😀abc" * 4 + "\nsmall\nnext line"),
    ):
        cases.append(_case(name, {
            "content": content, "tokens": 8, "overlap": 3,
        }, budget=True))
    # Integer code units transport literal surrogate inputs through the harness's
    # UTF-8 JSON request without replacing or dropping malformed code units.
    for name, units in (
        ("literal-pair", [0xD840, 0xDC00] * 5),
        ("literal-pair-at-edge", [97] * 31 + [0xD83D, 0xDE00, 98]),
        ("lone-high", [97] * 31 + [0xD800, 98, 10, 99]),
        ("lone-low", [97] * 31 + [0xDC00, 98, 10, 99]),
        ("reversed-surrogates", [0xDC00, 0xD800, 10, 97]),
        ("surrogate-tail", [97] * 25 + [0xD800, 0xD83D, 0xDE00, 10] + [98] * 15),
    ):
        cases.append(_case(name, {
            "contentUnits": units, "tokens": 8, "overlap": 3,
        }, budget=True))
    for name, content in (
        ("whitespace-ascii", " \t\n\r\n"),
        ("whitespace-bom", "\ufeff\n\u00a0"),
        ("whitespace-nel", "\u0085\n\u001c"),
        ("headings", "intro\n# title\n##\n####### no heading\n # indented\n- entry\n  child"),
        ("heading-bom", "intro\n#\ufeffheading\n- entry"),
        ("heading-nel", "intro\n#\u0085not-heading\n- entry"),
        ("heading-control", "intro\n#\u001cnot-heading\n- entry"),
        ("heading-levels", "intro\n" + "\n".join("#" * level + " h" for level in range(1, 7))),
    ):
        cases.append(_case(name, {"content": content, "perEntry": True}))
    for overlap in (-1, 0, 1, 80):
        cases.append(_case(f"overlap-{overlap}", {
            "content": "first line is fairly long\nshort\nlast line is fairly long",
            "tokens": 8, "overlap": overlap,
        }))
    for path in ("MEMORY.md", "USER.md"):
        cases.append(_case(f"oversized-entry-{path[:-3].lower()}", {
            "path": path,
            "content": "# section\n- " + "entry " * 30 + "\n  continuation\n- end\n",
            "tokens": 8, "overlap": 2, "perEntry": True,
        }))
    for name, value in (
        ("ascii", {"content": "a" * 33}),
        ("weights", {"content": "漢㐀ｶ\U0001d360\U00020000😀·"}),
        ("literal-supplementary", {"contentUnits": [0xD840, 0xDC00] * 3}),
        ("literal-emoji", {"contentUnits": [97, 0xD83D, 0xDE00, 98]}),
        ("malformed", {"contentUnits": [0xD800, 97, 0xDC00, 0xD83D, 0xDE00, 98]}),
        ("empty", {"content": ""}),
    ):
        cases.append(_case(f"helpers-{name}", {
            "kind": "helpers", **value,
            "limits": [-1, 0, 1, 2, 3, 4, 31, 32, 33, 80],
            "slices": [[0, 1], [0, 2], [1, 2], [1, 3], [-3, -1], [-2, None],
                       [0, None], [80, 90], [3, 1]],
        }, budget=True))
    return cases


def run_markdown_chunking(arguments: dict[str, Any]) -> dict[str, Any]:
    from memory_core.index.chunking import chunk_markdown
    from memory_core.index.sqlite_store import _text_hash

    content = ("".join(chr(unit) for unit in arguments["contentUnits"])
               if "contentUnits" in arguments else arguments["content"])
    source_lines = content.split("\n")
    # Return source readback as code units: scalar and literal-pair spellings
    # denote the same original JS string, while malformed units remain exact.
    def units(value: str) -> list[int]:
        encoded = value.encode("utf-16-le", "surrogatepass")
        return [int.from_bytes(encoded[index:index + 2], "little")
                for index in range(0, len(encoded), 2)]

    if arguments.get("kind") == "helpers":
        from memory_core.bootstrap._js import slice_utf16_safe
        from memory_core.index.cjk_chars import (
            estimate_string_chars,
            truncate_utf16_safe,
            utf16_length,
        )

        return {
            "estimatedChars": estimate_string_chars(content), "utf16Length": utf16_length(content),
            "truncatedCodeUnits": [units(truncate_utf16_safe(content, limit))
                                   for limit in arguments["limits"]],
            "slicedCodeUnits": [units(slice_utf16_safe(content, start, end))
                                for start, end in arguments["slices"]],
        }

    chunks = chunk_markdown(
        arguments.get("path", "MEMORY.md"), content,
        target_tokens=arguments.get("tokens", 400),
        overlap_tokens=arguments.get("overlap", 80),
        per_entry=arguments.get("perEntry", False),
    )
    results = []
    for chunk in chunks:
        results.append({
            "startLine": chunk.start_line, "endLine": chunk.end_line,
            "entryStartLine": chunk.entry_start_line, "entryEndLine": chunk.entry_end_line,
            "text": chunk.text, "hash": _text_hash(chunk.text),
            "sourceLineCodeUnits": [units(line) for line in
                                    source_lines[chunk.start_line - 1:chunk.end_line]],
            "entrySourceLineCodeUnits": ([units(line) for line in
                                          source_lines[chunk.entry_start_line - 1:chunk.entry_end_line]]
                                         if chunk.entry_start_line is not None else None),
        })
    return {"chunks": results}
