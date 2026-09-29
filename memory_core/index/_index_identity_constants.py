"""Upstream constants of the memory index identity and its search diagnostic.

Extracted by scripts/extract_upstream_constants.py.
Generated from OpenClaw eb377ac59e6c9fd6c7705028034812becf00271b:
extensions/memory-core/src/memory/manager-reindex-state.ts,
packages/memory-host-sdk/src/host/markdown-chunks.ts,
packages/memory-host-sdk/src/host/types.ts.
Do not edit by hand: re-run the script; tests/integration/test_extracted_upstream_constants.py
checks these values against the source.
The reasons come from resolveMemoryIndexIdentityState, the *_CODES from the
codes resolveMemoryIndexIdentityDiagnostic accepts per owner, the rebuild,
cause, paused and staleness texts from formatMemoryIndexRebuildGuidance and
resolveMemoryIndexSearchDiagnostic. The *_TEMPLATE texts are str.format
templates whose fields stand for upstream template expressions; the rebuild
command's --agent suffix is the *_AGENT_CLAUSE of its ternary. Texts that
name OpenClaw commands serve the compat runtime identity only.
"""

from __future__ import annotations

MEMORY_CHUNKING_VERSION = 5
MEMORY_INDEX_PROVENANCE_VERSION = 1
MEMORY_INDEX_METADATA_MISSING_REASON = 'index metadata is missing'
MEMORY_INDEX_NEWER_VERSION_REASON = 'the index was written by a newer OpenClaw version; upgrade OpenClaw or reindex explicitly'
MEMORY_INDEX_PROVENANCE_CHANGED_REASON = 'index provenance classifier changed'
MEMORY_INDEX_CHUNKING_VERSION_CHANGED_REASON = 'index chunking implementation changed'
MEMORY_INDEX_MODEL_CHANGED_TEMPLATE = 'index was built for model {meta_model}, expected {expected_model}'
MEMORY_INDEX_PROVIDER_CHANGED_TEMPLATE = 'index was built for provider {meta_provider}, expected {expected_provider}'
MEMORY_INDEX_PROVIDER_SETTINGS_CHANGED_REASON = 'index provider settings changed'
MEMORY_INDEX_SOURCES_CHANGED_REASON = 'index sources changed'
MEMORY_INDEX_SCOPE_CHANGED_REASON = 'index scope changed'
MEMORY_INDEX_CHUNKING_CHANGED_REASON = 'index chunking changed'
MEMORY_INDEX_FTS_TOKENIZER_CHANGED_REASON = 'index FTS tokenizer changed'
MEMORY_INDEX_VECTOR_DIMS_MISSING_REASON = 'index vector dimensions are missing'
MEMORY_INDEX_OPENCLAW_CODES: tuple[str, ...] = (
    'provenance_version',
    'chunking_version',
)
MEMORY_INDEX_CONFIGURATION_CODES: tuple[str, ...] = (
    'model',
    'provider',
    'provider_settings',
    'sources',
    'scope',
    'chunking',
    'vector_dims',
    'fts_tokenizer',
)
MEMORY_INDEX_IDENTITY_DEFAULT_REASON = 'memory index identity is missing or mismatched'
MEMORY_INDEX_REBUILD_COMMAND_TEMPLATE = 'openclaw memory status --index{agent_suffix}'
MEMORY_INDEX_REBUILD_AGENT_CLAUSE = ' --agent {agent_id}'
MEMORY_INDEX_REBUILD_KEYWORD_ONLY_DISCLOSURE = 'Rebuilding uses keyword indexing only and does not call an embedding provider.'
MEMORY_INDEX_REBUILD_PROVIDER_COST_DISCLOSURE = 'Rebuilding may call the configured embedding provider and can incur provider cost.'
MEMORY_INDEX_REBUILD_GUIDANCE_TEMPLATE = '{command}. {disclosure}'
MEMORY_INDEX_CONFIGURATION_CAUSE_TEMPLATE = 'the current memory configuration no longer matches the index ({reason})'
MEMORY_INDEX_METADATA_MISSING_CAUSE_TEMPLATE = 'the memory index metadata is missing ({reason}); no configuration change is needed'
MEMORY_INDEX_VERSION_CHANGED_CAUSE_TEMPLATE = 'this OpenClaw version changed the memory index format ({reason}); no configuration change is needed'
MEMORY_INDEX_PAUSED_WARNING_TEMPLATE = 'Tell the user: memory search is paused because {cause}.{prior_failure}'
MEMORY_INDEX_NEWER_ACTION_TEMPLATE = 'Tell the user to upgrade OpenClaw or reindex explicitly: {guidance}'
MEMORY_INDEX_REBUILD_ACTION_TEMPLATE = 'Tell the user to run: {guidance}'
MEMORY_INDEX_STALE_WARNING_TEMPLATE = 'Memory index is stale: {reason} (owner: {owner}, code: {code}). Search results may be incomplete.{prior_failure}'
MEMORY_INDEX_STALE_NEWER_ACTION_TEMPLATE = 'Upgrade OpenClaw or reindex explicitly: {guidance}'
MEMORY_INDEX_STALE_REBUILD_ACTION_TEMPLATE = 'Run: {guidance}'
