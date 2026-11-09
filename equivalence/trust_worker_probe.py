"""Uncredited causal-cut comparison of original source-worker redaction acceptance.

Original worker inputs, replies, transcript state and complete source projections
remain in the report. Physical source statistics are reported separately from
the targeted redaction result; this diagnostic awards no acceptance points.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from equivalence.get_contract import map_get_fixture_paths
from equivalence.release_runtime import prepare_release_runtime
from equivalence.trust_worker_runtime_bindings import prepare_trust_worker_runtime_bindings


ROOT = Path(__file__).resolve().parents[1]
SDK_FILES = ("memory_core/session_corpus.py", "memory_core/session_entry.py",
             "memory_core/session_catalog.py", "memory_core/redact.py", "memory_core/secret_registry.py")
ADAPTER_FILES = ("equivalence/trust-worker-runtime.mjs", "equivalence/trust_worker_probe.py",
                 "equivalence/trust_worker_runtime_bindings.py")
DECLARED_SECRETS = frozenset({"worker-fixture-credential", "unrelated-worker-credential-2"})


def _assert_synthetic_registry(values) -> None:
    if not isinstance(values, (list, tuple)) or any(not isinstance(value, str) or value not in DECLARED_SECRETS for value in values):
        raise ValueError("Undeclared registry member; sensitive snapshot was not recorded")


def _cases() -> list[dict]:
    return [{"id": identifier, "covers": [], "input": {
        "secret": "worker-fixture-credential", "sessionKind": "interactive", **options,
    }} for identifier, options in [
        ("registry-stable", {"mutations": 0}),
        ("registry-changed-once", {"mutations": 1}),
        ("registry-changed-twice", {"mutations": 2}),
        ("registry-duplicate-membership", {"mutations": 1, "initiallyRegistered": True}),
        ("observer-live-policy", {"mutations": 1, "observer": True}),
    ]]


def _sdk(input_value: dict, directory: Path) -> dict:
    if input_value.get("secret") != "worker-fixture-credential":
        raise ValueError("Only declared synthetic worker credentials are admitted")
    directory.mkdir()
    (directory / "openclaw.json").write_text(json.dumps({"logging": {}}))
    import memory_core
    from memory_core import redact, secret_registry
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_corpus import MemoryCoreSessionCorpus
    from memory_core.session_entry import build_session_entry

    if not Path(memory_core.__file__).resolve().is_relative_to(ROOT):
        raise RuntimeError("Worker diagnostic imported an SDK outside its owning worktree")
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)
    _assert_synthetic_registry(secret_registry.capture_secret_redaction_registry_snapshot().values)
    key, session_id = "agent:main:dm:worker-fixture", "worker-fixture"
    source_path = directory / "state/agents/main/sessions/worker-fixture.jsonl"
    catalog = MemorySessionCatalog(directory / "catalog.sqlite", store_path=source_path.with_name("sessions.json"),
                                   clock_ms=lambda: 1000)
    catalog.upsert_session(key, {"sessionId": session_id, "updatedAt": 1000, "sessionFile": str(source_path)})
    catalog.append_message(session_id, {"role": "user", "content": f"Remember {input_value['secret']}", "timestamp": 1000},
                           session_key=key, event_id="user-1", now_ms=1000, cwd="/fixture/work")
    corpus = MemoryCoreSessionCorpus(directory, catalog=catalog)
    file = corpus.discover_files()[0]
    before = asdict(catalog.read_transcript(session_id))
    if input_value.get("initiallyRegistered"):
        secret_registry.register_secret_value_for_redaction(input_value["secret"])
    preparations, mutations, callbacks = [], [], []

    def mutate(ordinal, cut):
        if ordinal <= input_value["mutations"]:
            value = input_value["secret"] if ordinal == 1 else f"unrelated-worker-credential-{ordinal}"
            before_revision = secret_registry.get_secret_redaction_registry_revision()
            secret_registry.register_secret_value_for_redaction(value)
            mutations.append({"ordinal": ordinal, "value": value, "before": before_revision,
                              "after": secret_registry.get_secret_redaction_registry_revision(), "cut": cut})

    def observer(message, observed_at):
        ordinal = len(callbacks) + 1
        callbacks.append({"ordinal": ordinal, "message": message, "observedAt": observed_at})
        mutate(ordinal, "transcript-callback")

    def profile(frame, event, value):
        if event == "return" and frame.f_code is build_session_entry.__code__:
            ordinal = len(preparations) + 1
            captured = frame.f_back.f_locals.get("redaction")
            if captured is not None:
                _assert_synthetic_registry(captured.registered_secret_values)
            preparations.append({"ordinal": ordinal, "actualPreparedEntry": asdict(value),
                                 "actualRegistrySnapshot": asdict(captured) if captured is not None else None})
            if not input_value.get("observer"):
                mutate(ordinal, "actual-preparation-return")

    previous = sys.getprofile()
    result = error = None
    try:
        sys.setprofile(profile)
        result = corpus.read_source_entry(file, on_transcript_message=observer if input_value.get("observer") else None)
    except Exception as exc:
        error = {"name": getattr(exc, "name", type(exc).__name__), "message": str(exc)}
    finally:
        sys.setprofile(previous)
    return {"file": asdict(file), "before": before, "after": asdict(catalog.read_transcript(session_id)),
            "preparations": preparations, "mutations": mutations, "callbackObservations": callbacks,
            "result": result, "error": error, "attempts": len(preparations)}


def _validate_native(value: dict, input_value: dict, runtime_root: str) -> None:
    expected = (Path(runtime_root) / "dist/config/sessions/session-transcript.worker.js").as_uri()
    if value["expected"] != expected or value["before"] != value["after"]:
        raise ValueError("Original worker proof changed its source or worker identity")
    if value.get("clock") != {"owner": "node:test", "apis": ["Date"], "nowMs": 1000,
                             "dateConstructorReplaced": True, "setTimeoutUnchanged": True}:
        raise ValueError("Native producers require their actual common Date-only fixture clock")
    source = value.get("source")
    if (not isinstance(source, dict) or source not in value.get("enumerated", [])
            or value["filename"] != source.get("sessionFile")
            or source.get("sessionId") != value["scope"]["sessionId"]
            or source.get("sessionKey") != value["scope"]["sessionKey"]):
        raise ValueError("Source identity must come from genuine original corpus enumeration")
    dispatched = [item for item in value["observations"] if item["event"] == "preparation-dispatch"]
    replies = [item for item in value["observations"] if item["event"] == "actual-preparation-reply"]
    if value["attempts"] != len(dispatched) or len(replies) != len(dispatched):
        raise ValueError("Actual worker dispatches and replies must remain paired")
    if len(dispatched) > 2:
        raise ValueError("The original snapshot owner permits at most two preparations")
    created = {(item["url"], item["threadId"]) for item in value["observations"] if item["event"] == "worker-created"}
    previous_revision = None
    accepted_entry = None
    for dispatch, reply in zip(dispatched, replies, strict=True):
        message, response = dispatch["message"], reply["reply"]
        if (dispatch["url"] != expected or reply["url"] != expected
                or dispatch["threadId"] != reply["threadId"] or dispatch["ordinal"] != reply["ordinal"]
                or message["input"]["kind"] != "session-entry" or message["taskId"] != response["taskId"]
                or response["status"] != "ok" or response["value"].get("ok") is not True
                or not isinstance(message["input"]["redaction"]["registryRevision"], int)
                or (dispatch["url"], dispatch["threadId"]) not in created
                or message["input"]["absPath"] != value["filename"]
                or any(message["input"]["options"].get(key) != item for key, item in value["scope"].items())):
            raise ValueError("An original source-worker request or actual successful reply is not authenticated")
        revision = message["input"]["redaction"]["registryRevision"]
        _assert_synthetic_registry(message["input"]["redaction"]["registeredSecretValues"])
        if previous_revision is not None and revision != previous_revision:
            raise ValueError("A retry must capture the actual current registry revision")
        mutations = [item for item in value["mutations"] if item["ordinal"] == dispatch["ordinal"]]
        if len(mutations) > 1:
            raise ValueError("Only one genuine registry action is admitted at each actual reply")
        current_revision = revision
        if mutations:
            mutation = mutations[0]
            if (mutation["before"] != revision or mutation["after"] not in (revision, revision + 1)
                    or mutation.get("cut") is not None):
                raise ValueError("Reply mutations must retain their actual original registry transitions")
            current_revision = mutation["after"]
        previous_revision = current_revision
        accepted_entry = response["value"]["value"]["entry"] if revision == current_revision else None
        if accepted_entry is not None and dispatch is not dispatched[-1]:
            raise ValueError("The untouched original parent must accept a stable preparation")
    if input_value.get("observer") and dispatched:
        raise ValueError("Observers must retain the original live in-process source path")
    if not input_value.get("observer"):
        expected_error = {"name": "Error", "message": "Session transcript redaction changed during preparation; retry the operation."}
        if accepted_entry is None:
            if len(dispatched) != 2 or value.get("error") != expected_error or "result" in value:
                raise ValueError("Only the original bounded retry diagnostic can finish two stale preparations")
        elif value.get("error") is not None or value.get("result") != accepted_entry:
            raise ValueError("The complete accepted source must equal the actual stable worker reply")


def run(checkout: Path, runtime_cache: Path, node: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    sdk_before = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (*SDK_FILES, *ADAPTER_FILES)}
    runtime = prepare_release_runtime(checkout, runtime_cache)
    bindings = prepare_trust_worker_runtime_bindings(checkout, Path(runtime["runtimeRoot"]))
    (output / "authentication-before.json").write_text(json.dumps({"runtime": runtime, "bindings": bindings, "sdk": sdk_before}))
    observations = []
    for case in _cases():
        directory = output / case["id"]
        directory.mkdir()
        request = {"input": case["input"], "runtimeRoot": runtime["runtimeRoot"], "fixtureDirectory": str(directory / "native-fixture")}
        request_path = directory / "input.json"
        request_path.write_text(json.dumps(request))
        completed = subprocess.run([str(node), str(ROOT / "equivalence/trust-worker-runtime.mjs"), str(request_path)],
                                   capture_output=True, text=True, timeout=60, cwd=ROOT,
                                   env={"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "en_US.UTF-8", "TZ": "UTC"})
        (directory / "native.stdout.json").write_text(completed.stdout)
        (directory / "native.stderr.log").write_text(completed.stderr)
        completed.check_returncode()
        native = json.loads(completed.stdout)
        _validate_native(native, case["input"], runtime["runtimeRoot"])
        sdk_directory = directory / "sdk-fixture"
        sdk_request = directory / "sdk-input.json"
        sdk_request.write_text(json.dumps({"input": case["input"], "fixtureDirectory": str(sdk_directory)}))
        sdk_process = subprocess.run(
            [sys.executable, "-m", "equivalence.trust_worker_probe", "--sdk-case", str(sdk_request)],
            capture_output=True, text=True, timeout=60, cwd=ROOT,
            env={"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                 "PYTHONPATH": str(ROOT), "LANG": "en_US.UTF-8", "TZ": "UTC",
                 "OPENCLAW_STATE_DIR": str(sdk_directory / "state"),
                 "OPENCLAW_CONFIG_PATH": str(sdk_directory / "openclaw.json"),
                 "OPENCLAW_HOME": str(sdk_directory)},
        )
        (directory / "sdk.stdout.json").write_text(sdk_process.stdout)
        (directory / "sdk.stderr.log").write_text(sdk_process.stderr)
        sdk_process.check_returncode()
        sdk = json.loads(sdk_process.stdout)
        (directory / "sdk.json").write_text(json.dumps(sdk, default=str))
        fields = ("content", "hash", "lineMap", "messageTimestampsMs", "lineProvenance", "sessionKind")
        native_body = {name: native.get("result", {}).get(name) for name in fields}
        sdk_body = {name: (sdk["result"] or {}).get(name) for name in fields}
        attempts_match = True if case["input"].get("observer") else native["attempts"] == sdk["attempts"]
        observations.append({"id": case["id"], "covers": [],
                             "redactionAcceptanceMatches": native_body == sdk_body and native.get("error") == sdk["error"] and attempts_match,
                             "completeProjectionMatches": map_get_fixture_paths(native.get("result"), directory / "native-fixture")
                                 == map_get_fixture_paths(sdk["result"], directory / "sdk-fixture"),
                             "native": native, "sdk": sdk})
    after = prepare_release_runtime(checkout, runtime_cache)
    after_bindings = prepare_trust_worker_runtime_bindings(checkout, Path(after["runtimeRoot"]))
    sdk_after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (*SDK_FILES, *ADAPTER_FILES)}
    (output / "authentication-after.json").write_text(json.dumps({"runtime": after, "bindings": after_bindings, "sdk": sdk_after}))
    if (runtime, bindings, sdk_before) != (after, after_bindings, sdk_after):
        raise RuntimeError("An authenticated owner changed during the worker diagnostic")
    report = {"covers": [], "acceptancePointsAwarded": 0, "observations": observations}
    (output / "report.json").write_text(json.dumps(report, default=str, indent=2))
    return report


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--sdk-case":
        request = json.loads(Path(sys.argv[2]).read_text())
        json.dump(_sdk(request["input"], Path(request["fixtureDirectory"])), sys.stdout, default=str)
        sys.stdout.write("\n")
        raise SystemExit(0)
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("checkout", "runtime-cache", "node", "output"):
        parser.add_argument("--" + argument, type=Path, required=True)
    options = parser.parse_args()
    report = run(options.checkout.resolve(), options.runtime_cache.resolve(), options.node.resolve(), options.output.resolve())
    print(json.dumps({"redactionAcceptanceMatches": sum(row["redactionAcceptanceMatches"] for row in report["observations"]),
                      "completeProjectionMatches": sum(row["completeProjectionMatches"] for row in report["observations"]),
                      "cases": len(report["observations"]), "acceptancePointsAwarded": 0}))
