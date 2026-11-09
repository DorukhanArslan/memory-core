# Promotion and heartbeat maintenance integration

This is the historical zero-credit maintenance closeout. Subsequent work is
recorded separately in the [promotion apply/reconciliation closeout](promotion_apply_reconcile_closeout.md):
its fresh integrated baseline verifies 64/128 conditions. That later evidence
does not rerun or relabel this maintenance package's original captures.

The later [host restart development packet](host_restart_recall_development_closeout.md)
adds three authenticated but mismatched process comparisons and awards zero
conditions. The current verified baseline remains 64/128, with 64 remaining;
this document's 62/128 figures below describe its historical maintenance baseline.

This package integrates already reviewed fixes for the existing promotion and
heartbeat contracts. It adds no acceptance condition and awards **zero new
acceptance points**. The last full differential baseline remains **62/128
(48.4%)**, with **66 conditions remaining**: 28 complete, six partial and 30
pending contracts. This percentage measures verified conditions, not effort or
time. The fixed 64-contract scope SHA-256 is
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`.

## Behavior fixed

- Promotion rejects candidates with no live source before reading MEMORY.md,
  planning a model request, or acquiring a promotion write lock. Rejection
  receipts and the SDK's richer result remain available. A valid candidate
  still respects the actual competing lock and is promotable after release.
- Heartbeat scratch belongs to a durable monitor identity and generation.
  Prepared host turns and first Lab edits retain that owner; competing edits,
  deleted owners and replacement generations cannot overwrite newer state.
- Doctor preview validates source without mutating it. Repair explicitly
  prepares configured monitors, preserves legacy operator notes/unset state,
  supports an explicit store filename and guards writes and rollback with the
  held owner, generation and revision.
- A confirmed single-thread Linux zombie claim can be recovered. Live,
  orphaned and multiple claims remain protected; unreadable or denied process
  evidence remains conservatively live. Scheduler execution was not added.

## Retained original comparisons

The promotion comparison retains its genuine directory-read failure before
the fix and matches the same input after the fix. Both immutable reports and
the source/capability limits are recorded in
[the promotion plan](promotion_apply_reconcile_plan.md). This is one bounded
input with empty coverage, not completion of contract 43.

Doctor retains the same 22 inputs and 44 Native/SDK phase pairs before and
after the fix. Corrected report SHA-256 is
`ed1c8aa06b8925af79c5b766d84ee4bab392b76cccca529d9b19551974536ca7`;
its 776-artifact manifest is
`08b2f3a75300772a48d086bd159390a798a212ffd19331cc16e20ec723dbc367`.
Independent review verified all artifacts and phases. Preview and durable
owner outcomes are fixed, but all 22 whole comparisons still differ under the
unchanged comparison rules. Actual IDs, CLI hints, physical paths, file
statistics and errors remain visible. Agreement of selected final monitor
fields is descriptive only and receives no credit. See
[the Doctor fix](heartbeat_doctor_sdk_fix.md).

The last complete differential catalog ran on `21177bf` with SDK source hash
`38f3c9ce2fcca74060c81b01ad17f893d6a5cd5d186061eed1a2f9158929192d`:
1,395 cases, 1,381 matches, 14 differences, no blocked cases or runner errors.
This maintenance closeout does not rerun that complete catalog or attribute
its historical evidence to the changed SDK. The acceptance count is unchanged;
the full gate remains mismatched/incomplete.

## Integration checks

The fresh complete regression run at clean
`10a9fbddeed0ad8b9dba46bcccb7fdde555d4c40` passed **6,713 tests, zero
failures and 1,625 historical/live skips in 429.28 seconds**. Skips grant no
acceptance credit. The 156-file SDK source SHA-256 is
`d420a282498ae38fbabd5026795e49332ccc343515b89f3d050179fd82849ad0`.

The first integration run at `d3af932` is retained unchanged: 6,712 passed,
one stale fixture failed and 1,625 skipped in 442.79 seconds. That fixture
held a promotion lock with no candidate. The corrected test records a real
recall against a real daily source, checks that the held lock preserves
MEMORY/source/recall and its own bytes, then promotes the exact same candidate
after release. It keeps the original locked-result expectation and changes no
production code. The focused promotion selection passed 45 tests.

Both clean offline wheel and sdist installation consumers passed at `d3af932`
with the identical SDK source hash. They check installed imports, real FTS and
host lifecycle, save/immediate recall/reopen, continuation and replay, trust,
public types and ten rejected invalid typed calls. They are not source-tree
imports presented as installed-package evidence.

Lint-only follow-up `5a46af3d3e83906129af3178c7b3777fe875f3eb` removes an
unused probe import and splits compound test statements. Its 45 affected guard
and scratch-authority tests pass in 4.37 seconds; all 36 changed Python files
pass Ruff. No SDK bytes changed. Historical protected captures remain bound to
their original producers and are not relabeled as executions of this edited
probe. Source inventory validates all 64 contracts, 128 conditions and 196
upstream modules; inventory itself grants no behavioral credit. Diff checks pass.

Retained integration log hashes:

| Local artifact under `.equivalence-results/` | SHA-256 |
| --- | --- |
| `heartbeat-promotion-integrated-regressions.log` (first failure) | `a9df794cd15948bce79243933ddd0f591af4bdea5023c7aad7f9e18ab10ae92d` |
| `heartbeat-promotion-integrated-regressions-real-candidate.log` | `3c25d5ed8e8b5fc2370cc65fd5b465ac653db0ee6f280f0e4cb5f9bd32df6da5` |
| `heartbeat-promotion-integrated-distributions.log` | `5ab5b80c2988231235994c790d95f1a56baeb13b3e2431d30e65498e4cd73827` |
| `heartbeat-promotion-lint-followup.log` | `f74be41fe67fa9552ff38e6f3c829ff9e0bee58357450396cea352de1098c0f2` |

Logs remain in this integration worktree; large raw packets remain in their
original sealed local directories. They are not claimed to be uploaded by a
Git commit. All checks used blank provider credentials and no paid model calls.
Reference source-build reproduction remains false.


## Stop point

At the user's request, work stops after this integration closeout. Expanded
executable preparation for the eight additional promotion inputs and whole-host
restart proof remains in separate branches. The provisional promotion literal
proposal included in this package is not an executed or accepted comparison.
The expanded adapters are not merged and receive no acceptance credit. No next
task, new protected capture, provider request or environment publication is
started as part of this closeout.

The status of every contract is retained in
[the full checklist](full-equivalence-checklist.md). No additional user detail
is needed to review this package; further work awaits the user's next command.
