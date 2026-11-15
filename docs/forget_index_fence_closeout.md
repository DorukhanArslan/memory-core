# Forget/index-fence partial implementation closeout

Updated 2026-11-15. This package fixes SDK behavior and improves the comparison
fixtures. It awards **zero acceptance points**. The latest independently
assessed local catalog remains **71/128 verified conditions, 57 remaining**;
`forget.index-fence` remains **0/2**. [PR #18](https://github.com/DorukhanArslan/memory-core/pull/18)
is a draft and is not merged. Complete equivalence is not established.

## Behavior changed

A note deleted while an older search or rebuild is running must stay deleted.
The SDK now keeps the real forget ledger writer through index publication,
rechecks purge selection after writer admission, and recovers publication
through the actual SQLite rebuild lease. This does not claim crash atomicity
across separate database files.

Managed on-search stores now observe eligible workspace memory-file changes
and publish through their ordinary guards. Closing the store stops its watcher
and joins admitted work. Search recall recording uses the actual surfaced raw
primary results, timezone and bound owner; HostKit waits for the queued work
without recording it a second time.

The last production correction makes normal keyword metadata use a fresh
reader while the original retrieval generation stays pinned. This filters
hits whose chunk IDs have since been deleted. Explicit caller-owned database
semantics remain available and unchanged.

## Verification completed

| Evidence | Actual result | Meaning |
| --- | --- | --- |
| Latest complete local catalog, `13b54e0`, full003 | 1,443 matches, 18 mismatches, four blocked; exit 2 | 71/128 verified; failed full gate |
| Fresh V6 keyword pair, `f549881` | Match; strict replay passed | Empty in-flight results and equal held indexes for this schedule |
| Fresh seven-case query packet, `f549881` | Seven matches; strict replay passed | Current SDK query outcomes for these inputs |
| Fresh Host v4 packet, `621c97b` | Four matches; strict replay passed | Same declared environment and complete public results |
| Corrected test/map files and adjacent coverage, `5b729e9` | 269 passed in 21.50 seconds | Focused software regression evidence |
| Hosted Python 3.11 and 3.12 | 9,365 passed, 7,213 skipped, zero failed per version | Both wheel/sdist consumers and typing checks also passed |

Skipped tests and standalone packets add no acceptance credit. The hosted
software tests executed synthetic merge `f23a3d1`; its complete Git tree is
exactly the tree of reviewed branch head `5b729e9`. Python 3.11 took 1,828.19
seconds and Python 3.12 took 1,390.36 seconds.

The earlier all-test whole003 on `b0b3778` remains failed: **9,979 passed, six
failed and 6,585 skipped**. The six failures concerned obsolete prefix/FTS
expectations and moved source-map anchors. The reviewed corrections changed
four test files and 28 source-map line integers; runtime adapters and SDK bytes
stayed identical. Its failed result is not relabeled by later passing checks.

## Full comparison still unresolved

The fresh hosted differential run
[43673106847](https://github.com/DorukhanArslan/memory-core/actions/runs/43673106847)
failed globally with `forget-index-fence-evidence-invalid`, exit 2, summary
`{}` and no case IDs. Its message is: "Whole forget/index-fence execution/authority
failed; no retry was made." The report SHA-256 is
`34213268069115e5b65cbd95b62ad687049f7dc2880ca37446da7687d0929ec5`.
The downstream complete-family replay and guard steps fail the original
report's final check. Reading the existing artifact in a separate
[diagnostic job](https://github.com/DorukhanArslan/memory-core/actions/runs/43707458327)
identified the failed Native case:
`forget-index-fence-v6-keyword-worker-before-forget-enrichment-after`.
Its process records `timedOut: true`, return code `-9` and unchanged protected
bytes. The registered caller has a 180-second limit. Further authenticated
reading locates the wait at frozen step 19, `selectedWatch`, after forget
completed. The genuine `MEMORY.md` notification already carries the final file
identity, but returns 1.240903 ms before the writer resumes from its awaited
rename. The observer wrongly requires notification time to follow that
post-await receipt and rejects it; the matching later snapshot read is present.
This establishes an observer false rejection. The complete product comparison
remains unresolved. Removing the time check outright would also admit an old seed
notification, so a correction must prove the actual publication/delivery link.
The original search separately returned its genuine 30-second timeout result.
The diagnostic jobs verified the original ZIP/report hashes and retained event
records without rerunning a comparison. No fix or new acceptance credit is
claimed, and unflushed later activity remains unknown. Overall CI is not green.

Local full003 remains its own historical measurement. It lost the earlier
query-sync and host-turn outcome points, while their separate boundary points
remain verified. Its fourteen older mismatch payload pairs stayed exact. The
later bounded preflights do not restore those points or establish the complete
thirteen-case forget family. The fixed scope is still **64 contracts and 128
conditions**, with 32 complete, seven partial and 25 pending contracts.

Full004 was prepared but never started. At the user's request, this closeout
uses the completed checks and defers another long comparison. No new long test
or temporary-copy removal is part of this closeout. Fourteen byte-preserving
archives have been verified; their 4.57 GB of original temporary test copies,
the failed snapshot fixture and its link remain live.

## Catalog and evidence identities

The current 1,465-case catalog uses V6 for the thirteen forget cases and Host
v4 for indices 1407–1410. The other 1,448 old definitions and all 80 builder
annotations remain exact. The original 1,452-case prefix has changed; only the
historical full003 catalog preserved that entire prefix. Reconstructing the
four old Host definitions authenticates the unchanged remainder. No old
capture or frozen input is relabeled as a new execution.

| Identity | SHA-256 |
| --- | --- |
| Current 162-file SDK | `03e33ba0daf2013064f28386450ea50ed180af141f045d74ce52309a1f4452ed` |
| Fixed scope | `a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9` |
| Local full003 report | `194a69ffda45a1af9a46bba87af17bc558739500bd4d5de19e9013d7b398795d` |
| Independent full003 assessment | `acbd2dc39279452b863dca04a397d50e7cca4e27c6fb6a969f3293b692718fb7` |

[Diagnostics](forget_index_fence_diagnostics.json) retain the exact source
identities, prior failed attempts, strict replay receipts and archive records.
Large raw artifacts are local evidence, not files uploaded by a Git commit.
Source classification remains `partial`; source-build reproduction is false.
The declared provider-none on-search schedules do not cover every provider or
interleaving. The older four-extra-hosted-mismatch investigation stays paused.

## Next work

Correct the observer's publication/delivery association for step 19 while
keeping stale notifications rejected. The existing failed capture stays failed.
When full verification resumes, perform one complete comparison and independent
assessment for the finished package, rather than repeating it after small
changes. The score stays 71/128 until that evidence supports an update.

After this verification closes, the next proposed contract is
`forget.lineage-tombstones`: preview a conversation's linked notes, commit its
deletion, then repeat and replay it to check that forgotten material is not
relearned. Both implementations delete a whole mixed-origin entry and report
`mixedLineage`; preserving another conversation's portion is not promised.
