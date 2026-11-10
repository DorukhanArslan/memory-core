# Host update and isolation acceptance

This records the original **66 → 68/128** package. The latest overall baseline is
**70/128**, with **58 remaining**, in the [active checklist](full-equivalence-checklist.md).
The later capture/CI corrections below award no additional acceptance credit.

Prepared 2026-11-10 (Europe/Istanbul). This package verifies **two original
conditions**, moving **66 → 68/128 (53.1%)**, with **60 remaining**. There are
31 complete, six partial and 27 pending contracts. The fixed 64-contract scope
SHA-256 remains
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`.
These percentages count verified conditions, not effort or elapsed work.

## Behavior verified

The closed four-case family verifies ASCII and Unicode preference replacement,
real write refusal, and real index-publication failure. Before replacement,
both engines actually retrieve the old preference. After a successful update,
the current answer uses the new source and the superseded-token query has no
hit. An unrelated fact and another populated agent/workspace remain intact.
After a refused update, the original source and answer remain available and
the failure is reported honestly.

Both engines use their real host loops and memory tools. Native coding
`write`/`edit` tools and SDK curated-memory tools are declared corpus producers;
their distinct raw API receipts are custody evidence rather than a claim of
write-tool API equivalence. Complete later search/get results and explicit
publication outcomes are compared. Answers come from actual get results, using
ranges selected by actual search hits. Source bytes and original dispatch,
result, refusal and publication receipts are bound by the evidence guard.

The write-refusal case makes a real second hard link only during the update.
The publication-failure case places a dangling symlink at the path that the
actual index publisher must open: Native's reindex-lock sidecar and SQLite's
SDK rollback journal. The committed file remains newer than the published
index; the next search reports the stale index and actual error. The fault is
then removed and a genuine successful publication restores the current result.
No fake exception, repaired output field or numeric tolerance supplies a match.

Both original `host.update-isolation` points require all four exact frozen
cases together. Incomplete, mismatched, blocked or unverified families cannot
receive either point. The [literal manifest](host_update_isolation_literals.json)
and earlier restart families remain unchanged by this verification package.

## Readiness correction

Review found a public direct-curator path that could commit a changed file,
fail real SQLite publication, yet leave `owner.publication_status()` claiming
ready because no runner had created a durable turn marker. The owner now also
reads actual retained memory-scope/full-publication failure state through its
ungated lifecycle snapshot. It conservatively reports pending, including after
close. Session-only success cannot clear a memory failure; a matching real
publication can restore readiness.

Three real filesystem regressions cover direct curator failure, scope-specific
recovery, whole-publication failure and closed-owner status. The correction
does not invent a failure, change frozen inputs or add another publication.
Normal eager APIs retain their behavior.

## Fresh complete catalog

The full gate ran on clean code commit
`57270dae8728f04a7f1293c59a5a1cd2abf7f777`, with **159 SDK Python files** and
canonical source SHA-256
`dad4499f58eb316a23bc674c7adbde87f231e9c5d054f2d18a25b729aadc1cb9`.
It uses pinned OpenClaw `v2026.9.9`, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`, and exact Node `v24.16.0`
(ICU 78.3, Unicode 17.0), executable SHA-256
`b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`.

In **1,605.968497 seconds**, the complete run executes **1,411 cases: 1,397
matched, 14 mismatched, zero blocked and no runner errors**. All four update
cases match with verified Native and SDK evidence. Both original conditions
are complete. There are 58 uncovered conditions plus two registered but
unresolved boundary conditions, so **60 remain**.

The full gate remains `mismatched` and `fullScopePassed=false`; this is bounded
coverage growth, not complete OpenClaw equivalence. The retained report is
`work/host-update-isolation-full-001.json`, 501,986,442 bytes, SHA-256
`6e402cbc21cd7fa2ac5b66b12f5313cbab56a8aaafa4b1ad03ee5c2fc003b6f7`.
The [committed diagnostics](host_update_isolation_diagnostics.json) retain all
four complete public Native/SDK results, original raw diagnostic hashes and
successful custody replay. Large actual captures remain in ignored `work/`
and `.equivalence-results/`.

An independent retained-evidence audit checks all 1,407 prior case identities,
inputs, coverage and statuses unchanged, and exactly four new matching cases.
It replays both custody guards and verifies 29 public reads per engine against
actual dispatch/results and source lines. The audit is
`work/update-final-audit.json`, 778,898 bytes, SHA-256
`162d712e48f9a8a4f70dea7a7a2896be367b20b5d26e8ea5aad6d453fffb8032`.
It adds no new execution or acceptance credit.

## Verification and retained evidence

Full regressions pass **7,797 tests**, with **1,648 uncredited skips**, in
377.61 seconds. No new skip is added. Both offline installed wheel and sdist
consumers pass; the valid typed consumer passes and **24 invalid calls** are
rejected. Ruff, source inventory and diff checks pass. Inventory remains
64 contracts, 128 original conditions and 196 upstream modules, and awards no
behavioral credit by itself.

The clean Claude input `db62dee` produced four matching development comparisons,
zero blocked/errors, with report SHA-256
`0dada6e39db9b433e80a96a7bb571a98a5d68dac6999998c5ba0f02aafe84674`.
After the readiness correction, the clean final SDK again matches all four;
that report SHA-256 is
`e8a8fa94c83afdfe98c5dae02a37a7b25ba2d360d9e86774cebe6078e813776d`.
Neither standalone report awards acceptance points; the fresh complete catalog
above supplies credit. The reports retain their own source identities and are
not relabeled as one another.

The original four sealed capture directories were copied byte-for-byte into
an explicitly labelled replay cache. All 163 recorded artifact hashes were
verified; files have independent inodes and no record or expected value was
rewritten. This let all **490 evidence tests pass with zero skips** against
genuine retained Native captures and fresh SDK fixtures. Replay is not a new
Native execution or another acceptance award. The replay-cache audit is
`work/update-native-capture-audit.json`, SHA-256
`9c92c4508c5efb7861c7962f35ee03da04bc6e37d0c8ffbdb7eaa5ad20ab68c8`.

## Declared limits and next work

This is an explicit-publication, provider-none host profile. It does not verify
automatic refresh timing, coding-versus-curation API identity, SubjectMemory
routing, embeddings or `consolidateMemory` execution. Source and official
compiled runtime provenance are authenticated separately; no independent source
build is claimed. No paid provider calls occur.

The update guard binds actual dispatch, source bytes, faults, publication and
retrieval dataflow. It does not claim the restart family's complete per-message
commit-to-physical-SQL/readback chain; those older chain counts are not reused
as evidence for this family.

The next original host contract is `host.turn-barrier` (#62): save naturally
and ask the immediate follow-up, without inserting forced synchronization.
Required maintenance settlement, optional maintenance preemption and honest
failure before the next admission need separate measured schedules. For example,
after “Remember that I take tea without sugar,” immediately ask “How do I take
tea?” and observe both the real answer and whether the next turn starts before
the required save work has settled. A pending optional job and an already
running writer are different boundaries.

## Capture and CI follow-up (2026-11-10)

The four follow-up commits ending at `fbe94b9` were integrated with the natural-turn
work on clean code commit `c45cb03fb02a5e029c903cc80356c9795789b5a2`. They correct the
comparison infrastructure without changing the SDK, frozen literals or scope:

- Accept the original hard-link refusal when its own path helper spells the same
  fixture paths relative to the process home as `~`. The guard still requires the
  exact refusal cause, this run's fixture directory, its workspace and `MEMORY.md`;
  mixed homes, other files, generic `~/workspace` and extra text are rejected.
- Remove an ignored ranking setting and require the actual original query defaults.
  Prompt assembly and ranking remain declared limits: the SDK includes its own
  `MEMORY.md` in project context while this original actor uses an empty system
  prompt. Answers are scripted from tool results; compared searches have at most
  one hit, and the original does not apply temporal decay to `MEMORY.md`.
- Record an entry as `vanished` if it disappears during the diagnostic filesystem
  listing. Custody does not use that listing; source, index, dispatch and transcript
  checks remain separate. Missing roots and errors other than `ENOENT` still fail.
- Retain reports from the hidden results directory and update-family host streams
  and raw captures in GitHub Actions. Replay the capture guard tests after the
  comparison, including a failed comparison. Missing captures can still cause
  replay skips; a green replay step alone does not establish Native execution.

Four fresh actual Native/SDK comparisons all match, with **zero mismatches,
zero blocked cases, no runner errors and successful final authentication**.
Both custody snapshots validate for every case. The standalone report is
`work/host-update-followups/attempt-001/report.json`, **16,477,206 bytes**, SHA-256
`85463fef47fb43e0587501d26c0e394377991ea1b9759c3c2951f802ef1944c3`.
It records the unchanged **159 SDK Python files** and canonical source SHA-256
`03bf15292a2a795c7e0a5897eb3cc742d2ba61ec11be516c9cbf16d5230c9aa2`.

An independent audit replays all four custody and protected Native trace checks,
rehashes **163 retained artifacts**, and confirms all eight complete public results
equal the committed update-family baseline. It records all eight actual raw files
in `work/host-update-followups-audit.json`, **6,562 bytes**, SHA-256
`b5ce9fa2b66731b141d88421aefbcaa3aa203d0079de8c0060e72017783cb2df`.

This focused rerun awards **zero new conditions** and does not rerun or relabel the
earlier complete catalog. The overall verified baseline stays **69/128**, with
**59 remaining** and the earlier **14 differences** still recorded. Next remains
the separate `host.turn-barrier.boundaries` condition: pending optional maintenance
and an already running writer need their own measured schedules.
