# Memory read path proof: first uncredited comparison

This dedicated matrix exercises fixed contract #2, `storage.path-safety`, through
the already authenticated public `memory_get` factory and complete execute
boundary. It adds no native runtime capability, provider, index manager, worker,
write operation, or acceptance credit. The fixed scope remains 64 contracts and
128 acceptance points. Every new case has `covers: []`.

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

## Remaining production work

The refusal causes need an IO-boundary correction using actual filesystem facts
and the attributed Node system-error bridge, retaining original Python exceptions.
Patterned roots need public API/type support and the same normalization/matching
policy already used by discovery. These are production changes, not output
normalization or comparison repairs.

The current production reader separately validates a path and calls
`Path.read_bytes()`. Native secure IO pins file/root identities, uses a nofollow
open, and checks identity and canonical containment around consumption. This
matrix does not schedule descriptor/path replacement races and cannot establish
that stronger equivalence. A deterministic OS scenario and coordinated production
design are required before claiming it. Retry timing, deadlines, general platform
semantics, and write admission are also outside this batch. Contract #3 is unchanged.

The focused fixture, evidence, and existing read regressions passed 65 tests;
Ruff, Python compilation, Node syntax checking, and whitespace checks passed.
These checks add no acceptance credit.
