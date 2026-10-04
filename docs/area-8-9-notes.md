# Areas 8 and 9: session corpus and session-memory hook (v2026.9.6)

Decision 4 applied: memory-core reads host-supplied transcript events; it does not read OpenClaw's SQLite.

## Area 9, session-memory hook (done)

Changed in `memory_core/session_memory.py` (and `bootstrap/startup.py`, `transcript_tree.py`):

- Rows are `role: <JSON string>` (one JSON string per record, U+0085/U+2028/U+2029 escaped); media placeholders are no longer stripped; a user slash command ends the turn but is not written; the trust class of the kept rows is computed (`classify_session_message_origin`, `SessionMemoryProjection.origin_class`, `SessionMemoryResult.origin_class`).
- New API (additive): `get_recent_session_projection_from_events`, `count_session_memory_messages`, `capture_session_memory_events` (visible branch via new `transcript_tree.select_visible_transcript_events`, 4096 messages / 8 MiB budgets), `save_session_memory(events=, event_type=, reason=, unavailable_reason=)`, `is_session_memory_trigger(type, action, reason)` (adds session/auto-reset with reason daily or idle).
- Heading carries the zone name (`America/New_York`), not the ICU short name; `Reason` line for session events; slug run only with a non-blank session id and content; slug prompt cut with `truncateUtf16Safe`.
- Bare reset limited prompt has its own next-step line (`BARE_SESSION_RESET_LIMITED_NEXT_STEP_LINE`).
- `get_recent_session_content*` and `.reset.` helpers stay as legacy file helpers over the same projection; `save_session_memory` no longer recovers `.reset.` files. `messages=`/`session_file=` remain convenience inputs.
- Deviations: no memory-write provenance record (trust class returned instead), no `context.agentId` requirement, session key written as given, errors raised, unknown zone raises, `max messages` Infinity projects nothing (upstream `Number.isFinite`). `memory_core/_intl_zone_names.py` is no longer used by the hook (still tested).

Oracle: `sessionMemorySlug`, `sessionMemoryHook[scenarios]` (now with auto-reset, sessionEntry precedence, quoting scenarios), `[zone_sweep]`, and `test_bare_session_reset_prompts_equal_upstream_source` pass; their worklist entry and the `sessionMemoryTranscript` retired op are removed. New op `sessionMemoryProjection` (82 cases) replaces the retired op. The hook op seeds transcripts into per-scenario agent SQLite stores.

Lead action: `docs/upstream_port_v2026_9_6.md` area 9 "Worklist areas" must become "none left" or `tests/parity/test_oracle_worklist.py::test_port_plan_assigns_every_worklist_area_to_one_plan_area` fails.

## Area 8, session corpus (ported as far as faithful)

New `memory_core/session_entry.py`: `build_session_entry` (`buildSessionEntryInProcess` over events or JSONL records: line map, timestamps, provenance, hash, wrapping at 800 UTF-16 units, sanitisation, inbound-metadata stripping, exec-completion/cron/heartbeat/silent/recalled/inter-session/dreaming exclusion, reset-recall cutoff, prefix hash). `MemoryCoreSessionCorpus.read_index_text` now uses it (text is whitespace-normalised and wrapped like upstream).

Oracle: new op `sessionCorpusEntry` (JSONL file branch of `buildSessionEntryInProcess`, identity redaction, 13 cases incl. hash) passes.

Gaps: `redactSensitiveText` (mode tools) is not ported, only a host `redact_text` hook (no redaction oracle op; R13 stays open); `stripInternalRuntimeContext` reuses the memory-core helper in `replay_history` (private import); `Date.parse` is ISO-only; session-key normalisation approximated; SQLite stats, archives, incognito, store classification not ported; reset-cutoff hash only compared as `absent` in the oracle.
