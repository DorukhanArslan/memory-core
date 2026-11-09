# Bootstrap discovery: native comparison evidence

This package compares the real OpenClaw bootstrap callers with the Python SDK.
It does not claim full workspace lifecycle equivalence or award coverage points.
Every scenario currently has `covers: []`.

The fixed condition is `prompt.bootstrap-discovery`:

- Outcomes: exercise setup states, session kinds, available files and compatibility layouts.
- Boundaries: compare ensure decisions, selected files and their order under the same inputs.

## Actual caller boundary

The original reference is the unchanged OpenClaw commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. The installed official release executes:

| Original export | Release entry |
| --- | --- |
| `ensureAgentWorkspace` | `dist/workspace-C0LMBmap.mjs`, export `t` |
| `loadWorkspaceBootstrapFiles` | `dist/workspace-C0LMBmap.mjs`, export `s` |
| `resolveBootstrapFilesForRun` | `dist/bootstrap-files-CgqY-7GK.mjs`, export `c` |

State snapshots, setup/status reads and state database close also call their
original release owners. The initial binder authenticated 29 source owners,
22 compiled owners, 34 import edges and five literal packaged templates. The
configured-classifier extension authenticates 40 source owners, 30 compiled
owners and 49 import edges. Earlier reports retain their original manifests.
The release was not rebuilt from source; `sourceBuildReproduced` remains false.

Each Native case and each SDK case runs in a fresh process. The Native profile
requires Node `v24.16.0`, ICU `78.3`, Unicode `17.0`, and executable SHA256
`b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`.
Only the `Date` clock is fixed. Fetch is denied; credentials are not forwarded.
No paid model calls are made.

The compared output contains complete ordered loaded/selected file objects,
warnings, ensure decisions and setup/status results. The only path alias replaces
the exact owned fixture prefix with `$FIXTURE`. SDK dataclasses use the declared
Native file wire shape; all extra SDK metadata remains in its raw observations.

Raw evidence retains both complete own API returns/errors, literal requests,
filesystem bytes and stat fields, independent directory enumerations, `.git`,
Native setup/attestation state, SDK JSON setup state, actual PIDs and authenticated
process/import traces. SQLite and SDK JSON state are not claimed to be physically
interchangeable. Registered hooks, remote access and personal profile overlays
are not replaced with fake managers or callbacks.

## Fixed eleven-case packet

The literal packet covers initial setup and customization; exact-case/sparse
files; creation templates and optional-file suppression; repeated reads in one
session; the SDK's default layout extension; purpose; implicit provisioning;
configured classification; disabled bootstrap seeding; guarded file reads; and
the legacy-state gate. Inputs were unchanged between the first and corrected runs.

| Actual proof | Clean SDK commit | Matched | Different | Blocked | Errors |
| --- | --- | ---: | ---: | ---: | ---: |
| First paired eleven | `6aa5adbcd073bed813f7dabb39e3057c47cbd05b` | 4 | 7 | 0 | 0 |
| After genuine creation/provisioning API fixes | `7ecd4c0` | 8 | 3 | 0 | 0 |

The first report is retained unchanged at
`.equivalence-results/bootstrap-discovery-first-paired-11.json`:

- Bytes: `78619748`
- SHA256: `29457ad9966b0a12539a95b23e50d23d0e22e73b78811b4affeb8080ebbf654e`
- A byte-identical gzip copy and manifest are committed under
  `tests/fixtures/bootstrap-discovery-protected-transport.json.gz`.

The corrected report is retained at
`.equivalence-results/bootstrap-discovery-corrected-paired-11.json`:

- Bytes: `78671451`
- SHA256: `18bc3a95796e5142bc1e6bea781dfc27b62e74898331a9977f3eba3bb69c38d9`
- Actual runtime evidence: eleven Native processes and eleven SDK processes.

The original Native-only development observation remains separate. It demonstrated
the three genuine exports but is not the paired proof or a source of coverage.

## Production changes

`initialize_agent_workspace` now distinguishes the host's existing `templates`
baseline from `creation_templates` for the supported three creation-time role
files. Creation bytes do not replace the setup-detection baseline.

The real initializer also supports approved `purpose` instructions,
`provisioning="runtime-managed-implicit"`, and `ensure_bootstrap_files=False`.
It preserves existing files and uses the shared atomic publication owner.
`bootstrap_pending` reports the ensure decision independently of a later status
query. Implicit provisioning returns `state=None` and `bootstrap_status=None`
because it does not read those facts.

The corrected paired run repaired the four original mismatches in those paths.
All 392 targeted bootstrap, authority, raw replay, transport and atomic-root
tests passed before that run. The exact source inventory also validated.

## Qualified acceptance definition

The outcomes interpretation is limited to ordinary successful local operations
using the explicit six-role OpenClaw-compatible layout and the built-in memory
owner. This definition was declared before the next paired run. It requires
all nine of these cases to match:

- `bootstrap-discovery-initial-whole-exports`
- `bootstrap-discovery-canonical-sparse-and-exact-case`
- `bootstrap-discovery-custom-three-templates-and-optional-skip`
- `bootstrap-discovery-same-session-repeat-after-write`
- `bootstrap-discovery-unsupported-purpose`
- `bootstrap-discovery-unsupported-runtime-managed-provisioning`
- `bootstrap-discovery-unsupported-configured-classification`
- `bootstrap-discovery-unsupported-ensure-bootstrap-false`
- `bootstrap-discovery-guarded-available-file-reads`

Historical `unsupported-` identifiers remain stable for the before/after
comparison; they do not assert that a repaired API is still unsupported.

Boundaries require **all eleven** cases, including
`bootstrap-discovery-memory-core-layout-extension` and
`bootstrap-discovery-legacy-state-gate`. Their actual different outputs must
remain covering that boundary requirement. A successful qualified outcomes
review cannot turn those failures into passes or claim the full two points.

The built-in classifier is now implemented through real filesystem paths and
`MemoryArtifactProvenanceStore`, reusing the index's `classify_memory_path` owner.
`HostKit` supplies the same trust store its writer and index use. The SDK adapter
observes the actual nested classifier and store returns without replacing them.
The next proof still uses the same eleven literal inputs. Coverage remains
unassigned until its actual result, independent review and the full gate.

## Remaining differences

- The default SDK layout deliberately adds `PROACTIVE_PREFERENCES.md` and its
  extension directories. The explicit `OPENCLAW_COMPAT_LAYOUT` retains the six
  Native roles. The default extension is kept visible in the ordinary packet.
- At the eight-match checkpoint, configured bootstrap classification was a
  genuine missing SDK composition, not a missing Native export. The original caller already executes
  `classifyActiveMemoryWorkspacePaths` through `dist/memory-runtime-BzdCLKPx.mjs`
  export `n` and the real memory-core workspace classifier/provenance owners.
  The new SDK owner reads physical filesystem identity and recorded origins;
  its paired verification is pending. Returning expected file lists from a
  callback is not equivalent.
- The SDK's legacy-state gate fails closed and exposes its own complete error
  fields. Native context selection catches setup errors and can continue.
  This stronger SDK behavior and the error differences remain visible.

An independent review must decide any qualified acceptance set. Neither the
default layout mode nor the legacy/configuration boundaries are silently removed
to turn this partial result into a full two-point claim.

## Integration commits

The bootstrap package commits are `19d6810`, `3d2b5a3`, `6aa5adb`, and `7ecd4c0`.
The production fix depends on the frozen shared atomic publication package.
Its local transplants are `a47d674`, `6c25fd7`, and `4084521`, corresponding to
original commits `13859db`, `e527fc4`, and `6f9878e`. A candidate that already
contains that package should reuse it rather than duplicate the transplants.

When combining runtime profiles, preserve the separate bootstrap-only executable
capability. It must not borrow the model, entry-provenance, single-source taint,
or provider-fixture permissions.
