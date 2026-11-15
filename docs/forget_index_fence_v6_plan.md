# Forget/index-fence V6 input freeze candidate

Prepared 2026-11-15 UTC. This closed input-only family is a new reviewed
schedule candidate. It runs no original engine, changes no production source,
registers no default cases and awards zero acceptance points. All fifteen
V1–V5 module/manifest/plan files and their original captures remain immutable.

The operation is `forget-index-fence-v6-runtime`, input kind is
`forget-index-fence-v6`, profile is
`provider-none-on-search-forget-index-fence-v6`, and all thirteen IDs begin
`forget-index-fence-v6-`. The module authenticates exact manifest bytes, each
independent case wire, and the complete ordered family. Both existing
`forget.index-fence.outcomes` and `forget.index-fence.boundaries` still require
one complete family of thirteen; a subset or mixed version earns neither.
The fixed scope remains 64 contracts and 128 conditions (scope SHA-256
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`).

## Sole causal revision from V5

V6 inherits the entire immutable [V5 plan](forget_index_fence_v5_plan.md),
including all source admission, original ownership, lifetime, physical capture,
clock, counter, negative-proof, whole-result and fail-closed custody rules,
with one explicitly superseded placement: member 10 (zero-based index 9),
`keyword-worker-before-forget-enrichment-after`, moves the existing complete
`await-original-watch-effects` step labelled `selectedWatch` from V5 step 22
to V6 step 18, immediately after original `forget:selected` completes and
before `capture-physical-state:afterForgetBeforeOriginalEnrichment`.

The original keyword reply remains held throughout this existing watch join
and the existing physical capture. Its existing release, public search await,
search-effects await, later business calls, later captures and close/reopen
sequence preserve their relative order. No actor is skipped. No extra join,
publication, sync, query, gate, source-clock tick or original method is added.
Removing only this one join in both manifests yields identical step lists.
Every other member is exactly V5 after the four explicit identity substitutions
(id, operation, input.kind, input.profile). All remaining keyword fields are
also exactly V5. There is no expected result/count or comparison allowance.

V5's original rationale for putting this join after release was the possibility
that watcher publication required the held search read generation. The actual
13b full-003 evidence disproved that dependency for this declared schedule:
Native watcher index COMMITs at 143003178726496 and 143003274119808 ns and
settlement at 143003313530487 ns occurred before capture; SDK forgetter index
COMMIT at 144510331514148 ns and publisher return at 144510362171926 ns,
and foreground index COMMIT at 144510395404268 ns and publisher return at
144510429144161 ns, all preceded the still-held keyword release at
144510677065951 ns. These are separate side-local monotonic observations,
not comparable cross-engine clocks or predicted output. The earlier source-
qualified join makes that existing accepted watcher frontier explicit before
both physical snapshots; the real 1500 ms debounce remains unchanged.

The Native business carrier remains the approved actual V3 carrier
`forgetIndexFenceV3Profile`, bootstrap `forget-index-fence-v3-bootstrap`, and
`official-release-forget-index-fence-v3` transport. These names do not claim
new original owners. V6 uses the unchanged `original-watch-effects-v5`,
`original-search-effects-v3`, and `owned-source-write-clock-v2` protocols.
Resolved original configuration, all business call arguments/order, initial
files, source clocks, actors, gates, model responses, captured fields, scores,
path policy and entire comparison/counter policies remain exactly V5.

No sleep, retry-until-equal, widened timer/deadline, field drop, sorting,
deduplication, output repair, whole/incremental production-policy change or
new acceptance condition is permitted. A failed join invalidates custody and
earns zero. V5 full-003 remains its actual original capture with twelve public
matches and one keyword mismatch; it is never relabelled into V6 evidence.

## Review and promotion boundary

These three new files are frozen for canonical input/source review before any
V6 original execution. Narrow adapters and strict guards may then explicitly
admit this exact family. Any original probe uses fresh separately versioned
captures and retains entire results and custody. Default case registration,
harness/CI promotion, source-wide acceptance and merge remain separate steps.
A later catalog migration must explicitly audit the thirteen FIF replacements
and any separately reviewed four Host V2 replacements. It cannot claim that
all original 1,452 definitions stayed unchanged if those Host cases migrate.
No new point or expanded scope is implied by this protocol candidate.

## Byte seals

The new manifest SHA-256 is `ce4ee37230a9a814d7f8440e7e9cc513ae5140ee2980aa01c45480493ef4998d`.
The module contains all thirteen canonical `id`/`operation`/`input` wire hashes.
The following prior byte seals are verified against source
`13b54e07bffe292599dab0ff5d89ea54e94e207a` and remain unchanged:

| Prior immutable path | SHA-256 |
| --- | --- |
| `equivalence/forget_index_fence.py` | `df365f400dbd1832e39209ba537c4c9e85a3aaa7de91b33bb1921eb78f7174d9` |
| `docs/forget_index_fence_literals.json` | `3e2e1590dde362027f0910efc2653822b19bb74a27e9b56e9c9cda4637fc3682` |
| `docs/forget_index_fence_plan.md` | `81f992e64a12f0d1ce7435e3883b037f3cccb4d96b67735e30cf1e7cfadf5832` |
| `equivalence/forget_index_fence_v2.py` | `e20505bf3f6501efb0b1fceb581cedc515a47fabe5a82f4e595b646ade9557cc` |
| `docs/forget_index_fence_v2_literals.json` | `c562fca43a1ec7fbb320da55cd2c0bb2201ab1392230c2398cccdf82a9111854` |
| `docs/forget_index_fence_v2_plan.md` | `0df1c7b48c6ff6f75eed881499fa6ceed1a761d95763a4a1d4b4dbffeb4e88d3` |
| `equivalence/forget_index_fence_v3.py` | `d0ffb0c88635d04994f7c0019346a389c823fd4f2e9bed3064e94a9059a66bc5` |
| `docs/forget_index_fence_v3_literals.json` | `acdcbfa022d43c9ab58dbfc43bfa1987798d5aa4a02f3f535bd44db2d449b01c` |
| `docs/forget_index_fence_v3_plan.md` | `376873a6111486b5f8612c8db8401d535131d102cd1bcfd2c5484ee11d9ea62b` |
| `equivalence/forget_index_fence_v4.py` | `5e4716b4fbaa68d4f6f7bbaf7f8aeba2bb867bab951a21d786a504c75a8cfc72` |
| `docs/forget_index_fence_v4_literals.json` | `d8945f9d1bf1aadc5b33c83a6a8a250e13ecefd4d51698e5cf170b8e8d8b6fd2` |
| `docs/forget_index_fence_v4_plan.md` | `00a3986598833ade6030a46e19d9c47a4d7f83fea04a9ef70a464ec55fa46cde` |
| `equivalence/forget_index_fence_v5.py` | `13be80d22c3070ecdbf368d327bbc71e1b35ea9ba9c933d761baacddff353cff` |
| `docs/forget_index_fence_v5_literals.json` | `a1da290cb134aca47678f97b7e2e182a48b746863857a3e3f5c9365db02aae83` |
| `docs/forget_index_fence_v5_plan.md` | `ac961b10dbcb52e774cffaa6c14198451c55fcec590afe151acaa80027dd7aae` |
