"""Upstream constants of the tool-call replay repair.

Extracted by scripts/extract_upstream_constants.py.
Generated from OpenClaw eb377ac59e6c9fd6c7705028034812becf00271b:
packages/agent-core/src/harness/session/tool-result-pairing.ts.
Do not edit by hand: re-run the script; tests/integration/test_extracted_upstream_constants.py
checks these values against the source.
DEFAULT_MISSING_TOOL_RESULT_TEXT is the synthetic tool result's text and a
parity-bound marker: upstream recognises a stored synthetic result by it.
"""

from __future__ import annotations

SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY = 'openclawSyntheticMissingToolResult'
DEFAULT_MISSING_TOOL_RESULT_TEXT = '[openclaw] missing tool result in session history; inserted synthetic error result for transcript repair.'
