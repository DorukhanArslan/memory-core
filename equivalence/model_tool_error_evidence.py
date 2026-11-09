"""Bind complete original formatter/tool errors to protected fresh execution."""
from __future__ import annotations

from pathlib import Path
import re

from equivalence.model_runtime_authority import validate_model_node_authority
from equivalence.model_runtime_evidence import _child, _registry
from equivalence.model_tool_error_bindings import REQUIRED_ERROR_ARTIFACTS
from equivalence.search_contract import _same_json, decode_search_tool_envelope


def _require(condition, message):
    if not condition:
        from equivalence.runtime_oracle import RuntimeOracleError

        raise RuntimeOracleError(message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def _error(observed, supplied):
    if isinstance(supplied, str):
        _same(observed, supplied, "A literal thrown string changed before reaching the original formatter")
        return
    _require(isinstance(supplied, dict) and isinstance(observed, dict)
             and set(observed) == {"name", "message", "own"}
             and observed["name"] == "Error" and observed["message"] == supplied["message"],
             "The original Error name, message or complete own-property observation changed")
    own = observed["own"]
    _require(isinstance(own, dict) and set(own) == {"message", "stack", *(key for key in ("code", "cause") if key in supplied)}
             and own["message"] == supplied["message"] and isinstance(own["stack"], str)
             and own["stack"].startswith("Error: " + supplied["message"]),
             "An original Error lost its full stack, own message, code or recursive cause")
    if "code" in supplied:
        _same(own["code"], supplied["code"], "The thrown original error code was replaced")
    if "cause" in supplied:
        _error(own["cause"], supplied["cause"])


def validate_model_tool_error_raw(row, case, diagnostic, evidence_directory, *, runtime_root, bootstrap,
                                   release_by_pid, local_by_pid, process_parents, worker_imports):
    del worker_imports
    from equivalence.runtime_oracle import ROOT

    value = case["input"]
    _require(isinstance(value, dict) and "error" in value and set(value) <= {"error", "patterns", "registeredSecrets"},
             "The error profile requires the unchanged fixed literal error fixture")
    _require(row.get("ok") is True and isinstance(diagnostic, list) and len(diagnostic) == 1,
             "Complete error evidence must retain its successful original execution")
    raw = diagnostic[0]
    _require(isinstance(raw, dict) and set(raw) == {"kind", "fixtureBase", "coordinatorPid", "input", "runtime", "child"}
             and raw["kind"] == "model-tool-error", "The error coordinator lost an evidence channel")
    _same(raw["input"], value, "The error coordinator changed its fixed literal input")
    base, coordinator, record = raw["fixtureBase"], raw["coordinatorPid"], raw["child"]
    _require(isinstance(base, str) and Path(base).is_absolute() and Path(base).parent == evidence_directory
             and re.fullmatch(r"native-model-error-[A-Za-z0-9_-]+", Path(base).name),
             "An error case escaped its exact owned storage root")
    runtime = validate_model_node_authority(raw["runtime"])
    _require(isinstance(record, dict) and type(coordinator) is int and coordinator > 0
             and type(record.get("pid")) is int and record["pid"] > 0 and record["pid"] != coordinator,
             "The original error case requires a distinct fresh child OS process")
    child = record["pid"]
    _require({entry["pid"] for entry in bootstrap if entry.get("isMainThread") is True} == {coordinator, child}
             and process_parents.get(child) == coordinator,
             "An error case bypassed the protected exact parent/child lineage")
    for entry in bootstrap:
        _same(entry.get("runtime"), runtime, "An error process or worker used an unauthenticated binary or Unicode engine")
    _require({str(ROOT / "equivalence/release-oracle.mjs"), str(ROOT / "equivalence/model-tool-error-runtime.mjs"),
              str(ROOT / "equivalence/model-runtime-observation.mjs")} <= local_by_pid.get(coordinator, set()),
             "The protected original error coordinator/observation owner did not execute")
    request = {"input": value, "directory": base, "runtimeRoot": runtime_root}
    output, _ = _child(record, request, runtime=runtime, cli="model-tool-error-cli.mjs",
                       phase_module="model-tool-error-phase.mjs", coordinator=coordinator, local_by_pid=local_by_pid)
    _require(set(REQUIRED_ERROR_ARTIFACTS) <= release_by_pid.get(child, set()),
             "A complete error case omitted the genuine formatter, registry, supplement or whole-tool owner")
    _require(str(ROOT / "equivalence/search-contract-runtime.mjs") in local_by_pid.get(child, set()),
             "The error case omitted its exact whole-envelope transport codec")
    observed = record["raw"]
    _require(set(observed) == {"kind", "pid", "ppid", "request", "runtime", "config", "registry", "error",
                               "formatter", "requests", "invocations"} and observed["kind"] == "model-tool-error",
             "The complete original error observation schema changed")
    logging = {"level": "silent", "consoleLevel": "silent", "file": str(Path(base) / "native.log"),
               **({"redactPatterns": value["patterns"]} if value.get("patterns") is not None else {})}
    config = {"agents": {"defaults": {"workspace": str(Path(base) / "workspace")}}, "logging": logging,
              "memory": {"search": {"enabled": True, "provider": "none", "fallback": "none", "sources": ["memory"]}}}
    _same(observed["config"], config, "The actual error formatter/tools consulted another config or corpus policy")
    registry = observed["registry"]
    _require(isinstance(registry, dict) and set(registry) == {"before", "registrations", "after"},
             "The real registry observation or registration journal was dropped")
    _registry(registry["before"])
    _same(registry["before"], {"revision": 0, "values": []}, "Every error case must start with an actually empty fresh registry")
    _require(isinstance(registry["registrations"], list) and len(registry["registrations"]) == len(value.get("registeredSecrets", [])),
             "A literal secret registration was omitted or inserted")
    previous = registry["before"]
    for registration, secret in zip(registry["registrations"], value.get("registeredSecrets", []), strict=True):
        _require(isinstance(registration, dict) and set(registration) == {"secret", "before", "after"}
                 and registration["secret"] == secret, "A registry receipt changed its literal synthetic secret")
        _same(registration["before"], previous, "A registry revision was reset or offset between actual registrations")
        _registry(registration["after"])
        _require(registration["after"]["revision"] >= previous["revision"] and secret in registration["after"]["values"],
                 "The genuine registration did not retain its literal secret and actual revision")
        previous = registration["after"]
    _registry(registry["after"])
    _same(registry["after"], previous, "Whole-tool execution unexpectedly reset or changed the process registry")
    _error(observed["error"], value["error"])
    _require(isinstance(observed["formatter"], str), "The complete original formatter return was omitted")
    requests, invocations = observed["requests"], observed["invocations"]
    _require(isinstance(requests, list) and len(requests) == 2 and isinstance(invocations, list) and len(invocations) == 2,
             "Both genuine supplemental callbacks and whole-tool executions must be retained")
    expected_tools = []
    for name, callback, params, actual_request, invocation in zip(
            ("get", "search"), ({"lookup": "topic", "agentId": "main"}, {"query": "topic", "agentId": "main"}),
            ({"path": "topic", "corpus": "wiki"}, {"query": "topic", "corpus": "wiki"}), requests, invocations, strict=True):
        _require(isinstance(actual_request, dict) and set(actual_request) == {"tool", "query", "thrownErrorIsOriginal", "error"}
                 and actual_request["tool"] == name and actual_request["thrownErrorIsOriginal"] is True,
                 "A whole-tool callback did not retain its actual same-error throw receipt")
        _same(actual_request["query"], callback, "The original tool dispatched different literal corpus/identity arguments")
        _same(actual_request["error"], observed["error"], "The callback replaced or truncated the original thrown error")
        _require(isinstance(invocation, dict) and set(invocation) == {"name", "callId", "params", "definition", "envelope", "decoded"}
                 and invocation["name"] == name and invocation["callId"] == "diagnostic-" + name,
                 "The original public execute call or complete return was omitted")
        _same(invocation["params"], params, "A whole-tool invocation changed its literal public arguments")
        definition = invocation["definition"]
        _require(isinstance(definition, dict) and definition.get("name") == "memory_" + name
                 and isinstance(definition.get("parameters"), dict) and isinstance(definition.get("execute"), dict)
                 and definition["execute"].get("$type") == "function" and isinstance(definition["execute"].get("source"), str),
                 "The actual complete tool definition or public execute owner was dropped")
        _same(invocation["decoded"], decode_search_tool_envelope(invocation["envelope"]),
              "The original complete JSON envelope no longer round-trips exactly")
        expected_tools.append({"name": name, "envelope": invocation["envelope"], "decoded": invocation["decoded"]})
    expected = {"provider": "none", "formatter": observed["formatter"], "tools": expected_tools}
    _same(output["result"], expected, "A child public result dropped formatter, complete envelope or decoded fields")
    _same(row["result"], expected, "The published error boundary differs from its complete protected child return")
