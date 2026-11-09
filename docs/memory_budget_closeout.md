# Memory Budget Comparison Closeout

The thirteen registered cases collectively support the two original fixed contract #38 conditions:

- `compaction.memory-budget.outcomes`: mixed user/generated sections and exact size/loss limits.
- `compaction.memory-budget.boundaries`: preserved bytes, removed sections, deferral and reconciliation markers.

Independent review approved the complete set. Registration is staged for the integrated full gate;
this document does not add points to the main checklist. Both conditions require **all thirteen**
case IDs declared in `MEMORY_BUDGET_REQUIRED_CASE_IDS`. The default-catalog regression independently
checks that exact set for each condition.

## Frozen evidence

The corrected protected paired report is
`.equivalence-results/memory-budget-corrected-paired-13.json`:

- Source/adapter commit: `05e4f94a88d36f9b8a4f015edc1f5649112da9a8`.
- Report SHA-256: `93901b96a3f66130fc4fb9f4c517400c0615c8188deeb0cf74a04b861d7593f9`.
- Result: **13 matched, 0 mismatched, 0 blocked, no errors**, 79.183093 seconds.
- SDK source: 150 files, SHA-256 `10df19b3e8399288f232c524b39ea59b870450fa2e7aa254d9e5013a23e76448`.

The historical report keeps its original empty `covers` arrays and `incomplete` status.
Its 128 uncovered conditions reflect the deliberately uncredited subset at capture time.
The earlier six-case report also remains unchanged, SHA-256
`0b19b6bcc41eb288f52277a78b56befc98ba648e906fca0b6fe123285b5572a7`.
Later registration does not rewrite either report or imply a new process execution.

## Required cases

| Case suffix after `memory-budget-` | Actual original behavior exercised |
|---|---|
| `mixed-sections-and-limits` | Whole compact helper; exact UTF-16 size/reserve and loss limits, mixed user/generated sections, ordering, headings, markers, CRLF, astral and lone-surrogate text. |
| `sdk-marker-extension-diagnostic` | Foreign runtime marked text remains preserved in explicit compatibility mode. |
| `fit` | Actual apply appends and persists the promoted recall mark. |
| `compact` | Actual apply removes eligible oldest generated sections and appends while preserving user text. |
| `defer` | Actual budget rejection preserves the document and rejects the candidate. |
| `reconcile` | Existing genuine marker produces reconciliation without a duplicate append. |
| `marker-preservation-boundaries` | ASCII-case positives and user-owned dotted/dotless-I, CR/LS/PS marker/project boundaries. |
| `foreign-marker-reconcile` | A foreign prefix with the same key cannot falsely reconcile in explicit compatibility mode. |
| `non-js-space-prefix-reconcile` | U+0085 before the prefix is not JavaScript whitespace. |
| `non-js-space-key-reconcile` | U+0085 is retained in the extracted key. |
| `js-bom-space-prefix-reconcile` | U+FEFF before the prefix is JavaScript whitespace. |
| `js-bom-space-key-reconcile` | U+FEFF is trimmed from the extracted key. |
| `literal-line-endings-fit` | Actual apply preserves CRLF/bare CR user bytes and validates the unchanged original preimage. |

## Comparison boundary

The source scope is ordinary JSON with explicit ISO dates, using the original whole compact
helper and genuine OpenClaw-compatible apply owner over literal persisted source/recall inputs.
The original default budget constant is also observed. Configuration-budget resolution, ranking,
models, general promotion lifecycle, arbitrary Unicode date collation, workspace locks and
physical storage-schema equivalence are outside this comparison.

The complete original apply result has eight fields: `memoryPath`, `applied`, `appended`,
`reconciledExisting`, `appliedCandidates`, `rejectedCandidates`, `compactedSections` and
`compactedDates`. Every field is compared, together with complete document bytes, recall state
and actual promotion events. The SDK's richer own return remains raw. The interface codec only
maps exact owned fixture-root prefixes, dataclass field spelling and JSON array representation;
it does not repair IDs/hashes, rewrite markers, sort outputs or tolerate score differences.

The report retains all 26 own Native/SDK raw channels, complete source calls, real persisted
schema/count/column/row observations and every owned file's bytes/lstat facts. Thirteen protected
trace contexts retain exact successful original rows from the same executions, full PID/owner maps,
and original trace text with byte counts/hashes. Both source/artifact identities are checked
before and after execution. No provider/model call or credential forwarding occurs.

The separate capability authenticates 19 committed original source modules, 13 published compiled
modules, one exact fs-safe NAPI artifact and eight actual source import links. Node authority is
24.16.0 / ICU 78.3 / Unicode 17, binary SHA-256
`b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`.
The actual keyed plugin-state store is configured through the genuine factory; no store is fabricated.

## Corrections and retained failures

Independent review found real user-content preservation and reconciliation gaps after the first
six-case run. Their original whole-helper/apply failures remain under
`memory-budget-review-boundaries-before`, `memory-budget-whitespace-before` and
`memory-budget-line-endings-before`. The last shows original success versus the SDK's former
false `MemoryWriteConflictError`. Earlier incorrect-prefix and collector-entry setup failures
are retained separately rather than replaced by corrected reports.

The production fixes select the same marker reader across compaction, reconciliation, preimages
and builtin origin pruning. Ordinary core promotion consciously keeps the Q22 dual-prefix reader;
explicit compatibility uses only the genuine prefix. Low-level omitted identity retains legacy
dual reading. Custom non-ASCII prefix characters remain literal. Opaque host indexed-key callbacks
retain host authority outside this qualified builtin profile.

Generated-block recognition follows original ASCII-prefix non-Unicode case matching and JavaScript
dot line boundaries. Key extraction preserves its separate `[^\n]` behavior with JavaScript
whitespace and trim. Actual MEMORY.md/preimage/hash readers preserve literal newlines; other shared
utility callers retain their legacy defaults and existing strict UTF-8 error policy.

The packaged two-profile development replay fixture remains authentic and unchanged. It comes from
a **separate** Native-only packet, not either paired report's process executions. Its raw SHA-256 is
`bce1562930c79f24aa5ae29f68e1ba33825e1d4343f8d4a802ccfc908e1842f9`.
Replay and tampering guards validate that captured boundary without inventing a fresh native run.

Before registration, 219 related production/default-SDK/raw/source-map checks passed. The source
inventory validated all 64 contracts, 128 conditions and 193 mapped original modules. Registration,
replay and source-map checks are rerun for this metadata-only closeout; the combined gate remains
responsible for final integrated acceptance.
