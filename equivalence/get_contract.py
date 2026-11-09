"""Paired memory-get inputs transported to actual reader and tool owners."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from typing import Any

from equivalence.search_contract import decode_search_tool_envelope


_PROFILE = (
    "Actual parameter and excerpt builders plus the complete provider-none memory_get "
    "factory/execute boundary over private real files, directories, symlinks and registered "
    "wiki callbacks. Trusted character caps and extra paths are paired native host config. "
    "Registered callbacks supply literal provider responses; genuine owners merge outcomes "
    "and preserve response details. Configured extra paths are plain files/directories; "
    "glob patterns are outside this profile. Filesystem races, retry timing, deadlines, session-history "
    "visibility, provider execution, operating-system-specific ELOOP cause text and general "
    "platform/Unicode path collation are not claimed."
)
_POLICY = (
    "Complete ordered tool envelopes and excerpt results without field projection, "
    "truncation repair, sorting or tolerance. The already-reviewed JSON carrier codec "
    "verifies text parses exactly to details, preserves every content/envelope field, and "
    "decodes only that verified text carrier for syntax-independent JSON comparison. "
    "Original wire strings and complete envelopes remain in raw diagnostics. Private "
    "$WORKSPACE path tokens resolve only caller inputs before execution; no output path "
    "normalization occurs. Provider request observations retain every actual keyword, "
    "with Python snake-case argument names mapped mechanically to native camelCase. "
    "Missing and explicit null fields stay distinct."
)
_FILESYSTEM_POLICY = _POLICY.replace(
    "no output path normalization occurs.",
    "only the filesystem cases map the exact owned private fixture-base prefix to "
    "$FIXTURE in JSON string values after the complete wire envelope validates. "
    "Error words/codes, every field, list order and raw envelopes remain intact.",
)


def build_get_contract_cases() -> list[dict[str, Any]]:
    """Bounded raw input, excerpt-boundary and actual tool/read scenarios."""
    cases: list[dict[str, Any]] = []

    def add(name: str, kind: str, **arguments: Any) -> None:
        cases.append({
            "id": f"get-contract-{name}", "requirement": "tools.get-contract", "covers": [],
            "operation": ("get-contract-helper-runtime" if kind == "definition"
                          else "get-contract-runtime" if kind == "tool" else "get-contract"),
            "input": {"kind": kind, **deepcopy(arguments)},
            "driverScope": _PROFILE, "normalizationPolicy": _POLICY,
        })

    for name, options in (
        ("default", {}), ("sessions", {"indexSessions": True}),
        ("extra-paths", {"extraPaths": ["notes"]}),
        ("sessions-extra-paths", {"indexSessions": True, "extraPaths": ["notes", "archive"]}),
        ("disabled", {"enabled": False}), ("missing-config", {"missingConfig": True}),
    ):
        add(f"definition-{name}", "definition", **options)
    for name, params in (
        ("non-record", None), ("array", []), ("missing-path", {}),
        ("blank-path", {"path": "\ufeff\t"}), ("wrong-path-type", {"path": 3}),
        ("path-js-trim", {"path": "\ufeff memory/a.md\u00a0"}),
        ("omitted-window", {"path": "MEMORY.md"}),
        ("null-window", {"path": "MEMORY.md", "from": None, "lines": None}),
        ("blank-window", {"path": "MEMORY.md", "from": "\ufeff\t", "lines": "\u00a0"}),
        ("numeric-strings", {"path": "MEMORY.md", "from": "+2.0", "lines": "3e1"}),
        ("from-zero", {"path": "MEMORY.md", "from": 0}),
        ("from-negative", {"path": "MEMORY.md", "from": -1}),
        ("from-fraction", {"path": "MEMORY.md", "from": 1.5}),
        ("from-boolean", {"path": "MEMORY.md", "from": True}),
        ("from-safe-integer", {"path": "MEMORY.md", "from": 9_007_199_254_740_991}),
        ("from-unsafe-integer", {"path": "MEMORY.md", "from": 9_007_199_254_740_992}),
        ("from-hex-string", {"path": "MEMORY.md", "from": "0x10"}),
        ("lines-zero", {"path": "MEMORY.md", "lines": 0}),
        ("lines-negative", {"path": "MEMORY.md", "lines": -2}),
        ("lines-fraction", {"path": "MEMORY.md", "lines": 1.5}),
        ("lines-boolean", {"path": "MEMORY.md", "lines": False}),
        ("lines-array", {"path": "MEMORY.md", "lines": [2]}),
        ("lines-nan-string", {"path": "MEMORY.md", "lines": "NaN"}),
        ("lines-overflow-string", {"path": "MEMORY.md", "lines": "1e999"}),
        ("lines-non-ascii-digits", {"path": "MEMORY.md", "lines": "١"}),
    ):
        add(f"params-{name}", "params", params=params)

    def excerpt(name: str, content: str, **options: Any) -> None:
        add(f"read-{name}", "read-result", options={"content": content, "relPath": "memory/a.md", **options})

    excerpt("empty", "")
    excerpt("terminal-newline", "one\ntwo\n")
    excerpt("no-terminal-newline", "one\ntwo")
    excerpt("trailing-blank-line", "one\n\n")
    excerpt("crlf-preserved", "one\r\ntwo\r\n")
    excerpt("bare-cr-preserved", "one\rtwo\n")
    excerpt("default-120-lines", "\n".join(f"line {index}" for index in range(1, 126)) + "\n")
    excerpt("explicit-line-window", "one\ntwo\nthree\nfour\n", **{"from": 2, "lines": 2})
    excerpt("at-final-line", "one\ntwo\n", **{"from": 2, "lines": 1})
    excerpt("beyond-final-line", "one\ntwo\n", **{"from": 7, "lines": 2})
    excerpt("clamped-low-level-window", "one\ntwo\n", **{"from": 0, "lines": 0})
    excerpt("trusted-default-lines", "one\ntwo\nthree\n", defaultLines=2)
    excerpt("explicit-lines-overrides-default", "one\ntwo\nthree\n", defaultLines=1, lines=3)
    excerpt("default-12000-char-boundary", "a" * 12_000)
    excerpt("default-12000-char-overflow", "a" * 12_001, suggestReadFallback=True)
    excerpt("line-boundary-char-cap", "ab\ncd\nef\n", maxChars=5)
    excerpt("line-separator-counts", "ab\ncd\n", maxChars=4)
    excerpt("oversized-first-line", "abcdef\nnext\n", maxChars=3, suggestReadFallback=True)
    excerpt("astral-fits-two-units", "😀x\n", maxChars=2)
    excerpt("astral-one-unit-empty-text-notice", "😀x\n", maxChars=1, suggestReadFallback=True)
    excerpt("astral-boundary-not-split", "a😀z\n", maxChars=2)
    excerpt("combining-and-nul", "e\u0301\x00z\n", maxChars=3)
    excerpt("zero-char-cap-clamps-one", "abc\n", maxChars=0)
    for name, options in (
        ("empty", {"selectedLines": [], "startLine": 3}),
        ("empty-line-more", {"selectedLines": [""], "startLine": 3, "moreSourceLinesRemain": True}),
        ("multiple-lines-cap", {"selectedLines": ["one", "two", "three"], "startLine": 4, "maxChars": 7}),
        ("astral-hard-cap", {"selectedLines": ["😀"], "startLine": 2, "maxChars": 1, "suggestReadFallback": True}),
    ):
        add(f"slice-{name}", "read-result-slice", options={"relPath": "memory/a.md", **options})

    def tool(name: str, files: dict[str, str], params: list[Any], **options: Any) -> None:
        add(f"tool-{name}", "tool", files=files, steps=[{"params": row} for row in params], **options)

    tool("raw-arguments-and-corpora", {"MEMORY.md": "one\ntwo\nthree\n"}, [
        None, [], {}, {"path": ""}, {"path": "MEMORY.md", "from": False},
        {"path": "MEMORY.md", "lines": 0}, {"path": "MEMORY.md", "lines": "NaN"},
        {"path": "MEMORY.md", "from": "2", "lines": "1"},
        *[{"path": "MEMORY.md", "corpus": corpus} for corpus in ("memory", "wiki", "all", "sessions", "MEMORY", " ", None, 3)],
    ])
    tool("eligible-and-refused-paths", {
        "MEMORY.md": "Root memory.\n", "memory.md": "Lower root.\n", "USER.md": "Persona.\n",
        "dreams.md": "Dreams.\n", "memory/a.md": "Nested memory.\n", "AGENTS.md": "Instructions.\n",
        "sessions/main/one.jsonl": "session bytes", "memory/.dreams/session-corpus/one.txt": "session bytes",
        "memory/.dreams/session-corpus/one.md": "Ordinary memory markdown.\n",
    }, [{"path": path} for path in (
        "MEMORY.md", "./MEMORY.md", "memory/../MEMORY.md", "$WORKSPACE/memory/a.md", "USER.md",
        "dreams.md", "memory.md", "memory/missing.md", "AGENTS.md", "memory/a.MD",
        "sessions/main/one.jsonl", "memory/.dreams/session-corpus/one.txt",
        "memory/.dreams/session-corpus/one.md", "memory/../../outside.md", "/outside/example.md",
    )])
    tool("filesystem-policy", {"memory/real/a.md": "Actual within-root content.\n", "memory/not-dir": "plain"},
         [{"path": path} for path in (
             "memory/leaf.md", "memory/external-leaf.md", "memory/inside/a.md", "memory/outside/a.md",
             "memory/outside/missing.md", "memory/missing-parent/a.md",
             "memory/directory.md", "memory/not-dir/a.md",
         )], directories=["memory/directory.md"], outsideFiles={"a.md": "Private fixture outside workspace.\n"},
         normalizeFixturePaths=True,
         symlinks={
             "memory/leaf.md": {"scope": "workspace", "path": "memory/real/a.md"},
             "memory/external-leaf.md": {"scope": "outside", "path": "a.md"},
             "memory/inside": {"scope": "workspace", "path": "memory/real"},
             "memory/outside": {"scope": "outside", "path": "."},
             "memory/missing-parent": {"scope": "outside", "path": "missing"},
         })
    cases[-1]["normalizationPolicy"] = _FILESYSTEM_POLICY
    add("symlink-loop-cause-diagnostic", "tool", files={}, normalizeFixturePaths=True,
        steps=[{"params": {"path": "memory/loop/a.md"}}],
        symlinks={"memory/loop": {"scope": "workspace", "path": "memory/loop"}})
    cases[-1].update({
        "requirement": "storage.path-safety", "normalizationPolicy": _FILESYSTEM_POLICY,
        "driverScope": _PROFILE + " Diagnostic only: the existing Python/Node operating-system "
        "symlink-loop cause difference remains visible and earns no tool-contract credit.",
    })
    tool("default-and-explicit-lines", {"MEMORY.md": "\n".join(f"line {i}" for i in range(1, 126)) + "\n"}, [
        {"path": "MEMORY.md"}, {"path": "MEMORY.md", "from": 121},
        {"path": "MEMORY.md", "from": 120, "lines": 6}, {"path": "MEMORY.md", "from": 999},
    ])
    tool("trusted-character-cap", {"memory/a.md": "a😀z\nnext\n", "memory/empty-astral.md": "😀\n"}, [
        {"path": "memory/a.md"}, {"path": "memory/empty-astral.md"},
    ], config={"maxChars": 1})
    tool("utf8-and-line-endings", {}, [{"path": "memory/raw.md"}, {"path": "memory/raw.md", "from": 2, "lines": 1}],
         fileBytes={"memory/raw.md": [0xEF, 0xBB, 0xBF, 0x61, 0xFF, 0x0D, 0x0A, 0x62, 0x0D, 0x0A]})
    tool("extra-path-admission", {"notes/a.md": "Extra directory.\n", "named.md": "Explicit extra file.\n",
                                  "notes/a.txt": "Not markdown.\n"}, [
        {"path": "notes/a.md"}, {"path": "named.md"}, {"path": "notes/a.txt"},
    ], config={"extraPaths": ["notes", "named.md"]})
    wiki = {"path": "provider/cedar", "corpus": "compiled-wiki", "title": "Cedar", "kind": "article",
            "content": "Full provider-owned text.\nSecond line.", "snippet": "Provider snippet.", "score": 0.8,
            "from": 44, "lines": 2, "nextFrom": 46, "truncated": True, "status": "provider-status",
            "opaque": {"nested": [None, False, "Çay 😀\x00"]}}
    tool("wiki-full-metadata-and-memory-precedence", {"MEMORY.md": "Builtin memory wins.\n"}, [
        {"path": "./wiki/cedar", "from": 2, "lines": 1, "corpus": "wiki"},
        {"path": "\ufeff /wiki/opaque\\lookup\u00a0", "from": 3, "lines": 1, "corpus": "wiki"},
        *[{"path": f"wiki/{variant}", "corpus": "wiki"} for variant in ("empty", "null", "missing")],
        {"path": "MEMORY.md", "corpus": "all"}, {"path": "memory/missing.md", "corpus": "all"},
        {"path": "AGENTS.md", "corpus": "all"},
    ], supplements=[{"pluginId": "zeta", "result": {**wiki, "path": "provider/zeta"}},
                    {"pluginId": "alpha", "result": wiki, "resultsByLookup": {
                        "wiki/empty": {"path": "provider/empty", "content": "", "snippet": "Must not replace empty content."},
                        "wiki/null": {"path": "provider/null", "content": None, "opaque": None},
                        "wiki/missing": {"path": "provider/missing", "opaque": None},
                    }}], options={"agentSessionKey": "agent:main:main", "sandboxed": True})
    tool("wiki-miss-and-unregistered", {}, [
        {"path": "wiki/missing", "corpus": "wiki"}, {"path": "memory/missing.md", "corpus": "all"},
    ], supplements=[{"pluginId": "alpha", "result": None}])
    tool("wiki-partial-failure", {"MEMORY.md": "Builtin memory.\n"}, [
        {"path": "wiki/cedar", "corpus": "wiki"}, {"path": "MEMORY.md", "corpus": "all"},
    ], supplements=[{"pluginId": "zeta", "error": "zeta read unavailable"}, {"pluginId": "alpha", "result": wiki}])
    tool("wiki-multiple-failure-order", {}, [
        {"path": "wiki/cedar", "corpus": "wiki"}, {"path": "memory/missing.md", "corpus": "all"},
    ], supplements=[{"pluginId": "zeta", "error": "zeta read unavailable"},
                    {"pluginId": "alpha", "error": "alpha read unavailable"}])
    add("tool-live-disabled", "tool", files={"MEMORY.md": "Memory.\n"}, steps=[
        {"params": {"path": "MEMORY.md"}, "disableConfig": True},
    ])
    # The corrected native run matched every tool-contract fixture. Independent
    # review keeps the actual OS-owned loop cause as a separate open diagnostic.
    parameter_errors = {
        "non-record", "array", "missing-path", "blank-path", "wrong-path-type",
        "from-zero", "from-negative", "from-fraction", "from-boolean", "from-unsafe-integer",
        "from-hex-string", "lines-zero", "lines-negative", "lines-fraction", "lines-boolean",
        "lines-array", "lines-nan-string", "lines-overflow-string", "lines-non-ascii-digits",
    }
    for case in cases:
        if case["requirement"] != "tools.get-contract":
            continue
        kind = case["input"]["kind"]
        if kind in {"read-result", "read-result-slice"} and case["id"] not in {
            "get-contract-read-empty", "get-contract-slice-empty",
        }:
            case["covers"] += ["tools.get-contract.outcomes", "tools.get-contract.boundaries"]
        elif kind == "params" and case["id"].removeprefix("get-contract-params-") in parameter_errors:
            case["covers"].append("tools.get-contract.boundaries")
        elif kind == "tool":
            if case["id"] != "get-contract-tool-live-disabled":
                case["covers"].append("tools.get-contract.outcomes")
            case["covers"].append("tools.get-contract.boundaries")
    return cases


def _error(error: BaseException) -> dict[str, Any]:
    result = {"name": getattr(error, "name", type(error).__name__), "message": str(error)}
    if hasattr(error, "status"):
        result["status"] = error.status
    return {"error": result}


def run_get_contract(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict[str, Any]:
    """Pass independently owned fixture inputs through actual production APIs."""
    from memory_core.tools.common import (
        MemoryToolInputError, as_tool_params_record, read_positive_integer_param, read_string_param,
    )

    value = deepcopy(arguments)
    kind = value["kind"]
    if kind == "params":
        try:
            raw = as_tool_params_record(value.get("params"))
            params = {"path": read_string_param(raw, "path", required=True)}
            for key in ("from", "lines"):
                result = read_positive_integer_param(raw, key)
                if result is not None:
                    params[key] = result
            return {"params": params}
        except MemoryToolInputError as error:
            return _error(error)
    if kind in {"read-result", "read-result-slice"}:
        return _run_excerpt(value)
    if kind in {"definition", "tool"}:
        return _run_boundary(value, evidence_directory=evidence_directory)
    raise ValueError(f"Unsupported get-contract operation: {kind}")


def _run_excerpt(value: dict[str, Any]) -> dict[str, Any]:
    from memory_core.tools.memory_get import (
        build_memory_read_result, build_memory_read_result_from_slice,
    )

    names = {"relPath": "rel_path", "from": "from_line", "defaultLines": "default_lines",
             "maxChars": "max_chars", "suggestReadFallback": "suggest_read_fallback",
             "selectedLines": "selected_lines", "startLine": "start_line",
             "moreSourceLinesRemain": "more_source_lines_remain"}
    options = {names.get(key, key): item for key, item in value["options"].items()}
    owner = build_memory_read_result if value["kind"] == "read-result" else build_memory_read_result_from_slice
    return {"result": owner(**options)}


def _run_boundary(value: dict[str, Any], *, evidence_directory: Path | None) -> dict[str, Any]:
    from equivalence.get_fixture_filesystem import (
        derive_get_filesystem_observation, derive_get_read_race_observation, get_fixture_read_race,
        owned_get_extra_paths, owned_get_input_path,
        snapshot_get_fixture,
    )
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.supplements import RegisteredMemoryCorpusSupplement
    from memory_core.tools.get_factory import create_memory_get_tool

    with tempfile.TemporaryDirectory(prefix="memory-get-contract-") as temporary:
        directory = Path(temporary)
        workspace, outside = directory / "workspace", directory / "outside"
        workspace_kind = value.get("workspaceKind", "directory")
        if workspace_kind == "directory":
            workspace.mkdir()
        elif workspace_kind == "file":
            workspace.write_bytes(b"workspace is a regular file\n")
        elif workspace_kind != "missing":
            raise ValueError("Unknown owned workspace fixture kind")
        outside.mkdir()
        settings, options = value.get("config", {}), value.get("options", {})
        config = MemoryConfig(
            workspace_dir=workspace, flags=FeatureFlags(vector_search=False, memory=value.get("enabled", True)),
            session_search=value.get("indexSessions", False),
            memory_get_max_chars=settings.get("maxChars", 12_000),
        )
        if value["kind"] == "definition":
            tool = create_memory_get_tool(None if value.get("missingConfig") else config,
                                          extra_paths=value.get("extraPaths", []))
            result = {"provider": "none", "definition": tool.definition if tool is not None else None}
            _write_evidence(evidence_directory, [{"kind": "definition", "result": deepcopy(result)}])
            return result

        for root, files in ((workspace, value.get("files", {})), (outside, value.get("outsideFiles", {}))):
            for relative, text in files.items():
                filename = _fixture_path(root, relative)
                filename.parent.mkdir(parents=True, exist_ok=True)
                filename.write_bytes(text.encode("utf-8"))
        for relative, octets in value.get("fileBytes", {}).items():
            filename = _fixture_path(workspace, relative)
            filename.parent.mkdir(parents=True, exist_ok=True)
            filename.write_bytes(bytes(octets))
        for relative in value.get("directories", []):
            _fixture_path(workspace, relative).mkdir(parents=True, exist_ok=True)
        for relative, target in value.get("symlinks", {}).items():
            filename = _fixture_path(workspace, relative)
            filename.parent.mkdir(parents=True, exist_ok=True)
            if target["scope"] not in {"workspace", "outside"}:
                raise ValueError("A fixture symlink must target an owned root")
            target_root = workspace if target["scope"] == "workspace" else outside
            filename.symlink_to(_fixture_path(target_root, target["path"]))
        for relative, target in value.get("hardlinks", {}).items():
            filename = _fixture_path(workspace, relative)
            filename.parent.mkdir(parents=True, exist_ok=True)
            if target["scope"] not in {"workspace", "outside"}:
                raise ValueError("A fixture hardlink must target an owned root")
            target_root = workspace if target["scope"] == "workspace" else outside
            filename.hardlink_to(_fixture_path(target_root, target["path"]))

        filesystem = ({"before": snapshot_get_fixture(directory)}
                      if value.get("observeFilesystem") else None)

        requests: list[dict[str, Any]] = []
        providers = [_LiteralSupplement(fixture, requests) for fixture in value.get("supplements", [])]
        supplements = [RegisteredMemoryCorpusSupplement(provider.fixture["pluginId"], provider,
                                                        reader=provider.read) for provider in providers]
        live_config = config
        tool = create_memory_get_tool(
            config, get_config=lambda: live_config, supplements=supplements,
            extra_paths=owned_get_extra_paths(value.get("extraPaths", settings.get("extraPaths", [])), directory),
            agent_session_key=options.get("agentSessionKey"), sandboxed=options.get("sandboxed"),
        )
        if tool is None:
            raise ValueError("The actual SDK memory get tool was unavailable")
        steps, raw = [], []
        race_observation = None
        for index, step in enumerate(value["steps"]):
            live_config = (replace(config, flags=replace(config.effective_flags(), memory=False))
                           if step.get("disableConfig") else config)
            params = deepcopy(step.get("params"))
            if isinstance(params, dict) and isinstance(params.get("path"), str):
                params["path"] = owned_get_input_path(
                    params["path"], directory, require_owned=bool(value.get("observeFilesystem")),
                )
            with get_fixture_read_race(value.get("readRace"), directory) as current_race:
                try:
                    envelope = tool.execute(f"fixture-{index}", params)
                except Exception as error:
                    result = _error(error)
                    wire = result
                else:
                    wire = {"result": envelope}
                    result = {"result": decode_search_tool_envelope(envelope)}
            race_observation = current_race
            steps.append(result)
            raw.append({"index": index, "params": params, **deepcopy(wire),
                        "requests": deepcopy(requests), "fixtureBase": str(directory),
                        "factoryExecuted": True, "provider": "none"})
        observed = {"provider": "none", "steps": steps, "requests": requests}
        if filesystem is not None:
            filesystem["after"] = snapshot_get_fixture(directory)
            observed["filesystem"] = derive_get_filesystem_observation(filesystem)
            snapshot_record = {"kind": "filesystem", "fixtureBase": str(directory), "filesystem": filesystem}
            if race_observation is not None:
                snapshot_record["readRace"] = race_observation
                observed["readRace"] = derive_get_read_race_observation(race_observation, str(directory), native=False)
            raw.append(snapshot_record)
        _write_evidence(evidence_directory, raw)
        return map_get_fixture_paths(observed, directory) if value.get("normalizeFixturePaths") else observed


def map_get_fixture_paths(value: Any, fixture_base: str | Path) -> Any:
    """Map only the exact owned fixture base in complete JSON string values."""
    base = str(fixture_base).rstrip("/")
    if not base or not Path(base).is_absolute():
        raise ValueError("A private absolute fixture base is required")
    if isinstance(value, str):
        return "$FIXTURE" if value == base else value.replace(base + "/", "$FIXTURE/")
    if isinstance(value, list):
        return [map_get_fixture_paths(item, base) for item in value]
    if isinstance(value, dict):
        return {key: map_get_fixture_paths(item, base) for key, item in value.items()}
    return deepcopy(value)


def _fixture_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in relative.replace("\\", "/").split("/"):
        raise ValueError("Fixture files must remain inside their owned root")
    for parent in (root, *(root / path).parents):
        if parent == root.parent:
            break
        if parent.is_symlink():
            raise ValueError("Fixture creation must not follow parent symlinks")
    return root / path


class _LiteralSupplement:
    """Literal provider responses; actual production owns lookup/range policy."""

    def __init__(self, fixture: dict[str, Any], requests: list[dict[str, Any]]):
        self.fixture, self.requests = deepcopy(fixture), requests

    def read(self, **query: Any) -> Any:
        names = {"from_line": "fromLine", "line_count": "lineCount", "agent_id": "agentId",
                 "agent_session_key": "agentSessionKey"}
        self.requests.append({"pluginId": self.fixture["pluginId"],
                              "query": {names.get(key, key): item for key, item in query.items()}})
        if "error" in self.fixture:
            raise RuntimeError(self.fixture["error"])
        replies = self.fixture.get("resultsByLookup", {})
        return deepcopy(replies[query["lookup"]] if query["lookup"] in replies else self.fixture.get("result"))

    def search(self, **_query: Any) -> list:
        return []

    def get(self, **_query: Any) -> None:
        return None


def _write_evidence(directory: Path | None, raw: list[dict[str, Any]]) -> None:
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "python-raw.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
