from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict


class MemoryCorpusResult(TypedDict, total=False):
    corpus: str
    path: str
    title: str
    kind: str
    score: float
    snippet: str
    content: str
    source: str


class MemoryCorpusSupplement(Protocol):
    def search(self, *, query: str, max_results: int, corpus: str) -> list[MemoryCorpusResult]:
        ...

    def get(self, *, path: str, corpus: str) -> MemoryCorpusResult | None:
        ...


@dataclass(frozen=True)
class StaticMemoryCorpusSupplement:
    results: list[MemoryCorpusResult]

    def search(self, *, query: str, max_results: int, corpus: str) -> list[MemoryCorpusResult]:
        del query, corpus
        return sort_corpus_results(self.results)[:max(1, max_results)]

    def get(self, *, path: str, corpus: str) -> MemoryCorpusResult | None:
        del corpus
        for result in self.results:
            if result.get("path") == path:
                return result
        return None


def sort_corpus_results(results: list[MemoryCorpusResult]) -> list[MemoryCorpusResult]:
    return sorted(results, key=lambda item: (-float(item.get("score", 0)), item.get("path", "")))
