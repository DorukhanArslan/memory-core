"""Authenticate exact-parent reexports used by native reuse comparisons.

The loader executes unchanged original owners. These projections bypass broad
facade initialization, so they provide no evidence for host orchestration.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Mapping

from equivalence.reference_bindings import (
    ReferenceBindingError, _NAMED_FROM, _git, _runtime_names,
)


_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
_TAG = "v2026.9.9"
_BOOTSTRAP = "src/agents/embedded-agent-helpers/bootstrap.ts"
_UTILS = "src/utils.ts"
_UTF16 = "packages/normalization-core/src/utf16-slice.ts"
_SCOPE = "src/agents/agent-scope.ts"
_SCOPE_CONFIG = "src/agents/agent-scope-config.ts"
_HOME = "src/infra/home-dir.ts"
_SESSION_FILES = "packages/memory-host-sdk/src/host/session-files.ts"
_CONFIG_UTILS = "packages/memory-host-sdk/src/host/config-utils.ts"
_AGENT_ID = "packages/normalization-core/src/agent-id.ts"
_SDK = "src/plugin-sdk/memory-core-host-runtime-core.ts"
_RUNTIME = "packages/memory-host-sdk/src/runtime-core.ts"
_SESSION = "packages/memory-host-sdk/src/host/openclaw-runtime-session.ts"
_TOKENS = "src/auto-reply/tokens.ts"
_FLUSH = "src/auto-reply/reply/memory-flush.ts"
_COMPACTION = "src/agents/compaction.ts"
_PLANNING = "src/agents/compaction-planning.ts"
_SESSIONS = "src/config/sessions.ts"
_TYPES = "src/config/sessions/types.ts"
_MODEL_SELECTION = "src/agents/model-selection.ts"
_MODEL_REF = "src/agents/model-ref-shared.ts"
_PROVIDER_ID = "packages/model-catalog-core/src/provider-id.ts"
_ANTHROPIC = "packages/ai/src/internal/anthropic.ts"
_ANTHROPIC_POLICY = "packages/ai/src/transports/anthropic-payload-policy.ts"
_OPENAI = "packages/ai/src/internal/openai-responses-payload-policy.ts"
_OPENAI_POLICY = "packages/ai/src/transports/openai-responses-payload-policy.ts"
_SOURCE_SHA256 = {
    _BOOTSTRAP: "8ad046746a92d2b1fa2833cfb1c2a79edb5272b593c8f325ac4c26203e0dd5f2",
    _UTILS: "c0a559097bda662fd274b2e0233593d1a36a0b197df4835bd299dbdb141b53d4",
    _UTF16: "12fd3212b08522a1523263c92f654151ad01605ee48a0ff58a1256889fb7cb5f",
    _SCOPE: "ef187176518fe241b49b205693cd70dc877e61fabe65e720013b0cf31f43beb7",
    _SCOPE_CONFIG: "97afbaa31c3014db8ac76550907e25b60b449052aee03a7591917391c768b245",
    _HOME: "a7f0ebd9376ee385c28451ed2a32bee4c18b023f97ceb55235de15ba23f43941",
    _SESSION_FILES: "d184bf1a1b098a02b08ed131321fb47d6caf5bee9e1cc6d88751502dbb8761ee",
    _CONFIG_UTILS: "670063dd2236bd0340950d19accb55b022efcaee7be1275491777c5a1f65fa53",
    _AGENT_ID: "111d17050ea5854bb0343ee2987cd9d2e63506ec132a1d4fb39555d112dc8094",
    _SDK: "9d0fc4e1f1ec1f4c4a140a2a5b8cb63246c18091274cc8ffa51b5274b03a653b",
    _RUNTIME: "8a5d3679d1408c47b92ca06667b6793c66b0095211706286fe7d24bb6a5f81de",
    _SESSION: "51fed14e0695f0caf97d1b3296ed5cdba7b8867bca4de8611509af68fce14eed",
    _TOKENS: "9c014b2a1ca154d88df9f7a902ceb2ef3145bb3010e018d3b1c123b149dcd3c9",
    _FLUSH: "dedf96e5f7dabc0f7f37e61b58576553c68d60462a466ce1788c6e68d1e00145",
    _COMPACTION: "e49d127f437f2cc805f52fcd02f6bfb5e9d8bebb1ff6819f10c722a3aba487e8",
    _PLANNING: "91a6ebfc495db87aec5c1edabf84702ddfcfb6ef15db3f6ae2591a570e1cb8b4",
    _SESSIONS: "3b706bbbc1139e88cec506dce9deb1ef558e9bd2b7cd48534e1247c74e6a61f3",
    _TYPES: "7abd5c78151e952b54a165313cfda3239213e9ea331e325e92e10b8119b38bd8",
    _MODEL_SELECTION: "9546b9fda06d0e0f85f7a5fc534cb0989cafe55016b930d712db02696fa7dd64",
    _MODEL_REF: "b42a211c8922a18d8c03cce0a93552dab5badc5c1399409862b968f46df7e99f",
    _PROVIDER_ID: "12fc8a816ebb1a91685a26042b0161f278de0f019dd8a59f62a5deed6dfcd53d",
    _ANTHROPIC: "a74547069f23d24ccad9ac3ed95cc7c2902a5dc4dfb1495668a3a14838dcb8b6",
    _ANTHROPIC_POLICY: "9f99313e0ba2346303058b7306d95fa6ed30263d6842e2e6bef9511228fc0ba7",
    _OPENAI: "66cae7eccfdb3f33b86feb94000e4f3393059f6984cf586a7d5bebf67abf5275",
    _OPENAI_POLICY: "a0c89bab6a81c4a335c4971432cfb87fab8e6bf3a39bb1a5de15af3e17f1bfa9",
}


class ReuseBindingError(ValueError):
    """Original reuse binding provenance is missing or changed."""


def _named(sources: Mapping[str, str], module: str, specifier: str,
           names: tuple[str, ...], *, kind: str = "export", exact: bool = False) -> dict:
    matches = [match for match in _NAMED_FROM.finditer(sources[module])
               if match["kind"] == kind and match["specifier"] == specifier
               and all(re.search(rf"\b{re.escape(name)}\b", match["names"]) for name in names)
               and all((name, name) in _runtime_names(match) for name in names)]
    if len(matches) != 1 or (exact and _runtime_names(matches[0]) != [(n, n) for n in names]):
        raise ReuseBindingError("A reuse binding is not an unchanged direct named binding.")
    match = matches[0]
    return {"path": module, "kind": kind, "specifier": specifier, "bindings": list(names),
            "line": sources[module][:match.start()].count("\n") + 1,
            "declarationSha256": hashlib.sha256(match[0].encode()).hexdigest()}


def _local(sources: Mapping[str, str], module: str, names: tuple[str, ...]) -> dict:
    matches = [match for match in re.finditer(r"(?m)^export\s+\{([^}]+)\};", sources[module])
               if all(name in [n.strip() for n in match[1].split(",")] for name in names)]
    if len(matches) != 1:
        raise ReuseBindingError("A reuse binding has no unique unchanged local reexport.")
    match = matches[0]
    return {"path": module, "kind": "local-reexport", "bindings": list(names),
            "line": sources[module][:match.start()].count("\n") + 1,
            "declarationSha256": hashlib.sha256(match[0].encode()).hexdigest()}


def _declarations(sources: Mapping[str, str], module: str, names: tuple[str, ...]) -> list[dict]:
    result = []
    for name in names:
        matches = list(re.finditer(rf"(?m)^export\s+(?:async\s+)?(?:function|const|class)\s+{re.escape(name)}\b",
                                   sources[module]))
        if len(matches) != 1:
            raise ReuseBindingError("A reuse binding has no unique original declaration.")
        result.append({"path": module, "kind": "declaration", "binding": name,
                       "line": sources[module][:matches[0].start()].count("\n") + 1})
    return result


def _trace(sources: Mapping[str, str], *, bootstrap: bool, flush: bool, session: bool) -> list[dict]:
    result = []

    def add(parent, specifier, target, names, chain, *, kind="import"):
        first = _named(sources, parent, specifier, names, kind=kind, exact=True)
        chain = [first, *chain, *_declarations(sources, target, names)]
        result.append({"resolution": {"parent": parent, "specifier": specifier,
                                       "target": target, "bindings": list(names)}, "chain": chain})

    if bootstrap:
        names = ("sliceUtf16Safe", "truncateUtf16Safe")
        add(_BOOTSTRAP, "../../utils.js", _UTF16, names,
            [_named(sources, _UTILS, "@openclaw/normalization-core/utf16-slice", names)])
        names = ("resolveAgentConfig",)
        add(_BOOTSTRAP, "../agent-scope.js", _SCOPE_CONFIG, names,
            [_named(sources, _SCOPE, "./agent-scope-config.js", names)])
        names = ("resolveUserPath",)
        add(_SCOPE_CONFIG, "../utils.js", _HOME, names,
            [_named(sources, _UTILS, "./infra/home-dir.js", names, kind="import"),
             _local(sources, _UTILS, names)])
    if session:
        names = ("normalizeAgentId",)
        add(_SESSION_FILES, "./config-utils.js", _AGENT_ID, names,
            [_named(sources, _CONFIG_UTILS, "@openclaw/normalization-core/agent-id", names, kind="import"),
             _local(sources, _CONFIG_UTILS, names)])
    if flush:
        names = ("SILENT_REPLY_TOKEN",)
        add(_SDK, "../../packages/memory-host-sdk/src/runtime-core.js", _TOKENS, names,
            [_named(sources, _RUNTIME, "./host/openclaw-runtime-session.js", names),
             _named(sources, _SESSION, "../../../../src/auto-reply/tokens.js", names)], kind="export")
        names = ("estimateMessagesTokens",)
        add(_FLUSH, "../../agents/compaction.js", _PLANNING, names,
            [_named(sources, _COMPACTION, "./compaction-planning.js", names)])
        names = ("resolveFreshSessionTotalTokens",)
        star = 'export * from "./sessions/types.js";'
        if sources[_SESSIONS].count(star) != 1:
            raise ReuseBindingError("A reuse binding has no unique original star reexport.")
        add(_FLUSH, "../../config/sessions.js", _TYPES, names,
            [{"path": _SESSIONS, "kind": "star-reexport", "specifier": "./sessions/types.js",
              "bindings": list(names), "declarationSha256": hashlib.sha256(star.encode()).hexdigest()}])
        names = ("normalizeProviderId",)
        add(_FLUSH, "../../agents/model-selection.js", _PROVIDER_ID, names,
            [_named(sources, _MODEL_SELECTION, "./model-ref-shared.js", names),
             _named(sources, _MODEL_REF, "@openclaw/model-catalog-core/provider-id", names)])
        for specifier, facade, owner, name in (
            ("anthropic", _ANTHROPIC, _ANTHROPIC_POLICY, "resolveAnthropicServerCompactionPlan"),
            ("openai-responses-payload-policy", _OPENAI, _OPENAI_POLICY,
             "resolveOpenAIResponsesServerCompactionPlan"),
        ):
            names = (name,)
            add(_FLUSH, f"@openclaw/ai/internal/{specifier}", owner, names,
                [_named(sources, facade, f"../transports/{Path(owner).stem}.js", names)])
    return result


def prepare_reuse_bindings(checkout: Path, *, bootstrap: bool = False,
                           flush: bool = False, session: bool = False) -> dict:
    """Return authenticated exact-parent resolutions; never synthesize modules."""
    checkout = Path(checkout).resolve()
    selected = set()
    if bootstrap:
        selected.update((_BOOTSTRAP, _UTILS, _UTF16, _SCOPE, _SCOPE_CONFIG, _HOME))
    if session:
        selected.update((_SESSION_FILES, _CONFIG_UTILS, _AGENT_ID))
    if flush:
        selected.update((_SDK, _RUNTIME, _SESSION, _TOKENS, _FLUSH, _COMPACTION,
                         _PLANNING, _SESSIONS, _TYPES, _MODEL_SELECTION, _MODEL_REF,
                         _PROVIDER_ID, _ANTHROPIC, _ANTHROPIC_POLICY, _OPENAI, _OPENAI_POLICY))
    try:
        if (_git(checkout, "rev-parse", "HEAD").decode().strip() != _COMMIT
                or Path(_git(checkout, "rev-parse", "--show-toplevel").decode().strip()).resolve() != checkout):
            raise ReuseBindingError("Reuse bindings require the exact pinned checkout.")
        if _git(checkout, "status", "--porcelain", "--untracked-files=no").strip():
            raise ReuseBindingError("Reuse bindings require unmodified tracked native files.")
        sources = {}
        for relative in sorted(selected):
            path = checkout / relative
            if path.is_symlink() or not path.resolve().is_relative_to(checkout):
                raise ReuseBindingError("A reuse binding source escaped the pinned checkout.")
            raw = path.read_bytes()
            expected = _SOURCE_SHA256[relative]
            if (hashlib.sha256(raw).hexdigest() != expected
                    or hashlib.sha256(_git(checkout, "show", f"HEAD:{relative}")).hexdigest() != expected):
                raise ReuseBindingError("A reuse binding source differs from its pinned Git source.")
            sources[relative] = raw.decode("utf-8")
        projections = _trace(sources, bootstrap=bootstrap, flush=flush, session=session)
    except (OSError, UnicodeError, ReferenceBindingError):
        raise ReuseBindingError("Native reuse binding source evidence is unavailable.") from None
    evidence = []
    for item in projections:
        resolution, chain = item["resolution"], item["chain"]
        evidence.append({
            **resolution, "scope": "native-reuse-pure-function-bindings", "chain": chain,
            "sources": [{"path": relative, "sha256": _SOURCE_SHA256[relative]}
                        for relative in sorted({edge["path"] for edge in chain})],
            "facadeExecutionVerified": False, "facadeInitializationBypassed": True,
            "fullManagerExecutionVerified": False, "fullHostOrchestrationVerified": False,
            "note": "Only verified original named bindings execute unchanged. Broad facade "
                    "initialization is bypassed; full host orchestration is not verified.",
        })
    return {"schemaVersion": 1, "kind": "native-reuse-binding-projection",
            "reference": {"tag": _TAG, "commit": _COMMIT},
            "allowedResolutions": [item["resolution"] for item in projections],
            "projectionEvidence": evidence}
