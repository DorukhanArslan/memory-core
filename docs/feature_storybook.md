# Feature Storybook

This file explains package behavior with concrete input/output stories. It is
not a parity claim by itself; use `docs/parity_matrix.md` for evidence labels.

## Story 1: Chat Turn With Managed Memory Flush

Goal: show how a normal chatbot can answer a user and persist durable memory
without the application manually assembling memory-injection or flush prompts.

### Starting Files

```text
my-agent-app/
  MEMORY.md
  memory/
  .openclaw-memory/main.sqlite
```

`MEMORY.md` may be empty or contain only the default template.

### User Input

```text
Bana Doruk diye hitap et.
```

### Package Call

```python
result = memory.chat(
    "Bana Doruk diye hitap et.",
    llm=llm.chat,
)
```

### Step 1: Recall Injection

The package first runs memory search with the user message as the query.

If there are no useful results, the answer call receives only:

```python
[
    {
        "role": "system",
        "content": "Use relevant memory when it helps answer the user. Do not mention memory unless useful.",
    },
    {
        "role": "user",
        "content": "Bana Doruk diye hitap et.",
    },
]
```

If memory already contains a related preference, the package inserts a second
system message:

```python
{
    "role": "system",
    "content": "Relevant memory:\nMemory recall:\n- memory/2026-05-30.md:3-3 score=0.91\n  User prefers to be addressed as Doruk.\n\nSource: memory/2026-05-30.md#L3",
}
```

### Step 2: Assistant Answer

The application LLM returns:

```text
Tamam Doruk.
```

The package stores this in:

```python
result.assistant_message == "Tamam Doruk."
```

### Step 3: Memory Flush Prompt

After the answer, the package runs a second LLM call using the OpenClaw-style
flush plan:

```python
[
    {
        "role": "system",
        "content": "Pre-compaction memory flush turn. ... Store durable memories only in memory/YYYY-MM-DD.md ...",
    },
    {
        "role": "user",
        "content": "Pre-compaction memory flush. ...\n\nRecent turn transcript:\nUser: Bana Doruk diye hitap et.\nAssistant: Tamam Doruk.",
    },
]
```

The flush model may return:

```text
- User prefers to be addressed as Doruk.
```

or:

```text
NO_REPLY
```

### Step 4: Durable Write

If the flush output is not empty and does not start with `NO_REPLY`, the package
appends it to the canonical daily file:

```text
memory/2026-05-30.md
```

The resulting file:

```markdown
- User prefers to be addressed as Doruk.
```

Then the package reindexes memory, so the next user turn can retrieve the new
preference.

If the flush output starts with `NO_REPLY`, no file is written.

### Returned Object

```python
result.assistant_message
result.flush_result.wrote
result.flush_result.path
result.flush_result.text
```

Example:

```python
result.assistant_message == "Tamam Doruk."
result.flush_result.wrote is True
result.flush_result.path == "memory/2026-05-30.md"
result.flush_result.text == "- User prefers to be addressed as Doruk."
```

### OpenClaw Comparison

OpenClaw official flow:

- `memory-core` registers a `flushPlanResolver`.
- Runtime decides whether to run memory flush using token/transcript gates.
- Runtime launches a separate memory-flush agent turn.
- The flush turn can write only to `memory/YYYY-MM-DD.md`.
- `NO_REPLY` means no user-visible reply is needed.

Python package flow:

- `build_memory_flush_plan(...)` mirrors the OpenClaw flush plan.
- `memory.chat(..., auto_flush=True)` always runs the flush step after the
  answer unless disabled.
- The package appends non-`NO_REPLY` flush output only to `memory/YYYY-MM-DD.md`.
- Full OpenClaw runtime gates, session-store metadata, model fallback, sandbox
  checks, and transcript-size dedupe are not implemented here.

Evidence label: `adapter-only` for `chat()` orchestration, with `source-backed`
flush-plan behavior.
