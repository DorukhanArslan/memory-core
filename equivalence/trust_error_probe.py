"""Uncredited, reproducible diagnostic for error redaction at real tool boundaries.

Run with explicit --checkout, --runtime-cache, --node and --output paths.
The existing official-artifact verifier runs before and after the whole batch.
No acceptance point is awarded: complete trust policies need broader callers.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import quote

from equivalence.release_runtime import prepare_release_runtime
from equivalence.search_contract import decode_search_tool_envelope


ROOT = Path(__file__).resolve().parents[1]


def _cases() -> list[dict]:
    credential = 'demo key"\\suffix!'
    encoded = quote(credential, safe="~()*!.'-")
    escaped = json.dumps(credential)[1:-1]
    return [
        {"id": "error-registered-surfaces", "covers": [], "input": {
            "registeredSecrets": [credential], "error": {
                "message": f"request {credential} serialized {escaped}",
                "cause": {"message": f"transport {encoded}", "code": "ECONNRESET"}}}},
        {"id": "error-configured-tool-boundaries", "covers": [], "input": {
            "registeredSecrets": ["demo-supplement-credential"],
            "patterns": ["([", "(a+)+b", "CUST-\\d+"],
            "error": {"message": "provider CUST-1234 demo-supplement-credential"}}},
        {"id": "error-default-patterns", "covers": [], "input": {
            "error": {"message": "provider token=abcdefghijklmnopqrstuvwxyz"}}},
        {"id": "error-contained-cause-diagnostic", "covers": [], "input": {
            "error": {"message": "request failed: transport failed",
                      "cause": {"message": "transport failed", "code": "ECONNRESET"}}}},
    ]


def _sdk(input_value: dict, directory: Path) -> dict:
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
        raise RuntimeError("Probe imported an SDK outside its owning worktree")
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)
    for secret in input_value.get("registeredSecrets", []):
        secret_registry.register_secret_value_for_redaction(secret)
    if "patterns" in input_value:
        redact.configure_logging_redaction(redact.LoggingConfig(tuple(input_value["patterns"])))

    def fixture_error(spec):
        if isinstance(spec, str):
            return spec
        error = MemoryToolError(spec["message"])
        if "code" in spec:
            error.code = spec["code"]
        if "cause" in spec:
            error.__cause__ = fixture_error(spec["cause"])
        return error

    error = fixture_error(input_value["error"])
    requests = []

    def failed(**options):
        requests.append(options)
        raise error

    try:
        directory.mkdir()
        config = MemoryConfig(workspace_dir=directory, flags=FeatureFlags(vector_search=False))
        store = SQLiteMemoryStore(config, None)
        supplement = RegisteredMemoryCorpusSupplement(
            "wiki-demo", StaticMemoryCorpusSupplement([]), reader=failed, searcher=failed,
        )
        get = create_memory_get_tool(config, supplements=[supplement])
        search = create_memory_search_tool(config, store, supplements=[supplement])
        if get is None or search is None:
            raise RuntimeError("The genuine SDK memory tool was unavailable")
        raw = {
            "get": get.execute("diagnostic-get", {"path": "topic", "corpus": "wiki"}),
            "search": search.execute("diagnostic-search", {"query": "topic", "corpus": "wiki"}),
        }
        return {"covers": [], "result": {
            "formatter": format_error_message(error),
            **{name: decode_search_tool_envelope(envelope) for name, envelope in raw.items()},
        }, "raw": {"envelopes": raw, "requests": requests}}
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
        env = {"PATH": str(args.node.resolve().parent) + os.pathsep + os.defpath,
               "LANG": "en_US.UTF-8", "TZ": "UTC"}
        completed = subprocess.run(
            [str(args.node.resolve()), str(ROOT / "equivalence/trust-error-runtime.mjs"), str(request_path)],
            capture_output=True, text=True, check=True, env=env, timeout=45, cwd=ROOT,
        )
        (directory / "native.stdout.json").write_text(completed.stdout)
        (directory / "native.stderr.log").write_text(completed.stderr)
        native = json.loads(completed.stdout)
        sdk = _sdk(case["input"], directory / "sdk-fixture")
        (directory / "sdk.json").write_text(json.dumps(sdk, ensure_ascii=True))
        observations.append({"id": case["id"], "covers": [],
                             "matches": native["result"] == sdk["result"],
                             "native": native["result"], "sdk": sdk["result"]})
    after = prepare_release_runtime(args.checkout.resolve(), args.runtime_cache.resolve())
    (output / "authentication-after.json").write_text(json.dumps(after))
    if after != authenticated:
        raise RuntimeError("Authenticated release changed during diagnostic batch")
    report = {"covers": [], "acceptancePointsAwarded": 0, "observations": observations}
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True))
    print(json.dumps({"matches": sum(row["matches"] for row in observations),
                      "cases": len(observations), "acceptancePointsAwarded": 0}))


if __name__ == "__main__":
    main()
