# Explicit scheduled memory tasks

The focused run at `6488da6` matched `automation.job-state.boundaries` on
OpenClaw `v2026.9.9`. The original cron service and the Python host each
opened the stored jobs anew for seven explicit drives. Four reads reached
the actual memory tool. The early, retry and disabled drives had no callback.
Two due tasks stayed independent, the missing note returned `not_found`, and
a changed source file returned its new contents at the next interval.

The original public task runner, memory tool, SQLite store worker and
read-location subprocess ran in a private fixture. The host serializes
admission of a named SDK heartbeat task and records it on completion.
Python host timers, cron/one-shot parsing, DST, full run history, failure
policy and legacy migration are outside this observation. The separate
`automation.job-state.outcomes` condition remains open. Only a new complete
catalog assessment can update the published score.

## Replaying the observations

The CI artifact includes the `automation-job-state` directory. Run this on
the code revision that produced it. Select the desired producer's
`sdk-attempt-*/review.json` when the artifact contains both subset and full runs.

```sh
python -m equivalence.automation_job_state_replay \
  --packet /path/to/automation-job-state/sdk-attempt-EXAMPLE/review.json \
  --evidence-root /path/to/automation-job-state
```

For the first focused run, supply `--report` with its JSON report in place of
`--packet`. The report SHA-256 is
`22648c21e7a88e0be6f96a67e504aad6356c987838d6908221ad5f346b0313bb`.
The replay checks the original and SDK streams, the submitted fixture, the
original module table and per-process traces, each callback and its full tool
response, the actual final SQLite records, and the SDK store and source files.
It returns seven drives and four durable receipts.

Earlier exploratory runs discovered the missing source-locked cron dependency
and the original SQLite cache requirements. The first seven-drive custody
check rejected an additional read-location subprocess after it observed all
seven calls. Its output was retained separately. The accepted run additionally
identified that published SQLite executable and verified its parent process
and loaded module. These earlier attempts earned zero conditions.
