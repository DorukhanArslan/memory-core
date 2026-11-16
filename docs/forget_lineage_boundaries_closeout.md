# Forgotten-session admission after durable reopen

The complete comparison verifies **77/128 conditions (60.2%),
51 remaining**: **36 complete, 5 partial and
23 pending contracts**. The original
`forget.lineage-tombstones.boundaries` condition adds **one point**, taking the
previous 76/128 assessment to 77/128 and completing this contract at 2/2.
The fixed scope remains 64 contracts and 128 conditions.

The [single full comparison](https://github.com/DorukhanArslan/memory-core/actions/runs/43796082206)
executes clean comparison commit `2e51b61b623528a17504d4e8f62db0c8d34d5b79`,
with product source pinned to `b08e28399fa00da4b735734170c4749b5b481bd8`.
The 162 SDK files retain SHA-256
`a90d994bcf005a26a4e15bf40b2e9b95f47a7a8c31cd864ed2131021d9046990`,
byte-identical to the previously merged product `1337209d`.
This package changes verification, not production SDK behavior.

## Actual complete result

The run retains **1,469 cases: 1,455 matched, 14 mismatched,
0 blocked and 0 runner errors**. Its actual process exit is
**1**, after 4,269.125 seconds. The full gate remains mismatched:
**49 uncovered and 2 registered unresolved conditions**.
All original 14 complete public mismatch pairs remain unchanged; their held
investigation is not reopened here.

Full report SHA-256: `10854f20f1bd963111044030dc38d3722c5fc81a0fe6f7b112efa5e465733b5a`.
Catalog SHA-256:
`74322960d928ecb2b1ed330f18f891d3e6efb04482eacd6bddf7823e4ea309a8`.
The original 1,468 definitions are preserved exactly, including their order,
inputs and annotations; only the new boundary case is appended. An explicit
migration authenticates that prefix and the existing HOME-policy/Host mappings.

The reference remains OpenClaw `v2026.9.9`, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`, under authenticated Node `24.16.0`.
Official compiled execution and committed-source authentication remain distinct;
no reproduced source build or universal interleaving coverage is claimed.

## One complete admission boundary flow

The separate, frozen `forget-boundaries-session-replay` case executes nine
operations: initial A/B admission, forget preview, A/B admission, actual forget
of A, durable-owner reopen, A/B admission, repeated forget, reopen and final
A/B admission. It calls the real original corpus enumeration, source conversion
and `sessionExclusionReason`, and the corresponding SDK owners.

Both sessions are admissible initially and after preview. After actual forget,
A is excluded with reason `forgotten` while B remains admissible. The same
decisions persist after reopen and repeated forget. Retained A transcript and
catalog bytes prove that admission is rejected through durable exclusion state,
rather than by removing the source transcript. Reopen reconstructs durable
owners in the same process; this case does not claim a fresh-process restart.

All **three complete forget reports**, nine observations and ten physical
snapshots are checked. Complete memory contents, origins, tombstones and retained
session catalogs are bound to captured physical files and SQL rows. Preview
leaves state unchanged; repeated forget preserves committed state. A-only and
indivisible A+B notes are removed, while independent B memory and daily material
remain. Raw SQL dumps are checked as actual observations, without claiming a
fresh SQLite reconstruction from database bytes.

Portable admission decisions explicitly represent an absent exclusion reason as
JSON null. Original Native `undefined` and SDK `None` remain in private raw
captures; no return value is rewritten. Private SDK source timestamps are bound
to the exact physical catalog `transcript_updated_at` value, including its
monotonic revision, rather than forced to equal the fixture clock.

Only the SDK's exact empty `memory/.dreams/short-term-promotion.lock.guard`
coordination inode is excluded from the portable file map after commit. Its
presence, timing and empty bytes are independently checked, and the raw file
is retained. No other state or report field is dropped. This boundary verifies
admission; it does not claim grounded learning, publication or a full ingestion
scan. Independent B admission is observed directly.

The new family has its own capability, input hash, operation and complete-family
gate. A missing/changed case, capability mismatch or failed raw-evidence check
earns no credit. Existing outcome and zero-credit diagnostic families retain
their identities and coverage.

## Retained failures and final evidence

The first focused attempt was blocked before adapter import because the new
capability was incorrectly dispatched as a generic model capability. Its report
remains unchanged. After that dispatch was corrected, the second focused run
captured the actual matching A/B behavior, but its evidence guard rejected the
SDK's physical transcript revision. The guard now checks the captured catalog
field exactly, without tolerance or modification of the business observation.
The original rejected report remains unchanged. A read-only replay of those
captures granted no acceptance credit; the single full run executes the final
guard and actual engines together.

The complete report is parsed through EOF by the frozen CI assessor. The original
13-case forget/index-fence family, four live Host captures, three outcome captures
and new boundary capture are independently replayed on that same host before
archiving. Local review recomputes every one of the 128 condition records from
the authenticated complete projection and verifies source/exit bindings, the
single-point change and unchanged 14 public mismatch pairs. It does not claim a
local download of the full report.

Reviewed summary artifact **14196958546**: 588,454 bytes, ZIP SHA-256
`aac278f98959344d11eacfaa133caf328df193c67ac31083ad562b92f5a9b481`. Original report and raw captures remain in artifact
**14197522556**: 2,350,808,635 bytes, SHA-256 `ca6d90435cebce0201a05448b6970752ef88026f0ea37313c1e64f2bd5e009df`.
Only the small summary is transferred locally, using eight bounded authenticated
GitHub job-log parts; its reconstructed ZIP must match the original size and
digest. No large capture archive is downloaded into this workspace.

The targeted checks passed 75 tests. Changed Python adapters passed lint;
JavaScript syntax, registration and source migration were checked before the
full run. No whole regression suite, paid-provider call or second full comparison
is used for this job.
