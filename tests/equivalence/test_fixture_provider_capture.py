"""Real preload capture guards using labelled artifacts, never parity evidence.

The native plugin loader copies its provider fixture into an owned immutable
capture. Only that reviewed JavaScript source may gain this narrow alias; these
tests do not authenticate or execute an OpenClaw behavioral reference.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from equivalence.runtime_oracle import ROOT, ReleaseOracleExecution, RuntimeOracleError


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def node() -> str:
    binary = shutil.which("node")
    if binary is None:
        pytest.skip("The real capture preload guard requires Node 24 or newer.")
    version = subprocess.run([binary, "--version"], capture_output=True, text=True,
                             check=True, timeout=10).stdout.strip()
    if int(version.lstrip("v").split(".")[0]) < 24:
        pytest.skip("The real capture preload guard requires Node 24 or newer.")
    return binary


@contextmanager
def _execution(tmp_path: Path, *, enabled: bool = True):
    runtime = tmp_path / "runtime/node_modules/openclaw"
    runtime.mkdir(parents=True)
    files = {
        "dist/labelled-artifact.mjs": b"export default {id: 'labelled-native-artifact'};\n",
        "dist/agent-runner-memory-Cc4lCZcs.mjs": b"// Labelled flush-owner trace fixture.\n",
        "dist/extensions/memory-core/manager-runtime.js": b"// Labelled manager trace fixture.\n",
        "dist/extensions/memory-core/memory-index.worker.js": b"// Labelled worker trace fixture.\n",
    }
    for relative, raw in files.items():
        file = runtime / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(raw)
    artifact = runtime / "dist/labelled-artifact.mjs"
    config = {
        "kind": "labelled-capture-transport-fixture", "runtimeRoot": str(runtime),
        "packages": [{
            "location": "node_modules/openclaw", "directory": str(runtime),
            "files": [{"path": relative, "sha256": _hash(raw)} for relative, raw in files.items()],
        }],
    }
    adapters = {path.name: _hash(path.read_bytes())
                for path in (ROOT / "equivalence").glob("*.mjs")}
    with ReleaseOracleExecution(config, adapters, fixture_captures=enabled) as execution:
        yield execution, artifact


def _capture(execution: ReleaseOracleExecution, filename: str = "flush-execution.mjs") -> Path:
    return (
        execution.state_directory / "tmp/plugin-captures"
        / "00000000-0000-4000-8000-000000000001/captures/openclaw-plugin-build-abc123"
        / "package-0/node_modules/equivalence" / filename
    )


def _import(node: str, execution: ReleaseOracleExecution, target: Path) -> tuple[dict, list[dict]]:
    script = """
let imported=false,exportedId=null;
try {
  const candidate=await import(TARGET_URL);
  imported=true;exportedId=candidate.default?.id??null;
} catch {}
process.stdout.write(JSON.stringify({imported,exportedId}));
""".replace("TARGET_URL", json.dumps(target.as_uri()))
    result = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        input="", capture_output=True, text=True, timeout=15,
        env={"PATH": os.defpath, "LANG": "en_US.UTF-8", "TZ": "UTC", **execution.env},
    )
    assert result.returncode == 0, result.stderr
    events = [json.loads(line)
              for trace in execution.trace_directory.glob("*.jsonl")
              for line in trace.read_text(encoding="utf-8").splitlines()]
    return json.loads(result.stdout), events


def test_exact_owned_provider_copy_loads_with_its_reviewed_source_hash_and_retained_proof(tmp_path, node):
    source = ROOT / "equivalence/flush-execution.mjs"
    with _execution(tmp_path) as (execution, _):
        target = _capture(execution)
        target.parent.mkdir(parents=True)
        target.write_bytes(source.read_bytes())
        result, events = _import(node, execution, target)
        assert result == {"imported": True, "exportedId": "fixture-memory-model"}
        captured = [event for event in events
                    if event.get("event") == "load" and event.get("kind") == "fixture-capture"]
        assert captured
        for event in captured:
            assert event["sourcePath"] == str(source.resolve())
            assert event["path"] == str(source.resolve())
            assert event["sha256"] == _hash(source.read_bytes())
            assert event["capturePath"] == target.relative_to(execution.state_directory).as_posix()
            proof = execution.evidence_directory / event["proofPath"]
            assert proof.is_file() and not proof.is_symlink()
            assert proof.stat().st_nlink == 1
            assert proof.read_bytes() == source.read_bytes()


@pytest.mark.parametrize("change", [
    "modified", "outside-context", "wrong-owned-prefix", "wrong-basename",
    "unknown-reviewed-source", "native-artifact-alias", "symlink", "hardlink",
    "symlink-parent", "disabled",
])
def test_provider_capture_policy_rejects_other_authority_and_nonindependent_files(tmp_path, node, change):
    source = ROOT / "equivalence/flush-execution.mjs"
    with _execution(tmp_path, enabled=change != "disabled") as (execution, artifact):
        target = _capture(execution)
        if change == "outside-context":
            target = tmp_path / "outside/captures/openclaw-plugin-build-abc123/flush-execution.mjs"
        elif change == "wrong-owned-prefix":
            target = execution.state_directory / "tmp/other-captures/flush-execution.mjs"
        elif change == "wrong-basename":
            target = _capture(execution, "different-provider.mjs")
        target.parent.mkdir(parents=True)
        if change == "symlink":
            target.symlink_to(source)
        elif change == "hardlink":
            mirror = tmp_path / "independent-mirror.mjs"
            mirror.write_bytes(source.read_bytes())
            os.link(mirror, target)
        elif change == "symlink-parent":
            outside = tmp_path / "outside-parent"
            outside.mkdir()
            (outside / target.name).write_bytes(source.read_bytes())
            target.parent.rmdir()
            target.parent.symlink_to(outside, target_is_directory=True)
        else:
            raw = source.read_bytes()
            if change == "modified":
                raw += b"\nexport const injectedCapture = true;\n"
            elif change == "unknown-reviewed-source":
                raw = (ROOT / "equivalence/flush-runtime.mjs").read_bytes()
            elif change == "native-artifact-alias":
                raw = artifact.read_bytes()
            target.write_bytes(raw)
        result, events = _import(node, execution, target)
        assert result == {"imported": False, "exportedId": None}, change
        assert any(event.get("event") == "rejected" for event in events), change
        assert not any(event.get("event") == "load" and event.get("kind") == "fixture-capture"
                       for event in events), change


def test_default_execution_does_not_enable_fixture_capture_aliases(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    config = {"runtimeRoot": str(runtime), "packages": []}
    adapters = {path.name: _hash(path.read_bytes())
                for path in (ROOT / "equivalence").glob("*.mjs")}
    with ReleaseOracleExecution(config, adapters) as execution:
        context = json.loads(execution.context_path.read_text(encoding="utf-8"))
        assert not context.get("fixtureSourceCaptures")


def _collection_fixture(execution: ReleaseOracleExecution) -> tuple[dict, dict]:
    """Supply labelled surrounding trace rows; only the capture import actually ran.

    These rows exercise the collector's rejection behavior. They are not a
    substitute for the authentic manager, worker and model callback comparisons.
    """
    trace = next(execution.trace_directory.glob("*-0.jsonl"))
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    pid = events[0]["pid"]
    for name in ("release-oracle.mjs", "flush-execution.mjs"):
        source = str((ROOT / "equivalence" / name).resolve())
        events.append({"event": "load", "kind": "oracle", "pid": pid, "threadId": 0,
                       "path": source, "sha256": execution._locals[source]})

    def loaded(relative, thread):
        digest = next(item["sha256"] for item in execution.config["packages"][0]["files"]
                      if item["path"] == relative)
        return {"event": "load", "kind": "release", "pid": pid, "threadId": thread,
                "package": "node_modules/openclaw", "path": relative, "sha256": digest}

    events.extend([
        loaded("dist/agent-runner-memory-Cc4lCZcs.mjs", 0),
        loaded("dist/extensions/memory-core/manager-runtime.js", 0),
    ])
    trace.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    worker = {**events[0], "threadId": 1, "isMainThread": False}
    (execution.trace_directory / f"{pid}-1.jsonl").write_text(
        json.dumps(worker) + "\n"
        + json.dumps(loaded("dist/extensions/memory-core/memory-index.worker.js", 1)) + "\n",
        encoding="utf-8",
    )
    case = {"id": "labelled-capture-collector", "operation": "flush-execution-runtime", "input": {}}
    diagnostic = execution.evidence_directory / _hash(case["id"].encode())
    diagnostic.mkdir()
    (diagnostic / "native-raw.json").write_text(
        json.dumps([{"modelCalls": [{"labelledTransportFixture": True}]}]), encoding="utf-8",
    )
    result = {"kind": "official-release-runtime-comparison", "sources": [], "results": [
        {"id": case["id"], "ok": True, "result": {"provider": "none", "snapshots": []}},
    ]}
    return case, result


def test_collector_keeps_exact_capture_proof_after_the_native_copy_is_removed(tmp_path, node):
    source = ROOT / "equivalence/flush-execution.mjs"
    with _execution(tmp_path) as (execution, _):
        target = _capture(execution)
        target.parent.mkdir(parents=True)
        target.write_bytes(source.read_bytes())
        result, _ = _import(node, execution, target)
        assert result["imported"]
        case, envelope = _collection_fixture(execution)
        target.unlink()  # The real loader can clean its immutable capture before collection.
        enriched = execution.collect(envelope, [case])
        (capture,) = enriched["fixtureCaptures"]
        assert capture["sourcePath"] == str(source.resolve())
        assert capture["sha256"] == capture["proofSha256"] == _hash(source.read_bytes())
        assert capture["bytes"] == len(source.read_bytes())
        assert enriched["releaseTrace"]["protectedWorkerThreads"] == 1


@pytest.mark.parametrize("change", [
    "wrong-operation", "unknown-source", "wrong-capture-prefix", "wrong-proof-path",
    "modified-proof", "symlink-proof", "hardlink-proof", "symlink-proof-parent", "missing-proof",
    "missing-model-callback", "empty-model-callback", "wrong-model-callback-shape",
])
def test_collector_rejects_forged_or_changed_capture_proof(tmp_path, node, change):
    source = ROOT / "equivalence/flush-execution.mjs"
    with _execution(tmp_path) as (execution, _):
        target = _capture(execution)
        target.parent.mkdir(parents=True)
        target.write_bytes(source.read_bytes())
        imported, _ = _import(node, execution, target)
        assert imported["imported"]
        case, envelope = _collection_fixture(execution)
        trace = next(execution.trace_directory.glob("*-0.jsonl"))
        events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        capture = next(event for event in events if event.get("kind") == "fixture-capture")
        proof = execution.evidence_directory / capture["proofPath"]
        if change == "wrong-operation":
            case["operation"] = "flush-trigger-runtime"
        elif change == "unknown-source":
            capture["sourcePath"] = str((ROOT / "equivalence/flush-runtime.mjs").resolve())
        elif change == "wrong-capture-prefix":
            capture["capturePath"] = "tmp/other-captures/flush-execution.mjs"
        elif change == "wrong-proof-path":
            capture["proofPath"] = "../unowned-proof.mjs"
        elif change == "modified-proof":
            proof.write_bytes(source.read_bytes() + b"\nexport const changedProof=true;\n")
        elif change in {"symlink-proof", "hardlink-proof"}:
            saved = execution.root / "saved-proof.mjs"
            proof.rename(saved)
            if change == "symlink-proof":
                proof.symlink_to(saved)
            else:
                os.link(saved, proof)
        elif change == "symlink-proof-parent":
            saved = execution.root / "saved-proof-directory"
            proof.parent.rename(saved)
            proof.parent.symlink_to(saved, target_is_directory=True)
        elif change == "missing-proof":
            proof.unlink()
        elif change in {"missing-model-callback", "empty-model-callback", "wrong-model-callback-shape"}:
            diagnostic = execution.evidence_directory / _hash(case["id"].encode()) / "native-raw.json"
            row = {} if change == "missing-model-callback" else {
                "modelCalls": [] if change == "empty-model-callback" else {"count": 1},
            }
            diagnostic.write_text(json.dumps([row]), encoding="utf-8")
        trace.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        expected = "actual native model callback" if "model-callback" in change else None
        with pytest.raises(RuntimeOracleError, match=expected):
            execution.collect(envelope, [case])
