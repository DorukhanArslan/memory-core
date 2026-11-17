# Prompt runtime-context acceptance closeout

Both original `prompt.runtime-context` conditions are verified: **82 → 84/128, net +2**.
The fixed 64-contract, 128-condition scope is unchanged. All 82 previously verified
conditions remain verified. **44 conditions remain**; the 64 contracts are
**39 complete, six partial and 19 pending**. The full gate still fails; fourteen old differences
remain open.

## Frozen source and authority

- Failed first full comparison: `a882d3d78424ca3552fabce53355da1a6a8cdb65`.
- Accepted partial-scope comparison: `a27ec473f04b7f36d4bf68b28397223d805583cf`;
  [full run 44137396647](https://github.com/DorukhanArslan/memory-core/actions/runs/44137396647),
  workflow **Recheck prompt runtime context once**.
- Product source: `907944efb61245208812e81b5555560051ae11cc`.
- SDK SHA-256: `375890b10db63088c9fb1d2e6ce7ddafed363acfd6aa020da52dfd46de0d0517`, 164 files.
- SDK Git tree: `c0e5c2f805931d02f3834f8b856e2cc65c8bb9a6`.
- Original OpenClaw `v2026.9.9`: `bcfc88812a35243893585dbeca87ca41b48272ca`.
- Ten-case input map SHA-256: `1a245537eb8ca6f96d8987756ae607a24f6fef010acc2a26f803d18f6358fe22`.
- Previous 1,490-case catalog: `a6b6d9d2fee122e0759d421d0d170ab171fecc58e86bbb3f322dc0154742d7b8`.
- New 1,500-case catalog: `96bf1edb8fe29618d1b62792d1ffbf58423cd16f804eb490ba3f0a7c6c187ebb`.
- Original owners: 93 source bindings, 54 compiled artifacts, 21 required observed owner triples and 21 source import links.
- Product PR: [#29](https://github.com/DorukhanArslan/memory-core/pull/29), draft at launch.

The official published modules and pinned committed source are authenticated
separately; a reproduced source build is not claimed. The comparison's SDK
bytes equal the measured product bytes. Complete source-before/after,
adapter inventory and actual process-exit bindings were authenticated.
The previous catalog remains an exact prefix; the append contains only
the ten frozen prompt cases. No common case-input bytes changed during diagnosis.

## Product change and compared boundary

The original conditions are `prompt.runtime-context.outcomes` and
`prompt.runtime-context.boundaries`. Native runs genuine admitted OpenClaw
harness attempts. SDK runs the production `HostSessionRunner` →
`HostTurn.model_request()` boundary with its real catalog and registered tools.
The deterministic provider observes requests and requests actual memory tools;
it does not compose expected prompts or return expected recall payloads.

Each operation compares the complete effective memory-guidance lines, the full
five-tool availability map, the complete cron-style clock DTO or null, and
every whole ordered message from every actual provider callback. Availability
covers `memory_search`, `memory_get`, `sessions_search`, `sessions_history` and
`session_status`. All original guidance-owner invocations remain raw; internal
refresh-call counts are not the effective-section business contract.

Clock-enabled operations explicitly call the original `resolveCronStyleNow`
host producer and inject its complete `timeLine` as an admitted runtime
instruction. Automatic cron-helper invocation by an ordinary agent attempt is
not claimed.

Full system prompts, complete offered registries/definitions, provider requests and replies, tool executions, API returns/errors, transcript trees, complete SQL
and physical files remain raw. Unrelated Native persona/system composition and
unrelated built-in tool definitions are captured but are not compared as this
memory/runtime component contract. No message field, content block, recall hit,
score, citation, metadata or tool-result text is removed to conceal a difference.

The new production owner separates a live current user from its canonical
admitted row. The live user has its actual content/timestamp; the durable row
retains its admission key. Later turns read the canonical row with that key.
Current assistant/tool-result projection likewise retains live fields while
persisted copies receive the host-owned run ID after trust stamping. Subsequent
turns reconstruct those canonical copies. Established `turn.messages` and
continuation APIs retain their canonical records; durable run metadata stays host-owned.

When model-only text actually replaces the bound current user's transcript
text, its live copy retains the exact original text in enumerable
`__openclawTranscriptPromptText`, matching the original transform owner. The
canonical transcript and underlying runtime user stay unchanged. The marker
and model-only replacement therefore do not leak into the next ordinary turn.

Admission checks the fully assembled **model** prompt, not the separate session
prompt. FEFF effective text can be truthy yet JS-blank while the session prompt
is synthetic and nonblank: this case makes zero provider calls. Empty human
text with a genuine nonblank runtime event still makes its actual call. This
is not a rule that rejects all runtime-only or conversation-data events.

V4 quotes conversation/heartbeat data and escapes authored internal delimiters;
V3 retains its original legacy projection. The current carrier is bound to its
owner and released when the turn settles. Existing history remains unchanged;
ordinary user/model/tool appends remain actual durable facts. Blank admission
may retain source-proven thinking-level/model-snapshot control events, without
inventing a canonical user, runtime carrier or successful model response.

This fixture's unowned `openai-completions` transport selects the original strict
tool-ID replay policy. The SDK selects its production counterpart explicitly;
the provider-neutral default is unset. Occurrences, collisions and result
aliases stay paired in actual model requests. Execution and durable IDs remain
original. Tool-use replies supply a deterministic real provider `responseId`;
the original generated-UUID fallback without provider identity is unclaimed.

The actual corpus is memory-only with cross-conversation/session indexing off.
SDK uses its existing public source-policy resolver and complete resolved
policy, preserving the full catalog while full/scoped indexing respects memory
selection. Actual SQLite ranking and complete search/get business values remain
present. Production model-tool JSON preserves full values, source field order,
two-space indentation, Unicode escaping and JS number spelling such as `e-7`.
Neither the comparison driver nor guard reparses/reformats model text to match.

## Frozen family and retained failures

The family has **10 cases, 43 operations and 40 submit operations**; submit
attempts do not imply provider calls. It covers tool/citation variants, clock
zones/DST/host fallback, fragment order, V3/V4, runtime-only/blank admission,
historical/current carriers, an intact image block, reopen, real search/get and
Unicode whitespace. Every actual provider-bound message is retained and
authenticated, including source-proven zero-call steps.

These five focused attempts and the first full run remain failed, with **zero global credit**. Source prefixes below identify their original commits/SDK bytes, not the final source;
complete identities remain in the original reports, source seals and per-worker
source-before receipts.

| Attempt | Original source: commit / SDK SHA (files) | Original result and duration | Cause / retained limit |
| --- | --- | --- | --- |
| focused-001 | `25832e50` / `267acedf` (163) | Blocked; Native exit 0; report 26.454132 s | Reviewed runtime entry absent from allowlist. Full Native raw was not retained (`unavailable-or-unsafe`). |
| focused-002 | `cead1986` / `c3ba4457` (163) | Blocked; Native killed -9; report 231.814852 s | Eight individually validated captures; real recall kept a plugin manager/worker alive past its 120 s oracle timeout. |
| tail-001 | `91b9ca06` / `616431d0` (163) | Failed; Native 0, Python/coordinator 1; worker 24.297551 s | Cleanup exited genuinely; guard wrongly required original tool IDs to survive strict provider replay. |
| tail-002 | `d8ce322a` / `82cb568a` (164) | Failed; Native 0, Python/coordinator 1; worker 25.530985 s | Guard misread the exact JS undefined transport tag; later offline validation exposed undefined-versus-JSON details semantics. |
| remaining-001 | `8b87f2a3` / `82cb568a` (164) | Failed; Native 0, Python/coordinator 1; worker 24.062380 s | Evidence wrongly required a call for the FEFF/NEL blank model prompt; the other three submits each called the provider. |
| full-44088814920 | `a882d3d7` / `375890b1` (164) | Blocked; OS exit 2; 7275.103640287 s | Old FIF split-old-full-complete-forget capture was 537,228,558 bytes: 357,646 above the unchanged 512 MiB guard. All ten new prompt cases matched; global assessment awarded nothing. |

Focused-001 retains 90,763 stdout bytes, traces and its exception, but no complete
Native raw. Its missing raw size cannot be reconstructed or asserted. Later
transport changes do not repair that missing evidence. Focused report SHA-256s:
001 `f1c947851cf43b1e0a891df780e948b166eeab7334be684ec64bdf80262d2876`;
002 `bc6751df2b3c8f972d3de81337a51972f009665ddb9e4f2e3646269b1564c0d9`.

Later SDK development checks and retained-pair replays keep their own source
identities. They do not relabel these failures or replace fresh family evidence.
Successful offline replays retain `originalProbeStillFailed:true` and zero fresh
Native engines, zero fresh SDK engines and zero global credit. Genuine cleanup,
lossless raw transport and causal-guard corrections retain complete outputs.
The exact undefined tag follows real JSON omission/null rules; forged tags and
real errors still fail. Scoped raw compression is lossless and separately sealed.

## Failed full run, read-only diagnosis and accepted recheck

The [first full run](https://github.com/DorukhanArslan/memory-core/actions/runs/44088814920)
retains **1,485 matched, fourteen old mismatches, one blocked**, no runner errors,
exit **2**, **7,275.103640287 s** and `fullScopePassed:false`. All ten new prompt
cases matched and their family gate was true, but independent FIF replay was
unavailable; assessment stayed **blocked**, with no candidate score or credit.
The 1,524,483,180-byte report SHA-256 is `868a3f85431f6be14617fe74c03eb697247420d605f1abdb2bea802531d19499`;
blocked assessment SHA-256 is `1088084cb83a8d4dd33fd510ef4cc1ac6a70fdf5ba0859fe17ad7eb901c9ab45`.

Read-only [diagnosis 44114457990](https://github.com/DorukhanArslan/memory-core/actions/runs/44114457990)
authenticated raw artifact `14339997707` inside GitHub only, SHA-256 `59e4a892bac968cda3c9133f5220be50c7660ddc27e28d8b5972f09c27351fb5`.
Receipt SHA-256: `53c735dd1d25688152ab26b5891853b35a0dd81e47fa624c441369fe0708aa81`.
The outer raw JSON was already compact. Nested coordinator stdout retained
default separator spaces; compact production of that same JSON would remove
15,049,701 outer bytes, yielding **522,178,857 bytes including writer LF**, below
the existing **536,870,912-byte** limit. This diagnosis executed no comparison
engines/business calls, emitted no capture values and rewrote no raw captures;
the estimate is not an independently reparsed acceptance capture or a new pass.

The user approved a new full measurement after this concrete diagnosis. Its
comparison-only change adds compact separators to the coordinator's successful
JSON output; the four workflow names change to keep the new run separate.
Product SDK bytes, all 1,500 case definitions, normalization policies and file
limits remain unchanged. The earlier failed report is not rewritten or accepted.

In the fresh recheck the formerly blocked FIF case matches. Its SDK raw file is
**474,472,916 bytes**, below the unchanged **536,870,912-byte** limit, SHA-256
`76ebfb29179b2467984799b95ce55a413d946374257e474a228c6d7750dfdcbf`.
This is a newly executed capture, not the hypothetical reformatted old value.
All thirteen FIF cases pass independent replay with complete baseline and final
source authentication. All ten prompt whole-pair raw replays also validate;
all fourteen complete-family gates pass.

## Complete assessment and independent review

The second full run retains **1,500 cases: 1,486 matched, fourteen mismatched,
zero blocked and no runner errors**. Its actual process exits **1**, after
**6,210.218580552 seconds**; `fullScopePassed:false` remains correct because
**42 conditions are uncovered and two registered conditions remain unresolved**.
The complete report is **1,522,925,718 bytes**, SHA-256
`080d8a69437fcc44db824583b5a7fb3b834be1c575220a7a000a5a28455a2dd4`.
Assessment SHA-256:
`20af968622ab7a29339d6a11bd9cf4c363099f1bba87d3907328b64b1f9cd701`.
Source-seal SHA-256:
`b544348f2f77dcb94c845c7d064f47018bce6a5fd9647ae276901178c5aaaff6`.

The frozen CI assessor parses the complete report to EOF and reopens retained
raw captures. Two separate local reviews recompute all 128 original conditions
from its complete-EOF projection and the frozen definitions, verifying source,
exit and replay receipts. Both review processes exit 0 without executing
original engines. Only `prompt.runtime-context.outcomes` and
`prompt.runtime-context.boundaries` change from false to true. This yields
**84/128, 44 remaining; 39 complete, six partial and 19 pending contracts**.

Root review receipt SHA-256:
`c3f9e466b43afb085106f3640199167256fcb38c24c107a0b9f805e8f9c641a7`.
Separate independent review receipt SHA-256:
`5e2e108e269ebdeb99a4c1d58458cadb4eee0ecd76e8287b3e6ba157ffd42f8b`.
The scripts and OS-exit receipts remain in the acceptance workspace; this does
not claim they were uploaded by a Git commit. The frozen CI assessor, runner,
replay commands and dependency preparation are retained on comparison `a27ec47`
in `.github/workflows/verify-merged-forget-once.yml`.

All fourteen old SDK whole-public mismatch hashes remain unchanged. Only the
uncredited Native warm-flush hash changes, to
`4cdb2aa71ea06ed46a094e47e3739276fae9238c4480d82a6eee896d6451b569`;
its case remains mismatched with `covers:[]`. No old difference receives credit,
and the four held value investigations remain on hold.

Only the **673,299-byte** summary was retrieved through sixteen authenticated
reader-job logs. Summary artifact `14362931007`, SHA-256
`f7424306a123f413789959d121667f165293c2bc32ba0dc4405c21dd22d4a242`.
The **2,459,063,218-byte** raw artifact `14363150675` remains in GitHub, SHA-256
`dfcd50425b1188148119f84d632e3fd055246d5ff9a81bf5f0f6802a13a8f98d`.
The complete report and raw archive were not downloaded locally. Complete
projection, source/exit receipts and both local reviews remain under
`work/prompt-runtime-context/acceptance/recheck/`; first-attempt records retain
their original directories and failed identities.

## Remaining scope

The profile fixes OpenClaw identity, sequential non-incognito manual turns,
projection versions 3/4, actual America/Los_Angeles host fallback and actual
12-hour detection. UTC/Istanbul/New York clocks and DST use paired modern times.
Python calendar support remains years 1–9999. Wider JavaScript dates, every
provider/media/sender-context/steering/retry mode, concurrent lifecycle, Google
cached-prefix insertion and unrelated full agent persona are not verified here.
Message isolation/quoting does not prove LLM obedience or universal injection
immunity. Helper-only probes and the strict9/UUID fallback paths receive no
credit. The older fourteen mismatches are not resolved by this closeout.
