"""Upstream constants of the memory_search and memory_get tools.

Extracted by scripts/extract_upstream_constants.py.
Generated from OpenClaw eb377ac59e6c9fd6c7705028034812becf00271b:
extensions/memory-core/src/memory-tool-contract.ts,
extensions/memory-core/src/tools.ts,
extensions/memory-core/src/memory-read-tool.ts,
extensions/memory-core/src/memory-corpus.ts,
extensions/memory-core/src/memory/search-deadline.ts,
packages/memory-host-sdk/src/host/read-file.ts,
packages/memory-host-sdk/src/host/read-file-shared.ts,
packages/memory-host-sdk/src/host/read-retry.ts,
packages/memory-host-sdk/src/host/fs-utils.ts,
node_modules/@openclaw/fs-safe/dist/root-context.js (@openclaw/fs-safe 0.18.1),
node_modules/@openclaw/fs-safe/dist/root-path.js (@openclaw/fs-safe 0.18.1),
node_modules/@openclaw/fs-safe/dist/root-path-errors.js (@openclaw/fs-safe 0.18.1),
node_modules/@openclaw/fs-safe/dist/root-path-existing.js (@openclaw/fs-safe 0.18.1),
node_modules/@openclaw/fs-safe/dist/path.js (@openclaw/fs-safe 0.18.1),
node_modules/@openclaw/fs-safe/dist/error-detail.js (@openclaw/fs-safe 0.18.1),
node_modules/@openclaw/fs-safe/dist/regular-file.js (@openclaw/fs-safe 0.18.1),
node_modules/@openclaw/fs-safe/dist/strict-file-identity.js (@openclaw/fs-safe 0.18.1).
Do not edit by hand: re-run the script; tests/integration/test_extracted_upstream_constants.py
checks these values against the source.
The *_TEMPLATE texts are str.format templates whose fields stand for upstream
template expressions; a *_CLAUSE is the literal a ternary inside a template adds.
The tool descriptions come from memory-tool-contract.ts describe(), the
## Memory Recall lines from buildMemoryPromptSection, the read texts from
readMemoryFile / buildMemoryReadResult and the fs-safe refusals from the built
@openclaw/fs-safe package that readMemoryFile resolves and reads through.
"""

from __future__ import annotations

MEMORY_SEARCH_TOOL_NAME = 'memory_search'
MEMORY_GET_TOOL_NAME = 'memory_get'
SEARCH_CORPUS_OUTCOME_GUIDANCE = 'Corpus outcomes cover each requested corpus; a corpus warning means results are partial and must be surfaced to the user.'
GET_READ_OUTCOME_GUIDANCE = 'status=ok means the requested excerpt was read; status=not_found means every requested available corpus missed; status=error means the requested read failed, not that memory is disabled.'
MEMORY_SEARCH_TOOL_DESCRIPTION_TEMPLATE = 'Mandatory recall step: semantically search {search} before answering questions about prior work, decisions, dates, people, preferences, or todos. Session results are transcript search references, not readable memory-file paths. Optional `corpus=wiki` or `corpus=all` also searches registered compiled-wiki supplements. `corpus=memory` restricts hits to indexed memory files (excludes session transcript chunks from ranking). `corpus=sessions` searches indexed session transcripts under the same visibility rules as session history tools and returns unavailable when semantic session indexing is disabled. Corpus outcomes cover each requested corpus; a corpus warning means results are partial and must be surfaced to the user. If response has disabled=true or stale=true, tell the user and include the warning/action guidance.'
MEMORY_GET_TOOL_DESCRIPTION_TEMPLATE = 'Safe exact excerpt read from {files}. Session transcript paths are unsupported; use the available session-history workflow for session hits. Defaults to a bounded excerpt when lines are omitted and includes truncation/continuation info when more content exists. `corpus=wiki` reads registered compiled-wiki supplements. status=ok means the requested excerpt was read; status=not_found means every requested available corpus missed; status=error means the requested read failed, not that memory is disabled. Corpus outcomes cover each requested corpus; a corpus warning means results are partial and must be surfaced to the user.'
MEMORY_SOURCE_FILES = 'MEMORY.md, USER.md, Markdown files recursively under memory/'
MEMORY_SOURCE_EXTRA_PATHS = 'configured extra paths'
MEMORY_SOURCE_SEARCH_TEMPLATE = '{files}, indexed session transcripts'
MEMORY_SEARCH_CORPORA: tuple[str, ...] = (
    'memory',
    'wiki',
    'all',
    'sessions',
)
MEMORY_GET_CORPORA: tuple[str, ...] = (
    'memory',
    'wiki',
    'all',
)
MEMORY_CORPUS_PARAM_ERROR_TEMPLATE = 'corpus must be one of: {allowed}'
MEMORY_RECALL_HEADING = '## Memory Recall'
SESSIONS_SEARCH_TOOL_NAME = 'sessions_search'
SESSIONS_HISTORY_TOOL_NAME = 'sessions_history'
MEMORY_RECALL_SEARCH_TEMPLATE = 'Before answering anything about prior work, decisions, dates, people, preferences, or todos: run memory_search{memory_get_clause}. If low confidence after search, say you checked.'
MEMORY_RECALL_SEARCH_GET_CLAUSE = '; for memory-file hits, use memory_get to pull only the needed lines'
MEMORY_RECALL_GET_ONLY = 'Before answering anything about prior work, decisions, dates, people, preferences, or todos that point to a specific memory file: run memory_get to pull only the needed lines. If low confidence after reading, say you checked.'
MEMORY_RECALL_SESSIONS_SEARCH_TEMPLATE = 'For session hits, use sessions_search with distinctive snippet text (and sessionKey set to the transcript ID when known){history_clause}.'
MEMORY_RECALL_SESSIONS_HISTORY_CLAUSE = ', then sessions_history with the returned sessionKey, messageId, and sessionId for a bounded sanitized excerpt'
MEMORY_RECALL_SESSIONS_NO_HISTORY_CLAUSE = '; exact session history is unavailable with the enabled tools'
MEMORY_RECALL_SESSIONS_HISTORY_ONLY = 'For session hits, use sessions_history with a known session key or transcript ID and a small limit; paginate its returned history metadata to locate the excerpt.'
MEMORY_RECALL_SESSIONS_SNIPPETS_ONLY = 'Session hits are search snippets only; exact session history is unavailable with the enabled tools.'
MEMORY_RECALL_SESSION_LINE_NUMBERS = 'Session search line numbers are not history offsets. Never read raw transcript files to expand session hits.'
MEMORY_RECALL_OUTCOME = 'Report partial, unavailable, or stale recall to the user, including returned warning and action guidance.'
MEMORY_RECALL_CITATIONS_OFF = 'Citations are disabled: do not mention file paths or line numbers in replies unless the user explicitly asks.'
MEMORY_RECALL_CITATIONS_ON = 'Citations: include Source: <path#line> when it helps the user verify memory snippets.'
MEMORY_PATH_REQUIRED_ERROR = 'path required'
MEMORY_PATH_NOT_ALLOWED_ERROR = 'path is not an allowed Markdown memory file'
MEMORY_PATH_NOT_ALLOWED_CODE = 'MEMORY_PATH_NOT_ALLOWED'
MEMORY_READ_FAILED_CODE = 'MEMORY_READ_FAILED'
DEFAULT_MEMORY_READ_LINES = 120
DEFAULT_MEMORY_READ_MAX_CHARS = 12000
MEMORY_READ_CONTINUE_TEMPLATE = '[More content available. Use from={next_from} to continue.]'
MEMORY_READ_MAX_CHARS_NOTICE = '[More content available. Requested excerpt exceeded the default maxChars budget.]'
MEMORY_READ_FALLBACK_HINT = ' If you need the full raw line, use read on the source file.'
TRANSIENT_MEMORY_READ_ERRNO = -11
TRANSIENT_MEMORY_READ_CODES: tuple[str, ...] = (
    'EAGAIN',
    'EWOULDBLOCK',
    'EDEADLK',
)
TRANSIENT_MEMORY_READ_MESSAGE_PATTERN = 'Unknown system error -11\\b'
TRANSIENT_MEMORY_READ_MESSAGE_FLAGS = 'i'
TRANSIENT_MEMORY_READ_ATTEMPTS = 3
TRANSIENT_MEMORY_READ_MIN_DELAY_MS = 25
TRANSIENT_MEMORY_READ_MAX_DELAY_MS = 50
DEFAULT_MEMORY_SEARCH_TIMEOUT_MS = 30000
MEMORY_CORPUS_TIMEOUT_TEMPLATE = '{operation} timed out after {seconds}s'
MEMORY_CORPUS_MEMORY_LABEL = 'Memory'
MEMORY_CORPUS_WIKI_LABEL = 'Wiki'
MEMORY_CORPUS_FAILURE_WARNING_TEMPLATE = '{label} corpus {outcome}: {error}'
MEMORY_CORPUS_NOT_REGISTERED_WARNING_TEMPLATE = '{label} corpus is not registered; results do not cover that requested corpus.'
MEMORY_CORPUS_PLUGIN_FAILURE_TEMPLATE = '{plugin_id}: {error}'
MEMORY_CORPUS_SUPPLEMENT_CONCURRENCY = 4
MEMORY_CORPUS_SUPPLEMENT_DEFAULT_MAX_RESULTS = 10
FS_SAFE_ROOT_BOUNDARY_LABEL = 'root'
FS_SAFE_OUTSIDE_WORKSPACE_CODE = 'outside-workspace'
FS_SAFE_OUTSIDE_WORKSPACE_ERROR = 'file is outside workspace root'
FS_SAFE_INVALID_PATH_CODE = 'invalid-path'
FS_SAFE_PATH_TOO_LONG_ERROR = 'relative path is too long'
FS_SAFE_ROOT_NOT_DIRECTORY_ERROR = 'root dir is not a directory'
FS_SAFE_NOT_DIRECTORY_TEMPLATE = 'Path component is not a directory: {path}'
FS_SAFE_SYMLINK_ESCAPE_TEMPLATE = 'Symlink escapes {boundary} ({root}): {path}'
FS_SAFE_UNSAFE_DETAIL_PATTERN = '[\\u0000-\\u001f\\u007f-\\u009f\\u2028\\u2029]'
FS_SAFE_UNSAFE_DETAIL_FLAGS = 'gu'
FS_SAFE_NOT_REGULAR_FILE_ERROR = 'path must be a regular file'
FS_SAFE_NOT_REGULAR_READ_TEMPLATE = 'File is not a regular file: {path}'
FS_SAFE_FILE_NOT_FOUND_TEMPLATE = 'File not found: {path}'
FS_SAFE_ROOT_NOT_FOUND_CODE = 'not-found'
FS_SAFE_ROOT_NOT_FOUND_ERROR = 'root dir not found'
FS_SAFE_SYMLINK_CODE = 'symlink'
FS_SAFE_SYMLINK_UNRESOLVED_ERROR = 'symlink path could not be resolved'
FS_SAFE_NOT_FOUND_CODES: tuple[str, ...] = (
    'ENOENT',
    'ENOTDIR',
)
FS_SAFE_SYMLINK_OPEN_CODES: tuple[str, ...] = (
    'ELOOP',
    'EINVAL',
    'ENOTSUP',
)
MEMORY_FILE_MISSING_CODES: tuple[str, ...] = (
    'ENOENT',
    'ENOTDIR',
    'not-file',
    'not-found',
)
FS_SAFE_PATH_MISMATCH_CODE = 'path-mismatch'
FS_SAFE_FILE_CHANGED_TEMPLATE = 'File changed during read: {path}'
FS_SAFE_IDENTITY_MISMATCH_ERROR = 'file identity changed or could not be verified'
