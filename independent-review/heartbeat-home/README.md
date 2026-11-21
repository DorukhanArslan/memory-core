# Independent review of the heartbeat migration and search retry

**118 of 128 conditions passed.** The corrected SDK passed the heartbeat scratch outcome condition. The search synchronization boundary condition reopened. The measured SDK is `f040ac1852a878672ff6f6ede85ebee393a8ffd6`, with 183 source files and SHA-256 `a00070f6ffd781c8372b06f7bc9b0546a5dacb59058144519e1ba7d9a174bba3`. [Measurement](https://github.com/DorukhanArslan/memory-core/actions/runs/44927413199) · [Recorded decision](result.json)

| Observation | Result |
| --- | --- |
| All registered examples | 1,653 matched, 9 differed, 0 blocked |
| Original acceptance conditions | 118 passed, 7 lack registered coverage, 3 have unresolved examples |
| Contracts | 54 complete, 10 partial |
| Heartbeat storage and migration | All 39 examples and 69 pairs of original and SDK phases matched |
| Reopened condition | `indexing.query-sync.boundaries`, triggered by `query-sync-boundaries-warm-failure-natural-retry` |
| Overall exit | 1, with `fullScopePassed: false` |

On the earlier SDK, 29 of the same 39 heartbeat examples matched. Ten repair replies displayed the location of the migrated file differently. The earlier run preserved the search retry condition. The next SDK supplied the configured home to the migration and passed two real examples on the hosted machine before starting the complete comparison. [Earlier archived measurement](https://github.com/DorukhanArslan/memory-core/actions/runs/44927439157/artifacts/14715754642) · [Corrected hosted preflight](https://github.com/DorukhanArslan/memory-core/actions/runs/44927413199/artifacts/14716800379)

The assessment read the complete report and replayed retained evidence. Its guarantee that all prior conditions still passed and one more condition had been earned failed. The independent review verified the actual host and SDK source, OS exit, complete catalog, 38 family gates and 128 individual results from the small artifact. It also checked the 39 heartbeat replay receipts against their original phase digests. The complete report has 1,910,522,940 bytes and SHA-256 `991afd681144986f77df7ff26601f5da3cf9f2d5b96d3ecd0dc3f643d7905d60`. [Archived original report](https://github.com/DorukhanArslan/memory-core/actions/runs/44927413199/artifacts/14722626407)

## What changed on the search retry

After a failed refresh, the test asked both systems to search again for the new word `boundarywillow297`. OpenClaw returned zero results, warned that the index was stale and suggested rebuilding it. The SDK returned the updated note from `memory/topics/note.md` with one hit and no warning. Six public fields capture that difference. Three file timestamps also used integer and decimal spellings for equal values. The recorded responses establish which answers differed. They leave the cause of the difference open. [Exact values from both systems](query-retry-difference.json) · [Original query records](https://github.com/DorukhanArslan/memory-core/actions/runs/44943504979/artifacts/14722198515)

A separate reader processed all 1,662 rows of the original report through its final byte, recounted all 38 family gates and recovered the original query and heartbeat responses. The 53,211-byte ZIP contains its count and every measured row digest. [Independent full-report recount](https://github.com/DorukhanArslan/memory-core/actions/runs/44943504979/artifacts/14722128682)

## Reproduce the decision

Use a clean checkout at measurement commit `6639e46da03d6f37dc144a826c26fa2f395a5fda` with its frozen Python dependencies. The Git object store must also contain the SDK product commit and previous independent decision `34b52d79f6082e061b8f1ce47a6ca27d407fb391`.

| Summary ZIP | SHA-256 |
| --- | --- |
| [Run 44927413199, 349,038 bytes](https://github.com/DorukhanArslan/memory-core/actions/runs/44927413199/artifacts/14721834715) | `838cf28293c08122089d5939c2d0e5c9204a095b3faddf2367433a1a28b04446` |
| [Run 44214324963, 308,200 bytes](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963/artifacts/14393591298) | `bca913e53324e08fa7b73a2f2bac8e31e07a2e4f784d38de327fd6c001d42a3d` |

Save each ZIP as `full-<run ID>.zip` and extract it into its sibling directory `full-<run ID>`. Save each GitHub artifact metadata object under the JSON key `artifact` in the sibling file `full-<run ID>-envelope.json`. Run the following with paths to the measurement checkout and the two extracted summaries.

```sh
python review.py \
  --measurement "$MEASUREMENT" \
  --summary "$SUMMARIES/full-44927413199" \
  --previous-summary "$SUMMARIES/full-44214324963" \
  --archive-sha256 838cf28293c08122089d5939c2d0e5c9204a095b3faddf2367433a1a28b04446
```

The resulting JSON has SHA-256 `c1924395d9c08255680d0868db9ef95340f980a657951f48d6735585a42543a6`.
