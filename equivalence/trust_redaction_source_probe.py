"""Uncredited, authenticated same-graph source redaction-policy comparisons.

The source-only graph is explicit: original private policy marks, text owners,
whole JSON walkers and transcript owner all execute unchanged TypeScript.
Valid native JS regex syntax unsupported by Python remains an ordinary diff.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from equivalence.dependencies import prepare_dependencies, validate_dependency_sources
from equivalence.harness import _committed_digest, _implementation_identity, _validate_reference


ROOT = Path(__file__).resolve().parents[1]
PROFILE = "explicit-all-source-redaction-policy"


def cases() -> list[dict]:
    text = " " * 16380 + "CUST-1234567890" + " " * 20000
    result = []

    def add(name, text, *, patterns=None, full_context=False, mode="tools", secrets=(), value=None):
        result.append({"id": name, "covers": [], "input": {
            "text": text, "fullContext": full_context, "mode": mode,
            **({"patterns": patterns} if patterns is not None else {}),
            "registeredSecrets": list(secrets),
            "value": value if value is not None else {"ordinary": text, "token": "fixture-value", "count": 7},
            "message": {"role": "toolResult", "toolCallId": "fixture-call", "toolName": "lookup",
                        "content": [{"type": "text", "text": text}], "details": {"token": "fixture-value"},
                        "timestamp": 1000},
        }})

    add("bounded-over-32768-cross-16384", text, patterns=["CUST-[0-9]+"])
    add("host-full-context-cross-16384", text, patterns=["CUST-[0-9]+"], full_context=True, mode="off")
    add("exact-32768-utf16", "😀" * 8190 + "CUST-1234567890" + " " * 16373, patterns=["CUST-[0-9]+"])
    add("over-32768-utf16", "😀" * 8190 + "CUST-1234567890" + " " * 16374, patterns=["CUST-[0-9]+"])
    add("default-literal-url-structured", 'Authorization: Bearer fixture-secret-value https://fixture.invalid/?access_token=fixture-token',
        value={"credentials": {"apiKey": 7, "password": False}, "authorization": "Bearer fixture-secret-value", "public": "ok"})
    add("registered-uri-json-off", 'raw pa"ss\\word+fixture URI pa%22ss%5Cword%2Bfixture JSON pa\\"ss\\\\word+fixture',
        secrets=['pa"ss\\word+fixture'], mode="off")
    add("mode-off-disables-patterns-only", "CUST-1234567890 registered-fixture", patterns=["CUST-[0-9]+"],
        mode="off", secrets=["registered-fixture"])
    add("configured-replaces-sensitive-merges-tool", "CUST-1234567890 token=fixture-token", patterns=["CUST-[0-9]+"])
    add("invalid-and-unsafe-rules-skip", "CUST-1234567890 abcdef token=fixture-token", patterns=["[", "/x/qq", "(a+)+$", "CUST-[0-9]+"])
    add("flags-capture-lookbehind", "PREFIX CUST-1234567890\nref: AB12\nref: cd34", patterns=["/(CUST-)([0-9]+)/gi", "/(?<=ref: )[a-z0-9]+/gim"])
    add("sticky-dotall-lookahead", "BEGIN\nsecret END SECRET", patterns=["/BEGIN.*?END/gs", "/SECRET(?=$)/y"])
    add("non-idempotent-stages", "foo ***", patterns=[r"foo|\*"])
    # These are supported by the real JS engine. They must stay visible even
    # when the Python regex implementation cannot compile their semantics.
    add("valid-js-unicode-property", "AAA ééé token=fixture-token", patterns=[r"/\p{L}+/gu"])
    add("valid-js-v-set-intersection", "ABC abc 123", patterns=[r"/[\p{ASCII}&&\p{Letter}]+/gv"])
    add("inline-image-whitespace-wrong-mime", "image result", value={"ordinary": "image result"})
    result[-1]["input"]["message"]["content"].extend([
        {"type": "image", "data": "iVBORw0KGgo=\n", "mimeType": "image/JPEG"},
        {"type": "base64", "data": "iVBORw0KGgo=\n", "mediaType": " image/GIF ", "media_type": "image/jpeg"},
        {"type": "image_url", "image_url": {"url": "DATA:image/jpeg;base64,iVBORw0KGgo=\n"}},
    ])
    for count in (8, 9, 22):
        add(f"unicode-literal-hint-{count}-astral", "prefix:" + "𐐀" * count,
            patterns=["/(prefix:)(𐐀+)/gu"])
    add("unicode-literal-odd-hint-boundaries", "prefix:a" + "𐐀" * 8 + "b", patterns=["/(prefix:)(a𐐀+b)/gu"])
    add("unicode-literal-lone-surrogate", "prefix:" + "\ud800" * 22, patterns=[r"/(prefix:)(\ud800+)/gu"])
    add("nonunicode-literal-astral-hint", "prefix:" + "𐐀" * 22, patterns=["/(prefix:)((?:𐐀)+)/g"])
    return result


def sdk(request: dict) -> dict:
    import memory_core
    from memory_core import redact, secret_registry
    from memory_core.model_tool_result import capture_model_visible_redaction_policy
    from memory_core.session_transcript_append import redact_message_for_storage

    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("The source probe imported an SDK outside its worktree")
    redact.configure_logging_redaction(None)
    output = []
    for case in request["cases"]:
        secret_registry.reset_secret_redaction_registry()
        value = case["input"]
        config = redact.LoggingConfig(tuple(value["patterns"]) if "patterns" in value else None)
        if value["fullContext"]:
            config = redact.mark_full_context_tool_payload_redaction(config)
        redact.configure_logging_redaction(config)
        for secret in value["registeredSecrets"]:
            secret_registry.register_secret_value_for_redaction(secret)
        try:
            policy = asdict(capture_model_visible_redaction_policy(config))
            output.append({"id": case["id"], "covers": [], "ok": True, "result": {
                "explicitSensitiveText": redact.redact_sensitive_text(value["text"], mode=value["mode"],
                    **({"patterns": value["patterns"]} if "patterns" in value else {})),
                "toolText": redact.redact_tool_payload_text(value["text"]),
                "modelText": redact.redact_model_visible_tool_payload_text(value["text"]),
                "structuredTool": redact.redact_secrets(value["value"]),
                "structuredModel": redact.redact_model_visible_secrets(value["value"]),
                "transcript": redact_message_for_storage(value["message"], config),
                "policy": {"patterns": list(policy["patterns"]), "fullContext": policy["full_context"],
                           "registryRevision": policy["registry_revision"]},
            }})
        except Exception as error:
            output.append({"id": case["id"], "covers": [], "ok": False,
                           "error": {"name": type(error).__name__, "message": str(error)}})
    redact.configure_logging_redaction(None)
    secret_registry.reset_secret_redaction_registry()
    return {"profile": PROFILE, "results": output}


def authenticate_capture(checkout: Path, dependencies: dict, value: dict) -> None:
    if (value.get("profile") != PROFILE or value.get("sourceFallback") is not False
            or value.get("compiledOpenClawModulesAllowed") is not False):
        raise ValueError("The explicit source policy authority is missing")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Original source evidence is missing")
    seen = set()
    for source in sources:
        relative = source.get("path")
        if (not isinstance(relative, str) or relative in seen or Path(relative).is_absolute()
                or ".." in Path(relative).parts or "dist" in Path(relative).parts):
            raise ValueError("Unexpected source graph member")
        seen.add(relative)
        actual = hashlib.sha256((checkout / relative).read_bytes()).hexdigest()
        if source.get("sha256") != actual or actual != _committed_digest(checkout, relative):
            raise ValueError("The source graph differs from its pinned Git object")
    required = {"src/logging/redact.ts", "src/logging/redact-internal-state.ts", "src/logging/logger.ts",
                "src/logging/secret-redaction-registry.ts", "src/agents/transcript-redact.ts", "tsconfig.json"}
    if not required.issubset(seen):
        raise ValueError("The required same-identity policy owners were not executed")
    validate_dependency_sources(dependencies, value.get("dependencySources"))


def run(checkout: Path, cache: Path, node: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    target = json.loads((ROOT / "equivalence/reference.json").read_text())
    adapters = ("equivalence/trust-redaction-source.mjs", "equivalence/trust_redaction_source_probe.py")
    def node_identity():
        versions = json.loads(subprocess.run([str(node), "--eval", "process.stdout.write(JSON.stringify({nodeVersion:process.version,icuVersion:process.versions.icu,unicodeVersion:process.versions.unicode}))"],
            check=True, capture_output=True, text=True, timeout=10).stdout)
        return {"execPath": str(node.resolve()), "sha256": hashlib.sha256(node.read_bytes()).hexdigest(), **versions}

    before = {"reference": _validate_reference(checkout, node, target), "sdk": _implementation_identity(), "node": node_identity(),
              "adapters": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in adapters}}
    dependencies = prepare_dependencies(checkout, cache)
    request = {"checkout": str(checkout), "fixtureDirectory": str(output / "native-fixture"),
               "dependencies": dependencies, "cases": cases()}
    request_path = output / "input.json"
    request_path.write_text(json.dumps(request))
    # Every child starts with an empty provider/config environment. Registry
    # reset precedes registration, and all registrations are literal fixtures.
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}
    with (output / "native.stdout.json").open("w") as out, (output / "native.stderr.log").open("w") as err:
        native_process = subprocess.run([str(node), "--experimental-transform-types", str(ROOT / "equivalence/trust-redaction-source.mjs"), str(request_path)],
            cwd=ROOT, env=env, stdout=out, stderr=err, timeout=120)
    if native_process.returncode:
        raise RuntimeError("The same-graph native source policy process failed; retained stderr is available")
    sdk_env = {**env, "PYTHONPATH": str(ROOT), "OPENCLAW_STATE_DIR": str(output / "sdk-state"),
               "OPENCLAW_CONFIG_PATH": str(output / "sdk-config.json"), "OPENCLAW_HOME": str(output / "sdk-home")}
    with (output / "sdk.stdout.json").open("w") as out, (output / "sdk.stderr.log").open("w") as err:
        sdk_process = subprocess.run([sys.executable, "-m", "equivalence.trust_redaction_source_probe", "--sdk-input", str(request_path)],
            cwd=ROOT, env=sdk_env, stdout=out, stderr=err, timeout=120)
    if sdk_process.returncode:
        raise RuntimeError("The SDK policy process failed; retained stderr is available")
    native = json.loads((output / "native.stdout.json").read_text())
    python = json.loads((output / "sdk.stdout.json").read_text())
    authenticate_capture(checkout, dependencies, native)
    if native.get("runtime") != before["node"]:
        raise RuntimeError("The native source process used a different executable or Unicode runtime")
    after = {"reference": _validate_reference(checkout, node, target), "sdk": _implementation_identity(), "node": node_identity(),
             "adapters": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in adapters}}
    if before != after or dependencies != prepare_dependencies(checkout, cache):
        raise RuntimeError("The compared source/dependency/SDK bytes changed during execution")
    observations = []
    for case, left, right in zip(request["cases"], native["results"], python["results"], strict=True):
        if left["id"] != case["id"] or right["id"] != case["id"] or left["covers"] or right["covers"]:
            raise ValueError("Case transport changed the fixed uncredited inputs")
        observations.append({"id": case["id"], "covers": [], "equal": left == right,
                             "differingFields": [key for key in set(left.get("result", {})) | set(right.get("result", {}))
                                                 if left.get("result", {}).get(key) != right.get("result", {}).get(key)]})
    report = {"profile": PROFILE, "covers": [], "awardedPoints": 0, "before": before, "after": after,
              "sourceFiles": len(native["sources"]), "dependencyFiles": len(native["dependencySources"]),
              "cases": observations}
    (output / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-input", type=Path)
    for option in ("checkout", "cache", "node", "output"):
        parser.add_argument("--" + option, type=Path)
    args = parser.parse_args()
    if args.sdk_input:
        print(json.dumps(sdk(json.loads(args.sdk_input.read_text()))))
        return
    report = run(args.checkout.resolve(), args.cache.resolve(), args.node.resolve(), args.output.resolve())
    print(json.dumps({"profile": PROFILE, "matched": sum(case["equal"] for case in report["cases"]),
                      "total": len(report["cases"]), "awardedPoints": 0}))


if __name__ == "__main__":
    main()
