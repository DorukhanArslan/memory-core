# Fixed #53 Doctor SDK repair

This change follows the sealed, independently reviewed before-fix observations
at clean producer `4178ceff0610c5ca3c70c8266acd164e6d95307b`. The ordinary pilot
and full 22-case/44-phase packet remain unchanged. The full before report SHA256
is `3dcd26fecddf76a0d1a2354bfed7a8be163bc569ebeb09e162b3c27133515377`;
its 753-artifact manifest is
`8b9fee9a4bbfe40c86de83d36d00faa866a962389afccaf753d7a05869bde39f`.
Those observations showed an unsupported SDK preview argument, missing durable
monitor preparation, and incorrect treatment of a single-thread Linux zombie.

`migrate_heartbeat_md(..., should_repair=False)` now performs real read-only
source validation and returns its preview warnings. It does not enroll owners,
recover interrupted claims, archive source, or write scratch. Existing callers
still repair by default. On repair, the default FileAutomationStore explicitly
prepares configured durable monitor owners before inspecting source, including
when source is absent, invalid or held. `monitor_agent_ids` identifies all
configured monitors; `agent_ids` identifies those enabled to import the source.
The former defaults to the latter. Disabled shared owners can therefore retain
their identity while enabled owners import and retain a shared source.

`FileAutomationStore.ensure_heartbeat_monitor()` returns the exact current
active owner, including an existing custom job id and generation, or enrolls
under the same existing store transaction. Doctor explicitly requests first
legacy-scratch adoption, preserving operator content, provenance, revision and
explicit unset. Construction and read APIs do not enroll. Migration holds the
returned owner through planning, compare-and-swap writes, verification and
rollback. Guarded deletion can additionally require that same active generation,
so a replacement at the same job id and revision cannot be deleted by a held
rollback. Omitting the new delete guard preserves deliberate orphan cleanup.

`FileAutomationStore(..., store_path=...)` adds an explicit filename capability.
Relative filenames are rooted at the supplied workspace; absolute filenames
are used explicitly. The existing default filename remains unchanged. This is
separate from the existing generic custom scratch-store protocol: hosts using
the small read/write/delete interface still own enrollment and storage. The
before-fix custom-store case also exposed a fixture mapping omission: its SDK
adapter always constructed the default workspace store. The corrected adapter
maps only the literal declared custom-store input to the new real public
filename argument, and all configured literal agent ids to `monitor_agent_ids`.
It does not emulate Native owners, repairs or expected snapshots.

Claim liveness reuses the existing conservative `pid_definitely_dead` helper.
Linux recovery requires actual State Z and Threads 1; unknown, unreadable,
permission-denied or missing thread evidence remains live. Live, orphaned and
multiple-claim safeguards remain in effect. No monitor is added to the
AutomationJob scheduler collection, and no cadence or scheduler execution is
introduced.

The focused public tests cover real reopen, preview mutation absence, source
validation, first operator/unset adoption, shared disabled-to-enabled owners,
custom filename partitions, a real live process and single-thread zombie,
missing thread evidence, held revision conflicts, and owner/generation ABA
during preparation and rollback. Source-map line updates are inventory only,
with no behavioral acceptance credit.

The same 22 Native inputs and approved original caller/capability/codec are used
for the corrected observation packet. Native UUIDs, archive suffixes, CLI hints,
actual error text, storage layout and physical metadata remain raw differences.
The historical before packets are never attributed to this SDK source. All
cases retain empty covers and zero credit until whole #53 review and a fresh
integrated gate.

The corrected packet has since passed independent read-only review of all 44
phase pairs and 776 sealed artifacts. The unchanged full comparisons still
differ in all 22 cases, so there is no acceptance credit. Actual preview,
durable monitor, custom filename, guarded rollback and confirmed-zombie fixes
are integrated and regression-tested. See the
[maintenance closeout](promotion_heartbeat_integration_closeout.md) for exact
producer identities, whole-suite/package results and the stop point.

## Migration outcomes with a configured state directory

During repair, a missing monitor gets a new job ID. An active monitor keeps its
ID across upgrades and restarts. A retired monitor's note can still be read by
its old ID. Supplying `state_dir` to `migrate_heartbeat_md` places the backup
under `backups/heartbeat-migration` in the host's state directory. The snapshot
filename includes the agent ID and the same source digest stored with its note.

The outcome comparison checks all 17 store fixtures and 22 Doctor fixtures. It
compares the complete repair replies, note text and revisions, ownership through
restart, retained files and archived bytes. Each run generates its own job IDs
and temporary directory names. The comparison follows each ID and name across
operations and checks whether the original file was moved. Raw findings, paths
and filesystem statistics remain available in the strict diagnostic packet.
The wording of restart instructions is tracked by `heartbeat.scratch.boundaries`.

The initial focused review of product `2ea7fb4` matched 39 cases across 69
native/SDK process pairs. Its compact JSON has SHA-256
`8ba612ab1c79d01113d5c19d041fc479a7e0be24da71ced4afe80e8a091ac528`.
The first hosted measurement matched 29 of those 39 cases. An independent
read of the archived outputs located all 13 differing strings in the change
messages of ten migrations. The note, owner and archive observations matched.
OpenClaw used the explicitly configured home when displaying paths. The SDK
abbreviated the runner account home with `~`. Product `f040ac1` honors
`OPENCLAW_HOME`, and each worker receives and records its own equivalent
fixture setting. The literal message comparison stays in force.
[First hosted measurement](https://github.com/DorukhanArslan/memory-core/actions/runs/44913992591) · [Archived observations](https://github.com/DorukhanArslan/memory-core/actions/runs/44926829799)

The corrected full measurement matched all 39 heartbeat cases. One earlier
query-sync retry case reopened. The SDK found the updated note on retry.
OpenClaw returned no results and a stale-index warning at that point. The
global measurement therefore stayed at 118/128. [Corrected measurement](https://github.com/DorukhanArslan/memory-core/actions/runs/44927413199) · [Original search replies](https://github.com/DorukhanArslan/memory-core/blob/5bd9ac41dfa66b7732a6898b6a4e02366dd836de/independent-review/heartbeat-home/query-retry-difference.json)

After preparing the pinned reference, Node, release runtime and scheduled-task
dependency as in the [comparison workflow](../.github/workflows/equivalence.yml),
run the focused comparison with `scripts/check_equivalence.py --heartbeat-scratch-only`
and the same `--reference`, `--node`, `--release-runtime` and `--report` arguments.
