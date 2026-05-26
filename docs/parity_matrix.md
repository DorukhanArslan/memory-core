# memory-core Lab / OpenClaw Memory-Core Parity Matrix

Reference target:

- Pinned OpenClaw commit recorded in this repo: `7f6798094ce9486a8f463772f4535484aca73fe2`
- Latest GitHub source inspected during planning: `8c7f226401131164a450ee14e13c581eaf489993`

This matrix tracks the Python lab against the OpenClaw workspace + memory core that affects chat behavior. The implementation target is the simple memory behavior plus the standard workspace bootstrap layer that is injected before memory context.

| Area | OpenClaw behavior | memory-core status | Gap / next action |
| --- | --- | --- | --- |
| Agent workspace | Active workspace is the default cwd and private operator state. Standard bootstrap files are created when missing unless bootstrap is skipped. | Implemented for demo workspace under tempdir. | No configurable `skipBootstrap` or profile-specific workspace path. |
| `AGENTS.md` bootstrap | Operating instructions loaded at the start of every session. | Implemented. | Demo uses memory-core defaults instead of upstream template text to avoid brand leakage in UI. |
| `SOUL.md` bootstrap | Persona, tone, boundaries; injected on normal sessions. | Implemented. | Demo defaults are concise Memory-Core-specific persona text. |
| `TOOLS.md` bootstrap | Local tool conventions; guidance only, not tool access control. | Implemented. | No dynamic tool inventory generation. |
| `IDENTITY.md` bootstrap | Agent name, vibe, emoji; created/updated by bootstrap ritual. | Implemented. | No bootstrap ritual UI; seeded default file only. |
| `USER.md` bootstrap | Stable user profile and address preferences; loaded every session. | Implemented. | No dedicated UI editor yet. |
| `HEARTBEAT.md` bootstrap | Optional heartbeat checklist; omitted on normal runs unless heartbeat context needs it. | Out of core scope. | Add only if heartbeat demo is in scope. |
| `BOOT.md` / `BOOTSTRAP.md` | Optional startup checklist / first-run ritual. | Out of core scope. | Add only if runtime automation is in scope. |
| Bootstrap injection order | OpenClaw resolves workspace files and injects bootstrap context before memory/tool recall; daily files are not normal bootstrap context. | Implemented for `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`. | Native Codex role-splitting is approximated as system messages in the lab. |
| Bootstrap truncation | Per-file default 12k chars and total default 60k chars, with `[MISSING] Expected at: ...` markers. `AGENTS.md` gets a special head/policy-digest/tail trim. | Partial. | Limits and missing marker match; `AGENTS.md` policy-digest truncation is approximated. Warning diagnostics are not surfaced separately in UI. |
| `MEMORY.md` bootstrap | Curated long-term memory file; injected on normal main/private sessions when present. | Implemented. | Add memory budget compaction parity. |
| Daily memory | Writes short-term facts to `memory/YYYY-MM-DD.md`; today/yesterday may be one-shot startup context on new/reset, but daily files are normally accessed by tools. | Implemented for writes and on-demand search; chat auto-recall still filters today/yesterday. | Consider removing chat auto-recall of yesterday for stricter tool-only behavior. |
| Pre-compaction flush prompt | Tool-style write decision near compaction. | Partial. | Prompt text is close, but not wired into actual OpenClaw runtime compaction. |
| `memory_search` | Hybrid memory/session/wiki search with citations and recall tracking. | Partial. | Memory/session corpora work; wiki/QMD paths missing. |
| `memory_get` | Safe file read for memory artifacts. | Implemented. | Confirm exact path allowlist and citation text against pinned source. |
| Hybrid search | FTS + vector + temporal decay + optional MMR. | Implemented. | Compare edge cases from upstream manager tests. |
| Embedding providers | Provider discovery and adapters for multiple providers. | Out of core scope. | Keep OpenAI-compatible provider for the lab. |
| Provider policy/cache | Provider state, cache, timeout, vector warnings. | Out of core scope. | Do not port unless runtime parity becomes a goal. |
| QMD backend | Optional QMD index/search/vsearch/query integration. | Out of core scope. | Do not port for core memory parity. |
| Short-term recall store | `memory/.dreams/short-term-recall.json`. | Implemented. | Need source-existence filtering and contaminated-snippet parity. |
| Promotion score | Frequency, relevance, diversity, recency, consolidation, conceptual, phase boost. | Implemented. | Keep strict OpenClaw formula; no Memory-Core-specific boost. |
| Promotion gates | Default score `0.75`, signals `3`, unique queries/days `2`. | Implemented. | Current UI labels memory-core defaults; strict OpenClaw mode should expose exact defaults. |
| Phase boost | Log-scaled light/REM hits with recency decay. | Partial. | memory-core phase boost is simpler; port OpenClaw formula. |
| Promotion apply | Rehydrate candidate from live source, skip stale/deleted/dreaming-fenced snippets. | Partial. | Implement live rehydration and dreaming fence checks. |
| Promotion markers | HTML marker `openclaw-memory-promotion:<key>` prevents duplicate writes. | Implemented internally. | UI hides brand, but internal marker remains upstream-compatible. |
| Memory budget | Compacts older promotion sections to keep `MEMORY.md` bounded. | Out of core scope. | Skip for the simple implementation. |
| `promote --json` / `--apply` | Preview first, apply only when requested. | Out of core scope. | UI/API can stay demo-specific. |
| `promote-explain` | Explains candidate scores and gate failures. | Partial. | UI evaluated candidates are enough for the lab. |
| Light dreaming | Ingests recent daily notes, stages phase signals, writes optional reports. | Partial. | Demo records phase signals from existing candidates only. |
| REM dreaming | Session/daily pattern extraction and narrative diary. | Partial. | Demo `DREAMS.md` is simplified; no detached narrative subagent. |
| Deep dreaming | Applies short-term promotions. | Partial. | Core behavior exists; config/cron/apply parity missing. |
| Dreaming scheduler | Managed cron job and heartbeat/system event trigger. | Out of core scope. | Manual button is enough for the lab. |
| `/dreaming` command | Enable/disable/status/help and config persistence. | Out of core scope. | Skip unless CLI parity is required later. |
| Session corpus | Redacted transcript ingestion with checkpoints and cron/heartbeat filtering. | Out of core scope. | Keep simple session-corpus demo only. |
| Redaction | Sensitive content redacted before corpus write. | Out of core scope. | Note as production hardening, not core memory. |
| Grounded backfill | Historical daily/session backfill with staged recall entries. | Out of core scope. | Skip for simple implementation. |
| REM harness | Evidence harness for REM behavior. | Out of core scope. | Skip for simple implementation. |
| Public artifacts/status | Structured status, public artifacts and diagnostics. | Partial. | Demo state endpoint is enough for the lab. |
| Audit/repair | Recall store, lock, QMD index, health diagnostics. | Partial. | memory-core audits recall store/lock only. |
| Runtime plugin integration | Plugin config, host APIs, private file store, memory events. | Out of core scope. | Explicitly not part of the simplified target. |

Immediate sprint focus:

1. Keep this matrix current.
2. Add fixture-based promotion comparison.
3. Keep runtime-only OpenClaw features out unless they affect core memory behavior.
