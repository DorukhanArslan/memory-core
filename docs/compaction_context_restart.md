# Compaction context after restart

The targeted family covers `compaction.context-assembly.boundaries`. A real OpenClaw
Responses stream captures a provider checkpoint. A subsequent function call reads a
line from `MEMORY.md`. The original embedded agent opens the stored transcript in a
new process and sends the next request to the original provider's HTTP transport.
An offline fixture supplies the provider replies. On the SDK side, separate
processes use the normal session runner, checkpoint tracker, memory tool and
Responses input. Each side saves its database and complete outgoing input.

| Restart | Observed provider input |
| --- | --- |
| Same model with the checkpoint in the retained history | The opaque checkpoint, assistant summary, tool call, matching result and current prompt are sent. |
| Same model with the checkpoint before the history limit | The history stage projects the checkpoint onto an empty assistant message. The final request drops that empty message and retains the call and its result. |
| Different model with the checkpoint in history | The request includes ordinary assistant text and the tool call and result. The opaque checkpoint stays bound to the original model. |

All three comparisons check the complete `input` array and the checkpoint, call
and tool result in the actual stores before and after restart. Tool details,
arguments and output text must match. Raw captures also preserve the full
request bodies, input and output events and host-specific metadata. The
separate outcomes condition covers active summaries, tool-result bounds and
the complete replay decision.

For a retained CI artifact, use the producing code revision and run the
following command for each `sdk-attempt-*/review.json` under
`compaction-context-assembly`.

```sh
python -m equivalence.compaction_assembly \
  --packet /path/to/compaction-context-assembly/sdk-attempt-EXAMPLE/review.json \
  --evidence-root /path/to/compaction-context-assembly
```
