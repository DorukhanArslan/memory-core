# OpenClaw Core Memory Python Port Design

Date: 2026-05-03

Status: approved for planning

Upstream reference: `openclaw/openclaw` commit `7f6798094ce9486a8f463772f4535484aca73fe2`

License note: upstream OpenClaw is MIT licensed. This project will preserve the upstream copyright and license notice for any ported behavior or substantial source-derived material.

## Goal

Implement OpenClaw's core memory system in Python with behavior, architecture, prompts, and structure matching the upstream `memory-core` implementation as closely as possible. The implementation will be a reusable Python library plus a local FastAPI demo website that exercises each core memory surface through real HTTP endpoints.

The parity target is behavioral and implementation-level parity with the referenced upstream commit. If the Python port intentionally differs from upstream behavior, the difference must be documented as an explicit deviation.

## Scope

In scope:

- Workspace memory files:
  - `MEMORY.md`
  - legacy/root `memory.md` handling where upstream behavior requires it
  - `memory/YYYY-MM-DD.md`
  - optional `DREAMS.md` as a readable memory-adjacent file surface
- `memory_search` tool:
  - mandatory recall-style tool contract
  - hybrid vector plus keyword search
  - memory corpus filtering
  - `maxResults`
  - `minScore`
  - citation decoration and injected character limits
- `memory_get` tool:
  - safe relative memory file reads
  - optional line windows
  - truncation behavior
  - path/line metadata
- Prompt section parity:
  - `## Memory Recall`
  - tool-availability-specific guidance
  - citation-mode-specific guidance
- SQLite-backed memory index:
  - chunked Markdown content
  - FTS keyword index
  - vector embedding storage
  - forced reindex
- Embedding provider adapter interface:
  - first concrete adapter: OpenAI-compatible embeddings
  - architecture ready for Gemini, Voyage, Mistral, or local adapters later
- FastAPI demo website:
  - exercises core memory files, reindexing, `memory_search`, `memory_get`, citations, and prompt section preview
- Tests:
  - unit tests
  - integration tests
  - FastAPI endpoint tests
  - deterministic fake-embedding tests
  - parity fixtures tied to the upstream commit

Out of scope for this first implementation:

- Dreaming phases and promotion
- `memory/.dreams/` machine state
- Active memory blocking sub-agent
- Session transcript memory search
- QMD backend
- Honcho backend
- LanceDB backend
- Memory Wiki
- Full OpenClaw gateway or channel integration
- Debounced file watching for automatic reindexing

## Architecture

The repository will contain a reusable Python library and a thin demo app:

```text
memory_core/
  memory_core/
    config.py
    workspace.py
    prompt_section.py
    tools/
      memory_search.py
      memory_get.py
      citations.py
    index/
      chunking.py
      sqlite_store.py
      fts.py
      vector.py
      hybrid.py
      mmr.py
      temporal_decay.py
    embeddings/
      base.py
      openai_compatible.py
    parity/
      upstream.py
  demo/
    app.py
    templates/
    static/
  tests/
    unit/
    integration/
    parity/
```

The library owns all OpenClaw-compatible behavior. The demo website must call the same public APIs used by tests, so the UI never becomes a second memory implementation.

Core indexing and search flow:

```text
Markdown files
  -> workspace discovery
  -> chunking
  -> SQLite index
       -> FTS keyword path
       -> embedding vector path
  -> hybrid merge
  -> citations/truncation
  -> memory_search JSON result
```

Core read flow:

```text
memory_get request
  -> safe relative path resolution
  -> optional line window
  -> truncation/citation metadata
  -> JSON result
```

## Prompt Section

`build_prompt_section()` will mirror upstream `extensions/memory-core/src/prompt-section.ts`.

Rules:

- If neither `memory_search` nor `memory_get` is available, return no section.
- If both are available, emit `## Memory Recall` plus guidance to run `memory_search` before answering about prior work, decisions, dates, people, preferences, or todos, then use `memory_get` for needed lines.
- If only `memory_search` is available, emit the search-only guidance.
- If only `memory_get` is available, emit the get-only guidance.
- If citation mode is off, instruct callers not to mention file paths or line numbers unless explicitly asked.
- Otherwise, allow `Source: <path#line>` when useful for verification.

The section header and short guidance strings should remain as close to upstream as license and Python packaging constraints allow.

## Tool Contracts

`memory_search` input:

```json
{
  "query": "router vlan preference",
  "maxResults": 5,
  "minScore": 0.2,
  "corpus": "memory"
}
```

Supported first-slice corpus behavior:

- `memory`: search indexed memory files.
- omitted corpus: equivalent to upstream default for memory files in this port.

`wiki`, `all`, and `sessions` are out of scope for this first slice because their corresponding upstream systems are also out of scope.

`memory_search` output:

```json
{
  "results": [
    {
      "corpus": "memory",
      "path": "memory/2026-05-03.md",
      "startLine": 4,
      "endLine": 8,
      "score": 0.82,
      "vectorScore": 0.9,
      "textScore": 0.7,
      "snippet": "...",
      "source": "memory"
    }
  ],
  "provider": "openai-compatible",
  "model": "text-embedding-3-small"
}
```

Unavailable search result:

- Because this project requires full hybrid search, missing provider configuration, failed embedding setup, or missing vectors should return an OpenClaw-style disabled/unavailable result rather than silently degrading to lexical-only search.

`memory_get` input:

```json
{
  "path": "MEMORY.md",
  "from": 10,
  "lines": 20
}
```

`memory_get` output:

- requested relative path
- returned text
- effective start and end line metadata when line windows are used
- truncation metadata if applicable
- disabled/error fields on failure

Path resolution must prevent reading arbitrary files outside the configured workspace.

## Index And Search

Indexing will follow OpenClaw's builtin memory engine:

- Index `MEMORY.md` and `memory/*.md`.
- Chunk Markdown into approximately 400-token chunks with approximately 80-token overlap.
- Store chunks in SQLite with:
  - stable id
  - relative path
  - start line
  - end line
  - source
  - snippet/text
  - embedding vector
  - FTS content
- Support forced reindex.
- Do not implement debounced file watching in the first slice. Reindexing is explicit through library, CLI/test helper, or demo endpoint calls.

Search runs two retrieval paths:

- Vector path:
  - embed the query
  - compute vector similarity against indexed chunk embeddings
- Keyword path:
  - build an FTS5 query from quoted tokens joined with `AND`
  - map BM25 rank to score using upstream's scoring formula

Hybrid merge:

- Merge vector and keyword results by stable chunk id.
- Preserve raw `vectorScore` and `textScore` diagnostics.
- Compute combined score as:

```text
score = vectorWeight * vectorScore + textWeight * textScore
```

- Apply temporal decay when enabled.
- Sort by score descending.
- Apply MMR re-ranking when enabled.

Temporal decay:

- Disabled by default.
- Default half-life: 30 days.
- `MEMORY.md` and non-dated memory files are evergreen.
- Dated `memory/YYYY-MM-DD.md` files can decay when enabled.

MMR:

- Disabled by default.
- Default lambda: 0.7.
- Tokenization and Jaccard similarity should follow upstream behavior, including CJK-aware token handling.

## Embeddings

The embedding layer uses a provider adapter interface.

First concrete adapter:

- OpenAI-compatible embeddings.
- Environment/config driven API key.
- Configurable base URL.
- Default model: `text-embedding-3-small`.

Tests use a deterministic fake embedding provider so automated test runs do not require external network access or API keys.

Live embedding tests are optional and gated by environment variables.

## Demo Website

The demo website will be a local FastAPI app with simple HTML templates.

Required UI:

- Workspace/config panel.
- Seed buttons for sample `MEMORY.md` and `memory/YYYY-MM-DD.md` fixtures.
- Reindex button.
- `memory_search` form:
  - query
  - max results
  - min score
- `memory_get` form:
  - path
  - from line
  - line count
- Result panel:
  - raw JSON output
  - snippets
  - scores
  - `Source: <path#line>` citation display
- Prompt section preview:
  - available tools
  - citation mode
  - generated `Memory Recall` section

The demo is a validation surface, not a separate product. It should stay small and focused on proving parity.

## Testing Strategy

Unit tests:

- prompt section builder
- safe path resolution
- memory file discovery
- chunking
- FTS query building
- BM25 rank-to-score mapping
- hybrid merge
- MMR
- temporal decay
- citations and truncation

Integration tests:

- temporary workspace with `MEMORY.md` and dated daily notes
- SQLite index creation
- forced reindex
- deterministic fake embeddings
- `memory_search` results with vector and keyword scores
- `memory_get` line windows and path safety

Demo tests:

- FastAPI route smoke tests
- seed fixture flow
- reindex endpoint
- search endpoint
- get endpoint
- prompt preview endpoint

Parity tests:

- Expected prompt section output from upstream commit.
- Expected FTS query tokenization.
- Expected BM25 rank-to-score mapping.
- Expected hybrid merge behavior.
- Expected MMR and temporal decay behavior on fixed fixtures.

## Error Handling

Search errors:

- Missing embedding provider/config returns disabled/unavailable search result.
- Embedding request failure returns disabled/unavailable search result with error metadata.
- Empty index returns an empty result list with provider/model metadata when the provider is otherwise healthy.

Read errors:

- Missing file returns disabled/error JSON.
- Unsafe path returns disabled/error JSON.
- Invalid line windows are normalized or rejected consistently with upstream behavior.

Index errors:

- Invalid or unreadable files are skipped or surfaced according to upstream behavior.
- SQLite setup failures fail the reindex operation with explicit error metadata.

## Configuration

Initial config should include:

- workspace directory
- agent id
- SQLite store path
- embedding provider id
- embedding model
- OpenAI-compatible base URL
- citation mode
- memory get maximum characters
- memory get default line count
- hybrid vector/text weights
- MMR config
- temporal decay config

Defaults must match upstream. The implementation plan must inspect the referenced upstream source before coding each default and capture the resolved values in parity tests.

## Accepted Decisions

- Use upstream `main` commit `7f6798094ce9486a8f463772f4535484aca73fe2`.
- First slice is core memory only.
- Use a reusable Python library plus FastAPI demo website.
- Require full hybrid search.
- Use provider adapter architecture with OpenAI-compatible adapter first.
- Treat behavior and implementation parity as the target, not just API similarity.
- Initialize this workspace as a git repository and commit the design document.

## Planning Verification Items

- Resolve upstream defaults for memory get truncation and default line count before implementing `memory_get`.
- Resolve upstream default hybrid vector/text weights before implementing `memory_search`.
- Inspect upstream SQLite schema and decide whether to port field names exactly or document Python-specific storage differences behind the same public behavior.
- Use forced reindex only in the first slice.
- Decide whether parity tests use short vendored upstream fixtures or generated equivalent fixtures before writing test data.
