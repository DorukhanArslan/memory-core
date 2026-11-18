# Independent review of the 1,623-case memory comparison

The accepted result is **118 of 128 conditions**, an increase of 34. The reviewed SDK is product commit `160c7c2d70aaa2a030a13103a8c56b8e23430015`. Its 183 Python source files have SHA-256 `07c4c507f75b17357f9d82e37cd67f59f968323c960f5f4ae02731644c84698a`.

| Measure | Result |
| --- | ---: |
| Matched cases | 1,615 |
| Differing cases | 8 |
| Blocked cases or engine errors | 0 |
| Complete / partial / pending contracts | 55 / 8 / 1 |
| Conditions without full registered coverage / registered but unresolved | 8 / 2 |

The original comparison ran for 5,499 seconds. Its full report has SHA-256 `2d661807ea171e02ee8f1676ac5eb94b30e720de396141ae65572e0c9e358e7f`. The first postprocessor read that report to the end and stopped on a relative path. A supplemental run authenticated the original archives, retained the eight groups already replayed, and finished replaying the remaining groups. It distinguishes the content recovered from the ZIP from filesystem identities and timestamps observed by the original processes. [Measurement](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963) · [Retained evidence review](https://github.com/DorukhanArslan/memory-core/actions/runs/44232754070)

The supplemental postprocessor stopped at its guard for unexpected changes to earlier differences. The independent review checked that guard against both SDK releases for case F14. The sole changes were the integer and floating-point JSON spellings of the same timestamp before and after the query. Both SDK runs returned an empty candidate list. The native whole output retained its previous hash. F14 remains open. The hosted postprocessors retain their original blocked results. The 118 figure comes from the independent recount of the 128 condition definitions and all 37 family gates. [Earlier SDK output](f14/before/single/public.json) · [Current SDK output](f14/after/single/public.json) · [Full independent decision](root-review.json.gz)

## Reproduction inputs

Use a clean checkout of measurement commit `8b00530188a1d6e87a02172bebf7b6e8b5c49433` with its frozen Python dependencies. The Git object store must include both the product and supplemental review commits. These three small ZIPs contain the inputs for the independent recount.

| Input | GitHub artifact | ZIP SHA-256 |
| --- | --- | --- |
| Previous accepted baseline | [14362931007](https://github.com/DorukhanArslan/memory-core/actions/runs/44137396647/artifacts/14362931007) | `f7424306a123f413789959d121667f165293c2bc32ba0dc4405c21dd22d4a242` |
| Measured suite | [14393591298](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963/artifacts/14393591298) | `bca913e53324e08fa7b73a2f2bac8e31e07a2e4f784d38de327fd6c001d42a3d` |
| Supplemental assessment | [14396301086](https://github.com/DorukhanArslan/memory-core/actions/runs/44232754070/artifacts/14396301086) | `ca5a68d2e184581b6f96840a67e22acdc8604cffece2c93f7924822333794512` |

Extract each ZIP to a directory called `full-<run ID>`. For the measured and supplemental runs, retain the ZIP next to its directory as `full-<run ID>.zip`. Save the GitHub artifact API's metadata object under the JSON key `artifact` in `full-<run ID>-envelope.json` next to it. Copy the included `baseline-root-review.json` into the extracted previous baseline as `root-review.json`.

Run the following from this directory in the measurement's Python environment. Set `EVIDENCE` to the parent of the extracted directories and `MEASUREMENT` to the measurement checkout.

```sh
python review_remainder.py "$EVIDENCE/full-44214324963" \
  --accepted-baseline "$EVIDENCE/full-44137396647" --compare "$MEASUREMENT" \
  --run-id 44214324963 --head 8b00530188a1d6e87a02172bebf7b6e8b5c49433 \
  --artifact-sha256 bca913e53324e08fa7b73a2f2bac8e31e07a2e4f784d38de327fd6c001d42a3d \
  --supplement "$EVIDENCE/full-44232754070" --supplement-run-id 44232754070 \
  --supplement-head 38c686d13ef7a9a88aa9e73ee226946d9bd252f0 \
  --supplement-sha256 ca5a68d2e184581b6f96840a67e22acdc8604cffece2c93f7924822333794512 \
  --f14-reproduction f14
```
