"""Uncredited original whole-result/storage diagnostics with actual carrier observations."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from equivalence.release_runtime import prepare_release_runtime


ROOT = Path(__file__).resolve().parents[1]


def _cases() -> list[dict]:
    return [
        {"id": "complete-tool-result", "input": {"value": {
            "content": [{"type": "text", "text": "Authorization: Bearer fixture-secret-value"},
                        {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"}],
            "details": {"token": "fixture-secret", "nested": {"apiKey": 7}}, "extra": [None, False]}}},
        {"id": "utf16-redaction-truncation-order", "input": {"value": {"content": [
            {"type": "text", "text": "a" * 7999 + "😀 token=abcdefghijklmnopqrstuvwxyz"}]}}},
        {"id": "prepared-nonidempotent-storage", "input": {
            "patterns": [r"foo|\*"], "block": {"type": "text", "text": "foo"},
            "message": {"role": "toolResult", "toolCallId": "call-1", "toolName": "demo", "timestamp": 1}}},
        {"id": "prepared-cloned-block-storage", "input": {
            "patterns": [r"foo|\*"], "block": {"type": "text", "text": "foo", "note": "foo"},
            "message": {"role": "toolResult", "toolCallId": "call-2", "timestamp": 1}}},
        {"id": "prepared-registry-invalidation-storage", "input": {
            "block": {"type": "text", "text": "later-credential"}, "laterRegisteredSecrets": ["later-credential"],
            "message": {"role": "toolResult", "toolCallId": "call-3", "timestamp": 1}}},
        {"id": "prepared-text-mutation-storage", "input": {
            "patterns": [r"foo|\*"], "block": {"type": "text", "text": "foo"}, "replacePreparedText": "foo",
            "message": {"role": "toolResult", "toolCallId": "call-4", "timestamp": 1}}},
    ]


def _sdk(input_value: dict) -> dict:
    import memory_core
    from memory_core import redact, secret_registry
    from memory_core.model_tool_result import (
        is_prepared_model_visible_tool_text, prepare_model_visible_tool_text_block,
        sanitize_tool_args, sanitize_tool_result,
    )
    from memory_core.session_transcript_append import redact_message_for_storage

    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("Probe imported an SDK outside its worktree")
    secret_registry.reset_secret_redaction_registry()
    config = redact.LoggingConfig(tuple(input_value["patterns"])) if "patterns" in input_value else None
    redact.configure_logging_redaction(config)
    try:
        for secret in input_value.get("registeredSecrets", []):
            secret_registry.register_secret_value_for_redaction(secret)
        result, identity = {}, {}
        if "value" in input_value:
            source = input_value["value"]
            prepared = sanitize_tool_result(source)
            result.update(sanitized=prepared, arguments=sanitize_tool_args(source))
            identity.update(sanitizedOutputReuse=sanitize_tool_result(prepared) is prepared,
                            originalInputReuse=sanitize_tool_result(source) is prepared)
        if "block" in input_value:
            prepared = prepare_model_visible_tool_text_block(input_value["block"], config)
            result["prepared"] = prepared
            identity["preparedBlockReuse"] = prepare_model_visible_tool_text_block(prepared, config) is prepared
            for secret in input_value.get("laterRegisteredSecrets", []):
                secret_registry.register_secret_value_for_redaction(secret)
            if "replacePreparedText" in input_value:
                prepared["text"] = input_value["replacePreparedText"]
            message = {**input_value["message"], "content": [prepared]}
            persisted = redact_message_for_storage(message, config)
            result["stored"] = persisted
            identity["storageMessageReuse"] = persisted is message
            identity["storageBlockPrepared"] = is_prepared_model_visible_tool_text(
                persisted["content"][0], persisted["content"][0]["text"], config,
            )
        return {"covers": [], "result": result, "identity": identity}
    finally:
        redact.configure_logging_redaction(None)
        secret_registry.reset_secret_redaction_registry()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("checkout", "runtime-cache", "node", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    authenticated = prepare_release_runtime(args.checkout.resolve(), args.runtime_cache.resolve())
    (output / "authentication-before.json").write_text(json.dumps(authenticated))
    observations = []
    for case in _cases():
        directory = output / case["id"]
        directory.mkdir()
        request = {"input": case["input"], "runtimeRoot": authenticated["runtimeRoot"],
                   "fixtureDirectory": str(directory / "native-fixture")}
        request_path = directory / "input.json"
        request_path.write_text(json.dumps(request))
        completed = subprocess.run(
            [str(args.node.resolve()), str(ROOT / "equivalence/trust-model-runtime.mjs"), str(request_path)],
            capture_output=True, text=True, check=True, timeout=45, cwd=ROOT,
            env={"PATH": str(args.node.resolve().parent) + os.pathsep + os.defpath, "LANG": "en_US.UTF-8", "TZ": "UTC"},
        )
        (directory / "native.stdout.json").write_text(completed.stdout)
        (directory / "native.stderr.log").write_text(completed.stderr)
        native, sdk = json.loads(completed.stdout), _sdk(case["input"])
        (directory / "sdk.json").write_text(json.dumps(sdk, ensure_ascii=True))
        observations.append({"id": case["id"], "covers": [],
                             "valueMatches": native["result"] == sdk["result"],
                             "identityMatches": native["identity"] == sdk["identity"],
                             "native": native, "sdk": sdk})
    after = prepare_release_runtime(args.checkout.resolve(), args.runtime_cache.resolve())
    (output / "authentication-after.json").write_text(json.dumps(after))
    if after != authenticated:
        raise RuntimeError("Authenticated release changed during the diagnostic batch")
    report = {"covers": [], "acceptancePointsAwarded": 0, "observations": observations}
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True))
    print(json.dumps({"valueMatches": sum(row["valueMatches"] for row in observations),
                      "identityMatches": sum(row["identityMatches"] for row in observations),
                      "cases": len(observations), "acceptancePointsAwarded": 0}))


if __name__ == "__main__":
    main()
