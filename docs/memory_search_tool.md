# memory_search Tool Contract

The active reference is OpenClaw **v2026.9.9**, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. Its production factory and query path
live in `extensions/memory-core/src/tools.ts`, `tools.shared.ts`,
`tools.citations.ts`, `memory-tool-contract.ts`, and `memory-search-tool-query.ts`.
This page describes the Python boundary and its explicit host responsibilities.
The acceptance target is `tools.search-contract`; this work does not establish
full deadline, provider lifecycle, session visibility, or recall parity.

## Entry points and defaults

| Entry point | Arguments and result |
| --- | --- |
| `execute_memory_search_tool(config, store, params)` | Reads raw model arguments and returns the complete provider-neutral payload dictionary. |
| `memory_search(config, store, *, query, max_results=6, min_score=0.35, corpus="all")` | Python convenience form of the raw executor. `None` means the numeric argument was omitted. |
| `Memory.search(query, max_results=5, min_score=0.0, corpus="all")` | Existing SDK convenience defaults; these are explicit arguments to the tool. |
| `create_memory_search_tool(config, store, ...)` | Creates the model-facing factory object, or returns `None` when disabled. Its `execute(tool_call_id, params)` returns the native-shaped JSON envelope. |

The raw tool resolves omitted numeric arguments from
`MemoryConfig.search_max_results` and `MemoryConfig.search_min_score`, whose
defaults are **6** and **0.35**. Explicit model arguments take precedence.
`Memory.search` retains its explicit **5 / 0.0** convenience policy; this is an
SDK extension, not an alternative claim about the native defaults. An omitted
raw `corpus` searches configured primary sources without querying wiki
supplements. The Python convenience calls default to `corpus="all"`.

```python
from memory_core.tools.search_factory import create_memory_search_tool

tool = create_memory_search_tool(memory.config, memory.store)
if tool is not None:
    definition = tool.definition
    arguments = tool.prepare_arguments({"query": "What tea do I prefer?", "max_results": 3})
    envelope = tool.execute("call-1", arguments)
    payload = envelope["details"]
```

The factory definition contains `label`, `name`, `description`, and `parameters`.
`memory_search_tool_definition(index_sessions=False, extra_paths=())` provides
the provider-neutral name, description, and schema without a factory object.
Session indexing and configured extra paths change the source guidance.
`extra_paths` describes sources the host indexes; it does not add an indexing
implementation.

`prepare_memory_search_arguments` normalizes `max_results` and `min_score` to
camelCase and removes their aliases. Explicit camelCase properties win,
including null and invalid values. With no aliases, it returns the original
input. It does not mutate the caller's arguments.

`serialize_search_tool_result(payload)` implements the native `jsonResult`
boundary:

```python
{
    "content": [{"type": "text", "text": "<pretty-printed JSON of the complete payload>"}],
    "details": payload,
}
```

The direct executor returns `payload` itself. Comparing that dictionary with
the native envelope's `details` is a transport mapping; it must retain every
observable payload field. The envelope's text represents that same full payload.

## Arguments and errors

Pass a parsed mapping. A JSON string or another non-record input reads as an
empty record, so a missing query fails validation. Parameters are read in order:
`query`, `maxResults`, `minScore`, then `corpus`.

| Parameter | Accepted input | Failure |
| --- | --- | --- |
| `query` | A nonblank string, trimmed with ECMAScript whitespace rules. | `query required` |
| `maxResults` / `max_results` | A positive safe integer or strict numeric string, such as `"5.0"` or `"1e1"`. | `maxResults must be a positive integer` |
| `minScore` / `min_score` | A finite number or strict numeric string, such as `".5"` or `"-2e-1"`. | `minScore must be a finite number` |
| `corpus` | `memory`, `wiki`, `all`, or `sessions`. Blank and non-string values read as omitted. | `corpus must be one of: memory, wiki, all, sessions` |

Missing or null numeric values and blank numeric strings read as omitted.
Booleans, lists, hexadecimal strings, numeric separators, full-width digits,
NaN, and infinity are rejected. Snake_case lookup applies only when the
camelCase key is absent.

Query and numeric errors raise `MemoryToolInputError`, whose native exception
name is `ToolInputError` and whose status is `400`. An unknown corpus raises
the ordinary `MemoryToolError`, whose native name is `Error` and which has no
status. Both expose the error message and a `to_tool_error()` host-loop form:

```python
{
    "status": "error",
    "tool": "memory_search",
    "error": "maxResults must be a positive integer",
}
```

This host-loop result is distinct from exception metadata and from the
unavailable search payload below. Blank facade queries raise too; hosts should
skip recall for silent input or handle that error.

## Corpus and trusted host policy

| Corpus | Primary store | Wiki supplements | Result policy |
| --- | --- | --- | --- |
| `memory` | Memory files only. | Not queried. | Primary ranking. |
| `sessions` | Indexed transcripts only. | Not queried. | Host session policy applies. |
| `wiki` | Not queried. | Queried. | Supplement ranking. |
| `all` | Configured primary sources. | Queried. | Balanced streams, then backfill. |
| Omitted or blank | Configured primary sources. | Not queried. | Primary ranking. |

`MemoryConfig.session_search=False` excludes sessions from ordinary searches
and refuses an explicit model `corpus="sessions"` with guidance. Trusted
conversation recall may select sessions independently. In particular,
`MemorySearchToolContext.conversation_recall_corpus="sessions"` forces that
corpus even when the model requests `all` or `wiki`. It does not make a model
argument authoritative or implement the host's full session-visibility policy.

`active_project_keys`, `agent_session_key`, `runtime_identity`, `supplements`,
and `context` are trusted executor keyword arguments. They are absent from the
model schema. Active project keys are copied once per call and retained across
its search/fallback stages. Registered supplements use
`RegisteredMemoryCorpusSupplement(plugin_id, supplement)` for stable plugin-id
ordering and failure labels; anonymous existing supplements remain supported.

The factory accepts `get_config`, which is read at creation and on each
execution. A missing or disabled live configuration revokes the tool before
query validation. `FeatureFlags.memory=False` and `context.enabled` also gate
factory availability. A live configuration cannot route an existing store to
a different workspace, agent, or index; create a tool with the matching store
instead.

## Results and citations

An ordinary result includes `results`, `provider`, `citations`, and search
`debug`. An embedding provider also supplies its `model`. The actual SQLite
FTS-only status reports `provider="none"` and **omits `model`**. Wiki-only
results omit primary provider/model/debug fields. A custom host manager's
explicit model, fallback, and mode are retained when present.

Each primary hit preserves all public fields emitted by its retrieval branch,
including score components, a vector candidate ID when present, null versus
omitted annotations, project keys, and provenance. Keyword-only hits do not
acquire a vector score, and vector-only hits do not acquire component scores.
The internal ranking timestamp `sourceMtime` is not a public hit field.
Presentation adds `corpus=source` and strips memory annotation carriers from
the snippet. Search results are **not** reclamped with the `memory_get` read
budget and do not gain `truncated` or `originalChars` fields.

`MemoryConfig.citation_mode` defaults to `auto`; invalid host values also
resolve to `auto`.

| Mode | Primary hit presentation |
| --- | --- |
| `on` | Include citations. |
| `off` | Omit the `citation` property and source suffix. |
| `auto` | Include citations for direct/default sessions; omit them when the parsed agent-session rest contains a `channel` or `group` token. |

The `citation` value is a label such as `MEMORY.md#L1-L3`, without a `Source:`
prefix. When included, the snippet preserves leading whitespace, trims only
its end, and appends `\n\nSource: MEMORY.md#L1-L3`. Supplements retain their own
presentation. Only primary results actually returned after corpus blending
receive the primary presentation.

## Manager status and diagnostics

`MemorySearchToolContext` connects a genuine host manager to the production
executor. Its fields are:

| Field | Meaning |
| --- | --- |
| `status` | Optional callable returning current manager status. Otherwise the tool reads a store status method, or actual SQLite provider, index identity, flags, and per-source counts. |
| `runtime_debug` | Optional callable reading manager-emitted debug events. The last event provides configured mode/fallback; the last bootstrap event is retained. |
| `manager_ms` | Optional measured manager-acquisition duration. Without an explicit context, the factory measures acquisition of its ready store; direct executor calls may omit it. |
| `clock` | Millisecond clock, real wall clock by default. Tests can inject a controlled clock into the same timing path. |
| `conversation_recall_corpus` | Trusted recall corpus policy. |
| `enabled` | Boolean or live callable for host enablement. |

The tool computes `searchMs`, `toolMs`, `outsideSearchMs`, `hits`,
`candidateHits`, `withheldHits`, and `searchWindow` from actual execution.
Optional native fields remain absent when the manager did not emit them.
Normal builtin FTS search has debug `effectiveMode="n/a"` and no top-level
`mode`; the tool does not infer a runtime event from a desired test outcome.

`lastSyncError` produces `stale=true` with warning/action guidance. Index
identity diagnostics retain their cause-specific behavior: configuration
mismatch, missing metadata, runtime-owned format changes, newer index formats,
and previous repair failures have different guidance. A runtime-owned failed
repair reports that the existing index was left unchanged. A live
`custom.automaticRebuildNotice` produces a new notice only when its sequence
changes during this search; an old notice is not replayed on every request.
Rebuild, staleness, recovery, and partial-corpus warnings compose with corpus
outcomes without dropping the other diagnostics.

These callbacks provide production status, not prebuilt expected results.
They do not implement an automatic sync lifecycle for a standalone Python
store. The host still owns reindexing and any manager acquisition/retirement.

## Unavailable, deadline, and cooldown behavior

A primary failure without another requested corpus returns:

```python
{
    "results": [],
    "disabled": True,
    "unavailable": True,
    "error": "provider failure reason",
    "warning": "Memory search is unavailable due to an embedding/provider error.",
    "action": "Check embedding provider configuration and retry memory_search.",
    "debug": {"warning": "...", "action": "...", "error": "provider failure reason"},
}
```

The reason is trimmed, defaulting to `memory search unavailable`. Explicit
warning/action overrides win. The canonical-session migration error code
`SESSION_CANONICAL_KEY_MIGRATION_REQUIRED` takes precedence over quota text;
other branches recognize quota, missing SQLite runtime, genuine deadline
provenance, and generic provider failure. Runtime-specific advice comes from
`RuntimeIdentity`; `OPENCLAW_COMPAT_RUNTIME_IDENTITY` supplies OpenClaw's exact
CLI/Gateway wording, while the default uses Python host guidance.

A genuine search deadline adds `timedOut=true` and `timeoutMs=30000`. A provider
message that merely says `memory_search timed out after 30s` does not acquire
deadline provenance. The active native constant is 30 seconds.

The existing Python workers have a 30-second per-corpus deadline and a
60-second failure cooldown. Wiki queries remain independent. Memory-file
keyword evidence can produce a partial response after a semantic deadline;
session transcript results are excluded from that partial fallback. Paused
indexes and partial results do not record a cooldown. Python scopes cooldowns
by the resolved store path plus agent identity to isolate independent hosted
workspaces. This is an explicit SDK extension to native agent-based keys.

Deadline, cancellation, cooldown configuration invalidation, automatic sync,
closed-manager refresh, provider transitions, and full session visibility
remain separately tracked contracts. Verifying the warning/output branches
here does not close those broader contracts. A Python fallback performs a fresh
keyword query; the native manager can retain a previously filtered partial
snapshot. An in-flight embedding HTTP request is not interrupted by SQLite
cancellation.

## Evidence and historical references

Current `tools.search-contract` evidence must run the pinned production
factory and real search engine, compare the complete public payload and
exception metadata, and retain the native envelope. Controlled clocks exercise
the real timing code. Helper-only fixtures supplement whole-tool cases;
they do not establish the complete contract by themselves. See
`docs/parity_matrix.md` for the acceptance ledger and current evidence.

Earlier oracle operations such as `memorySearch`,
`memorySearchUnavailableResult`, `memorySearchToolSequence`,
`memoryIndexIdentity`, `memoryToolDefinitions`, and `memoryGet` remain useful
historical regression coverage in `tests/integration/test_openclaw_ts_oracle.py`
and `scripts/openclaw_oracle_runner.ts`. Their older pins, projected shapes,
and fixture counts must not be presented as fresh v2026.9.9 whole-tool proof.
