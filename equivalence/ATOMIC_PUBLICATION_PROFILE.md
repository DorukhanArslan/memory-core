# Atomic publication proof profile

This is a proposed, bounded profile for the two original `storage.atomic-writes`
acceptance conditions. It grants no coverage. Production at `67e3051` remains
frozen while original observations and paired differences are retained.

The earlier development packet remains at
`/workspace/scratch/memory-core-atomic-publication/.equivalence-results/atomic-c-final-development/packet.json`:
32 cases, 31 matches, no protected execution, and no acceptance credit. Its one
remaining comparison difference preserves real physical publication receipts.

## Authority

The profile uses the authenticated official OpenClaw release at source commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. Compiled release bytes and exact pinned
TypeScript sources are separate authorities. Source build reproduction remains
false. No source module is imported under a widened source capability.

Each fresh process uses only the previously approved Node executable:

| Fact | Required value |
| --- | --- |
| Node | `v24.16.0` |
| ICU | `78.3` |
| Unicode | `17.0` |
| Executable SHA-256 | `b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd` |

A new atomic profile capability binds that binary to exactly the operations
below. It cannot borrow the model, entry-provenance, turn-taint source, or fixture
source-capture capabilities. Fetch remains denied, inherited provider credentials
are absent, and there are no provider, manager, index, worker, or full agent-tool
execution claims.

| Operation | Literal kind | Original executed owner |
| --- | --- | --- |
| `atomic-commit-runtime` | `commit` | `dist/short-term-promotion-memory-write-DLJgScco.mjs:commitMemoryContent` and its actual `HTLC95gL` implementation, including the opt-in original in-place repair branch |
| `atomic-append-runtime` | `append` | Authenticated `@openclaw/fs-safe/dist/root.js:root` → real `Root.append` and its actual writable descriptor owner |
| `atomic-bootstrap-runtime` | `bootstrap` | `dist/workspace-C0LMBmap.mjs:u` → actual `publishBootstrapFile`, default native retained-directory stage/publish/settlement owners |

The append operation requires its exact external package/path owner. It must not
import an unrelated OpenClaw manager merely to satisfy an existing generic entry
check. Only this one reviewed external entry may be added to that check. The
bootstrap operation must observe the genuine default NAPI binding and its
authenticated binary resolution; no alternate backend flag is set.

The commit profile calls the real original memory-write owner. It does not claim
the full promotion scheduler ran. SDK comparison calls the production owner used
by the real promotion/curation/forget callers. Their separate caller regressions
remain supporting evidence rather than substituted original execution.

## Literal fixtures and IO seams

Each case declares an owned relative target, exact initial bytes or absence,
mode, complete public request, optional concurrency schedule, and a closed list
of IO fault facts. The request includes the literal content/preimage/hash and
in-place policy; the adapter does not generate a matching published result.

Faults wrap real IO or native binding calls and delegate unchanged whenever their
owned path/fd, operation and occurrence do not match the literal fixture. A
partial write delegates the declared byte window before surfacing the literal
failure. A post-dispatch failure delegates the real publication or close first.
The adapter never supplies a writer, rollback algorithm, publication receipt,
expected filesystem snapshot, or synthetic success.

Initial cases preserve the existing 32 development intents. Protected partial
write cases use these literal IO seams. The genuine `RLIMIT_FSIZE` observations
remain separate diagnostics: a process-wide file limit can also truncate the
protected trace writer and therefore cannot silently serve as acceptance proof.

Additional bounded cases must include:

- Primary write/sync failure followed by a delegated close failure, retaining
  both original errors and the actual surviving files.
- Preparation/publication failure followed by owned cleanup failure, retaining
  complete actual cleanup receipts and aggregate/suppressed errors.
- Bootstrap publication that really dispatches before a lost reply, retaining
  its actual indeterminate outcome and any preserved stage.
- A stage pathname replaced before cleanup, with the actual foreign winner and
  owned original identity kept distinct.
- Genuine cooperating replacement and exclusive-create concurrency schedules,
  retaining actual queue/IO phases instead of assuming both owners stage
  concurrently.

The first protected matrix is fixed at 41 literal cases: the earlier 32 intents
and these nine additions. Their complete occurrence, errno/code and message facts
are in `atomic_publication_cases.py` before capture.

| ID suffix | Literal boundary |
| --- | --- |
| replacement committed close | Successful publication, then delegated stage-handle close rejects |
| replacement preparation and close | Stage fsync rejects, then delegated close rejects |
| replacement read and settlement | Target preimage read rejects, owned cleanup rejects, delegated close rejects |
| append sync and disposal | Target fsync rejects, then genuine delegated async disposal/close rejects |
| bootstrap preparation and cleanup | Stage fsync rejects, then delegated native remove-staged-file rejects |
| bootstrap committed close | Published file, then delegated owned-fd close rejects |
| bootstrap lost publication reply | Actual rename-no-replace/link dispatch completes, then EIO rejects |
| bootstrap publication refused | EIO rejects before dispatch while a real owned stage exists |
| bootstrap foreign cleanup entry | Primary failure, real original stage parked, foreign name replaces it before cleanup |

The exact resulting error shape is observed from the original owner. Existing
SDK differences remain ordinary mismatches until a separately authorized genuine
production correction is made.

## Complete observations

Retain complete public return/error envelopes. Error traversal includes own and
non-enumerable producer fields, recursive causes, aggregate `errors`, suppressed
`error`/`suppressed`, `details`, categories, publication fields, and array shape.
No error category-only comparison is allowed. Original stacks, Python exception
types/context, OS errno/syscall/path data and all pre-codec values remain raw.

Raw evidence binds the literal input to the actual operation, original owner
imports, process/thread, delegated IO sequence, before/after whole owned tree,
file bytes, modes, descriptor identities and stage observations. Failed or
rejected evidence is retained with its original streams. The collector checks
that every declared fault actually dispatched; an untriggered fault cannot pass.

## Return and exit observation phases

The second protected attempt is retained as blocked at the replacement
read/cleanup/close case. Its independent reread happened after process exit,
while the adapter's snapshot was at owner return. The genuine original
`registerTempPathForExit` handler removed the retained stage between those phases.
This timing assumption was rejected rather than used to discard either tree.

An atomic-only immutable preload observer now invokes each exact original export
from the host-bound literal case. It accepts only the declared step ID and owned
fixture root, never a supplied function, outcome or tree. Original Promise
settlement and full producer errors are recorded by the trusted observer. Once
all declared calls settle, exactly one return checkpoint reads the entire subject
through original pre-hook no-follow descriptor operations and binds the actual
native journal bytes/hash and IO count. Unknown, duplicate and out-of-phase calls
are rejected. The adapter tree is compared to this independent return tree.

Original process-exit handlers remain installed. Scoped transparent observers
retain actual owned exit cleanup IO, a separate trusted exit tree, and an anchored
post-process collector reread. A genuine operation-return/process-exit difference
is retained explicitly, without pretending the phases are identical. This profile
compares operation-return behavior; it does not claim SDK/reference process-exit
registry interchangeability or restart behavior.

## Receipt codec

The following codec is declared before capture. It does not claim physical
receipts are interchangeable between implementations.

1. Convert Node bigint wrappers to Python integers losslessly. Values must be
   exact integers, with no tolerance, floating conversion or rounding.
2. Replace only the exact owned fixture root prefix in path fields.
3. Label a temporary basename/path only after an actual exclusive open or
   original native stage-creation call binds it to the owned stage.
   A separate `exclusive-attempt-N` path label is permitted only for an exact
   owned O_CREAT|O_EXCL request, flags/mode and actual rejection with no returned
   or hidden allocated fd. This namespace cannot validate a receipt or imply
   that a post-dispatch open did not allocate anything. Attempt count/order and
   all actual fields remain retained.
4. Label a receipt's directory/file identity only after its original physical
   fields match independent same-stage fd/fstat/open/link/IO observations. Device,
   inode, nlink, size, mode, owner, and nanosecond times are checked according to
   their actual producer types and stage/event. The complete original values
   remain retained in raw evidence.
   A prepared file receipt requires the last actual same-actor fstat after its
   successful stage sync and before that stage's publication request, within the
   allocated descriptor generation. Earlier snapshots and reused fd numbers
   cannot provide its timestamp tokens. Time labels name this `prepared` phase.
5. A nanosecond value can refer only to that validated stage/event. There is no
   general mtime/ctime normalization, wall-clock fixture, guessed identity,
   cross-object alias, or timestamp tolerance. Any receipt that cannot be bound
   independently remains an ordinary mismatch.

SDK exclusive publication uses the retained-directory Linux
`renameat2(RENAME_NOREPLACE)` or Darwin `renameatx_np(RENAME_EXCL)` primitive.
An unavailable ABI fails before allocating a stage. The present authenticated
execution profile is Linux; Darwin execution is untested and no portability
equivalence is inferred.

The raw validator precedes token labeling. It must reject a changed receipt stat,
unowned stage, wrong descriptor, wrong IO event, reused basename, missing producer
field, incomplete error or fabricated dispatch before comparison.

## Acceptance limit

Original outcomes require append, replacement, exclusive creation and concurrent
rename results. Original boundaries require injected write, flush, fsync and
publication failures with surviving-file inspection. No source/helper fixture,
development packet, or path-only result can close either condition alone.

All new case `covers` lists remain empty until a protected paired formal packet
passes, independent whole-condition review approves an exact mapping, and the
combined candidate's required regression and package gates complete.
