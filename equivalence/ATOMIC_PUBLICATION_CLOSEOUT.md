# Atomic publication closeout

Independent review approved staging the two original `storage.atomic-writes`
conditions for the exact Linux, default NAPI, operation-return profile. The
default catalog now maps all 41 whole-operation cases to
`storage.atomic-writes.outcomes` and 32 cases to
`storage.atomic-writes.boundaries`. Main points remain conditional on a fresh
combined comparison and the required regression and package gates.

No production change is included in this metadata closeout. The verified SDK
production source SHA-256 is
`50071dd8158f1edf34dbe27fe53dd1930c0d6a8d4db047aae79b556b3354771d`.

## Retained proof history

Every historical report keeps its original empty `covers` lists. The metadata
review does not rewrite those reports or their failures.

| Observation | Result | Retained artifact |
| --- | --- | --- |
| Original development packet | 31/32 matched; physical receipt difference retained; unprotected and uncredited | `atomic-c-final-development/packet.json` in the original atomic-publication worktree |
| First protected packet | 33/41 matched, 8 ordinary mismatches, 0 blocked | `atomic-protected-first41.json` |
| Second protected attempt | Blocked at replacement read/cleanup/close after 34 prior Native cases | `atomic-protected-second41.json` |
| Independent return/exit diagnostic | 1/1 matched; return and exit trees differ visibly | `atomic-return-exit-first1.json` |
| Third protected packet | 41/41 matched, 0 mismatches, 0 blocked, no errors | `atomic-protected-third41.json` |

The protected artifacts are retained under `.equivalence-results/` in the
atomic-proof worktree. The successful third packet ran from clean commit
`5367136fa5a4387cc459a9912712db216084e670`. Its report SHA-256 is
`21a7a0362f0515a715fca9b997b43582c2990cc953c2df673f095f97d98f1586`.

The first eight differences exposed genuine SDK defects: preparation/cleanup
aggregate messages, overwritten append errors, lost bootstrap settlement
receipts, and the different lost-reply domain of link-plus-unlink publication.
The SDK now uses source-based settlement phases and a genuine exclusive rename.
Complete original errors, causes, arrays, fields, IO, bytes, modes and physical
identities remain available in the reports.

## Return and process exit are distinct

The second attempt compared a snapshot at original owner return with a collector
reread after process exit. The original replacement owner had registered its
retained stage for genuine exit cleanup. Its original exit handler removed that
stage after the adapter snapshot, so the completeness guard correctly refused
the mistaken same-phase comparison.

The second report retains the original raw return snapshot, streams and guard
failure. That attempt did not retain the full differing collector tree. No
missing post-exit observation was reconstructed or inserted afterward.

The corrected proof uses an atomic-only immutable trusted preload observer. It
invokes the exact original exports from the bound literal case, records actual
Promise settlement, and accepts no supplied function, result or tree. An
exactly-once return checkpoint independently reads the entire owned subject with
original pre-hook, no-follow descriptor IO and binds the actual journal hash.
The adapter's complete return tree is checked against that observation.

Original exit hooks remain enabled. Their actual owned exit IO, a separate
trusted exit tree, and an anchored post-process reread are retained separately.
The diagnostic and final packet visibly preserve three entries at owner return
and two after the original exit cleanup in the affected case. No stage was
discarded from the return result to force a match.

## Exact acceptance mapping

All 41 cases contribute their complete operation outcomes. The 32 boundary cases
are the 30 cases with literal IO/mutation faults plus the two genuine read-only
directory/target permission flows.

The following nine cases map only to outcomes; every other atomic case maps to
both original conditions:

- `storage.atomic-writes.ordinary-replace`
- `storage.atomic-writes.bootstrap-missing`
- `storage.atomic-writes.bootstrap-existing`
- `storage.atomic-writes.append-existing-newline`
- `storage.atomic-writes.append-existing-without-newline`
- `storage.atomic-writes.append-leading-newline`
- `storage.atomic-writes.append-missing`
- `storage.atomic-writes.cooperating-checked-replacements`
- `storage.atomic-writes.exclusive-bootstrap-winner-during-staging`

There are no source-only or helper-only credits. Actual append, checked
replacement, exclusive creation and concurrent writers execute the original
owners. Boundary cases retain real partial writes, sync failures, publication
failures, secondary close/cleanup failures, foreign entries and indeterminate
receipts with their complete surviving trees.

## Authority and limits

The source reference remains OpenClaw commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. The approved executable is exact Node
24.16.0, ICU 78.3, Unicode 17.0, with its authenticated SHA-256. Source and official
release-byte authority remain distinct; source-build reproduction is false.
The default Linux NAPI binary and every required owner remain authenticated.

Receipt tokens require actual exclusive allocation, actor/fd generation and the
corresponding prepared post-sync fstat. Rejected exclusive attempts have their
own namespace and cannot impersonate allocated stages. Original physical values
remain raw. General timestamp normalization and numeric tolerance are absent.

The SDK contains Linux `renameat2(RENAME_NOREPLACE)` and Darwin
`renameatx_np(RENAME_EXCL)` paths. Unavailable ABIs fail before staging. Darwin
execution is untested; Linux proof does not establish macOS runtime equivalence.
SDK/reference process-exit registry interchangeability and restart behavior are
also unclaimed. Exit observations qualify the operation-return scope explicitly.

There are no provider, index, manager, worker, scheduler, full agent-tool or paid
model-call claims in this profile. Real `RLIMIT_FSIZE` development diagnostics are
retained separately; protected partial-write seams do not impose a process-wide
limit that could truncate their own trace.
