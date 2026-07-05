"""Parity tests for the extract_keywords port.

Expected outputs were captured from OpenClaw HEAD (4c42815348) by running
``extractKeywords`` from packages/memory-host-sdk/src/host/query-expansion.ts
on the same inputs.
"""

from __future__ import annotations

import pytest

from memory_core.index.keywords import extract_keywords


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("that thing we discussed about the API", ["discussed", "api"]),
        ("please find the glacier backups thing", ["glacier", "backups"]),
        ("what was the solution for the bug", ["solution", "bug"]),
        ("alpha project", ["alpha", "project"]),
        ("glacier", ["glacier"]),
        (
            "Doruk tercihleri neydi acaba",
            ["doruk", "tercihleri", "neydi", "acaba"],
        ),
        (
            "之前讨论的那个方案",
            ["之", "讨", "论", "个", "方", "案", "前讨", "讨论", "论的", "的那", "个方", "方案"],
        ),
        ("API를 어디서 논의했지", ["api를", "api", "어디서", "논의했지"]),
        ("バグの解決策", ["バグ", "解決策", "解決", "決策"]),
        (
            "ERR_CRM_409_CONFLICT retry limit 42",
            ["err", "crm", "conflict", "retry", "limit"],
        ),
    ],
)
def test_extract_keywords_matches_openclaw(query: str, expected: list[str]):
    assert extract_keywords(query) == expected


def test_extract_keywords_drops_stop_words_short_words_and_numbers():
    assert extract_keywords("is it in 2026 ok") == []
    assert extract_keywords("the a an 12 345") == []
    assert extract_keywords("go to DB") == []


def test_extract_keywords_deduplicates_preserving_order():
    assert extract_keywords("glacier backups glacier") == ["glacier", "backups"]
