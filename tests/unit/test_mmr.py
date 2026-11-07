"""MMR ranking regressions for snippets outside the lexical token alphabet."""

from dataclasses import dataclass

import pytest

from memory_core.index.mmr import apply_mmr_to_hybrid_results


@dataclass(frozen=True)
class Hit:
    path: str
    score: float
    snippet: str


def hits(first: str, second: str, third: str, *, tied: bool = False) -> list[Hit]:
    return [
        Hit("memory/a.md", 1.0, first),
        Hit("memory/b.md", 1.0 if tied else 0.9, second),
        Hit("memory/c.md", 1.0 if tied else 0.8, third),
    ]


@pytest.mark.parametrize("first,second,third", [
    (" Привет ", "привет", "Пока"),
    ("\t😀\r\n", "😀", "😃"),
    ("\ufeff!!!\ufeff", "!!!", "???"),
    ("\u00a0Привет\u00a0", "привет", "Пока"),
    ("\u2003\u2028Привет\u2029\u3000", "привет", "Пока"),
    (" \t\r\n", "", "!!!"),
])
@pytest.mark.parametrize("lambda_", [0.0, 0.5])
def test_diversity_recognizes_trimmed_duplicate_empty_token_snippets(first, second, third, lambda_):
    original = hits(first, second, third)

    ranked = apply_mmr_to_hybrid_results(original, enabled=True, lambda_=lambda_)

    assert ranked == [original[0], original[2], original[1]]
    assert [hit.snippet for hit in original] == [first, second, third]
    assert all(any(item is hit for hit in original) for item in ranked)


@pytest.mark.parametrize("padding", ["\u0085", "\u001c", "\u200b"])
def test_python_only_whitespace_and_zero_width_space_do_not_collapse_distinct_snippets(padding):
    original = hits(padding + "Привет" + padding, "привет", "Пока")

    ranked = apply_mmr_to_hybrid_results(original, enabled=True, lambda_=0)

    assert ranked == original


def test_equal_score_ties_keep_first_seen_order_after_choosing_diverse_snippet():
    original = hits(" Привет ", "привет", "Пока", tied=True)

    assert apply_mmr_to_hybrid_results(original, enabled=True, lambda_=0) == [
        original[0], original[2], original[1],
    ]


def test_disabled_mmr_keeps_unmodified_input_order():
    original = hits(" Привет ", "привет", "Пока")

    ranked = apply_mmr_to_hybrid_results(original, enabled=False, lambda_=0)

    assert ranked == original
    assert ranked is not original
    assert all(item is hit for item, hit in zip(ranked, original, strict=True))
