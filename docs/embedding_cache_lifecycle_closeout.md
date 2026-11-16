# Managed embedding-cache acceptance

The complete assessment verifies **81/128 conditions (63.3%), 47 remaining**:
**38 complete, five partial and 21 pending contracts**. Both original
`indexing.embedding-cache` conditions are verified: **79 → 81/128, net +2**.
Verified IDs are `indexing.embedding-cache.outcomes` and
`indexing.embedding-cache.boundaries`. The fixed 64-contract, 128-condition scope
is unchanged.

## Frozen inputs and authority

- Full comparison: `d53c91e294204567f9a7735ccc69029669639070`.
- Approved product source: `f8a8ffd09f633996f299a93ab7306282f0448130`.
- SDK source SHA-256: `48973e195a41e1d2dfdc8bbe366293b8ebed0830571b3d0764ebe8a8a7b443a0`.
- Original OpenClaw `v2026.9.9` source pin:
  `bcfc88812a35243893585dbeca87ca41b48272ca`.
- Actual original owners: 47 source bindings, 25 authenticated compiled artifacts,
  six import links, and the real protected indexing worker route. The compiled
  owners come from the integrity-pinned official npm release; its source build
  was not reproduced.
- Approved runtime: Node `v24.16.0`, ICU `78.3`, Unicode `17.0`; executable SHA-256
  `b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`.
- Focused executable: `/workspace/memory-core/work/node-v24.16.0-linux-x64/bin/node`.
  Full-run executable: `/opt/hostedtoolcache/node/24.16.0/x64/bin/node`.
- Frozen eight-case input map SHA-256:
  `3856a25129df0b84e9b49906b8f08b462290bd9ddd1720ddfb2ca6f5429d1790`.

## Product changes

1. Add the effective cache-enabled setting to real SDK indexing: disabled runs
   bypass cache reads/writes; enabling it permits durable reuse.
2. Read cache at each source boundary, allowing a later source in the same
   refresh to reuse vectors already admitted by an earlier source.
3. Admit generated vectors against their own fresh source and prepare each
   source when its turn starts. Preserve the separate whole-index publication,
   owner, revision and forget fences.

Fresh candidate reads currently rediscover the authoritative workspace per changed
source. Large forced warm refreshes therefore perform repeated source discovery;
refresh throughput was not benchmarked in this acceptance job.

## Compared boundary

The eight cases contain 76 operations: 38 syncs and four queries. Focused-006
retains 52 actual embedding callback receipts on each side. Coverage includes
reuse/reopen, edits/rename/removal, provider/model/endpoint/alias/dimension changes,
disable/re-enable, retry/split retention, malformed vectors, source freshness,
and generated-cache survival across real SQLite publication failure/recovery.

The complete cache compares all seven SQL columns plus `embeddingHex`, with
decoded vector values and exact BLOB bytes retained. Complete effective identity
and every ordered document/query request, returned vector and fixture error
remain compared. Query embeddings are actually requested again, not called cached.

The deterministic plugin is registered through the genuine original plugin API.
Its `ollama` provider ID selects the original sequential indexing branch; the
fixture does not contact a real Ollama service. The other fixture IDs are also
owned registrations. Fetch remains denied; no paid provider calls are made.

Actual sync/search returns, exceptions and full index/source/SQL state remain
unchanged in raw evidence. The shared cache packet has no outer completion flag
and does not normalize Native/SDK API outcomes into equal completion results.

In source-freshness operation index 9, Native really publishes while the SDK
rejects whole-index publication after the independent source mutation. Both
retain matching admitted cache entries and complete callback receipts. That real
publication difference remains explicit in raw evidence and is outside these two
cache conditions under the policy frozen before any engine run. This closeout
does not claim general sync, publication or search-ranking equivalence.

## Retained focused attempts and narrow validation

All six attempts remain under `work/embedding-cache/acceptance/focused-00N/`.

| Attempt | Retained result | Meaning |
| --- | --- | --- |
| 001 | Blocked | Setup/provider entry gate; no behavioral credit. |
| 002 | Blocked | Original loader setup; no behavioral credit. |
| 003 | Blocked | Original indexing/state setup; no behavioral credit. |
| 004 | Blocked | Post-exit evidence guard; no behavioral credit. |
| 005 | 7 matched, 1 mismatched | Genuine source-freshness cache-admission difference. |
| 006 | 8 matched, 0 mismatched, 0 blocked | Both-point family gate satisfied locally. |

Focused-005 report SHA-256:
`8308834aaa983cc60575fa7182f1390761efe5669cc58729e0f9e50492130d23`.
Focused-006 report SHA-256:
`6fb5f4fc79c6b8e4a4218408c10a5b87c08e5434e7ae9b1b97203405159cc94f`.
Focused-006 took 93.19 seconds; its exit code 1 reflects incomplete global scope,
not a family failure. Focused execution alone does not update the global score.

Nine targeted SDK regressions passed in 0.20 seconds, including the four earlier
checks repeated after the source fix. Ten closed-family/capability/source-authority
checks passed in 0.13 seconds. No whole Python suite was run for this job.

## One complete comparison and independent audit

The [single run](https://github.com/DorukhanArslan/memory-core/actions/runs/43884962457)
retains **1,483 cases: 1,469 matched, 14 mismatched, zero blocked and no runner
errors**. Actual exit is **1**, duration **7,052.32 seconds**. The full gate stays
failed: **45 uncovered and two registered unresolved conditions** remain.
Product source was unmerged when measured; its 162 SDK files and Git tree
`6e774f28cb3480e10eb43a099761ca12ae5d8932` exactly match the comparison SDK.

Full report `.equivalence-results/full.json` SHA-256:
`a9f573fa61457e4955b006f9a7286012a8c78720eba97e341eb3c511220d0879`.

The original 1,475 definitions remain an exact prefix (SHA-256
`8c6f2adb034b7360f0ef9beeb45383d77b7df9bfe9057d2f8df98eb1ac397335`).
The explicit eight-case append yields catalog SHA-256
`33277abb724a6b89423085e735fc08b950b647b577db9879df8f2395e519a93d`.
All 12 atomic family gates hold. Independent replay validates FIF13, Host4,
forget outcomes3/boundary1, recall6 and cache8 against actual retained packets.
The cache replay verifies 76 operations and 52 actual provider callbacks per side.

The frozen CI assessor parses the full report to EOF. Local root review checks
the complete case/status/coverage projection, source/exit bindings and all 128
conditions independently. It confirms exactly the two original cache points
changed, preserving every previously verified condition. Root review SHA-256:
`9c4f7e7a07b6452c29f2b18a525422e265df8e62a1e5c54727ddf4c167ec1e0e`.

Only the **630,262-byte** summary ZIP was retrieved, through 16 authenticated
reader logs: artifact **14245714258**, SHA-256
`ab82e4eb94a1d734ef3def578efcfecb5cd9b773f078b232321236c7f5eee63f`.
Run/head metadata, every part, ZIP size/digest and extraction paths are verified.
The full raw artifact **14246234369** remains retained on GitHub:
**2,412,910,349 bytes**, SHA-256
`2a9a969b6ccccd378f9f1484f55bf9b2874c2f8a4178c0dcd9e07c3e47a7c923`.
It was not downloaded locally. Native on-disk attempt paths are already retired;
lossless captures are replayed. SDK raw/physical files were reopened in CI.

All 14 old cases remain mismatched. Their complete SDK public hashes match the
original 14-case baseline. The uncredited warm-flush Native hash changed from
`4cdb2aa71ea06ed46a094e47e3739276fae9238c4480d82a6eee896d6451b569`
to `208c57d0be33f822c949bc0dd3a4136e11593b56d6e07a91f32f665cb5cdcf3f`.
This is retained as a real Native variation, without relabeling the earlier
capture or investigating the separately deferred four hosted differences.

Local receipts remain under `work/embedding-cache/acceptance/full-43884962457/`:
`assessment.json`, `forget-family-replay.json`, `source-seal.json`,
`source-after.json`, `launch.json`, `os-exit.json` and `root-review.json`.
The only accepted global delta is **+2**; full equivalence remains unclaimed.
