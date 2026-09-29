# memory_search Tool Contract

`memory_search` follows OpenClaw's memory-core tool
(`extensions/memory-core/src/tools.ts`, `tools.shared.ts`, `memory-corpus.ts`,
`memory-search-tool-query.ts`) at release tag v2026.9.6 (`eb377ac59e6`; area 5 of
docs/upstream_port_v2026_9_6.md). This page covers what a host sees: params, errors,
result shapes, the per-corpus outcomes, the deadline, the cooldown and index-identity
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
format). The texts are upstream's `memory-tool-contract.ts` at v2026.9.6,
script-extracted: the description names the searched files (`MEMORY.md,
USER.md, Markdown files recursively under memory/`, plus `indexed session
transcripts` when sessions are searched: `search_sources=`, default memory and
sessions, as memory-core searches them) and tells the model to surface a
per-corpus warning and the `warning`/`action` of an unavailable or stale
result, so hosts should send it unchanged. Both schemas carry `minimum: 1`
where upstream has it and `additionalProperties: false`.
`memory_get` has the same pair: `execute_memory_get_tool(config, params)` reads
`path` (required, JavaScript trim), `from` and `lines` (positive integers;
blank reads as omitted) and `corpus` (`memory`, `wiki` or `all`) and raises
`MemoryToolInputError` tagged `memory_get`, and `memory_get_tool_definition()`
returns its definition, whose description explains `status` ok/not_found/error.

Both tools take the parsed argument mapping. A JSON string, or anything else
that is not a mapping, reads as `{}` (upstream `asToolParamsRecord`), so the
call fails with `query required` / `path required`; parse the model's argument
text first. (`MemoryCurator.dispatch` also accepts the JSON text.)

`execute_memory_search_tool` and `memory_search` also take:

- `supplements=`: compiled-wiki supplements searched for `corpus=wiki`/`all`;
- `search_sources=`: upstream's `searchSources`, what an omitted or `all` corpus searches
  and whether `corpus=sessions` is enabled; default memory and sessions, as memory-core
  indexes both (decision D1);
- `on_recall=`: a callback that receives the memory-corpus hits the result returns, when
  the memory search was ok or partial (`tools.ts:477-508`, where upstream records them as
  short-term recalls with dreaming enabled); an error it raises is ignored;
- `agent_session_key=`: accepted for upstream's `agentSessionKey`; since v2026.9.6 the
  cooldown is keyed by agent alone, and memory-core has no session-visibility filter or
  supplement context (decision D7), so nothing reads it;
- `runtime_identity=`: `MEMORY_CORE_RUNTIME_IDENTITY` by default,
  `OPENCLAW_COMPAT_RUNTIME_IDENTITY` for OpenClaw's exact texts.

## Params

Params are read before any search work, in this order
(`readStringParam` / `readPositiveIntegerParam` / `readFiniteNumberParam`,
`src/agents/tools/common.ts`; `readCorpusParam`, `extensions/memory-core/src/tools.ts:86-98`):

| Param | Accepted | Error message |
| --- | --- | --- |
| `query` | a string that is not blank after trimming; the trimmed text is searched | `query required` |
| `maxResults` / `max_results` | a positive safe integer, or a strict numeric string (`"5"`, `"1e1"`, `" +5 "`, `"5.0"`); a blank string reads as omitted | `maxResults must be a positive integer` |
| `minScore` / `min_score` | a finite number, or a strict numeric string (`"0.3"`, `".5"`, `"-2e-1"`); a blank string reads as omitted | `minScore must be a finite number` |
| `corpus` | `memory`, `wiki`, `all` or `sessions` (trimmed); non-strings and blanks read as omitted | `corpus must be one of: memory, wiki, all, sessions` |

- `True`/`False`, lists, `"0x10"`, `"1_000"`, full-width digits, `NaN` and
  `inf` are rejected. A missing key, `None` or a blank string (`""`, `"  "`, the
  ECMAScript whitespace set) reads as omitted (`isBlankParamValue`, since
  b22c36f1125 and aaf5ab910cb).
- The snake_case alias is read only when the camelCase key is absent:
  `{"maxResults": None, "max_results": 1}` means "maxResults omitted".
- Invalid input raises `MemoryToolInputError` (`status == 400`), the port of
  upstream `ToolInputError`. It is not a result payload. A host tool loop sends
  the model `error.to_tool_error()`, which is what OpenClaw's tool adapter
  sends (`src/agents/agent-tool-definition-adapter.ts`):

```python
from memory_core import MemoryToolInputError
from memory_core.tools.memory_search import execute_memory_search_tool

try:
    result = execute_memory_search_tool(config, store, {"query": "x", "maxResults": 0})
except MemoryToolInputError as error:
    result = error.to_tool_error()
# {"status": "error", "tool": "memory_search", "error": "maxResults must be a positive integer"}
```

### Blank queries

`memory_search` and the facade raise as well, so the change reaches every caller
built on them: `Memory.search("")` and `SubjectMemory.prepare_live_turn` with a
blank `user_utterance` (a silent ASR turn, for example) raise
`MemoryToolInputError("query required")`. Before this
contract port they returned `{"results": [], "disabled": True, "error": "query
required"}` and recall injected nothing. Hosts that can pass blank input must
skip recall for it or catch the error. `tests/unit/test_client.py` pins this;
whether the facade should return an empty recall instead is an open decision.

### Corpus

The corpus is checked against the tool's closed enum (`readCorpusParam`,
4b3ee5e7eb6): an unknown corpus fails closed with `corpus must be one of:
memory, wiki, all, sessions` instead of falling through to an unrestricted
search. Upstream throws a plain `Error` there; the model sees the same payload,
and memory-core raises `MemoryToolInputError`.

| `corpus` | Memory index | Supplements | Result mix |
| --- | --- | --- | --- |
| `memory` | memory files only | no | memory hits |
| `sessions` | session transcripts only (the not-enabled result when `search_sources` has no `sessions`) | no | session hits |
| `wiki` | not searched | yes | supplement hits, `corpora: [wiki]` |
| `all` | the search sources | yes | balanced: each corpus first gets up to `ceil(max/2)` of its own hits in its own order, the rest of the budget goes to the higher next hit, then the two streams merge by their heads; `corpora: [memory, wiki]` |
| omitted or blank | the search sources | no | memory and session hits |

The memory and supplement searches of `wiki`/`all` run at once, each as a corpus attempt
(`memory-corpus.ts`): `ok`, `unavailable` (with its error), `partial` (the deadline left
keyword-only memory hits) or `not-registered` (no supplement). `corpora` lists them memory
first; a failed attempt adds `<Memory|Wiki> corpus <outcome>: <error>` to `warning` and its
error to `error`, and a lone `not-registered` wiki warns that the requested corpus is not
covered. So under `all` a memory outage keeps the wiki hits, and a wiki outage keeps the
memory hits; only a memory-only call (`memory`, `sessions`, omitted) returns the unavailable
result below. Supplement hits merge score descending, then by path, cut to
`max(1, maxResults ?? 10)`.

## Results

Success:

```python
{"results": [...], "provider": "openai-compatible", "model": "text-embedding-3-small", "citations": "on"}
```

`provider`/`model` are absent when memory was not searched (`corpus=wiki`, or a failed
memory corpus under `corpus=all`). FTS-only stores report `none` / `fts-only`. `wiki` and
`all` add `corpora` (and `warning`/`error`/`timedOut`/`timeoutMs` when a corpus failed or
timed out). A partial search (the deadline ended the semantic leg after the keyword leg had
memory-file hits) returns those hits with `partial: True`, `timedOut`, `timeoutMs`,
`corpora: [{"corpus": "memory", "outcome": "partial", "error": ...}]` and the warning
`Memory corpus partial: memory_search timed out after 30s Only memory-file keyword matches
are included; ...`, and records no cooldown. A search on an index whose chunker is older
but whose content scope still matches runs keyword-only and adds `stale: True` with the
stale warning and action (below).

Unavailable (an error, a deadline without partial hits, an active cooldown, or
`corpus=sessions` when sessions are not searched):

```python
{
    "results": [],
    "disabled": True,
    "unavailable": True,
    "timedOut": True,          # the tool's own deadline only
    "timeoutMs": 30000,
    "error": "memory_search timed out after 30s",
    "warning": "Memory search did not finish within its time limit.",
    "action": "Retry memory_search after a short wait: ...",
    "debug": {"warning": "...", "action": "...", "error": "memory_search timed out after 30s"},
}
```

`error` is the trimmed reason, or `memory search unavailable` if there is none.
The warning and action are chosen in upstream's order (`tools.shared.ts:92-150`):

| Case | Warning / action |
| --- | --- |
| code `SESSION_CANONICAL_KEY_MIGRATION_REQUIRED` | the session catalog needs canonical-key migration (action from `RuntimeIdentity`; memory-core never raises the code itself) |
| reason matches `insufficient_quota`, `quota` or `429` | provider quota exhausted / top up or switch provider |
| reason matches `missing node:sqlite`, `no such built-in module: node:sqlite` | runtime lacks SQLite (text from `RuntimeIdentity`) |
| the tool's own deadline (a flag carried from the deadline error, never its text: a provider may emit the same words) | `Memory search did not finish within its time limit.` / retry after a short wait; with an agent id the action names that agent's index (`RuntimeIdentity.memory_search_deadline_agent_action`) |
| anything else | embedding/provider error / check provider configuration |

Paused (the index identity is missing or mismatched): the same shape, with the error,
warning and action of upstream's index search diagnostic
(`resolveMemoryIndexSearchDiagnostic`, packages/memory-host-sdk/src/host/types.ts:313-360):
`error` is the identity reason, the warning is `Tell the user: memory search is paused
because <cause>.` (the configuration no longer matches the index, the metadata is missing,
this version changed the index format, or the reason itself for a newer index) and the
action is `Tell the user to run: <rebuild guidance>` (`Tell the user to upgrade ... or
reindex explicitly: ...` for a newer index). The rebuild guidance is the rebuild command
plus whether it calls an embedding provider (`Rebuilding uses keyword indexing only and
does not call an embedding provider.` for provider `none`, else `Rebuilding may call the
configured embedding provider and can incur provider cost.`). Under the memory-core identity
the command is `SQLiteMemoryStore.reindex(workspace)`; in OpenClaw compat mode it is
`openclaw memory status --index --agent <id>`. Under `corpus=all` a paused memory corpus is
`unavailable` in `corpora`, the paused warning follows the corpus warning and the paused
action is the result's `action`; the wiki hits stay. In memory-core the host owns
reindexing, so the model relays a step that an end user of the host app cannot take;
whether the memory-core text should address the host instead is an open decision (D4).

The live recall helper keeps only `results`: `SubjectMemory.prepare_live_turn`
drops the `disabled`, `warning` and `action` of an unavailable or paused result,
so recall injects nothing and nobody is told. The helper is adapter-only (no
upstream counterpart; `LangGraphMemoryRecall`, which did the same, was removed in
0.2.0, pending Doruk's confirmation as L1 in docs/integrations/langgraph.md). The upstream
shape is
the model's own `memory_search` call through `HostKit.tools()` and
`HostKit.dispatch`, which return the whole payload; a host that needs the signal
without the kit calls `Memory.search` (or `execute_memory_search_tool`) and
checks `disabled` (and, under `corpus=all`, the memory entry of `corpora`).

## Deadline and cooldown

- A call runs under one 30 s deadline (`MEMORY_SEARCH_TOOL_TIMEOUT_MS`, upstream's
  `DEFAULT_MEMORY_SEARCH_TIMEOUT_MS` since d46f9ebf2b2 #147702); each corpus task runs on a
  daemon worker thread and races it, the supplements under a deadline of their own. This
  works from any thread and inside a running event loop. When the time is up the task fails
  with `memory_search timed out after 30s` at once, and the search's `CancellationSignal`
  is aborted: the open SQLite statement is interrupted and `SQLiteMemoryStore.search` stops
  at its next checkpoint (before and after the query embedding, and between FTS probes). A
  search only reads, so the abandoned worker leaves nothing half-written.
- With an embedding provider the store runs its keyword leg before embedding the query and
  publishes the memory-file keyword hits (`on_partial_results`); a deadline after that makes
  the memory corpus `partial` instead of unavailable.
- A memory failure (an error, or the deadline without partial hits) starts a 60 s cooldown
  (`MEMORY_SEARCH_TOOL_COOLDOWN_MS`), for any corpus; a supplement failure never does.
  Cooldowns are process-wide, keyed by the store's resolved path plus `config.agent_id`
  (`memory_search_tool_cooldown_key`), and hold the failure (`error`, `deadline`, `code`)
  and the configuration that recorded it (`memory_search_tool_config_key`: the
  `MemoryConfig` and the store's provider identity, for upstream's runtime config key); a
  read under another configuration drops the entry. While a cooldown is active, memory is
  not searched and the unavailable result (or the memory corpus under `all`) repeats the
  recorded failure, deadline flag included.
- `corpus=wiki` never reads or records a cooldown. A paused index records no cooldown.
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
`chunkOverlap` 80, `chunkingVersion`, `ftsTokenizer` `unicode61`, `provenanceVersion`, and
`vectorDims` when embedded (upstream's `nextMeta` key order).

`store.index_identity()` compares this record with the current store. It
returns `{"status": "valid"}`, or the first failing check with upstream's reason, `code`
and `owner` (`resolveMemoryIndexIdentityState` at v2026.9.6, 28630a9a650 #114819):

| Order | Reason | `code` / `owner` |
| --- | --- | --- |
| 1 | `index metadata is missing` | `metadata_missing` / `openclaw` |
| 2 | the index was written by a newer version (provenance or chunking) | `provenance_version` or `chunking_version` / `openclaw`, `versionOrder: "newer"` |
| 3 | `index provenance classifier changed` | `provenance_version` / `openclaw`, `versionOrder: "older"` |
| 4 | `index chunking implementation changed` | `chunking_version` / `openclaw`, `versionOrder: "older"`, `chunkingVersionOnly` when 7-10 still match |
| 5 | `index was built for model <stored>, expected <current>` | `model` / `configuration` |
| 6 | `index was built for provider <stored>, expected <current>` | `provider` / `configuration` |
| 7 | `index provider settings changed` | `provider_settings` / `configuration` |
| 8 | `index sources changed` | `sources` / `configuration` |
| 9 | `index scope changed` | `scope` / `configuration` |
| 10 | `index chunking changed` | `chunking` / `configuration` |
| 11 | `index FTS tokenizer changed` | `fts_tokenizer` / `configuration` |
| 12 | `index vector dimensions are missing` | `vector_dims` / `configuration` |

`owner: "openclaw"` is upstream's protocol value for the runtime's own index format; it is
kept verbatim (only the stale warning's prose names memory-core under the memory-core
identity). The versions are compared as JavaScript does (`(v ?? 0) > N` with `ToNumber` on
the stored JSON). Decision D2: memory-core's store writes and compares its own versions,
provenance 0 and chunking 0 (`MEMORY_CORE_INDEX_VERSIONS`; it has neither upstream's
provenance classifier nor its v5 chunker yet), so an index written before this port reads
as valid and nothing is rebuilt; the oracle compares the function at the tag's 1 and 5.

While the identity is not valid, `store.search` returns no hits and `memory_search` returns
the paused result, except an older chunking version on an otherwise matching index with FTS
on, which searches keyword-only and reports `stale`. `reindex` writes fresh metadata.
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
- The cooldown key adds the store's resolved path to upstream's agent id
  (`tools.ts:269`). Upstream's agent owns exactly one workspace and one index; in
  memory-core every `Memory.from_workspace()` store and every `SubjectMemory` workspace
  defaults to `agent_id="main"`, so an agent-only key would let one workspace's provider
  error pause memory search in all of them for 60 s.
- Omitted `maxResults`/`minScore` fall back to 5 / 0.0 (the memory-core facade
  defaults); upstream reads the agent config (6 / 0.35). The facade and
  `memory_search` default to `corpus="all"` (decision D8, unchanged), where upstream's
  default is an omitted corpus: a default call therefore carries `corpora`, and during a
  cooldown returns the per-corpus result (memory unavailable) instead of the unavailable
  result. Pass `corpus=None` for upstream's omitted-corpus behaviour.
- memory-core searches session transcripts by default (`search_sources`, decision D1);
  upstream searches them only when configured.
- There is no search-time repair (decision D3). Upstream rebuilds a missing or older
  runtime-owned identity during the search and warns `Automatic memory index repair was
  requested. ...`; memory-core returns the paused result until the host calls `reindex`.
  The tool-sequence oracle builds the TS index with an explicit sync first, as the Python
  fixture reindexes.
- The texts that name OpenClaw commands or config (the deadline action with an agent, the
  canonical-key action, the sessions-not-enabled action, the rebuild command, the
  version-change cause and the upgrade actions) have memory-core wording under the default
  identity (decision D4, proposed; compat mode keeps upstream's texts).
- Supplements keep memory-core's protocol (decision D7): no plugin id (several failures
  are joined unlabelled, in the caller's order), and a search receives the int limit and the
  corpus instead of upstream's optional `maxResults` and agent context.
- Error messages keep the explicit cause chain (`formatErrorMessage`) but skip
  upstream's token redaction. Redact tool results if provider errors can carry
  secrets.
- Not ported: provider identity aliases, `extraPaths` and multimodal indexing
  (the scope hash is fixed to upstream's defaults), the manager-context error
  and closed-store refresh branches (a memory-core store is built by the host), the
  QMD backend, session-visibility filtering, the deadline's pause/resume for a managed
  local embedding service, a caller `AbortSignal`, the repair-failure and
  `lastSyncError` staleness branches (no background sync), the `auto` citations mode, and
  the success `fallback`, `mode` and `debug` fields.
- Embedding HTTP calls are not interrupted. An abandoned worker finishes its
  current provider call, then stops at the next checkpoint.
- Under the memory-core identity, the SQLite warning and action wording is
  memory-core's own (upstream's names its Node runtime).

## Oracle coverage

Each of these runs the real TypeScript export at v2026.9.6
(`scripts/openclaw_oracle_runner.ts`, `tests/integration/test_openclaw_ts_oracle.py`):

| Operation | Fixtures |
| --- | --- |
| `memorySearch` with `rawParams` (through the real `toToolDefinitions` wrapper) | 19 invalid-param cases (incl. the unknown corpus), 6 accepted coercion/alias/corpus cases (xfail at v2026.9.6 on ranking, area 6), 5 blank-param cases on a single daily file |
| `memorySearchUnavailableResult` | 25 reasons and overrides incl. the deadline flag, the agent id and the canonical-key code (compat identity, exact) |
| `memorySearchToolSequence` | 17 tool calls in one process (a pre-sync, session search on both sides): cooldown record/replay/expiry with the failure's deadline flag, the wiki bypass, per-corpus outcomes under `all`, the keyword partial at the deadline; exact on a one-chunk MEMORY.md, xfail on a two-line one until area 6's chunking |
| `memoryIndexIdentity` | 50 identity states (versions, codes, owners, check order), 5 provider-key, 4 source and 2 scope-hash cases |
| `memoryIndexSearchDiagnostic` | 16 provider statuses through the five diagnostic exports (rebuild guidance, paused causes, staleness) |
| `memoryCorpusMetadata` | the per-corpus metadata of attempt lists |
| `memorySearch` with `embeddingModel` | the paused payload after a model change (`corpus=memory`; the `corpus=all` fixture waits on area 6) |
| `memoryToolDefinitions` | the `memory_search` and `memory_get` names, descriptions and schemas |
| `memoryGet` with `rawParams` (through the real `toToolDefinitions` wrapper) | 23 `memory_get` param cases (incl. the corpus enum) |
