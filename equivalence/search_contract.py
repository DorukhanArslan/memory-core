"""Actual memory-search owners and complete tool-boundary comparisons.

Fixtures describe caller input and host-owned state. They do not implement a
second parameter parser, presentation algorithm, ranking pass or warning owner.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any


_NOW_MS = 1_738_368_000_000
_PROFILE = (
    "Actual SDK parameter/presentation owners and official native owners, plus "
    "provider-none indexed searches through the complete tool factory/execute boundary. "
    "Compiled definition/argument preparation helpers execute their official export. "
    "Clocks are fixed before tool execution; temporal decay is disabled. Controlled "
    "supplement failures exercise genuine warning composition; unavailable helpers prove "
    "payload shapes only. Deadline/cooldown timing, provider execution/fallback/bootstrap, "
    "real transcript visibility, stale/rebuild lifecycle, general ICU ordering and "
    "warm-index Unicode defects are not claimed."
)
_POLICY = (
    "Complete ordered public payloads are compared without field projection, result "
    "sorting, score rounding or tolerance. The declared provider-neutral JSON carrier "
    "codec retains every content item and details field, verifies that the actual text "
    "carrier decodes exactly to details, and compares its decoded JSON value. Original "
    "wire strings/envelopes remain in both raw diagnostics; byte-identical JSON spacing "
    "and number spelling are outside this engine contract. Missing and explicit null "
    "properties remain distinct. Actual public error name, status and message are retained."
)


def _row(path: str = "memory/cedar.md", **fields: Any) -> dict[str, Any]:
    return {"path": path, "startLine": 2, "endLine": 4, "score": 0.75,
            "snippet": "Cedar tea preference.\n", "source": "memory", **fields}


def build_search_contract_cases() -> list[dict[str, Any]]:
    """Bounded raw-argument, full-presentation and whole-tool scenarios."""
    cases: list[dict[str, Any]] = []

    def add(name: str, kind: str, **arguments: Any) -> None:
        cases.append({
            "id": f"search-contract-{name}", "requirement": "tools.search-contract",
            "operation": ("search-contract-helper-runtime" if kind in {"definition", "prepare-arguments"}
                          else "search-contract-runtime" if kind == "tool" else "search-contract"), "covers": [],
            "input": {"kind": kind, **deepcopy(arguments)},
            "driverScope": _PROFILE, "normalizationPolicy": _POLICY,
        })

    for name, options in (
        ("default", {}), ("sessions", {"indexSessions": True}),
        ("extra-paths", {"extraPaths": ["notes"]}),
        ("sessions-extra-paths", {"indexSessions": True, "extraPaths": ["notes", "archive"]}),
        ("disabled-factory", {"enabled": False}),
        ("missing-config", {"missingConfig": True}),
    ):
        add(f"definition-{name}", "definition", **options)
    for name, params in (
        ("non-record", None), ("unchanged", {"query": "cedar", "unknown": 1}),
        ("snake-aliases", {"query": "cedar", "max_results": "3", "min_score": "0.2"}),
        ("camel-precedence", {"query": "cedar", "maxResults": 2, "max_results": 9,
                              "minScore": 0, "min_score": 1}),
        ("explicit-null-precedence", {"query": "cedar", "maxResults": None, "max_results": 3}),
        ("retains-caller-extras", {"query": "cedar", "min_score": "", "activeProjectKeys": ["alpha"]}),
    ):
        add(f"prepare-{name}", "prepare-arguments", params=params)

    params_cases = (
        ("non-record", None), ("missing-query", {}), ("empty-query", {"query": ""}),
        ("wrong-query-type", {"query": 3}), ("query-js-trim", {"query": "\ufeff cedar\u00a0"}),
        ("omitted", {"query": "cedar"}),
        ("null", {"query": "cedar", "maxResults": None, "minScore": None}),
        ("blank-js-whitespace", {"query": "cedar", "maxResults": "\ufeff\t", "minScore": "\ufeff\u00a0"}),
        ("numeric-strings", {"query": "cedar", "maxResults": "+3.0", "minScore": "-.25e1"}),
        ("snake-aliases", {"query": "cedar", "max_results": "2e1", "min_score": ".5"}),
        ("camel-precedence", {"query": "cedar", "maxResults": 1, "max_results": 2,
                               "minScore": 0, "min_score": 1}),
        ("camel-invalid-precedence", {"query": "cedar", "maxResults": False, "max_results": 3}),
        ("limit-zero", {"query": "cedar", "maxResults": 0}),
        ("limit-negative", {"query": "cedar", "maxResults": -1}),
        ("limit-fraction", {"query": "cedar", "maxResults": 1.5}),
        ("limit-safe-integer", {"query": "cedar", "maxResults": 9_007_199_254_740_991}),
        ("limit-unsafe-integer", {"query": "cedar", "maxResults": 9_007_199_254_740_992}),
        ("limit-hex-string", {"query": "cedar", "maxResults": "0x10"}),
        ("limit-array", {"query": "cedar", "maxResults": [2]}),
        ("score-zero", {"query": "cedar", "minScore": 0}),
        ("score-negative", {"query": "cedar", "minScore": -3}),
        ("score-boolean", {"query": "cedar", "minScore": True}),
        ("score-nan-string", {"query": "cedar", "minScore": "NaN"}),
        ("score-overflow-string", {"query": "cedar", "minScore": "1e9999"}),
        ("score-non-ascii-digits", {"query": "cedar", "minScore": "١"}),
        ("score-object", {"query": "cedar", "minScore": {"value": 0.1}}),
        ("score-trailing-junk", {"query": "cedar", "minScore": "0.1 trailing"}),
    )
    for name, params in params_cases:
        add(f"params-{name}", "params", params=params)

    presentation_cases = (
        ("empty", [], "auto", None),
        ("on-full-metadata", [_row(importance=9, triggers="tea; Çay 😀\x00", projectKey="alpha",
          provenance={"originClass": "owner", "sessionKind": "interactive", "observedAt": _NOW_MS},
          vectorScore=0.4, textScore=0.8, id="provider-owned-id", sourceMtime=_NOW_MS,
          originClass="legacy-owner", opaque={"nested": [None, False, 0]})], "on", None),
        ("off-removes-existing-citation", [_row(citation="caller citation", corpus="caller corpus")], "off", None),
        ("auto-direct", [_row()], "auto", "agent:main:telegram:direct:42"),
        ("auto-group", [_row()], "auto", "agent:main:telegram:group:42"),
        ("auto-channel", [_row()], "auto", "agent:main:discord:channel:42"),
        ("auto-unscoped-group", [_row()], "auto", "telegram:group:42"),
        ("invalid-mode-default", [_row()], "invalid", None),
        ("single-line-session", [_row("sessions/one.jsonl", source="sessions", startLine=7, endLine=7,
                                     provenance=None, importance=None)], "on", None),
        ("annotation-carriers", [_row(snippet="  Cedar. <!-- importance: 9 --> <!-- trigger: tea --> <!-- project: alpha -->\n")], "on", None),
        ("trim-end-and-unclosed-carrier", [_row(snippet="  Çay 😀\x00 <!-- importance: 9\n\ufeff\u00a0")], "on", None),
        ("long-snippet-is-complete", [_row(snippet="Çay 😀 " * 2_100)], "off", None),
    )
    for name, rows, mode, session in presentation_cases:
        add(f"presentation-{name}", "presentation", results=rows, citationMode=mode, sessionKey=session)

    for name, error, overrides in (
        ("blank", "\ufeff \t", {}), ("quota", "provider returned 429: quota exhausted", {}),
        ("sqlite", "No such built-in module: node:sqlite", {}),
        ("deadline-provenance", "provider did not finish", {"deadline": True, "agentId": "main"}),
        ("timeout-text-is-not-provenance", "memory_search timed out", {}),
        ("session-migration", "canonical session key required", {"code": "SESSION_CANONICAL_KEY_MIGRATION_REQUIRED"}),
        ("explicit-overrides", "quota exceeded", {"warning": "Host warning.", "action": "Host action."}),
    ):
        add(f"unavailable-{name}", "unavailable", error=error, overrides=overrides)

    def tool(name: str, files: dict[str, str], steps: list[dict[str, Any]], **options: Any) -> None:
        add(f"tool-{name}", "tool", files=files, mtimeMs=_NOW_MS, nowMs=_NOW_MS,
            steps=steps, **options)

    files = {f"memory/{letter}.md": f"Cedar preference {letter}.\n" for letter in "abcdefgh"}
    tool("raw-defaults-and-overrides", files, [
        {"params": {"query": "cedar"}},
        {"params": {"query": "cedar", "maxResults": 2, "minScore": 0}},
        {"params": {"query": "cedar", "max_results": "3", "min_score": "0"}, "prepareArguments": True},
    ])
    tool("configured-query-defaults", {**files, "MEMORY.md":
         "- Cedar preference. <!-- importance: 10 -->\n"}, [
        {"params": {"query": "cedar"}},
        {"params": {"query": "cedar", "minScore": 0}},
        {"params": {"query": "cedar", "minScore": 0, "maxResults": 3}},
    ], config={"query": {"maxResults": 2, "minScore": 0.75}})
    tool("corpus-validation", {"MEMORY.md": "Cedar preference.\n"}, [
        {"params": {"query": "cedar", "corpus": corpus, "minScore": 0}}
        for corpus in ("memory", "wiki", "all", "sessions", "unknown", "MEMORY", " ", None, 3)
    ], config={"sources": ["memory"]})
    tool("invalid-arguments", {"MEMORY.md": "Cedar preference.\n"}, [
        {"params": params} for params in (
            None, [], {}, {"query": ""}, {"query": "cedar", "maxResults": False},
            {"query": "cedar", "maxResults": 0}, {"query": "cedar", "minScore": "NaN"},
            {"query": "cedar", "maxResults": None, "minScore": "\ufeff\t"},
        )
    ])
    annotation_files = {"MEMORY.md": "- Cedar preference. <!-- importance: 9 --> <!-- trigger: tea, Çay 😀 --> <!-- project: alpha -->\n",
                        "memory/other.md": "Cedar ordinary preference.\n"}
    tool("citation-on-full-metadata", annotation_files, [{"params": {"query": "cedar", "minScore": 0}}],
         config={"citations": "on"}, options={"activeProjectKeys": ["alpha"]})
    tool("citation-off", annotation_files, [{"params": {"query": "cedar", "minScore": 0}}],
         config={"citations": "off"})
    tool("citation-auto-group", annotation_files, [{"params": {"query": "cedar", "minScore": 0}}],
         config={"citations": "auto"}, options={"agentSessionKey": "agent:main:telegram:group:42"})
    tool("trusted-session-override", {"MEMORY.md": "Cedar preference.\n"}, [
        {"params": {"query": "cedar", "corpus": "memory"}},
        {"params": {"query": "cedar", "corpus": "unknown"}},
    ], config={"sources": ["memory"]}, options={"conversationRecall": {"corpus": "sessions"}})
    tool("live-disabled", {"MEMORY.md": "Cedar preference.\n"}, [
        {"params": {"query": "cedar"}, "disableConfig": True},
    ])
    wiki_rows = [{"corpus": "wiki", "source": "wiki", "path": "wiki/cedar", "title": "Cedar",
                  "kind": "article", "score": 0.95, "snippet": "Wiki cedar preference.",
                  "content": "Full wiki cedar article.", "opaque": {"keep": [None, 1]}}]
    tool("supplement-partial-warning", {"MEMORY.md": "Cedar preference.\n"}, [
        {"params": {"query": "cedar", "corpus": "all", "minScore": 0}},
        {"params": {"query": "cedar", "corpus": "wiki", "minScore": 0}},
    ], supplements=[{"pluginId": "zeta", "error": "zeta corpus unavailable"},
                    {"pluginId": "alpha", "results": wiki_rows}])
    tool("supplement-multiple-failure-order", {"MEMORY.md": "Cedar preference.\n"}, [
        {"params": {"query": "cedar", "corpus": "all", "minScore": 0}},
        {"params": {"query": "cedar", "corpus": "wiki", "minScore": 0}},
    ], supplements=[{"pluginId": "zeta", "error": "zeta corpus unavailable"},
                    {"pluginId": "alpha", "error": "alpha corpus unavailable"}])
    # Accepted after the initial 69 native/SDK comparisons and independent
    # review. The committed gate re-executes the tightened config fixtures.
    input_tools = {"raw-defaults-and-overrides", "configured-query-defaults", "corpus-validation",
                   "invalid-arguments", "trusted-session-override", "live-disabled"}
    payload_tools = {"raw-defaults-and-overrides", "configured-query-defaults", "corpus-validation",
                     "citation-on-full-metadata", "citation-off", "citation-auto-group",
                     "supplement-partial-warning", "supplement-multiple-failure-order"}
    for case in cases:
        kind = case["input"]["kind"]
        if kind in {"definition", "prepare-arguments", "params"}:
            case["covers"].append("tools.search-contract.outcomes")
        if kind == "unavailable" or (kind == "presentation" and case["input"]["results"]):
            case["covers"].append("tools.search-contract.boundaries")
        if kind == "tool":
            name = case["id"].removeprefix("search-contract-tool-")
            if name in input_tools:
                case["covers"].append("tools.search-contract.outcomes")
            if name in payload_tools:
                case["covers"].append("tools.search-contract.boundaries")
    return cases


def _error(error: BaseException) -> dict[str, Any]:
    result = {"name": getattr(error, "name", type(error).__name__), "message": str(error)}
    if hasattr(error, "status"):
        result["status"] = error.status
    return {"error": result}


def decode_search_tool_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Decode the verified JSON carrier while retaining the complete envelope.

    This transport policy accounts only for equivalent JSON number spelling and
    whitespace. Every content item, other item field and details value survives.
    The caller retains the untouched producer envelope as execution evidence.
    """
    def invalid_constant(_value: str) -> None:
        raise ValueError("Search tool JSON carrier must contain standard JSON")

    result = deepcopy(envelope)
    content = result.get("content")
    if ("details" not in result or not isinstance(content, list) or not content
            or not isinstance(content[0], dict) or content[0].get("type") != "text"
            or not isinstance(content[0].get("text"), str)):
        raise ValueError("Search tool envelope must retain its actual JSON text carrier and details")
    try:
        decoded = json.loads(content[0]["text"], parse_constant=invalid_constant)
        json.dumps(result["details"], allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("Search tool JSON carrier must contain standard JSON") from error
    if not _same_json(decoded, result["details"]):
        raise ValueError("Search tool JSON carrier differs from its actual details")
    content[0]["text"] = decoded
    return result


def _same_json(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_json(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def run_search_contract(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict[str, Any]:
    """Arrange host input and call production owners without a reference algorithm."""
    from memory_core.tools.citations import (
        build_memory_search_presentation, resolve_memory_citations_mode, should_include_citations,
    )
    from memory_core.tools.common import (
        MemoryToolInputError, as_tool_params_record, read_finite_number_param,
        read_positive_integer_param, read_string_param,
    )

    value = deepcopy(arguments)
    kind = value["kind"]
    if kind == "params":
        try:
            raw = as_tool_params_record(value.get("params"))
            params = {"query": read_string_param(raw, "query", required=True)}
            for key, reader in (("maxResults", read_positive_integer_param),
                                ("minScore", read_finite_number_param)):
                result = reader(raw, key)
                if result is not None:
                    params[key] = result
            return {"params": params}
        except MemoryToolInputError as error:
            return _error(error)
    if kind == "presentation":
        mode = resolve_memory_citations_mode(value.get("citationMode"))
        include = should_include_citations(mode, value.get("sessionKey"))
        return {"citations": mode, "includeCitations": include,
                "results": build_memory_search_presentation(value["results"], include)}
    if kind == "unavailable":
        from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
        from memory_core.tools.memory_search import build_memory_search_unavailable_result

        overrides = value.get("overrides", {})
        kwargs = {("agent_id" if key == "agentId" else key): item
                  for key, item in overrides.items()}
        return {"result": build_memory_search_unavailable_result(
            value.get("error"), runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, **kwargs,
        )}
    if kind in {"definition", "prepare-arguments", "tool"}:
        return _run_boundary(value, evidence_directory=evidence_directory)
    raise ValueError(f"Unsupported search-contract operation: {kind}")


def _run_boundary(value: dict[str, Any], *, evidence_directory: Path | None) -> dict[str, Any]:
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.supplements import RegisteredMemoryCorpusSupplement
    from memory_core.tools.memory_search import MemorySearchToolContext
    from memory_core.tools.search_factory import create_memory_search_tool
    from memory_core.workspace import MemoryWorkspace

    if value["kind"] != "tool":
        return _run_compiled_helper(value, evidence_directory=evidence_directory)
    if any(not isinstance(value.get(key), (int, float)) or isinstance(value[key], bool)
           or not math.isfinite(value[key]) for key in ("nowMs", "mtimeMs")):
        raise ValueError("Whole-tool fixtures require explicit finite paired clock and file mtime inputs")
    # Host paths are private to one invocation; the tool sees actual published
    # SQLite rows, never rows fabricated by this transport.
    with tempfile.TemporaryDirectory(prefix="memory-search-contract-") as temporary:
        root = Path(temporary)
        for relative, content in value.get("files", {}).items():
            path = Path(relative)
            if path.is_absolute() or ".." in relative.replace("\\", "/").split("/"):
                raise ValueError("Workspace files must remain in their private fixture root")
            filename = root / path
            filename.parent.mkdir(parents=True, exist_ok=True)
            filename.write_text(content, encoding="utf-8")
            os.utime(filename, ns=(value["mtimeMs"] * 1_000_000, value["mtimeMs"] * 1_000_000))
        settings, options = value.get("config", {}), value.get("options", {})
        query = settings.get("query", {})
        config = MemoryConfig(
            workspace_dir=root, store_path=root / "index.sqlite",
            citation_mode=settings.get("citations", "auto"),
            session_search="sessions" in settings.get("sources", ["memory"]),
            search_max_results=query.get("maxResults", 6), search_min_score=query.get("minScore", 0.35),
            flags=FeatureFlags(vector_search=False, text_search=True, mmr=False, temporal_decay=False),
        )
        store = SQLiteMemoryStore(config, None)
        store.reindex(MemoryWorkspace(root))
        supplements = [RegisteredMemoryCorpusSupplement(
            fixture["pluginId"], _FixtureSupplement(fixture),
        ) for fixture in value.get("supplements", [])]
        steps, raw = [], []
        live_config = config
        clock_ms = value["nowMs"]
        context = MemorySearchToolContext(manager_ms=0, clock=lambda: clock_ms)
        tool = create_memory_search_tool(
            config, store, get_config=lambda: live_config, context=context,
            agent_session_key=options.get("agentSessionKey"),
            active_project_keys=options.get("activeProjectKeys"),
            conversation_recall=options.get("conversationRecall"), supplements=supplements,
            runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        )
        if tool is None:
            raise ValueError("The actual SDK provider-none memory search tool was unavailable")
        for index, step in enumerate(value["steps"]):
            live_config = (replace(config, flags=replace(config.effective_flags(), memory=False))
                           if step.get("disableConfig") else config)
            clock_ms = step.get("nowMs", value["nowMs"])
            params = deepcopy(step.get("params"))
            try:
                if step.get("prepareArguments"):
                    params = tool.prepare_arguments(params)
                envelope = tool.execute(f"fixture-{index}", params)
            except Exception as error:
                result = _error(error)
                wire = result
            else:
                wire = {"result": envelope}
                result = {"result": decode_search_tool_envelope(envelope)}
            steps.append(result)
            raw.append({"index": index, "params": params, **deepcopy(wire),
                        "published": store.read_published_index(),
                        "constructorExecuted": True, "provider": "none"})
        _write_evidence(evidence_directory, raw)
        return {"provider": "none", "steps": steps}


class _FixtureSupplement:
    """Controlled provider responses; production owners aggregate and present them."""

    def __init__(self, fixture: dict[str, Any]):
        self.fixture = deepcopy(fixture)

    def search(self, **_query: Any) -> list[dict[str, Any]]:
        if "error" in self.fixture:
            raise RuntimeError(self.fixture["error"])
        return deepcopy(self.fixture.get("results", []))

    def get(self, **_query: Any) -> None:
        return None


def _write_evidence(directory: Path | None, raw: list[dict[str, Any]]) -> None:
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "python-raw.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )


def _run_compiled_helper(value: dict[str, Any], *, evidence_directory: Path | None) -> dict[str, Any]:
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.tools.search_factory import (
        create_memory_search_tool, prepare_memory_search_arguments,
    )

    if value["kind"] == "prepare-arguments":
        params = value.get("params")
        prepared = prepare_memory_search_arguments(params)
        result = {"provider": "none", "params": prepared, "sameInput": prepared is params,
                  "inputAfter": params}
    else:
        with tempfile.TemporaryDirectory(prefix="memory-search-definition-") as temporary:
            root = Path(temporary)
            config = MemoryConfig(workspace_dir=root, store_path=root / "index.sqlite",
                                  session_search=value.get("indexSessions", False),
                                  flags=FeatureFlags(vector_search=False, memory=value.get("enabled", True)))
            store = SQLiteMemoryStore(config, None)
            tool = create_memory_search_tool(
                None if value.get("missingConfig") else config, store, extra_paths=value.get("extraPaths", []),
            )
            result = {"provider": "none", "definition": tool.definition if tool is not None else None}
    _write_evidence(evidence_directory, [{"kind": value["kind"], "result": deepcopy(result)}])
    return result
