# Memory read path proof and reviewed registration

This dedicated matrix exercises fixed contract #2, `storage.path-safety`, through
the already authenticated public `memory_get` factory and complete execute
boundary. The static families add no native memory owner, provider, index
manager, worker, or write operation. One separately approved official test-hook
capability controls the real pre-open OS mutation described below. The fixed
scope remains 64 contracts and 128 acceptance points.

All first, corrected, and public-get regression packets retain their original
`covers: []` metadata and hashes. After independent review, the default catalog
registers both fixed #2 conditions only on the complete eleven-family set.
The integrated full gate remains the final step; no other contract gains credit.

The isolated tree starts at `2a56ed8fed789668af77333f0c7e31ff495d3231`. Production
Python sources were unchanged for this first comparison; their aggregate source
SHA-256 is `61088d9e3eb8fd20b107fa9bda2c653ec1c34fb857b7e41a3af0b38904cd313d`.

The ten batches execute 98 whole-tool requests: relative/absolute root paths,
traversal and misses, encoded literal names and raw boundaries, symlink admission,
two OS symlink loops, nonregular files and hardlinks, missing/non-directory
workspaces, plain configured roots, and patterned configured roots. Read arguments
retain their exact suffixes. `$WORKSPACE` and `$OUTSIDE` expand only to the private
case's sibling owned roots. Fixture creation uses a separate strict path validator;
configuration cannot authorize a root outside the total private fixture base.

Both owned roots are observed before the factory/execute calls and after all
calls, before cleanup. Snapshots use `lstat`, preserve symlink targets without
following them, classify every encountered OS file type, and retain complete
regular-file bytes with matching opened descriptor identities. All actual stat
properties remain in raw evidence. The public comparison retains content, file
type, POSIX mode/uid/gid/nlink/rdev, complete regular bytes, actual hardlink
relations, and exact within-side stability of write-related stat facts. Access
times remain raw and may change through reads. Process-specific inode/timestamp
values are not compared across independent fixtures. Actual pre/post inode,
device, size, allocation, modification/change time, and other write-related facts
must remain stable within each side.

The complete production result envelopes and original JSON text carriers remain
in raw evidence. Carriers must parse exactly to details before comparison. Only
the exact owned fixture-base prefix receives the existing `$FIXTURE` identity
codec. Errors, causes, codes, field absence, path suffixes, and operation order
are not rewritten. The harness revalidates snapshot comparison facts and actual
expanded arguments against raw evidence on both sides.

## First result

`.equivalence-results/storage-path-contract-first.json` records **7 matched,
3 mismatched, 0 blocked**, and no runner errors. Every batch loaded 2,885
authenticated release files, used provider none, and denied network fetches.
All ten filesystem observations match and retain unchanged content and
write-related stats. Native diagnostics retain 218 actual lstat observations and
110 complete regular-file byte observations across pre/post snapshots.

The retained report is 1,548,882 bytes, SHA-256
`789545b74d659f3456faaf4c5ae5c9065fd057833edf0d740c75d16705b45359`.

The mismatches are concrete production differences:

- An inside-root broken parent symlink reports the generic Python symlink-escape
  cause. Native retains `ENOENT: no such file or directory, stat '<target>'` and
  the `ENOENT` cause code. A parent symlink to a regular file likewise needs
  the actual resolved target's non-directory cause and `ENOTDIR` code.
- Both loop forms retain Python's `Symlink loop from ...` cause. Native retains
  `ELOOP: too many symbolic links encountered, realpath '<link>' | ELOOP`.
- The SDK rejects path/pattern mapping entries before applying configured-root
  admission. Native admits matched files and same-root pattern unions, refuses
  excluded paths with `MEMORY_PATH_NOT_ALLOWED`, reports admitted missing leaves
  as `not_found`, and admits an explicitly configured Markdown file independently
  of its pattern. All eight patterned-root requests preserve this difference.

The other lexical, traversal, encoded, null-byte, hardlink, workspace-root, and
plain-extra-root batches match. No production fix preceded this first report.

## Production follow-up

Commit `e1273befa21329fe82fa8245cbd660abbb3d4abe` corrects refusal causes at their
actual IO boundaries using the attributed Node system-error bridge, retaining
original Python exceptions. It adds public path/pattern root support using the
existing discovery normalization and matcher. These are production changes;
the comparisons do not repair output or synthesize expected results.

The previous production reader separately validated a path and called
`Path.read_bytes()`. The replacement read owner now follows the original
local-descriptor and root-admission owners: pin root and leaf identities, open
with nofollow/nonblocking flags, check root/file/canonical-file/root identity and
containment, then consume the same descriptor. It reuses the existing descriptor
byte loop and IO fact bridge. Hardlinks retain the native allow policy, all
rejection paths close descriptors, and no extra post-consumption pathname gate
is added. The original consumed descriptor remains authoritative.

The separate genuine pre-open replacement scenario below covers one exact OS
cut. Other replacement schedules have SDK unit guards, but no native proof is
claimed for them. Retry timing, deadlines, general platform semantics, and write
admission remain outside this batch. Contract #3 is unchanged.

The focused fixture, evidence, and existing read regressions passed 65 tests;
Ruff, Python compilation, Node syntax checking, and whitespace checks passed.
These checks add no acceptance credit.

## First controlled OS replacement

A separate one-call case uses the already loaded official
`@openclaw/fs-safe/dist/test-hooks.js` setter, authenticated with its two genuine
callers. The only installed hook is `afterPreOpenLstat`. It runs after the
original file's lstat observation and before the original async open, renames
that owned file to an owned backup, and creates a real symlink to the sibling
owned outside sentinel. It supplies no read result, file bytes, descriptor,
policy error, backend override, or replacement filesystem implementation.

The exact hook capability is restricted to this literal case under the existing
whole-get operation. Direct oracle imports of the hook are denied to other
operations. Imports run under the normal environment; `NODE_ENV=test` exists
only during the synchronous setter invocation and is restored before tool
execution. The raw record attests before/during/after environment, actual
mutation identities, original caller stack, arming, one dispatch, and clearing
the hook. `VITEST` and native backend variables remain untouched.

`.equivalence-results/storage-path-read-race-first.json` retains **0 matched,
1 mismatched, 0 blocked**, no runner errors, and no credit. Its SHA-256 is
`3f2e9a04982215740a83d5d84f77d64c668768a9ff493f6f381266e3d500becc`.
It predates the secure descriptor read fix. The SDK actually consumes the
outside sentinel through its previous `Path.read_bytes()` call. Native returns
`symlink open blocked | ELOOP: too many symbolic links encountered, open
'<owned path>' | ELOOP`. The observed filesystem mutation and race facts match;
both unchanged flags are false because the fixture deliberately mutated the
filesystem. This is an external OS input, not a product write.

The genuine dispatch stack includes `local-file-descriptor.js:41` and
`root-impl.js:454`; all 2,885 release artifacts remain authenticated. No backend
fallback was installed. The first ten-case packet and this race packet remain
unchanged after subsequent production work.

## Corrected committed comparisons

The same ten original static inputs and the separate race input were compared
again on clean commit `e1273befa21329fe82fa8245cbd660abbb3d4abe`. Every input was
asserted unchanged against its retained first packet before execution. Production
source SHA-256 is
`d694238b1ffda6b6ec20b4867136be5106729ea827a573c178b817fb9f198cb3`, across 151 Python
source files.

`.equivalence-results/storage-path-contract-corrected11.json` records **11 matched,
0 mismatched, 0 blocked**, 99 complete whole-tool calls, and no runner errors.
Each batch retains 2,885 authenticated release files. Its SHA-256 is
`d9ffe25b271e06fe961072bf272a314531713ab45ac7c356dd0e1ff923472a0f`.
All static before/after content and write-stat observations stay unchanged.
The intentionally mutated race fixture retains matching changed observations;
the SDK now returns the complete original symlink/open/ELOOP refusal instead of
consuming the outside sentinel.

The 12 previously accepted whole-get batches were also repeated with their
original product inputs, clearing only this repeat report's coverage metadata.
`.equivalence-results/storage-path-get-regression12.json` records **12 matched,
0 mismatched, 0 blocked**, 65 complete calls, and no runner errors on the same
clean committed source. Its SHA-256 is
`21c334b2a2436eb7e2509f6bd8ce6a1532702b702036bfb584eac7e81059f992`.

The final affected regression set passed **371 tests**, plus **2 public consumer
typing checks**. It includes real leaf, parent, root, hardlink-alias, FIFO, unlink,
and late-consumption OS scenarios, descriptor release, raw-stat completeness,
snapshot identity, exact capability boundaries, and existing read contracts.
Ruff and whitespace checks pass. Every retained capture keeps `covers: []`;
those reports leave all 128 points uncovered in their isolated comparison scope.
Their historical coverage metadata is not rewritten after review.

## Reviewed two-condition registration

Independent source, security, and raw-evidence review accepted all eleven
families for both `storage.path-safety.outcomes` and
`storage.path-safety.boundaries`. The review replayed all 22 filesystem
observations, eleven raw journal hashes, nine negative tamper carriers, and
the three original hook/caller artifact hashes. It found no descriptor cleanup,
read admission, error-shape, or source provenance gap within this profile.

The default [path catalog](../equivalence/storage_path_contract.py) now returns
all eleven families exactly once. Every family carries both condition IDs.
The [registration guard](../equivalence/storage_path_acceptance.py) pins their
literal IDs, all eleven reviewed input hashes, and the 99 original requests.
Removing a family, one condition from one family, snapshots, calls, or reviewed
fixture bytes fails before a point can be claimed. Existing source helpers and
the old loop diagnostic retain empty coverage and cannot substitute for the
whole-tool proof. Historical uncredited reports remain valid diagnostics.

The original actor chain is:

| Original owner | Python owner |
| --- | --- |
| `extensions/memory-core/src/tools.ts:createMemoryGetTool` | `memory_core/tools/get_factory.py:create_memory_get_tool` |
| `extensions/memory-core/src/memory-read-tool.ts:executeMemoryReadResult` | `memory_core/tools/memory_get.py:_read_builtin` and the complete tool envelope |
| `packages/memory-host-sdk/src/host/read-file.ts:readAgentMemoryFile/readMemoryFile` | `memory_core/workspace.py:resolve_memory_read_path` and `memory_core/tools/get_paths.py:resolve_memory_get_read_path` |
| Official `@openclaw/fs-safe/dist/local-file-descriptor.js`, `root-read-admission.js`, `strict-file-identity.js`, `root-context.js` | `memory_core/memory_read.py:read_memory_file_bytes` |
| Original Node system-error facts and formatter | `memory_core/_memory_scan_io.py:bridge_memory_read_io_error`, retaining the real Python exception |

The compiled owners are authenticated official artifacts, separately linked to
the unchanged pinned source; this is not a reproduced source build. Runtime
declarations record the actual package paths, SHA-256 values, exports, original
caller edges and loaded artifacts. The generic get profile has no hook
permission. Only the exact whole-get race input can acquire the one official
hook, and other operations, input changes, extra hooks, broad test mode, or
backend overrides are rejected.

This registration closes only the two fixed path/read conditions after root
integration. The stronger race evidence is one genuine leaf-to-symlink
replacement at the original pre-open seam. Regular replacement, parent/root
replacement, shared-inode alias, FIFO, unlink, and late-consumption schedules
remain SDK unit evidence. Arbitrary scheduling, retries, deadlines, general
platform/Unicode path behavior, and write admission are not claimed.

Registration validation passed **337 catalog, harness, source-map and evidence
tests**, followed by **491 capability and cross-lane guards** in an overlapping
suite. These include denial of the hook to generic get, helper get, search,
session and workspace operations, and rejection of mixed profile capabilities.
The pinned source inventory validates all 64 contracts and 128 points; source
presence itself contributes no behavioral credit. Ruff and whitespace checks
pass, and no production source changed during registration.

`.equivalence-results/storage-path-registration-replay.json` explicitly records
`freshNativeExecution: false`: all eleven current SDK families and 99 calls
still match the retained authenticated Native packet, with 22 original raw
journal hashes and 22 filesystem observations revalidated. Its SHA-256 is
`f73a7b9aba245b68df64094c9950d725f9641f3c37642391a1088a3e16884d76`.
All four historical packet hashes above remain unchanged. This replay checks
registration continuity; the parent integrated full run supplies the final gate.
