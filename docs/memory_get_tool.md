# memory_get Tool Contract

The active reference is OpenClaw **v2026.9.9**, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. The relevant owners are
`extensions/memory-core/src/tools.ts`, `memory-read-tool.ts`, `memory-corpus.ts`,
and `packages/memory-host-sdk/src/host/read-file.ts` and `read-file-shared.ts`.
This document describes the Python read boundary and its supported host policy.
It does not establish complete filesystem, deadline, or manager lifecycle parity.

## Entry points

| API | Purpose |
| --- | --- |
| `create_memory_get_tool(config, ...)` | Create a model-facing read tool, or return `None` when disabled. No store or index is required. |
| `tool.definition` | A defensive copy of its `label`, `name`, `description`, and JSON `parameters`. |
| `tool.execute(tool_call_id, params)` | Validate model arguments, perform the read, and return the complete JSON result envelope. |
| `execute_memory_get_tool(config, params, ...)` | Run the same read from raw model arguments and return its payload dictionary directly. |
| `memory_get(config, *, path, from_line=None, lines=None, corpus="memory", ...)` | Python convenience form below raw argument validation. |
| `memory_get_tool_definition(extra_paths=())` | Return the provider-neutral name, description, and schema. |

The factory exposes read-only `name`, `label`, `description`, and `parameters`
properties as well. Native `memory_get` has no argument-preparation callback;
the Python factory does not invent one.

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

## Filesystem policy and configured extra paths

Built-in reads use the existing workspace memory-path gate: supported root
memory files and Markdown files under `memory/`. Transcript search references
are not readable memory-file paths. Lexical path resolution, allowed-file
checks, and existing symlink policy apply before the read. Missing permitted
files return `status="not_found"` with empty text.

The factory and direct APIs accept trusted `extra_paths`, a sequence of plain
file or directory paths. A configured Markdown file or a Markdown descendant
of a configured directory can be read outside the built-in memory paths.
Directory descendants do not follow symlinks, regular hard links are allowed,
and a missing authorized leaf is a missing read. Extra paths change the tool's
source guidance and actual authorization. A model cannot configure new roots.

Only **plain file/directory entries** are supported here. Native
`{path, pattern}` entries are unsupported. Native descriptor identity,
concurrent replacement/race behavior, and complete filesystem equivalence
remain unverified under separate storage contracts.

Portable filesystem-policy causes are retained in the full tool diagnostic.
For example, a directory or FIFO leaf reports
`path must be a regular file | not a file | not-file`. An escaping parent
symlink retains the `Symlink escapes root (<root>): <parent>` cause, and a
non-directory parent retains its path and `ENOTDIR` cause. These are changes
to diagnostic detail; they do not broaden which files are admitted.

OS-owned cause strings remain platform-specific. The known third
`storage.path-safety` diagnostic, a parent symlink loop, retains the actual
Python ELOOP cause and remains outside this portable comparison profile. Its
stable policy code and prefix do not establish full native diagnostic parity.
The first raw comparison that exposed the filesystem difference is retained.
Evidence keeps complete original wire diagnostics; a private-fixture prefix
codec can identify each run's owned temporary roots without rewriting the
remaining path, error wording, cause chain, or other result fields. This is not
a general filesystem-error normalization policy.

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

The Python read calls are synchronous. Complete deadline/abort behavior
(`tools.deadline-cooldown`, contract #24) and unavailable/manager lifecycle behavior
(`tools.unavailable-partial`, contract #25) remain open. Successful bounded reads and synchronous error
payloads do not close those broader contracts.
