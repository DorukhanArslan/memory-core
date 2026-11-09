"""Uncredited actual AgentSession/host settlement and process-reopen diagnostics.

The native side uses the real registered-tool AgentSession and guarded SQLite
writer. The SDK side invokes the real host example, dispatcher, settlement,
catalog and continuation reader. Literal assistant messages are provider input;
no model, paid provider, HTTP response replacement or expected-result recipe runs.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from equivalence.harness import _implementation_identity, _validate_reference
from equivalence.release_runtime import prepare_release_runtime


ROOT = Path(__file__).resolve().parents[1]


def cases() -> list[dict]:
    model = {"id": "test-model", "name": "Test Model", "api": "openai-responses", "provider": "test-provider",
             "baseUrl": "https://example.invalid", "reasoning": False, "input": ["text"],
             "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, "contextWindow": 200000, "maxTokens": 8192}

    def response(content, reason, turn):
        return {"role": "assistant", "content": content, "api": model["api"], "provider": model["provider"],
                "model": model["id"], "usage": {"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0,
                    "totalTokens": 2, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}},
                "stopReason": reason, "timestamp": 1000, "turnId": turn}

    seed = {"sessionId": "redaction-fixture", "sessionKey": "agent:main:dm:redaction-fixture", "nowMs": 1000,
            "systemPrompt": "Use lookup when asked.", "model": model,
            "writePrompt": "Run lookup.", "continuePrompt": "What did lookup return?",
            "writeResponses": [response([{"type": "toolCall", "id": "call-1", "name": "lookup", "arguments": {"query": "request"}}],
                "toolUse", "00000000-0000-7000-8000-000000000001"),
                response([{"type": "text", "text": "done"}], "stop", "00000000-0000-7000-8000-000000000001")],
            "continueResponses": [response([{"type": "text", "text": "remembered"}], "stop", "00000000-0000-7000-8000-000000000002")]}
    fixtures = [
        ("guarded-nonidempotent-order", {"content": [{"type": "text", "text": "foo"}], "details": {"token": "fixture-secret"}}, {"patterns": [r"foo|\*"]}),
        ("literal-uri-json-structured", {"content": [{"type": "text", "text": 'Authorization: Bearer fixture-secret-value https://fixture.invalid/?access_token=fixture-token'}],
         "details": {"credentials": {"apiKey": 7, "password": False}, "ordinary": "ok"}}, {}),
        ("registered-encoded-forms", {"content": [{"type": "text", "text": 'raw pa"ss\\word+fixture URI pa%22ss%5Cword%2Bfixture JSON pa\\"ss\\\\word+fixture'}],
         "details": {"note": 'pa"ss\\word+fixture'}}, {"registeredSecrets": ['pa"ss\\word+fixture'], "modeProbe": 'pa"ss\\word+fixture token=fixture-token'}),
        ("utf16-bound-and-persisted-details", {"content": [{"type": "text", "text": "😀" * 8190 + "CUST-1234567890" + " " * 16374}],
         "details": {"status": "complete", "log": " token=" + "z" * 40000, "sessions": [{"sessionId": f"session-{i}"} for i in range(12)]}},
         {"patterns": ["CUST-[0-9]+"]}),
        ("invalid-patterns-and-late-registration", {"content": [{"type": "text", "text": "CUST-1234567890 later-fixture-secret"}],
         "details": {"note": "later-fixture-secret"}}, {"patterns": ["[", "/x/qq", "(a+)+$", "CUST-[0-9]+"], "lateRegisteredSecret": "later-fixture-secret"}),
        ("image-record-and-url-canonicalization", {"content": [
            {"type": "image", "data": "iVBORw0KGgo=\n", "mimeType": "image/JPEG"},
            {"type": "image_url", "image_url": {"url": "DATA:image/jpeg;base64,iVBORw0KGgo=\n"}},
        ], "details": {"status": "complete"}}, {}),
        ("ordinary-prototype-key", {"content": [{"type": "text", "text": "complete"}], "details": {"__proto__": "literal", "password": "fixture-secret"}}, {}),
    ]
    output = []
    for name, result, extra in fixtures:
        value = deepcopy(seed)
        for key in ("patterns", "registeredSecrets", "lateRegisteredSecret", "modeProbe", "directGuardMessage"):
            value.pop(key, None)
        value.update(extra)
        value["toolResult"] = result
        output.append({"id": name, "covers": [], "input": value})
    return output


def sdk_phase(request: dict) -> dict:
    import memory_core
    from examples.session_tool_result import HostToolSession
    from memory_core import redact, secret_registry
    from memory_core.turn_tool_dispatch import TurnTool

    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("The session probe imported an SDK outside its worktree")
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)
    value, phase = request["input"], request["phase"]
    config = redact.LoggingConfig(tuple(value["patterns"]) if "patterns" in value else None)
    redact.configure_logging_redaction(config)
    for secret in value.get("registeredSecrets", []):
        secret_registry.register_secret_value_for_redaction(secret)
    host = HostToolSession(Path(request["directory"]), session_id=value["sessionId"], session_key=value["sessionKey"],
                          logging_config=config, now_ms=value["nowMs"])
    raw = {"pid": os.getpid(), "ppid": os.getppid(), "phase": phase, "request": request,
           "before": host.catalog.read_transcript(value["sessionId"]).events, "stages": [], "executions": []}
    provider_messages, persisted = [], []
    if phase != "verify":
        responses = value["writeResponses"] if phase == "write" else value["continueResponses"]
        host.begin_turn(responses[0]["turnId"])
        persisted.append(host.append_message({"role": "user", "content": [{"type": "text", "text": value["writePrompt"] if phase == "write" else value["continuePrompt"]}],
                                              "timestamp": value["nowMs"]}, now_ms=value["nowMs"]))
        for response in responses:
            provider_messages.append(deepcopy(host.model_messages()))
            persisted.append(host.append_message(deepcopy(response), now_ms=value["nowMs"]))
            for block in response["content"]:
                if block["type"] != "toolCall":
                    continue
                executions = []

                def execute(call_id, arguments):
                    result = deepcopy(value["toolResult"])
                    executions.append({"callId": call_id, "arguments": deepcopy(arguments), "result": deepcopy(result)})
                    return result

                def live_listener(_event):
                    if value.get("lateRegisteredSecret"):
                        secret_registry.register_secret_value_for_redaction(value["lateRegisteredSecret"])

                outcome = host.dispatch(TurnTool("lookup", execute), block, now_ms=value["nowMs"], on_event=live_listener)
                actual = {**executions[0], "telemetry": outcome["telemetry"]}
                raw["executions"].append(actual)
                raw["stages"].extend(outcome["stages"])
                persisted.append(outcome["appendResult"]["message"])
    continuation = host.continuation()
    raw["after"] = host.catalog.read_transcript(value["sessionId"]).events
    raw["continuation"] = continuation
    result = {"phase": phase, "providerMessages": provider_messages, "toolExecutions": raw["executions"],
              "persistedMessages": persisted,
              "storedMessages": [entry["message"] for entry in raw["after"] if entry.get("type") == "message"],
              "modelContext": continuation["context"], "modelMessages": continuation["llmMessages"]}
    if phase == "write" and "modeProbe" in value:
        result["explicitOffDiagnostic"] = redact.redact_sensitive_text(value["modeProbe"], mode="off")
    redact.configure_logging_redaction(None)
    secret_registry.reset_secret_redaction_registry()
    return {"result": result, "raw": raw}


def _owned_identity() -> dict:
    files = ("equivalence/trust-model-session-phase.mjs", "equivalence/trust_model_session_probe.py", "examples/session_tool_result.py")
    return {"sdk": _implementation_identity(), "adapters": {
        filename: hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() for filename in files}}


def run(checkout: Path, cache: Path, node: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    target = json.loads((ROOT / "equivalence/reference.json").read_text())
    reference = _validate_reference(checkout, node, target)
    runtime = prepare_release_runtime(checkout, cache)
    before = _owned_identity()
    observations = []
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}
    for case in cases():
        directory = output / case["id"]
        directory.mkdir()
        phases = []
        for phase in ("write", "continue", "verify"):
            results = {}
            for side in ("native", "sdk"):
                request = {"input": case["input"], "phase": phase, "directory": str(directory / side),
                           "runtimeRoot": runtime["runtimeRoot"]}
                request_path = directory / f"{side}-{phase}.input.json"
                request_path.write_text(json.dumps(request))
                if side == "native":
                    command = [str(node), str(ROOT / "equivalence/trust-model-session-phase.mjs"), str(request_path)]
                    child_env = env
                else:
                    command = [sys.executable, "-m", "equivalence.trust_model_session_probe", "--sdk-input", str(request_path)]
                    child_env = {**env, "PYTHONPATH": str(ROOT), "OPENCLAW_STATE_DIR": str(directory / "sdk-state"),
                                 "OPENCLAW_CONFIG_PATH": str(directory / "sdk-config.json"), "OPENCLAW_HOME": str(directory / "sdk-home")}
                with (directory / f"{side}-{phase}.stdout.json").open("w") as out, (directory / f"{side}-{phase}.stderr.log").open("w") as err:
                    completed = subprocess.run(command, cwd=ROOT, env=child_env, stdout=out, stderr=err, timeout=120)
                if completed.returncode:
                    raise RuntimeError(f"The retained {side} {phase} session process failed for {case['id']}")
                results[side] = json.loads((directory / f"{side}-{phase}.stdout.json").read_text())
            left, right = results["native"]["result"], results["sdk"]["result"]
            phases.append({"phase": phase, "equal": left == right, "differingFields": [
                key for key in left.keys() | right.keys() if left.get(key) != right.get(key)],
                "processesDistinct": results["native"]["raw"]["pid"] != results["sdk"]["raw"]["pid"]})
        observations.append({"id": case["id"], "covers": [], "phases": phases})
    after = _owned_identity()
    if before != after or runtime != prepare_release_runtime(checkout, cache) or reference != _validate_reference(checkout, node, target):
        raise RuntimeError("The original runtime, source or SDK changed during session diagnostics")
    report = {"profile": "actual-AgentSession-and-SDK-host-settlement", "covers": [], "awardedPoints": 0,
              "reference": reference, "runtime": runtime, "before": before, "after": after, "cases": observations,
              "identityDiagnostic": "Native original-input WeakMap reuse and SDK uncached raw dictionaries remain a separate visible mismatch; value matches do not establish identity parity."}
    (output / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-input", type=Path)
    for option in ("checkout", "runtime-cache", "node", "output"):
        parser.add_argument("--" + option, type=Path)
    args = parser.parse_args()
    if args.sdk_input:
        print(json.dumps(sdk_phase(json.loads(args.sdk_input.read_text()))))
        return
    report = run(args.checkout.resolve(), args.runtime_cache.resolve(), args.node.resolve(), args.output.resolve())
    phases = [phase for case in report["cases"] for phase in case["phases"]]
    print(json.dumps({"matchedPhases": sum(phase["equal"] for phase in phases), "totalPhases": len(phases), "awardedPoints": 0}))


if __name__ == "__main__":
    main()
