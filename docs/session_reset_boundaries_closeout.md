# Session reset-hook boundary acceptance

The complete assessment verifies **82/128 conditions (64.1%), 46 remaining**:
**38 complete, six partial and 20 pending contracts**. The original
`sessions.reset-hook.boundaries` condition is verified: **81 → 82/128, net +1**.
The fixed 64-contract, 128-condition scope is unchanged. All previously verified
conditions remain verified; `sessions.reset-hook.outcomes` stays open.

## Frozen source and authority

- Full comparison: `a1bdec4e12fd434fdbb868f0ca0fb2319811fc4e`.
- Approved product source: `3d70e59d5a282bfa22738451244b37e35662f38d`.
- SDK source SHA-256: `ae9c42578a913e04816b67831d70b540bd89bb1e65c07d9a656efc00f7df283b`, across 162 files.
- Original OpenClaw `v2026.9.9` source: `bcfc88812a35243893585dbeca87ca41b48272ca`.
- Seven-case input map SHA-256: `6d2d4043125f71ae236fe4482af8e2aec408d9a63b0ea00de201d315daa500ae`.
- Original owners: 51 source bindings, 41 compiled artifacts, 39 required loaded
  artifacts, 29 observed owner triples, 12 source links and one native fs-safe artifact.

The official published runtime is authenticated separately from the pinned
source; a reproduced source build is not claimed. Product source was unmerged
when measured. The comparison SDK exactly matches its 162 product source files,
and source-after evidence preserves the frozen source and adapter identities.

## Product change and compared boundary

The production diff changes only `memory_core/session_memory.py`: 19 additions
and six deletions, **net +13 lines**, including the corrected explanation.
Capture now selects the latest reset on the actual visible branch, keeps its
explicitly retained user/assistant prefix, and includes subsequent events before
applying the existing capture limits. Compaction alone does not close this
history window. Discarded ancestors and unselected branches remain excluded.

Seven cases contain **47 operations: 10 hooks, 10 syncs, 13 searches, 10 get-all
operations and four fault/mode controls**. They cover owner/nonowner and tainted
input, Unicode/multiline source text, reset-kept prefixes and branches, seeded
and successive same-minute filename collisions, SQLite trust failure/recovery,
and actual POSIX publication EACCES with reservation rollback and recovery.

Native uses the real registered manual new/reset hook, dispatcher and pending
write drainer. Actual SQLite transcript owners persist/read the complete input
tree, and the hook performs its own capture. The driver supplies neither a
preprojected window nor `previousSessionMemory`. SDK rereads its host-persisted
raw tree and invokes real save, trust, indexing and search/get owners. Explicit
provider-none index sync and real tools follow publication on both sides.
UTC, default capture limits and `llmSlug:false` are fixed inputs.

Every complete memory Markdown artifact, every full public trust record in a
path-keyed map, and every ordered whole decoded search/get payload compares.
Hits, scores, citations and provenance fields remain present. Actual reader-list
order remains unchanged in raw evidence; cross-language list ordering is not
the shared trust-map contract. Real returns, exceptions, complete owned logs,
SQL/index state, physical files, source identities and IO/drain receipts remain raw.
Native logged failures and SDK raised failures are not mapped to a success flag.

Connection-local **TEMP triggers on the original main handle** observe trust
writes; a persistent audit table retains their committed rows. Full live temp
schema is captured separately from physical main SQL. The declared Native SQL
fault also uses a TEMP trigger. Canonical schema validation remains active;
actual failure and reservation/rollback receipts are required. The original
TEMP-trigger examples are static source proof, not executed upstream tests.
Replay proves zero committed reservations for the SQL-abort hook, and a real
committed INSERT followed by its matching compensating DELETE for the EACCES
hook. Both cases recover after their external fault is removed.

Actual source mtimes and wall-clock inputs are paired before indexing/recall.
SDK clock receipts prove restoration and unchanged datetime arithmetic/ranking
owners; no returned score is rewritten. Real asynchronous recall owners are
drained before complete physical capture.

## Retained failed attempts and targeted validation

The production reset-window fix preceded all three focused attempts. Each
failed report remains immutable and earns no global credit.

| Attempt | Retained result; report duration | Cause |
| --- | --- | --- |
| 001 | Blocked; 17.95 seconds; exit 2 | Observational reader selected the default agent DB instead of the genuine seeded-scope transcript DB. |
| 002 | Blocked; 17.96 seconds; exit 2 | Canonical worker validation correctly rejected permanent observer triggers; genuine TEMP triggers corrected the fixture. |
| 003 | Six validated mismatches, one SDK block; 94.57 seconds; exit 2 | SDK ranking clock was unpaired; the guard rejected a genuine empty get-all's zero calls. |

Focused-003 report SHA-256:
`8df831dd0ae7b36b0080d4653cb953efb3ba62f609c07a17eb0008e22d776046`.
The TEMP revision changed only the trust-fault Native SQL prefix and its seals;
the 47-operation order and whole compared result fields stayed fixed.
Later clock/guard corrections changed only adapters, preserving production SDK
bytes and all Native captures. Nine targeted SDK checks plus six authority
checks passed in **0.22 seconds**; only six authority checks were repeated after
the TEMP seal revision, passing in **0.07 seconds**. No full Python suite ran.

SDK-only helper 001 failed during import, executing zero acceptance engines.
Helper 002 validated seven fresh SDK runs against authenticated retained Native
003 packets: seven raw-valid whole matches in **2.872 seconds** internally
(6.944 seconds for its parent process), zero fresh Native runs and zero global
credit. This development check did not replace the failed focused report.

## One full comparison and independent audit

The [single full run](https://github.com/DorukhanArslan/memory-core/actions/runs/43961408161)
retains **1,490 cases: 1,476 matched, 14 mismatched, zero blocked and no runner
errors**. Actual exit is **1**, OS elapsed time **5,568.25 seconds**. The full gate stays
failed: **44 uncovered and two registered unresolved conditions** remain.
Full report SHA-256:
`f972a33cafa280c0a58098f3b3e5616185a33bd23df769ecb4d221a6b5f9544f`.

All previous 1,483 definitions remain an exact prefix, SHA-256
`33277abb724a6b89423085e735fc08b950b647b577db9879df8f2395e519a93d`.
The seven-case append yields catalog SHA-256
`a6b6d9d2fee122e0759d421d0d170ab171fecc58e86bbb3f322dc0154742d7b8`.
All **13 family gates** hold. Independent replay validates FIF13, Host4, forget
outcomes3/boundary1, recall6, cache8 and reset7. Reset replay confirms all 47
operations and their 10 hooks/10 syncs/13 searches/10 get-all operations. Native
retained complete captures are authenticated; deleted Native temp roots are
not claimed reopened. Actual retained SDK physical files are reopened.

The frozen CI assessor parsed the complete report to EOF. Independent local
root review recomputes all 128 conditions and confirms exactly this one-point
change, preserved previous credit and unchanged source/exit bindings. Review SHA-256:
`70187575703adf4f0cbf308aad54be4e690d45592222a8ceb30ca9930fa28ccb`.
All 14 old SDK whole-public hashes are unchanged. Only Native
`flush-execution-warm-index-first-recall` changes its public hash to
`cb844e6214b8fd7526c42e6e3dd968c97ea9963230260e4c29ce178f0fb94ec5`;
it remains mismatched and receives no credit.

Only the **647,615-byte** summary ZIP, artifact **14280809935**, was retrieved:
SHA-256 `37f342b5d80d59243559bb8ce881761825cd6f9e44326a6ca75e57d488cceb54`.
The **2,408,984,153-byte** raw artifact **14281278336** was not downloaded;
its metadata digest is `3da71327f7c08fd7a8aa253895570d589097960b326a31112e08c085456f79b4`.
Root review uses the complete CI projection and replay receipts, not a claimed
local download of the full report or a second execution of original engines.

## Remaining scope

`sessions.reset-hook.outcomes` remains open. Sequential drained collisions do
not prove arbitrary concurrent/late-creator exclusive publication parity:
Native prechecks availability then uses replacement-capable `Root.write`.
Incognito admission, automatic reset, model-generated slugs, universal Gateway
registration and complete HostKit startup/lifecycle also remain unverified here.
The source-map classification stays **partial**; its only numeric edit moves
the existing `save_session_memory` anchor **1089 → 1102**.
