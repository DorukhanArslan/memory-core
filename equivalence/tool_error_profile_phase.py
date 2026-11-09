"""Fresh SDK process: real formatter, registered failures and whole tool owners."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import traceback

from equivalence.search_contract import decode_search_tool_envelope
from equivalence.tool_error_profile import (
    ROOT, assert_synthetic_error_registry, validate_tool_error_input,
)


def _error_record(error):
    if not isinstance(error, BaseException):
        return deepcopy(error)
    return {"name": getattr(error, "name", type(error).__name__), "message": str(error),
            "properties": deepcopy(vars(error)),
            "cause": _error_record(error.__cause__),
            "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))}


def run_phase(request):
    if type(request) is not dict or set(request) != {"input", "directory"}:
        raise ValueError("A formatter/tool child accepts only literal input and its owned fixture directory")
    value = request["input"]
    validate_tool_error_input(value)
    directory = Path(request["directory"])
    if not directory.is_absolute():
        raise ValueError("A formatter/tool child requires an absolute owned fixture directory")
    import memory_core
    from memory_core import redact, secret_registry
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.supplements import RegisteredMemoryCorpusSupplement, StaticMemoryCorpusSupplement
    from memory_core.tools.common import MemoryToolError, format_error_message
    from memory_core.tools.get_factory import create_memory_get_tool
    from memory_core.tools.search_factory import create_memory_search_tool

    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("The formatter/tool child imported an SDK outside its owning worktree")
    # Audit the fresh registry BEFORE any snapshot or introspection. There is no
    # reset call: nonzero revisions or ambient values reject the experiment.
    if (secret_registry.get_secret_redaction_registry_revision() != 0
            or secret_registry.has_registered_secret_values_for_redaction()):
        raise RuntimeError("A formatter/tool child requires a fresh synthetic-only registry at revision zero")

    def snapshot():
        captured = secret_registry.capture_secret_redaction_registry_snapshot()
        assert_synthetic_error_registry(captured.values)
        return {"revision": captured.revision, "values": list(captured.values)}

    registry = {"before": snapshot(), "registrations": []}
    directory.mkdir()
    config_file = {"agents": {"defaults": {"workspace": str(directory)}},
                   "logging": {"level": "silent", "consoleLevel": "silent",
                               **({"redactPatterns": value["patterns"]} if "patterns" in value else {})},
                   "memory": {"search": {"enabled": True, "provider": "none", "fallback": "none", "sources": ["memory"]}}}
    (directory / "openclaw.json").write_text(json.dumps(config_file), encoding="utf-8")
    for secret in value.get("registeredSecrets", []):
        before = snapshot()
        secret_registry.register_secret_value_for_redaction(secret)
        registry["registrations"].append({"value": secret, "before": before, "after": snapshot()})
    if "patterns" in value:
        redact.configure_logging_redaction(redact.LoggingConfig(tuple(value["patterns"])))

    def fixture_error(spec):
        if isinstance(spec, str):
            return spec
        error = MemoryToolError(spec["message"])
        if "code" in spec:
            error.code = spec["code"]
        if "cause" in spec:
            error.__cause__ = fixture_error(spec["cause"])
        return error

    error = fixture_error(value["error"])
    requests = []

    def failed(tool):
        def execute(**options):
            requests.append({"tool": tool, "options": deepcopy(options), "error": _error_record(error),
                             "throwsRegisteredError": True})
            raise error
        return execute

    config = MemoryConfig(workspace_dir=directory, flags=FeatureFlags(vector_search=False))
    store = SQLiteMemoryStore(config, None)
    supplement = RegisteredMemoryCorpusSupplement(
        "wiki-demo", StaticMemoryCorpusSupplement([]), reader=failed("get"), searcher=failed("search"))
    factories = (("get", create_memory_get_tool(config, supplements=[supplement]), {"path": "topic", "corpus": "wiki"}),
                 ("search", create_memory_search_tool(config, store, supplements=[supplement]), {"query": "topic", "corpus": "wiki"}))
    formatter = format_error_message(error)
    invocations, tools = [], []
    for name, tool, params in factories:
        if tool is None:
            raise RuntimeError("The actual SDK memory tool was unavailable")
        call_id = "diagnostic-" + name
        envelope = tool.execute(call_id, params)
        decoded = decode_search_tool_envelope(envelope)
        invocations.append({"name": name, "callId": call_id, "params": deepcopy(params),
                            "envelope": deepcopy(envelope), "decoded": deepcopy(decoded)})
        tools.append({"name": name, "envelope": envelope, "decoded": decoded})
    registry["after"] = snapshot()
    result = {"provider": "none", "formatter": formatter, "tools": tools}
    return {"result": result, "raw": {"kind": "model-tool-error", "pid": os.getpid(), "ppid": os.getppid(),
              "implementationRoot": str(Path(memory_core.__file__).resolve().parents[1]), "fixtureBase": str(directory),
              "input": deepcopy(value), "config": {"host": config_file, "sdk": asdict(config)}, "registry": registry,
              "error": _error_record(error), "formatter": formatter, "requests": requests, "invocations": invocations}}


if __name__ == "__main__":
    json.dump(run_phase(json.load(sys.stdin)), sys.stdout, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
