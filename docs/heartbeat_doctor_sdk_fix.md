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
