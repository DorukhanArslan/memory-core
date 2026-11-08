"""Provenance regressions; fixture functions are never native oracle evidence."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from equivalence import reuse_bindings as bindings


@pytest.fixture
def sources():
    return {
        bindings._BOOTSTRAP: (
            'import { sliceUtf16Safe, truncateUtf16Safe } from "../../utils.js";\n'
            'import { resolveAgentConfig } from "../agent-scope.js";\n'
        ),
        bindings._UTILS: (
            'export { sliceUtf16Safe, truncateUtf16Safe } from "@openclaw/normalization-core/utf16-slice";\n'
            'import { resolveEffectiveHomeDir, resolveUserPath } from "./infra/home-dir.js";\n'
            'export { resolveConfigDir, resolveUserPath };\n'
        ),
        bindings._UTF16: ('export function sliceUtf16Safe() {}\n'
                          'export function truncateUtf16Safe() {}\n'),
        bindings._SCOPE: 'export { resolveAgentConfig, other } from "./agent-scope-config.js";\n',
        bindings._SCOPE_CONFIG: ('import { resolveUserPath } from "../utils.js";\n'
                                'export function resolveAgentConfig() {}\n'),
        bindings._HOME: 'export function resolveUserPath() {}\n',
    }


def test_projection_is_exact_parent_original_owner_and_never_rewrites(sources):
    before = deepcopy(sources)
    projections = bindings._trace(sources, bootstrap=True, flush=False, session=False)
    assert sources == before
    assert [item["resolution"]["target"] for item in projections] == [
        bindings._UTF16, bindings._SCOPE_CONFIG, bindings._HOME,
    ]
    assert all(item["chain"][0]["kind"] == "import" for item in projections)


@pytest.mark.parametrize("mutation", [
    "import-extra", "import-alias", "export-alias", "export-type-only",
    "export-target", "duplicate-export", "local-alias", "local-missing",
    "owner-declaration-missing", "owner-declaration-duplicate",
])
def test_changed_reexport_or_declaration_is_rejected(sources, mutation):
    if mutation == "import-extra":
        sources[bindings._BOOTSTRAP] = sources[bindings._BOOTSTRAP].replace(
            "sliceUtf16Safe, truncateUtf16Safe", "sliceUtf16Safe, truncateUtf16Safe, unreviewed")
    elif mutation == "import-alias":
        sources[bindings._BOOTSTRAP] = sources[bindings._BOOTSTRAP].replace(
            "resolveAgentConfig }", "resolveAgentConfig as renamed }")
    elif mutation == "export-alias":
        sources[bindings._SCOPE] = sources[bindings._SCOPE].replace(
            "resolveAgentConfig,", "other as resolveAgentConfig,")
    elif mutation == "export-type-only":
        sources[bindings._SCOPE] = sources[bindings._SCOPE].replace("export {", "export type {")
    elif mutation == "export-target":
        sources[bindings._SCOPE] = sources[bindings._SCOPE].replace("agent-scope-config", "other")
    elif mutation == "duplicate-export":
        sources[bindings._SCOPE] *= 2
    elif mutation == "local-alias":
        sources[bindings._UTILS] = sources[bindings._UTILS].replace(
            "resolveConfigDir, resolveUserPath };", "resolveConfigDir, other as resolveUserPath };")
    elif mutation == "local-missing":
        sources[bindings._UTILS] = sources[bindings._UTILS].replace(
            "export { resolveConfigDir, resolveUserPath };", "")
    elif mutation == "owner-declaration-missing":
        sources[bindings._HOME] = ""
    else:
        sources[bindings._HOME] *= 2
    with pytest.raises(bindings.ReuseBindingError):
        bindings._trace(sources, bootstrap=True, flush=False, session=False)


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch, sources):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path).decode().strip()

    git("init", "-q")
    for relative, source in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture")
    monkeypatch.setattr(bindings, "_COMMIT", git("rev-parse", "HEAD"))
    monkeypatch.setattr(bindings, "_SOURCE_SHA256", {
        path: hashlib.sha256(source.encode()).hexdigest() for path, source in sources.items()
    })
    return tmp_path


def test_pinned_projection_explicitly_limits_execution_claims(checkout):
    result = bindings.prepare_reuse_bindings(checkout, bootstrap=True)
    assert len(result["allowedResolutions"]) == len(result["projectionEvidence"]) == 3
    for evidence in result["projectionEvidence"]:
        assert evidence["facadeInitializationBypassed"] is True
        assert evidence["facadeExecutionVerified"] is False
        assert evidence["fullHostOrchestrationVerified"] is False
        assert evidence["fullManagerExecutionVerified"] is False
        assert all(len(item["sha256"]) == 64 for item in evidence["sources"])


def test_modified_pinned_source_is_rejected(checkout):
    (checkout / bindings._UTILS).write_text("export const replacement = true;\n")
    with pytest.raises(bindings.ReuseBindingError, match="unmodified"):
        bindings.prepare_reuse_bindings(checkout, bootstrap=True)


def test_reviewed_digest_and_git_source_must_agree(checkout, monkeypatch):
    expected = dict(bindings._SOURCE_SHA256)
    expected[bindings._SCOPE] = "0" * 64
    monkeypatch.setattr(bindings, "_SOURCE_SHA256", expected)
    with pytest.raises(bindings.ReuseBindingError, match="pinned Git source"):
        bindings.prepare_reuse_bindings(checkout, bootstrap=True)


def test_wrong_commit_and_nested_checkout_are_rejected(checkout, monkeypatch):
    with pytest.raises(bindings.ReuseBindingError, match="exact pinned"):
        bindings.prepare_reuse_bindings(checkout / "src", bootstrap=True)
    monkeypatch.setattr(bindings, "_COMMIT", "0" * 40)
    with pytest.raises(bindings.ReuseBindingError, match="exact pinned"):
        bindings.prepare_reuse_bindings(checkout, bootstrap=True)


@pytest.fixture
def optional_sources():
    return {
        bindings._SESSION_FILES: 'import { normalizeAgentId } from "./config-utils.js";\n',
        bindings._CONFIG_UTILS: (
            'import { normalizeAgentId } from "@openclaw/normalization-core/agent-id";\n'
            'export { normalizeAgentId };\n'),
        bindings._AGENT_ID: 'export function normalizeAgentId() {}\n',
        bindings._SDK: ('export { SILENT_REPLY_TOKEN } '
                        'from "../../packages/memory-host-sdk/src/runtime-core.js";\n'),
        bindings._RUNTIME: 'export { SILENT_REPLY_TOKEN } from "./host/openclaw-runtime-session.js";\n',
        bindings._SESSION: 'export { SILENT_REPLY_TOKEN } from "../../../../src/auto-reply/tokens.js";\n',
        bindings._TOKENS: 'export const SILENT_REPLY_TOKEN = "";\n',
        bindings._FLUSH: (
            'import { estimateMessagesTokens } from "../../agents/compaction.js";\n'
            'import { resolveFreshSessionTotalTokens, type SessionEntry } from "../../config/sessions.js";\n'
            'import { normalizeProviderId } from "../../agents/model-selection.js";\n'
            'import { resolveAnthropicServerCompactionPlan } from "@openclaw/ai/internal/anthropic";\n'
            'import { resolveOpenAIResponsesServerCompactionPlan } '
            'from "@openclaw/ai/internal/openai-responses-payload-policy";\n'),
        bindings._COMPACTION: 'export { estimateMessagesTokens } from "./compaction-planning.js";\n',
        bindings._PLANNING: 'export function estimateMessagesTokens() {}\n',
        bindings._SESSIONS: 'export * from "./sessions/types.js";\n',
        bindings._TYPES: 'export function resolveFreshSessionTotalTokens() {}\n',
        bindings._MODEL_SELECTION: 'export { normalizeProviderId } from "./model-ref-shared.js";\n',
        bindings._MODEL_REF: 'export { normalizeProviderId } from "@openclaw/model-catalog-core/provider-id";\n',
        bindings._PROVIDER_ID: 'export function normalizeProviderId() {}\n',
        bindings._ANTHROPIC: ('export { resolveAnthropicServerCompactionPlan } '
                              'from "../transports/anthropic-payload-policy.js";\n'),
        bindings._ANTHROPIC_POLICY: 'export function resolveAnthropicServerCompactionPlan() {}\n',
        bindings._OPENAI: ('export { resolveOpenAIResponsesServerCompactionPlan } '
                           'from "../transports/openai-responses-payload-policy.js";\n'),
        bindings._OPENAI_POLICY: 'export function resolveOpenAIResponsesServerCompactionPlan() {}\n',
    }


def test_optional_projections_execute_only_original_owners(optional_sources):
    before = deepcopy(optional_sources)
    projections = bindings._trace(optional_sources, bootstrap=False, session=True, flush=True)
    assert optional_sources == before
    assert len(projections) == 7
    assert {item["resolution"]["target"] for item in projections} == {
        bindings._AGENT_ID, bindings._TOKENS, bindings._PLANNING, bindings._TYPES,
        bindings._PROVIDER_ID, bindings._ANTHROPIC_POLICY, bindings._OPENAI_POLICY,
    }


@pytest.mark.parametrize("mutation", ["session-local-alias", "star-target", "ai-owner", "ai-alias"])
def test_optional_projection_provenance_changes_are_rejected(optional_sources, mutation):
    if mutation == "session-local-alias":
        optional_sources[bindings._CONFIG_UTILS] = optional_sources[bindings._CONFIG_UTILS].replace(
            "export { normalizeAgentId }", "export { other as normalizeAgentId }")
    elif mutation == "star-target":
        optional_sources[bindings._SESSIONS] = optional_sources[bindings._SESSIONS].replace("types.js", "other.js")
    elif mutation == "ai-owner":
        optional_sources[bindings._ANTHROPIC] = optional_sources[bindings._ANTHROPIC].replace(
            "anthropic-payload-policy.js", "other.js")
    else:
        optional_sources[bindings._OPENAI] = optional_sources[bindings._OPENAI].replace(
            "resolveOpenAIResponsesServerCompactionPlan }", "other as resolveOpenAIResponsesServerCompactionPlan }")
    with pytest.raises(bindings.ReuseBindingError):
        bindings._trace(optional_sources, bootstrap=False, session=True, flush=True)
