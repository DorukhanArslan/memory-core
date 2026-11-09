# Host restart recall development — 2026-11-09

This package adds executable, authenticated diagnostics for existing requirement
63, `host.restart-recall`. **Acceptance remains 64/128 (50.0%), with 64 remaining.**
The contract remains pending at 0/2. All three new literals have `covers: []`,
are absent from the default differential catalog and award zero conditions.
The SDK production tree and the 64-contract/128-condition scope are unchanged.

The clean `534b94ba4a18752a9dae8ac8e23adfd69929dd0a` comparison reports
**0 matches, 3 mismatches, 0 blocked cases and no runner errors**.
`finalAuthenticationPassed` is true. Each case retains 20 exact JSON differences;
none is rounded, dropped or replaced with a successful expected response.
The [committed diagnostic summary](host_restart_recall_diagnostics.json) retains
complete comparable results, differences and raw-artifact hashes. It is a
summary of execution, not a replacement for live process evidence.

## Actual host flow

The [three frozen inputs](host_restart_recall_literals.json) exercise ASCII,
Unicode and an actual filesystem read failure. Each implementation runs a real
producer plus a fresh reader chat in one process, exits that process completely,
then starts an independent host process with a third fresh session and the same
durable locations. A separate agent/workspace must not retrieve the saved fact.

The source begins absent. Native passes the original coding `write` tool,
including its private execution preparer and outcome hook, into the original
compiled AgentLoop. The SDK dispatches its real registered `append_daily_note`
through `HostSessionRunner`. Both genuinely produce the same UTF-8 daily note.
These unlike producer APIs and their complete receipts remain raw; this package
does not claim write/curation API parity. Native explicitly marks the memory
watch dirty and awaits real index synchronization after the write. That is
declared fixture maintenance, not evidence for the automatic next-turn barrier.

Readers receive only their own generic prompt/query, fresh identities, clock
and locations. The inherited capability carries opaque input hashes, not a
full producer fixture path. Complete initial callback inputs are checked for
the unique saved answer, including system/runtime context, tools, messages and
Native model/options. Original search results supply the get path and range;
the terminal assistant echoes the actual model-visible get result. Successful
gets are bound to the observed saved source bytes. No-hit isolation replies
come from actual empty results.

In the failure case, after actual search and before actual get, the selected
source is genuinely renamed outside the indexed workspace and replaced with a
directory. Both implementations return the complete `MEMORY_READ_FAILED`
payload; the assistant returns that error JSON. The SDK also records the tool
failure in its host outcome. It is not converted to an empty successful read.

Native actually loads the session store with `skipCache`, verifies each fresh
key is absent, reads its original empty transcript and persists emitted loop
messages. This verifies bounded fresh-session reconstruction, not restoration
of an earlier chat. The separate session-history worker declarations are
authenticated only. Full embedded-runner orchestration, daemon startup,
crash recovery and concurrent writers remain outside this development proof.

## Why complete results still differ

| Difference | Actual observation and next action |
| --- | --- |
| Source policy and FTS scores | Native defaults `rememberAcrossConversations` to true, indexing both `memory` and `sessions` even for a memory-only query. The SDK adapter explicitly disables session search/indexing. Native's ASCII index contains the 7-token note and a 13-token writer transcript; SDK has one FTS document. BM25 uses whole-table statistics before corpus filtering. Align actual indexed/search source policies and publication cadence before diagnosing a scoring defect. |
| Search timing | Native's real tool uses the controlled Date clock; HostKit does not forward its injected clock into its search context. SDK timing values remain real, and its payload omits `managerMs`. Forward the clock at the actual host tool boundary and investigate genuine manager telemetry. |
| Provenance time | `observedAt` comes from each real file's independently produced mtime. No source retiming or timestamp alias is applied. A later paired metadata-control policy must preserve real write/index custody. |
| Empty-index lifecycle | The isolated Native result includes `corpora: []` and its actual automatic-repair warning; SDK's eager index lifecycle omits both. Both retrieve no primary memory. Compare the lifecycle owners; keep the warning and field-presence differences visible. |

The Native isolated index may contain its own fact-free session prompt. Its
memory-source chunk count is zero and no saved answer appears in its chunks;
the check does not pretend the entire index is empty. Requested sync/query
settings are retained alongside the original owners' actual resolved behavior;
no manual restarted-process sync is called, while original automatic behavior
is left intact. Controlled saved acknowledgements and transcript publication
cadence also need explicit alignment when session indexing is compared.

## Authority and retained attempts

The reference is OpenClaw `v2026.9.9`, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. Independent bindings pin 60 source
owners, 63 compiled artifacts and the published native file-safety module.
Official release setup verifies 83 packages/24,707 files. The approved Node is
24.16.0 / ICU 78.3 / Unicode 17; executable SHA-256:
`b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`.
Source-build reproduction remains false; no source substitutions are permitted.

Each actual coordinator, child and worker inherits the separate protected
preload. Checks bind real process ancestry, main-thread imports, role adapters,
producer exit before reader spawn, original index/search/publication/plugin-state
worker routes, full stdin/stdout, close receipts and before/after source hashes.
Publication uses the original canonical agent SQLite carrier/backend route.
No provider credentials are passed; runtime fetch is denied and no paid calls
are made. Structural replay is explicitly not live execution or acceptance.

- `work/host-restart/attempt-001/`: all three native processes completed, but
  the new verifier requested an unlisted central runtime entry and blocked all
  comparisons. Streams and artifacts remain unchanged. The verifier now uses
  the existing reviewed manager entry and independently requires AgentLoop.
- `work/host-restart/attempt-002/`: three authenticated mismatches, no blocked
  cases/errors, before final transport/guard hardening. Those observations
  remain bound to their original adapter hashes.
- `work/host-restart/attempt-003-clean/`: final clean-commit capture with an
  incremental UTF-8 process decoder and expanded custody guards; three
  mismatches, zero blocked/errors. Report size is 15,093,348 bytes and SHA-256 is
  `cc5df7887a3945e0c90253b53ce3098c4ee30e7c4ff851df72d3c58a962e3d4f`.

Every attempt owns a new directory; there is no automatic retry. Original
failures are not discarded or relabeled. Raw artifacts/dependencies remain
local under ignored `work/` and `.reference/`; pushing Git does not upload them.
The committed summary provides their identities and full public differences.
Independent read-only review verified all 120 listed artifact hashes, the SDK
and adapter source hashes, three main-process plus 13 worker traces per case,
and all 18 Native/SDK read chains. Reconstructing the Native FTS table in a
separate in-memory database and removing only its session row reproduces the
SDK text score exactly; the original evidence was left unchanged.

## Validation and next package

The 26 focused guards pass: real SDK processes for all three literals,
adversarial receipt replay, exact literal/zero-credit enforcement, pre-import
capability rejection and actual inherited ESM-worker transport. Replay rejects
even a self-consistent forged get/answer when the saved source bytes disagree.
Two initial test-setup errors (a null runtime-context mutation and a CommonJS
eval worker instead of the original ESM route) were corrected before this run;
they contribute no behavioral evidence. Ruff, naming and source-inventory checks
pass. The fresh full regression run passes **6,785 tests, zero failures and
1,648 skips in 298.08 seconds**. Skips grant no acceptance credit and retain
the same historical/live and old absolute-runtime-path limits as the prior
baseline. The full log is `work/host-restart/full-regressions.log`.

The unchanged 156-file SDK SHA-256 is
`0944d2bcdd15096e59e1ec3715d47e57013427fec85dc47c541fa176c8739997`.
The last complete default differential catalog remains the historical clean
`b090394` report: 1,403 cases, 1,389 matches, 14 differences and zero blocked/errors.
This development package does not claim a new full-catalog or package-consumer run.

Next, align actual source-policy resolution and transcript publication in the
paired hosts, then address the clock/telemetry and empty-index lifecycle gaps
without suppressing fields. Preserve these diagnostic inputs and reports.
Only after complete paired results and the required boundaries pass should
acceptance-family registration and a fresh full gate target the two existing
`host.restart-recall` conditions.

With the existing verified dependencies installed, reproduce using a new path:

```sh
.venv/bin/python scripts/check_host_restart.py \
  --reference work/openclaw-v2026.9.9 \
  --node work/node-v24.16.0-linux-x64/bin/node \
  --release-runtime .reference/release-runtime \
  --output work/host-restart-new-attempt
```

The command refuses existing output directories, never downloads or retries,
and returns 1 for genuine mismatches (2 for blocked/error cases). Exit 0 would
mean only that the selected development pairs matched; it would award no credit.
