# Feature Flags

`memory_core.FeatureFlags` is the central switchboard for optional memory-core
capabilities. The contract: **disabled means inert**. A disabled capability
must not call its backing provider, alter scores, or leave side effects.
`tests/unit/test_flags.py` enforces this with negative tests (for example,
`test_vector_disabled_never_calls_embedder`).

```python
from pathlib import Path

from memory_core import FeatureFlags, Memory, MemoryConfig

config = MemoryConfig(
    workspace_dir=Path("."),
    flags=FeatureFlags(vector_search=False),  # deterministic FTS-only mode
)
memory = Memory.from_workspace(".", config=config)  # no embedding provider needed
```

## Flags

| Flag | Default | Disabled behavior |
| --- | --- | --- |
| `vector_search` | `True` | FTS-only mode. Mirrors OpenClaw's `provider: "none"`: the embedder is never invoked (no provider required), keyword hits keep their full BM25-derived text score (no text-weight scaling), and when the strict `min_score` pass is empty the threshold relaxes to `0`. `memory_search` reports `provider: "none"`, `model: "fts-only"`. |
| `text_search` | `True` | Vector-only mode. Mirrors OpenClaw's non-hybrid path: raw vector scores, strict `min_score` filter, no keyword relaxation. |
| `mmr` | `False` | No MMR re-ranking of hybrid results. |
| `temporal_decay` | `False` | Scores are not decayed by memory-file age. |
| `subject_promotion` | `False` | `memory_core.live.SubjectConsolidation` raises `SubjectPromotionDisabledError` on every call before touching the subject workspace. memory-core extension (decision Q16), no upstream counterpart. Enable per subject with `SubjectMemory.open(..., flags=FeatureFlags(vector_search=False, subject_promotion=True))`. |
| `curated_memory_writes` | `True` | memory-core extension (Q16), not OpenClaw parity. `MemoryCurator` offers no tools and every curation call raises `CurationUnavailableError` before reading or writing any workspace file; `after_write` hooks never run. The host kit reads it from `memory.config`: `HostKit.tools()` lists no curation tools, the Memory Recall section names only the memory tools, and `HostKit.dispatch` answers a curation call with the `tool <name> is not available` payload, writing and reindexing nothing. The memory flush's `write` tool never depends on it. |

At least one of `vector_search` / `text_search` must stay enabled;
`FeatureFlags(vector_search=False, text_search=False)` raises `ValueError`.

The host kit's `dreaming_enabled` option (default `False`, upstream `dreaming.enabled`) is
a kit option, not a flag: with it off, `HostKit.dispatch` records no short-term recalls and
writes nothing under `memory/.dreams/` (docs/host_kit.md, decision Q8).

## Resolution rules

- `MemoryConfig.flags` is optional. When it is `None`, flags derive from the
  legacy config booleans (`mmr_enabled`, `temporal_decay_enabled`) so existing
  configs keep working.
- When `flags` is set explicitly, it wins over the legacy booleans.
- `MemoryConfig.effective_flags()` returns the resolved value; the SQLite store
  resolves it once at construction time.
- With `vector_search` enabled, constructing a store without an embedding
  provider raises `ValueError`. This is a deliberate fail-closed choice for
  explicit configuration errors; OpenClaw's runtime fallback chain
  (fallback provider activation, keyword-only degradation on embedding
  outage) is host-runtime behavior and out of package scope.
- `Memory.from_workspace()` runs the same check (plus the `agent_id` store-path
  check) before it creates anything, so a call that raises leaves no
  `MEMORY.md`, `memory/` or `.memory-core/` behind.
- The index records whether it was built FTS-only or with which provider and
  model. Reopening a store with `vector_search` switched (or another embedding
  model or endpoint) makes `memory_search` return the paused result until the
  store is reindexed (`docs/memory_search_tool.md`, Index identity).

## Parity notes

FTS-only semantics were aligned to the upstream OpenClaw search pipeline
(`extensions/memory-core/src/memory/manager.ts`, keyword-only branch and
`selectScoredResults` relaxation; provider identity fallback
`{ id: "none", model: "fts-only" }` in `manager-reindex-state.ts`).
