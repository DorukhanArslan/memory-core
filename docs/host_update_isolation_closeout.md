# Host update and isolation acceptance

This records the original **66 → 68/128** package. The latest overall baseline is
**69/128**, with **59 remaining**, in the [active checklist](full-equivalence-checklist.md).
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

## Second-environment record (2026-11-10)

These runs were made in a separate environment from the credited run and from
the follow-up above. They award no condition and are not relabeled.

**Hosted incident.** The hosted differential job had ended `blocked` (exit 2)
with `host-update-evidence-invalid`, instead of its known `mismatched` state,
for the first pull request of this package and for its merge (runs 42779752218
and 42781400036). Its reports were not retained. Running the write-refusal case
with the fixture below the process's home reproduced the block; it matched
after the first correction. With the checkout itself below the process's home,
all four cases then passed through the real gate path.

**Complete runs.** Each ran on a clean commit as an unprivileged account
without capabilities and with an empty home directory, which stayed empty.

- the first merge `5da6169`: 1,411 cases, 1,397 matched, 14 mismatched, zero blocked, in
  1,900.486715 seconds; report 502,347,294 bytes, SHA-256
  `8b1a3ff1948293c712e3cfe1fb720e7bf3b378fb16c35e8894079898c6af46a0`.
- the first two corrections, `7c2a43d`: 1,411 cases, 1,397 matched, 14 mismatched, zero blocked, in
  1,943.781972 seconds; report 502,274,707 bytes, SHA-256
  `364a421a89912d0d91704f7387670a478d5d69c7dee2ce6c8058c8c73f3398fa`.
- all four corrections, `fbe94b9`: 1,411 cases, 1,397 matched, 14 mismatched, zero blocked, in
  1,910.907751 seconds; report 502,280,550 bytes, SHA-256
  `2c0f08d5aa4d8bdf07f8d673d8eb433baca9514a12c22a0bb33cb5e3cb2cb121`.
- the integrated tree `3dafdb5`: 1,415 cases, 1,397 matched, 18 mismatched, zero blocked, in
  2,100.527191 seconds; report 529,512,935 bytes, SHA-256
  `b81c7674da864c57088d23cc44a5f6057d21f4772180291a03ec08c1a7b689f1`.

The first three have the credited SDK source identity, the same 14
differences and 68 verified conditions. The last has the integrated source
(`03bf15292a2a795c7e0a5897eb3cc742d2ba61ec11be516c9cbf16d5230c9aa2`).
Its 18 differences are those 14 and the four natural-turn cases of the later
package: there the original's first cold search carried no automatic-repair
notice, while the SDK's did. That report therefore also counts 68 verified
conditions. The hosted `main` job (run 42809917492) logged the same counts,
while the hosted pull-request job on the same tree (run 42808405837) logged
1,401 matched and 14 mismatched. The hosted reports could not be read from
this environment, so their case rows were not inspected. That question
belongs to the natural-turn package and is not settled here.

All four update cases matched with validated evidence in each of these four
runs. After the corrections neither hosted job was blocked, and the
capture-replay step passed on the hosted captures in both. Full regressions
on `fbe94b9` pass **7,804 tests** with **1,674 uncredited skips** there. The
reports were retained in that environment's working storage and are not
preserved with the code.

**Earlier attempts.** They are retained and earn nothing.

- The first complete attempt, on clean `a090388`, ended blocked after
  724.668175 seconds at the existing case
  `flush-execution-conditional-separators`, before any case of this family ran
  (report SHA-256
  `f8d47b2a4a2ede1dd6b07627ca6585e6caed18614532c3ef2c6d85f3555dce2b`). The cause
  was the run environment: the unprivileged namespace mapped the process to an
  account whose home directory it could not search, and the original's legacy
  workspace-state check treats an unreadable path as possibly present. Alone,
  that case blocks under the same mapping and matches under an account with an
  accessible empty home.
- A complete run on clean `330b0ac` matched all four cases of the earlier
  literals (1,411 cases, 1,397 matched, 14 mismatched, zero blocked; report
  SHA-256 `fd931d4a8eb501b2cceff56771f54a88f1baafe6fb9e4db3bab72c391c6d7394`).
  Independent review then found that the capture guard checked little of what
  executed, that the crediting lines had no test, and that the superseded
  query had no positive control. The literals were re-frozen and the guard and
  tests strengthened before the credited run, so that run supplies no credit.

**Limits not listed above.**

- The original resolves each agent's workspace from its configuration. On the
  SDK the host adapter opens one owner per agent on separate workspace and
  index paths.
- On the SDK the update tool's own refresh has already failed with the same
  error when the stale read runs. The compared payload cannot show which
  record produced the report; custody receipts bind the forced publication.
- The source timestamp is the same before and after the update, so a
  provenance timestamp change cannot be seen.
- The original prints the refusal through a helper that needs a resolvable
  home directory. A runner whose user has neither an account entry nor `HOME`
  was not tried.
