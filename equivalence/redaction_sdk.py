"""Fresh-process calls to actual SDK redaction, settlement and storage owners."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


class RedactionChildError(RuntimeError):
    """Retain the real failed child streams without replacing its observation."""

    def __init__(self, message: str, record: dict) -> None:
        super().__init__(message)
        self.record = record


def _environment(root: Path) -> dict[str, str]:
    return {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC", "PYTHONPATH": str(ROOT),
            "OPENCLAW_STATE_DIR": str(root / "state"), "OPENCLAW_CONFIG_PATH": str(root / "openclaw.json"),
            "OPENCLAW_HOME": str(root / "home")}


def _registry_snapshot() -> dict:
    from memory_core.secret_registry import capture_secret_redaction_registry_snapshot

    value = capture_secret_redaction_registry_snapshot()
    return {"revision": value.revision, "values": list(value.values)}


def _ordinary_fresh_registry() -> dict:
    import memory_core

    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("The redaction child imported an SDK outside its worktree")
    before = _registry_snapshot()
    if before != {"revision": 0, "values": []}:
        raise RuntimeError("The redaction child registry was not initially empty")
    return before


def _source_policy(arguments: dict) -> dict:
    from memory_core import redact, secret_registry
    from memory_core.model_tool_result import capture_model_visible_redaction_policy
    from memory_core.redact_user_patterns import compile_config_regex
    from memory_core.session_transcript_append import redact_message_for_storage

    if arguments.get("kind") != "source-policy":
        raise ValueError("A fixed source-policy case is required")
    before = _ordinary_fresh_registry()
    config = redact.LoggingConfig(tuple(arguments["patterns"]) if "patterns" in arguments else None)
    if arguments.get("fullContext"):
        config = redact.mark_full_context_tool_payload_redaction(config)
    redact.configure_logging_redaction(config)
    for secret in arguments["registeredSecrets"]:
        secret_registry.register_secret_value_for_redaction(secret)
    after = _registry_snapshot()
    if any(value not in arguments["declaredRegistryValues"] for value in after["values"]):
        raise RuntimeError("The redaction child registry contains an undeclared value")
    policy = asdict(capture_model_visible_redaction_policy(config))
    extra = {}
    if arguments.get("directRegex"):
        compiled = compile_config_regex(arguments["directRegex"]["source"], arguments["directRegex"]["flags"])
        extra["directCompiler"] = ({"pattern": compiled.pattern, "flags": compiled.flags,
            "reason": compiled.reason, "accepted": compiled.regex is not None} if compiled else None)
    result = {
        "explicitSensitiveText": redact.redact_sensitive_text(arguments["text"], mode=arguments["mode"],
            **({"patterns": arguments["patterns"]} if "patterns" in arguments else {})),
        "toolText": redact.redact_tool_payload_text(arguments["text"]),
        "modelText": redact.redact_model_visible_tool_payload_text(arguments["text"]),
        "structuredTool": redact.redact_secrets(arguments["value"]),
        "structuredModel": redact.redact_model_visible_secrets(arguments["value"]),
        "transcript": redact_message_for_storage(arguments["message"], config),
        "policy": {"patterns": list(policy["patterns"]), "fullContext": policy["full_context"],
                   "registryRevision": policy["registry_revision"]}, **extra,
    }
    public = {"provider": "none", "result": result, "registry": {"before": before, "after": after}}
    return {"result": public, "raw": {"registry": public["registry"], "output": deepcopy(public)}}


def _model_helper(arguments: dict) -> dict:
    from memory_core import redact, secret_registry
    from memory_core.model_tool_result import (
        is_prepared_model_visible_tool_text, prepare_model_visible_tool_text_block,
        sanitize_tool_args, sanitize_tool_result,
    )
    from memory_core.session_transcript_append import redact_message_for_storage

    if arguments.get("kind") != "model-helper":
        raise ValueError("A fixed model-helper case is required")
    before = _ordinary_fresh_registry()
    config = redact.LoggingConfig(tuple(arguments["patterns"])) if "patterns" in arguments else None
    redact.configure_logging_redaction(config)
    for secret in arguments.get("registeredSecrets", []):
        secret_registry.register_secret_value_for_redaction(secret)
    snapshots = [before, _registry_snapshot()]
    result, identity, observations = {}, {}, {}
    if "value" in arguments:
        source = arguments["value"]
        prepared = sanitize_tool_result(source)
        result.update(sanitized=prepared, arguments=sanitize_tool_args(source))
        identity.update(sanitizedOutputReuse=sanitize_tool_result(prepared) is prepared,
                        originalInputReuse=sanitize_tool_result(source) is prepared)
        observations["sourceAfterCalls"] = deepcopy(source)
    if "block" in arguments:
        prepared = prepare_model_visible_tool_text_block(arguments["block"], config)
        result["prepared"] = prepared
        identity["preparedBlockReuse"] = prepare_model_visible_tool_text_block(prepared, config) is prepared
        observations["preparedBeforeMutation"] = deepcopy(prepared)
        for secret in arguments.get("laterRegisteredSecrets", []):
            secret_registry.register_secret_value_for_redaction(secret)
        snapshots.append(_registry_snapshot())
        if "replacePreparedText" in arguments:
            prepared["text"] = arguments["replacePreparedText"]
        message = {**arguments["message"], "content": [prepared]}
        persisted = redact_message_for_storage(message, config)
        result["stored"] = persisted
        identity["storageMessageReuse"] = persisted is message
        identity["storageBlockPrepared"] = is_prepared_model_visible_tool_text(
            persisted["content"][0], persisted["content"][0]["text"], config,
        )
        observations["messageAfterStorage"] = deepcopy(message)
    allowed = set(arguments.get("registeredSecrets", []) + arguments.get("laterRegisteredSecrets", []))
    if any(value not in allowed for snapshot in snapshots for value in snapshot["values"]):
        raise RuntimeError("The model-helper registry contains an undeclared value")
    public = {"provider": "none", "result": result, "identity": identity}
    return {"result": public, "raw": {"registrySnapshots": snapshots, "observations": observations,
                                        "output": deepcopy(public)}}


def _session_phase(request: dict) -> dict:
    from examples.session_tool_result import HostToolSession
    from memory_core import redact, secret_registry
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.turn_tool_dispatch import TurnTool
    from equivalence.session_contract import _catalog_sql

    before_registry = _ordinary_fresh_registry()
    value, phase, root = request["input"], request["phase"], Path(request["directory"])
    label = phase["label"]
    if not root.is_absolute() or label not in ("write", "continue", "verify"):
        raise ValueError("A session phase needs its exact owned identity and instructions")
    root.mkdir(parents=True, exist_ok=True)
    if label == "verify" and (set(value) != {"nowMs", "agentId", "sessionId", "sessionKey"} or set(phase) != {"label"}):
        raise ValueError("The verifier accepts identity only")
    if label != "verify":
        config = redact.LoggingConfig(tuple(value["patterns"]) if "patterns" in value else None)
        redact.configure_logging_redaction(config)
        for secret in value.get("registeredSecrets", []):
            secret_registry.register_secret_value_for_redaction(secret)
        host = HostToolSession(root, session_id=value["sessionId"], session_key=value["sessionKey"],
                              logging_config=config, now_ms=value["nowMs"])
        catalog = host.catalog
    else:
        if not (root / "session-catalog.sqlite").is_file():
            raise RuntimeError("The verifier requires the actual saved catalog")
        catalog = MemorySessionCatalog(root / "session-catalog.sqlite", clock_ms=lambda: value["nowMs"])
        entry = catalog.get_session_entry(value["sessionKey"])
        if entry is None or entry.get("sessionId") != value["sessionId"]:
            raise RuntimeError("The verifier could not reopen the saved session identity")
    raw = {"label": label, "request": deepcopy(request), "registrySnapshots": [before_registry],
           "beforeSql": _catalog_sql(catalog), "stages": [], "toolOutcomes": [], "executions": [], "messageAdmissions": [],
           "storePaths": {"databasePath": str(catalog.path), "catalogStorePath": str(catalog.store_path)}}
    provider_messages, persisted = [], []
    if label != "verify":
        raw["registrySnapshots"].append(_registry_snapshot())
        responses = phase["responses"]
        host.begin_turn(responses[0]["turnId"])
        if phase.get("directGuardMessage"):
            from memory_core.tool_result_persistence import settle_session_tool_result

            direct = settle_session_tool_result(catalog, value["sessionId"], deepcopy(phase["directGuardMessage"]),
                session_key=value["sessionKey"], now_ms=value["nowMs"], logging_config=config)
            host.live_messages = deepcopy(host.continuation()["context"]["messages"])
            persisted.append(direct.append_result["message"])
        user = {"role": "user", "content": [{"type": "text", "text": phase["prompt"]}], "timestamp": value["nowMs"]}
        persisted.append(host.append_message(user, now_ms=value["nowMs"]))
        raw["messageAdmissions"].append({"input": deepcopy(user), "stored": deepcopy(persisted[-1])})
        for response in responses:
            provider_messages.append(deepcopy(host.model_messages()))
            persisted.append(host.append_message(deepcopy(response), now_ms=value["nowMs"]))
            raw["messageAdmissions"].append({"input": deepcopy(response), "stored": deepcopy(persisted[-1])})
            for block in response["content"]:
                if block["type"] != "toolCall":
                    continue
                if "toolResult" not in phase:
                    raise ValueError("This phase has no declared tool execution fixture")
                executions = []

                def execute(call_id, arguments):
                    result = deepcopy(phase["toolResult"])
                    executions.append({"callId": call_id, "arguments": deepcopy(arguments), "result": deepcopy(result)})
                    return result

                def live_listener(_event):
                    if phase.get("lateRegisteredSecret"):
                        secret_registry.register_secret_value_for_redaction(phase["lateRegisteredSecret"])
                        raw["registrySnapshots"].append(_registry_snapshot())

                outcome = host.dispatch(TurnTool("lookup", execute), block, now_ms=value["nowMs"], on_event=live_listener)
                actual = {**executions[0], "telemetry": outcome["telemetry"]}
                raw["executions"].append(actual)
                raw["stages"].extend(outcome["stages"])
                raw["toolOutcomes"].extend(outcome["toolOutcomes"])
                persisted.append(outcome["appendResult"]["message"])
    raw["registrySnapshots"].append(_registry_snapshot())
    # Only literal fixture secrets can enter these fresh, credential-free hosts.
    allowed = set(value.get("registeredSecrets", []))
    if phase.get("lateRegisteredSecret"):
        allowed.add(phase["lateRegisteredSecret"])
    if 'pa"ss\\word+fixture' in allowed:
        allowed.update(['pa%22ss%5Cword%2Bfixture', 'pa\\"ss\\\\word+fixture'])
    if any(secret not in allowed for snapshot in raw["registrySnapshots"] for secret in snapshot["values"]):
        raise RuntimeError("The session phase registry contains an undeclared value")
    continuation = catalog.read_continuation(value["sessionId"], session_key=value["sessionKey"])
    transcript = catalog.read_transcript(value["sessionId"])
    result = {"phase": label, "providerMessages": provider_messages, "toolExecutions": raw["executions"],
              "persistedMessages": persisted, "storedMessages": [entry["message"] for entry in transcript.events if entry.get("type") == "message"],
              "modelContext": continuation["context"], "modelMessages": continuation["llmMessages"]}
    if label == "write" and "modeProbe" in phase:
        result["explicitOffDiagnostic"] = redact.redact_sensitive_text(phase["modeProbe"], mode="off")
    raw.update(continuation=continuation, afterSql=_catalog_sql(catalog), output=deepcopy(result))
    if label == "verify" and raw["beforeSql"] != raw["afterSql"]:
        raise RuntimeError("The identity-only verifier mutated the persisted catalog")
    return {"result": result, "raw": raw}


def _child(request: dict) -> dict:
    import memory_core

    if request["operation"] == "redaction-policy-source":
        value = _source_policy(request["input"])
    elif request["operation"] == "model-tool-result-runtime":
        value = _model_helper(request["input"])
    elif request["operation"] == "model-session-runtime":
        value = _session_phase(request)
    else:
        raise ValueError("An ordinary redaction operation is required")
    value["raw"].update(pid=os.getpid(), ppid=os.getppid(),
        implementationRoot=str(Path(memory_core.__file__).resolve().parents[1]), request=deepcopy(request))
    return value


def _spawn(request: dict, root: Path) -> tuple[dict, dict]:
    wire = json.dumps(request, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    record = {"request": deepcopy(request), "requestJson": wire,
              "requestSha256": hashlib.sha256(wire.encode("ascii")).hexdigest(), "startedAtNs": str(time.monotonic_ns())}
    process = subprocess.Popen([sys.executable, "-m", "equivalence.redaction_sdk", "--child"],
        cwd=ROOT, env=_environment(root), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = process.communicate(wire, timeout=100)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        record.update(pid=process.pid, stdout=stdout, stderr=stderr, exit={"code": process.returncode, "signal": None},
                      finishedAtNs=str(time.monotonic_ns()))
        raise RedactionChildError("The isolated SDK redaction process exceeded its deadline", record) from None
    record.update(pid=process.pid, stdout=stdout, stderr=stderr, exit={"code": process.returncode, "signal": None},
                  finishedAtNs=str(time.monotonic_ns()))
    if process.returncode:
        raise RedactionChildError("The isolated SDK redaction process failed", record)
    try:
        output = json.loads(stdout)
        if output["raw"]["pid"] != process.pid or output["raw"]["ppid"] != os.getpid():
            raise ValueError("Process ownership mismatch")
    except (ValueError, KeyError, TypeError):
        raise RedactionChildError("The SDK redaction output belongs to a different process", record) from None
    record["raw"] = output["raw"]
    return output["result"], record


def _evidence(directory: Path | None, raw: dict) -> None:
    if directory is not None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=True, indent=2) + "\n")


def _one(operation: str, arguments: dict, evidence_directory: Path | None) -> dict:
    raw = {"kind": operation, "coordinatorPid": os.getpid(), "children": []}
    with tempfile.TemporaryDirectory(prefix="python-redaction-") as temporary:
        root = Path(temporary)
        raw["fixtureBase"] = str(root)
        try:
            result, record = _spawn({"operation": operation, "input": deepcopy(arguments)}, root)
            raw["children"].append(record)
            return result
        except RedactionChildError as error:
            raw["children"].append(error.record)
            raise
        finally:
            _evidence(evidence_directory, raw)


def run_redaction_policy(arguments: dict, *, evidence_directory: Path | None = None) -> dict:
    return _one("redaction-policy-source", arguments, evidence_directory)


def run_model_tool_result(arguments: dict, *, evidence_directory: Path | None = None) -> dict:
    return _one("model-tool-result-runtime", arguments, evidence_directory)


def run_model_sessions(arguments: dict, *, evidence_directory: Path | None = None) -> dict:
    if arguments.get("kind") != "model-session" or [phase.get("label") for phase in arguments.get("phases", [])] != ["write", "continue", "verify"]:
        raise ValueError("The model session needs exactly three fresh ordered phases")
    raw = {"kind": "model-session", "coordinatorPid": os.getpid(), "input": deepcopy(arguments), "phases": []}
    common = {key: deepcopy(value) for key, value in arguments.items() if key not in ("kind", "phases")}
    outputs = []
    with tempfile.TemporaryDirectory(prefix="python-model-session-") as temporary:
        root = Path(temporary)
        raw["fixtureBase"] = str(root)
        try:
            for phase in arguments["phases"]:
                identity = ({key: common[key] for key in ("nowMs", "agentId", "sessionId", "sessionKey")}
                            if phase["label"] == "verify" else common)
                result, record = _spawn({"operation": "model-session-runtime", "input": identity,
                                        "phase": deepcopy(phase), "directory": str(root)}, root)
                raw["phases"].append(record)
                outputs.append(result)
        except RedactionChildError as error:
            raw["phases"].append(error.record)
            raise
        finally:
            _evidence(evidence_directory, raw)
    return {"provider": "none", "phases": outputs}


if __name__ == "__main__":
    try:
        json.dump(_child(json.load(sys.stdin)), sys.stdout, ensure_ascii=True, allow_nan=False)
        sys.stdout.write("\n")
    except Exception as error:
        json.dump({"fatal": {"type": type(error).__name__, "message": str(error)}, "pid": os.getpid()}, sys.stdout, ensure_ascii=True)
        sys.stdout.write("\n")
        raise
