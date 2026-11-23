# OpenClaw v2026.9.9 memory comparison

**119 of 128 acceptance conditions passed.** The Python SDK recovered the search retry condition. All 118 conditions accepted on the preceding candidate passed again. [Full comparison](https://github.com/DorukhanArslan/memory-core/actions/runs/45153594838) · [354,903-byte evidence archive](https://github.com/DorukhanArslan/memory-core/actions/runs/45153594838/artifacts/14820546579)

| Measured result | Count |
| --- | ---: |
| Matching examples | 1,654 of 1,662 |
| Previously recorded differences still open | 8 |
| Blocked examples / engine errors | 0 / 0 |
| Complete / partial contracts | 55 / 9 |
| Conditions awaiting a registered example | 7 |
| Conditions with registered examples that still differ | 2 |
| Search synchronization boundary cases | 8 of 8 matched |
| Heartbeat storage and migration cases | 39 of 39 matched across 69 paired process phases |

Both systems returned zero results, the stale-index warning and the same recovery action on the first retry after a failed update. After reopening, both found the updated note once and returned it without a warning. Across all 1,662 examples, only this retry changed its match status. The original eight differences remain open. One of those examples, the first search after a flush, again produced a different OpenClaw output digest across runs and retained its previous SDK digest. It carries no acceptance point. The full comparison exited with code 1 and recorded `fullScopePassed: false`. [Observed public replies](public-45153594838.json)

The independent count reproduced all 128 condition decisions and all 38 family gates from the complete report projection. It also verified the 214 recorded physical replays in the 32 families with separate replay counts. The hosted assessment completed without errors. [Independent count and case IDs](independent-45153594838.json)

| Source or artifact | Identity |
| --- | --- |
| Measured product | `fc4aad3995d5f547f7a844d8b9024523d85b032d` |
| Measurement commit | `8a8b447bf539c4f270c5d319da9ca84d5879530d` |
| Pinned OpenClaw commit | `bcfc88812a35243893585dbeca87ca41b48272ca` |
| SDK Git tree | `067066c08f64c53a378d707276da6c795b80cc53` |
| SHA-256 of 183 SDK source files | `df9cb99bb5b8423bf1e45d2b5c7eb018f1c55622f300d37e1ffffe47950e3bd6` |
| Full report SHA-256, 1,909,410,536 bytes | `8f9a1471a20e8a89d3c7a71f03dde773285b4a113db3ea0ab5fc2c0e0b977119` |
| Compact evidence archive SHA-256 | `68590697b56a6fed14c3d3b49d62714fb3c4cc2f34332a2d9177b79b58c09a4a` |

## Reproducing the count

Use a clean checkout of the measurement commit with its frozen dependencies. Keep the measured product and the two preceding review commits, `5bd9ac41dfa66b7732a6898b6a4e02366dd836de` and `34b52d79f6082e061b8f1ce47a6ca27d407fb391`, in the same Git object database. The reviewers read the original frozen case definitions and the retained per-case results.

Place the two GitHub summary ZIPs and the two adjacent envelope JSON files in the same directory. Name the ZIPs `full-45153594838.zip` and `full-44927413199.zip` and extract each into the directory with the same name without the extension. The hosted summary in each ZIP contains the original process exit and the full report digest. [Current summary](https://github.com/DorukhanArslan/memory-core/actions/runs/45153594838/artifacts/14820546579) · [Preceding summary](https://github.com/DorukhanArslan/memory-core/actions/runs/44927413199/artifacts/14721834715)

From the directory containing those summaries, run the two reviewers with the Python interpreter from the measurement environment. Set `measurement` to the clean checkout path and `review` to the directory containing this README.

```bash
args=(--measurement "$measurement" --summary full-45153594838 --run 45153594838
      --head 8a8b447bf539c4f270c5d319da9ca84d5879530d
      --product fc4aad3995d5f547f7a844d8b9024523d85b032d
      --archive-sha256 68590697b56a6fed14c3d3b49d62714fb3c4cc2f34332a2d9177b79b58c09a4a)
python "$review/review_search.py" "${args[@]}"
python "$review/review_public_changes.py" "${args[@]}" --previous-summary full-44927413199
```
