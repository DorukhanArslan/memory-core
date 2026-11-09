# memory_get Tool Contract

The active reference is OpenClaw **v2026.9.9**, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. The relevant owners are
`extensions/memory-core/src/tools.ts`, `memory-read-tool.ts`, `memory-corpus.ts`,
and `packages/memory-host-sdk/src/host/read-file.ts` and `read-file-shared.ts`.
This document describes the Python read boundary and its supported host policy.
It describes the read interface and its deadline/cancellation controls, without
claiming complete filesystem, network cancellation, or manager lifecycle parity.

## Entry points

| API | Purpose |
| --- | --- |
| `create_memory_get_tool(config, ...)` | Create a model-facing read tool, or return `None` when disabled. No store or index is required. |
| `tool.definition` | A defensive copy of its `label`, `name`, `description`, and JSON `parameters`. |
| `tool.execute(tool_call_id, params, signal=None)` | Validate model arguments, perform the read, and return the complete JSON result envelope. |
| `execute_memory_get_tool(config, params, ...)` | Run the same read from raw model arguments and return its payload dictionary directly. |
| `memory_get(config, *, path, from_line=None, lines=None, corpus="memory", ...)` | Python convenience form below raw argument validation. |
| `memory_get_tool_definition(extra_paths=())` | Return the provider-neutral name, description, and schema. |

The factory exposes read-only `name`, `label`, `description`, and `parameters`
properties as well. Native `memory_get` has no argument-preparation callback;
the Python factory does not invent one.

The factory and both direct functions accept trusted `execution=` with a
`MemoryToolDeadlineContext`. A factory call's optional third `signal` argument
overrides that context's parent signal for that call. These are host options,
not properties in the model's argument schema.

The factory returns the native-shaped envelope:

```python
{
    "content": [{"type": "text", "text": "<pretty-printed JSON of the complete payload>"}],
    "details": payload,
}
```

`serialize_get_tool_result(payload)` is the same serialization boundary.
`execute_memory_get_tool` and `memory_get` return `payload` itself. Transport
comparisons must retain the full ordered result, optional fields, null values,
and diagnostics; the envelope text and details describe that same payload.

## Arguments and read budgets

Raw arguments must be a parsed mapping. Other inputs, including JSON text,
read as an empty record. The readers validate `path`, `from`, `lines`, and then
`corpus` in that order.

| Argument | Meaning |
| --- | --- |
| `path` | Required nonblank string, trimmed with ECMAScript whitespace rules. |
| `from` | Optional positive safe integer or strict numeric string; one-based starting line. |
| `lines` | Optional positive safe integer or strict numeric string; requested line count. |
| `corpus` | `memory`, `wiki`, or `all`. Blank and non-string values read as omitted. |

Missing, null, and blank numeric values read as omitted. Booleans, fractions,
unsafe integers, hexadecimal strings, NaN, and infinity do not satisfy the
positive integer reader. The Python convenience function remains below these
readers: its numeric range options are floored and bounded to at least one.

Workspace reads default to **120 lines** and **12,000 UTF-16 code units**,
configured through `MemoryConfig.memory_get_default_lines` and
`MemoryConfig.memory_get_max_chars`. Astral characters such as emoji consume
two UTF-16 units. The character budget applies to excerpt text before the
continuation notice is appended.

The reader retains whole lines while they fit. An oversized first line is
truncated without splitting a surrogate pair. A terminal newline closes the
last line; it does not create another readable blank line.

Successful workspace reads return:

```python
{
    "status": "ok",
    "text": "the selected excerpt",
    "path": "MEMORY.md",
    "from": 1,
    "lines": 1,
}
```

When whole-line paging can continue, the result adds `truncated=True`,
`nextFrom`, and `[More content available. Use from=N to continue.]`. A hard
single-line truncation omits `nextFrom` and uses the maxChars notice. Built-in
workspace reads also suggest the raw source reader for that case.

If a one-unit budget cannot fit the first emoji, the result still reports one
included line and `truncated=True`. Its text contains the continuation notice
even though the excerpt body is empty. It does not return half a surrogate or
silently drop the notice. Configured extra paths use the same truncation
builder without the built-in raw-reader suggestion.

`build_memory_read_result` and `build_memory_read_result_from_slice` are the
shared production builders used by the actual reader. They support raw
content and an already selected line slice, respectively.

## Corpus selection and wiki excerpts

An omitted corpus reads the built-in memory file. `wiki` queries registered
supplements without reading that file. `all` attempts both corpora: a successful
primary excerpt takes precedence, while a missing or failed primary read can
fall back to the wiki result. Corpus outcomes and warnings remain visible even
when another corpus supplies successful content.

The wiki provider owns its excerpt. Its returned `content` becomes `text`,
`status` becomes `ok`, and every other returned detail is preserved. The tool
does not apply another line selection or character budget, normalize the
provider's result path, invent `from`/`lines`, or replace empty content with a
snippet. Empty strings and null content remain distinct. Provider titles,
citations, custom metadata, and null values survive the boundary.

Use `RegisteredMemoryCorpusSupplement(plugin_id, supplement, reader=...)` for
the native excerpt-reader protocol. The explicit callback receives:

| Keyword | Source |
| --- | --- |
| `lookup` | The trimmed model lookup, otherwise unchanged. |
| `from_line`, `line_count` | Validated range arguments, when present. |
| `agent_id` | The trusted configuration's agent. |
| `agent_session_key`, `sandboxed` | Trusted host context, when supplied. |

Absent optional values are omitted; `sandboxed=False` is retained. These
context fields are not model schema properties. Registrations are ordered by
plugin ID, the first non-null result wins, and other provider failures still
appear in corpus diagnostics.

An anonymous legacy supplement keeps its existing
`get(path=..., corpus=...)` call signature. A registration without an explicit
reader also supports that existing provider API. That call style is an SDK
extension: providers using it do not receive native range/context keywords.
Their returned excerpt still passes through the complete result mapping.

Registered providers are coordinated with at most four concurrent callbacks.
Completed excerpts and other providers' failures remain available when one
provider blocks. Plugins receive their documented query/context keywords,
without an added cancellation-signal argument.

## Runnable integration example

This example performs real file and wiki reads without a model, embedding
provider, SQLite store, or index:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_core.config import MemoryConfig
from memory_core.supplements import (
    RegisteredMemoryCorpusSupplement,
    StaticMemoryCorpusSupplement,
)
from memory_core.tools.get_factory import create_memory_get_tool


def read_wiki(*, lookup, from_line=1, line_count=120, **trusted_context):
    if lookup != "wiki/preferences":
        return None
    source = ["Preferred tea: rooibos.", "Preferred answer language: English."]
    selected = source[from_line - 1:from_line - 1 + line_count]
    return {
        "path": lookup,
        "corpus": "wiki",
        "content": "\n".join(selected),
        "from": from_line,
        "lines": len(selected),
        "title": "User preferences",
    }


with TemporaryDirectory() as temporary:
    workspace = Path(temporary)
    (workspace / "MEMORY.md").write_text("Preferred tea: rooibos.\n", encoding="utf-8")
    wiki = RegisteredMemoryCorpusSupplement(
        "example-wiki", StaticMemoryCorpusSupplement([]), reader=read_wiki,
    )
    tool = create_memory_get_tool(
        MemoryConfig(workspace_dir=workspace),
        supplements=[wiki],
        agent_session_key="agent:main:main",
        sandboxed=False,
    )
    assert tool is not None
    file_result = tool.execute("file-1", {"path": "MEMORY.md", "lines": 1})
    wiki_result = tool.execute("wiki-1", {
        "path": "wiki/preferences", "corpus": "wiki", "from": 2, "lines": 1,
    })
    assert file_result["details"]["text"] == "Preferred tea: rooibos."
    assert wiki_result["details"]["text"] == "Preferred answer language: English."
    assert wiki_result["details"]["title"] == "User preferences"
```

## Execution and cancellation

`MemoryToolDeadlineContext` supplies `signal`, a monotonic millisecond `clock`,
`schedule(delay_ms, callback)` returning a timer-cancellation function, and
`wait(event, seconds_or_none)`. Defaults use real timers and workers. Controlled
hosts can provide those same execution dependencies; they do not supply
prebuilt read results or expected timeout payloads.

The corpus determines which path is supervised:

| Read path | Execution policy |
| --- | --- |
| Omitted corpus or `memory` | Native unguarded built-in read. It does not gain a deadline or caller-abort check from this context. |
| `wiki` | Registered-provider coordination under one absolute 30-second budget and the caller's signal. |
| `all` | Built-in and wiki work run concurrently under the same absolute 30-second budget and caller signal. |

Raw arguments validate before wiki/all deadline admission. Those guarded reads
retain completed work and compose genuine deadline/corpus diagnostics when
other work exceeds the budget. A completed primary excerpt can therefore
remain `status="ok"` with a wiki warning and `timedOut=True`; a timeout does
not erase its content. Completion is checked against the absolute budget even
when an overdue timer has not yet been dispatched.

A caller abort of guarded work propagates its original exception object.
Cancellation stops waiting; it does not forcibly terminate a file or provider
callback. Late completions cannot mutate an already returned result. This does
not guarantee cancellation of an external provider's in-flight network call.
Reads do not use the search tool's failure cooldown.

```python
from memory_core.cancellation import CancellationSignal
from memory_core.tools.deadline import MemoryToolDeadlineContext

signal = CancellationSignal()
execution = MemoryToolDeadlineContext(signal=signal)
# Pass execution=execution to create_memory_get_tool or a direct read call.
# Another host task can abort signal while a wiki/all read is waiting.
```

Search's managed-readiness pause control and its independently budgeted wiki
work are described in [memory_search Tool Contract](memory_search_tool.md).
Ordinary memory-file reads need no index or memory-search manager.

## Filesystem policy and configured extra paths

Built-in reads use the existing workspace memory-path gate: supported root
memory files and Markdown files under `memory/`. Transcript search references
are not readable memory-file paths. Lexical path resolution, allowed-file
checks, and existing symlink policy apply before the read. Missing permitted
files return `status="not_found"` with empty text.

The factory and direct APIs accept trusted `extra_paths`, a sequence of file or
directory paths and `{"path": ..., "pattern": ...}` entries. A configured
Markdown file or a matched Markdown descendant of a configured directory can
be read outside the built-in memory paths. Patterns use the discovery owner's
POSIX glob matcher; multiple patterns on one root form a union. An explicitly
configured Markdown file is admitted independently of its pattern.
Directory descendants do not follow symlinks, regular hard links are allowed,
and a missing authorized leaf is a missing read. Extra paths change the tool's
source guidance and actual authorization. A model cannot configure new roots.

For example, `extra_paths=["notes", {"path": "archive", "pattern": "public/**/*.md"}]`
authorizes Markdown under `notes` and the matching part of `archive`. These are
trusted host arguments, separate from the model's closed tool schema.

Actual file bytes come from one checked descriptor. Reads reject final
symlinks, use a nonblocking nofollow open, and verify root, file, and canonical
file identities before consuming that descriptor. Hardlinks retain the native
read policy. A regular-file identity mismatch becomes `not_found`; an open
redirected to a symlink returns the actual refusal and OS cause. The read owner
does not reopen the pathname or reject an already consumed excerpt because a
later pathname change occurred.

Portable filesystem-policy causes are retained in the full tool diagnostic.
For example, a directory or FIFO leaf reports
`path must be a regular file | not a file | not-file`. An escaping parent
symlink retains the `Symlink escapes root (<root>): <parent>` cause, and a
non-directory parent retains its path and `ENOTDIR` cause. These are changes
to diagnostic detail; they do not broaden which files are admitted.

On Linux, ordinary OS failures use the same attributed Node system-error facts
and IO bridge as discovery, including resolved-target `ENOENT`, `ENOTDIR`, and
`ELOOP` causes. Original Python exceptions remain available on the IO error.
The first raw comparisons exposing the cause, pattern, and pre-open replacement
differences are retained in [the path-safety proof notes](storage_path_safety_proof.md).
Evidence preserves complete original wire diagnostics; only each run's exact
owned fixture prefix receives an identity codec. General platform behavior,
retry timing, and arbitrary replacement schedules remain unverified. The proof
packets retain their original uncredited metadata. Independent review registers
both fixed path/read conditions only on the complete eleven-family default set;
the integrated full gate remains the final acceptance step.

## Errors and live configuration

Raw path/range failures raise `MemoryToolInputError`, with native name
`ToolInputError` and status `400`. An unknown corpus raises `MemoryToolError`,
with native name `Error` and no status. Both can be converted with
`to_tool_error()` for a host model loop. These exceptions are distinct from a
failed read payload.

A failed primary read normally returns `path`, empty `text`, `status="error"`,
`code`, and the formatted `error`. Existing error codes are retained; otherwise
the code is `MEMORY_READ_FAILED`. A refused memory path uses
`MEMORY_PATH_NOT_ALLOWED`. Missing files are `not_found`, rather than errors.
Wiki/all reads compose each requested corpus's outcome, warning, and error
without hiding successful provider metadata.

`create_memory_get_tool` accepts `get_config`. It takes precedence over the
configuration snapshot and is consulted at creation and each execution.
Missing configuration or `FeatureFlags.memory=False` omits/revokes the tool.
Execution after revocation raises the ordinary native-shaped disabled error
before validating read arguments. A live configuration cannot move a captured
tool to another workspace or agent; create a new tool for that owner.

The acceptance ledger separately tracks `tools.deadline-cooldown` and
`tools.unavailable-partial`. Controlled callback cases exercise the actual
deadline, cancellation, coordination, and payload owners; they do not prove
provider network cancellation, general filesystem concurrency, or an automatic
manager/index lifecycle. Original wire diagnostics and the bounded comparison
profile remain part of that evidence.
