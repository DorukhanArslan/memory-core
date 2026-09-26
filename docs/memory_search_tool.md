# memory_search Tool Contract

`memory_search` follows OpenClaw's memory-core tool
(`extensions/memory-core/src/tools.ts`, `tools.shared.ts`) at pin
`4c42815348ae336bf18e16ab049b6dbe0e4b8223`. This page covers what a host sees:
params, errors, result shapes, the deadline, the cooldown and index-identity
gating. The "Deviations" section lists where memory-core differs from upstream on
purpose; `docs/parity_matrix.md` records the evidence.

## Entry points

| Call | Use it for |
| --- | --- |
| `execute_memory_search_tool(config, store, params)` | The model's raw tool-call arguments (a mapping). |
| `memory_search(config, store, *, query, max_results=5, min_score=0.0, corpus="all")` | Python calls. `None` for a param means "omitted". |
| `Memory.search(...)` | The facade; same defaults as `memory_search`. |

`memory_search_tool_definition()` returns the upstream tool's name, verbatim
description and JSON schema as `{"name", "description", "parameters"}` (the
shape `MemoryCurator.tool_definitions()` uses; wrap it in the host's tool
format). The description tells the model to pass on the `warning` and `action`
of an unavailable or paused result, so hosts should send it unchanged.
`memory_get` has the same pair: `execute_memory_get_tool(config, params)` reads
`path` (required, JavaScript trim), `from` and `lines` (positive integers) and
raises `MemoryToolInputError` tagged `memory_get`, and
`memory_get_tool_definition()` returns its definition.

Both tools take the parsed argument mapping. A JSON string, or anything else
that is not a mapping, reads as `{}` (upstream `asToolParamsRecord`), so the
call fails with `query required` / `path required`; parse the model's argument
text first. (`MemoryCurator.dispatch` also accepts the JSON text.)

`execute_memory_search_tool` and `memory_search` also take `supplements=`,
`agent_session_key=` (a cooldown-key fallback) and `runtime_identity=` (`MEMORY_CORE_RUNTIME_IDENTITY` by default,
`OPENCLAW_COMPAT_RUNTIME_IDENTITY` for OpenClaw's exact texts).

## Params

Params are read before any search work, in this order
(`readStringParam` / `readPositiveIntegerParam` / `readFiniteNumberParam`,
`src/agents/tools/common.ts`):

| Param | Accepted | Error message |
| --- | --- | --- |
| `query` | a string that is not blank after trimming; the trimmed text is searched | `query required` |
| `maxResults` / `max_results` | a positive safe integer, or a strict numeric string (`"5"`, `"1e1"`, `" +5 "`, `"5.0"`) | `maxResults must be a positive integer` |
| `minScore` / `min_score` | a finite number, or a strict numeric string (`"0.3"`, `".5"`, `"-2e-1"`) | `minScore must be a finite number` |
| `corpus` | any string (trimmed); non-strings and blanks read as omitted | none |

- `True`/`False`, lists, `"0x10"`, `"1_000"`, full-width digits, `NaN` and
  `inf` are rejected. A missing key or `None` reads as omitted.
- The snake_case alias is read only when the camelCase key is absent:
  `{"maxResults": None, "max_results": 1}` means "maxResults omitted".
- Invalid input raises `MemoryToolInputError` (`status == 400`), the port of
  upstream `ToolInputError`. It is not a result payload. A host tool loop sends
  the model `error.to_tool_error()`, which is what OpenClaw's tool adapter
  sends (`src/agents/agent-tool-definition-adapter.ts`):

```python
from memory_core import MemoryToolInputError, execute_memory_search_tool

try:
    result = execute_memory_search_tool(config, store, {"query": "x", "maxResults": 0})
except MemoryToolInputError as error:
    result = error.to_tool_error()
# {"status": "error", "tool": "memory_search", "error": "maxResults must be a positive integer"}
```

### Blank queries

`memory_search` and the facade raise as well, so the change reaches every caller
built on them: `Memory.search("")`, `Memory.prepare_turn("  ")` and
`SubjectMemory.prepare_live_turn` with a blank `user_utterance` (a silent ASR
turn, for example) raise `MemoryToolInputError("query required")`. Before this
contract port they returned `{"results": [], "disabled": True, "error": "query
required"}` and recall injected nothing. `LangGraphMemoryRecall` still skips a
query that is empty after `str.strip()`. Hosts that can pass blank input must
skip recall for it or catch the error. `tests/unit/test_client.py` pins this;
whether the facade should return an empty recall instead is an open decision.

### Corpus

The tool has no corpus enum check. Upstream enforces the schema enum
(`memory|wiki|all|sessions`) in its agent loop, and in memory-core that loop is
the host's.

| `corpus` | Memory index | Supplements | Result mix |
| --- | --- | --- | --- |
| `memory` | memory files only | no | memory hits |
| `sessions` | session transcripts only | no | session hits |
| `wiki` | not searched | yes | supplement hits |
| `all` | every source | yes | balanced: up to `ceil(max/2)` per side, then backfill |
| omitted, blank or anything else | every source | no | memory and session hits |

## Results

Success:

```python
{"results": [...], "provider": "openai-compatible", "model": "text-embedding-3-small", "citations": "on"}
```

`provider`/`model` are absent when memory was not searched (`corpus=wiki`, or
`corpus=all` during a cooldown). FTS-only stores report `none` / `fts-only`.

Unavailable (a timeout, an error, or an active cooldown):

```python
{
    "results": [],
    "disabled": True,
    "unavailable": True,
    "error": "memory_search timed out after 15s",
    "warning": "Memory search is unavailable due to an embedding/provider error.",
    "action": "Check embedding provider configuration and retry memory_search.",
    "debug": {"warning": "...", "action": "...", "error": "memory_search timed out after 15s"},
}
```

`error` is the trimmed reason, or `memory search unavailable` if there is none.
The warning and action are chosen by the lower-cased reason:

| Reason matches | Warning / action |
| --- | --- |
| `insufficient_quota`, `quota` or `429` | provider quota exhausted / top up or switch provider |
| `missing node:sqlite`, `no such built-in module: node:sqlite` | runtime lacks SQLite (text from `RuntimeIdentity`) |
| anything else | embedding/provider error / check provider configuration |

Paused (the index identity is missing or mismatched): the same shape, with
`error` set to the identity reason, the fixed warning
`Tell the user: memory search is paused because the memory index was built with a different embedding provider/model/settings.`
and `RuntimeIdentity.memory_search_paused_action` as the action. Under the
memory-core identity that action is
`Tell the user to run: SQLiteMemoryStore.reindex(workspace).`
In OpenClaw compat mode it is upstream's text, which names two `openclaw` CLI
commands that both reindex. The memory-core text keeps upstream's "Tell the user"
frame and names only the reindex call (`index_identity()` only reports and never
lifts the pause). In memory-core the host owns reindexing, so the model relays a step
that an end user of the host app cannot take; whether the memory-core text should
address the host instead is an open decision.

## Deadline and cooldown

- Each search runs on a daemon worker thread with a 15 s deadline
  (`MEMORY_SEARCH_TOOL_TIMEOUT_MS`). This works from any thread and inside a
  running event loop. On timeout the caller gets the unavailable result
  (`memory_search timed out after 15s`) at once. Then the search's
  `CancellationSignal` is aborted: the open SQLite statement is interrupted and
  `SQLiteMemoryStore.search` stops at its next checkpoint (before and after the
  query embedding, and between FTS probes). A search only reads, so the
  abandoned worker leaves nothing half-written.
- A timeout or error starts a 60 s cooldown (`MEMORY_SEARCH_TOOL_COOLDOWN_MS`).
  Cooldowns are process-wide and keyed by the store's resolved path plus
  `config.agent_id ?? agent_session_key ?? "default"`
  (`memory_search_tool_cooldown_key`). While a cooldown is active, memory is
  not searched and the unavailable result repeats the recorded error.
- `corpus=wiki` never reads or records a cooldown. `corpus=all` still searches
  supplements during a cooldown, and records one only when the memory phase
  failed. A paused index records no cooldown.
- Only stores that open the same index file with the same agent id share a
  cooldown. Workspaces and live subjects that all use the default
  `agent_id="main"` have separate indexes, so one failing never pauses the
  others.
- Tests call `reset_memory_search_tool_cooldowns()`;
  `tests/conftest.py` does this around every test.

## Index identity

`SQLiteMemoryStore.reindex` stores what the index was built with as JSON under
the key `memory_index_meta_v1` in the `memory_index_meta` table: `model`
(`fts-only` without embeddings), `provider` (`none`), `providerKey` (the SHA-256
of the provider's cache-key JSON; `OpenAICompatibleEmbeddingProvider` includes
its base URL but never the API key), `sources`, `scopeHash`, `chunkTokens` 400,
`chunkOverlap` 80, `ftsTokenizer` `unicode61`, and `vectorDims` when embedded.

`store.index_identity()` compares this record with the current store. It
returns `{"status": "valid"}`, or the first failing check, with the reason
worded exactly as upstream's `resolveMemoryIndexIdentityState`:

1. `index metadata is missing`
2. `index was built for model <stored>, expected <current>`
3. `index was built for provider <stored>, expected <current>`
4. `index provider settings changed`
5. `index sources changed`
6. `index scope changed`
7. `index chunking changed`
8. `index vector dimensions are missing`
9. `index FTS tokenizer changed`

While the identity is not valid, `store.search` returns no hits and
`memory_search` returns the paused result. `reindex` writes fresh metadata.
Stores created before this table existed, and stores that were never
reindexed, read as `index metadata is missing` until their next reindex.
`Memory.from_workspace()` reindexes by default. Switching `vector_search`, the
embedding model or the endpoint therefore pauses search until the host
reindexes.

Upgrading: an index built before identity gating has no stored identity, so
every search on it returns the paused result until it is reindexed. Hosts that
open stores with `Memory.from_workspace(reindex=False)`, or keep a store open
across the upgrade, must call `SQLiteMemoryStore.reindex(workspace)` (`memory.store.reindex(memory.workspace)`
on the facade) once after upgrading.

## Deviations from upstream

- `store_path` stays configurable (default `<workspace>/.memory-core/<agent_id>.sqlite`,
  decision Q15). Upstream ignores `memorySearch.store.path` and uses
  `<stateDir>/agents/<agentId>/agent/openclaw-agent.sqlite`.
- The cooldown key adds the store's resolved path to upstream's
  `agentId ?? agentSessionKey ?? "default"` (`tools.ts:76-81`). Upstream's
  agent owns exactly one workspace and one index; in memory-core every
  `Memory.from_workspace()` store and every `SubjectMemory` workspace defaults
  to `agent_id="main"`, so an agent-only key would let one workspace's
  provider error pause memory search in all of them for 60 s.
- Omitted `maxResults`/`minScore` fall back to 5 / 0.0 (the memory-core facade
  defaults); upstream reads the agent config (6 / 0.35). The facade and
  `memory_search` default to `corpus="all"`, where upstream's default is an
  omitted corpus. So during a cooldown a default call returns an empty success
  instead of the unavailable result. Pass `corpus=None` for upstream's
  omitted-corpus behaviour.
- There is no sync lifecycle. Upstream rebuilds a missing identity on its next
  sync and runs a forced sync after an empty result; memory-core pauses until the
  host calls `reindex`.
- Error messages keep the explicit cause chain (`formatErrorMessage`) but skip
  upstream's token redaction. Redact tool results if provider errors can carry
  secrets.
- Not ported: provider identity aliases, `extraPaths` and multimodal indexing
  (the scope hash is fixed to upstream's defaults), the manager-context error
  and closed-store refresh branches (a memory-core store is built by the host), the
  QMD backend, session-visibility filtering, and the success `fallback`,
  `mode` and `debug` fields.
- Embedding HTTP calls are not interrupted. An abandoned worker finishes its
  current provider call, then stops at the next checkpoint.
- Under the memory-core identity, the SQLite warning and action wording is
  memory-core's own (upstream's names its Node runtime).

## Oracle coverage

Each of these runs the real TypeScript export at the pin
(`scripts/openclaw_oracle_runner.ts`, `tests/integration/test_openclaw_ts_oracle.py`):

| Operation | Fixtures |
| --- | --- |
| `memorySearch` with `rawParams` (through the real `toToolDefinitions` wrapper) | 18 invalid-param cases, 7 accepted coercion/alias/corpus cases |
| `memorySearchUnavailableResult` | 13 reasons and overrides (compat identity, exact) |
| `memorySearchToolSequence` | 17 tool calls in one process: cooldown record/replay/expiry, the wiki and all rules, the supplement-phase rule, a timeout |
| `memoryIndexIdentity` | 26 identity states, 5 provider-key, 4 source and 2 scope-hash cases |
| `memorySearch` with `embeddingModel` | end-to-end pause after a model change |
| `memoryToolDefinitions` | the `memory_search` and `memory_get` names, descriptions and schemas |
| `memoryGet` with `rawParams` (through the real `toToolDefinitions` wrapper) | 19 `memory_get` param cases |
