from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict

from memory_core.bootstrap._js import locale_sort_key


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
class RegisteredMemoryCorpusSupplement:
    """A host-registered supplement with its real plugin identity.

    Registration lets the corpus coordinator reproduce native plugin-id order
    and failure attribution. Anonymous supplements remain supported separately.
    """

    plugin_id: str
    supplement: MemoryCorpusSupplement

    def search(self, *, query: str, max_results: int, corpus: str) -> list[MemoryCorpusResult]:
        return self.supplement.search(query=query, max_results=max_results, corpus=corpus)

    def get(self, *, path: str, corpus: str) -> MemoryCorpusResult | None:
        return self.supplement.get(path=path, corpus=corpus)


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
    """Score descending, then ``localeCompare`` on the path (OpenClaw
    ``extensions/memory-core/src/tools.shared.ts`` ``searchMemoryCorpusSupplements``)."""
    return sorted(
        results,
        key=lambda item: (-float(item.get("score", 0)), locale_sort_key(item.get("path", ""))),
    )
