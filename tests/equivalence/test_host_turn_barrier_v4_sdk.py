"""Labelled startup/dispatch doubles; no original host or Git helper executes."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time

import pytest

from equivalence import host_turn_barrier_v4 as frozen
from equivalence import host_turn_barrier_v4_environment as environment
from equivalence import host_turn_barrier_v4_sdk as launcher
from equivalence import host_turn_barrier_v4_sdk_start as startup

REFERENCE = Path("/workspace/memory-core/work/openclaw-v2026.9.9")
RUNTIME = Path("/workspace/memory-core/.reference/release-runtime/node_modules/openclaw")
NODE = Path("/workspace/memory-core/work/node-v24.16.0-linux-x64/bin/node")


@pytest.fixture
def packet(tmp_path, monkeypatch):
    if not (REFERENCE / "src/infra/git-root.ts").is_file():
        pytest.skip("No retained original source bytes for labelled startup validation")
    capture = tmp_path / "capture"
    capture.mkdir()
    # V4's real /var/tmp execution needs its separately reviewed runtime view.
    # Unit tests use an explicitly labelled temporary-root/no-Git filesystem
    # double; these packets can never qualify as actual V4 environment evidence.
    labelled_contract = deepcopy(environment.environment_contract())
    labelled_contract["environment"]["temporaryRoot"] = "/tmp"
    monkeypatch.setattr(environment, "environment_contract", lambda: deepcopy(labelled_contract))
    def labelled_ancestors(path):
        value = environment.directory(path, missing=True)
        return [{"path": str(item), "exists": item.exists(),
                 "identity": environment.identity(item) if item.exists() else None,
                 "gitEntryPresent": False} for item in (value, *value.parents)]
    monkeypatch.setattr(environment, "ancestor_facts", labelled_ancestors)
    mapping = environment.allocate_execution(capture, "sdk")
    helper = tmp_path / "LABELLED_RUNTIME" / environment.GIT_HELPER
    helper.parent.mkdir(parents=True)
    shutil.copyfile(RUNTIME / environment.GIT_HELPER, helper)
    runtime = {"runtimeRoot": str(helper.parents[1]), "packages": [{
        "location": "LABELLED_RUNTIME_NO_ORIGINAL_EXECUTION", "directory": str(helper.parents[1]),
        "files": [{"path": environment.GIT_HELPER, "sha256": environment.GIT_HELPER_SHA256}],
    }]}
    node_authority = {"execPath": str(NODE), "nodeVersion": "v24.16.0", "icuVersion": "78.3",
                      "unicodeVersion": "17.0", "sha256": "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"}
    path = capture / "host-v4-context.json"
    git_path = capture / "git-before-context.json"
    git = environment.prepare_git_probe(mapping, node=NODE, node_authority=node_authority,
        runtime=runtime, reference_root=REFERENCE, path=git_path)
    case = frozen.build_cases()[0]
    request = {"input": frozen.business_case(case)["input"], "directory": mapping["state"]}
    wire = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    executable = Path(sys.executable).absolute()
    context = {
        "schemaVersion": 1, "kind": "host-turn-barrier-v4-sdk-start-context",
        "contractSha256": frozen.CONTRACT_SHA256, "case": case, "registered": False,
        "caseWireSha256": hashlib.sha256(frozen.case_wire(case)).hexdigest(),
        "mapping": mapping, "environment": environment.expected_environment(
            mapping, source_root=environment.ROOT, executable=executable),
        "initialArgv": [str(executable), "-m", startup.START_MODULE, str(path)],
        "execArgv": [str(executable), "-m", startup.HOST_MODULE],
        "executable": {"launchPath": str(executable), "realPath": str(executable.resolve()),
            "sha256": environment.digest(executable), "pythonVersion": platform.python_version(),
            "cacheTag": sys.implementation.cache_tag},
        "sourceRoot": str(environment.ROOT), "sourceFiles": startup.source_seals(),
        "startupCodeSha256": startup.startup_code_sha256(),
        "gitContextPath": str(git_path), "gitContextSha256": environment.digest(git_path),
        "gitSourceAuthority": environment.git_source_authority(git_path, git),
        "requestSha256": hashlib.sha256(wire.encode()).hexdigest(),
    }
    environment.write_exclusive(path, context)
    try:
        yield {"path": path, "context": context, "git": git, "mapping": mapping, "case": case}
    finally:
        shutil.rmtree(mapping["executionRoot"])


def test_actual_runtime_guard_rejects_a_present_git_marker(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValueError, match="Git ancestry"):
        environment.ancestor_facts(tmp_path)


def test_validated_startup_preserves_exact_original_host_stdin_owner(packet):
    context, git = startup.validate_context(packet["path"], packet["context"])
    assert context is packet["context"]
    assert git == packet["git"]
    assert context["execArgv"][1:] == ["-m", "equivalence.host_turn_barrier_sdk_cli"]


@pytest.mark.parametrize("attack", [
    "extra", "wire", "owner", "cwd", "environment", "exec", "source", "executable", "git", "code",
])
def test_startup_rejects_reassigned_case_source_environment_and_exec_owner(packet, attack):
    context = deepcopy(packet["context"])
    if attack == "extra":
        context["expectedOutcome"] = "match"
    elif attack == "wire":
        context["caseWireSha256"] = "0" * 64
    elif attack == "owner":
        context["mapping"]["engine"] = "native"
    elif attack == "cwd":
        context["mapping"]["cwd"] = str(Path(context["mapping"]["executionRoot"]) / "other")
    elif attack == "environment":
        context["environment"]["HOME"] = context["mapping"]["state"]
    elif attack == "exec":
        context["execArgv"] = [context["execArgv"][0], "-c", "print('counterfeit')"]
    elif attack == "source":
        context["sourceFiles"][next(iter(context["sourceFiles"]))] = "0" * 64
    elif attack == "executable":
        context["executable"]["sha256"] = "0" * 64
    elif attack == "git":
        context["gitContextSha256"] = "0" * 64
    else:
        context["startupCodeSha256"] = "0" * 64
    with pytest.raises(ValueError):
        startup.validate_context(packet["path"], context)


def test_startup_self_observes_then_execs_once_without_reading_stdin(packet, monkeypatch):
    context = packet["context"]
    monkeypatch.chdir(packet["mapping"]["cwd"])
    monkeypatch.setattr(os, "environ", dict(context["environment"]))
    monkeypatch.setattr(sys, "argv", [str(Path(startup.__file__)), str(packet["path"])])
    monkeypatch.setattr(sys, "orig_argv", list(context["initialArgv"]))

    class NoRead(io.StringIO):
        def read(self, *args, **kwargs):
            raise AssertionError("The startup must leave original stdin unread")

    monkeypatch.setattr(sys, "stdin", NoRead("LABELLED_ORIGINAL_HOST_STDIN"))
    proof = {"kind": "LABELLED_GIT_PROOF_NO_ORIGINAL_EXECUTION"}
    checked = []
    monkeypatch.setattr(startup, "run_git_probe", lambda *args, **kwargs: proof)
    monkeypatch.setattr(startup, "validate_git_proof", lambda value, *args, **kwargs:
                        checked.append(value is proof))

    class ObservedExec(BaseException):
        pass

    calls = []
    def exec_once(executable, argv, env):
        calls.append((executable, argv, env))
        receipt = startup.read_json(packet["path"].parent / "environment-before-exec.json")
        assert receipt["pid"] == os.getpid() and receipt["ppid"] == os.getppid()
        assert receipt["cwd"] == os.getcwd() == packet["mapping"]["cwd"]
        assert receipt["initialArgv"] == context["initialArgv"]
        assert receipt["execArgv"] == context["execArgv"]
        assert receipt["environment"] == env == context["environment"]
        assert receipt["startupSource"]["functionCodeSha256"] == context["startupCodeSha256"]
        assert receipt["originalGitProof"] == proof
        raise ObservedExec

    monkeypatch.setattr(os, "execve", exec_once)
    with pytest.raises(ObservedExec):
        startup.main()
    assert checked == [True] and len(calls) == 1
    assert calls[0][0] == context["execArgv"][0] and calls[0][1] == context["execArgv"]
    assert sys.stdin.tell() == 0


@pytest.mark.parametrize("wire", ['{"a":1,"a":2}', '{"x":NaN}', '{"x":1e4000}'])
def test_startup_json_rejects_ambiguous_source_context(tmp_path, wire):
    path = tmp_path / "context.json"
    path.write_text(wire)
    with pytest.raises(ValueError):
        startup.read_json(path)


def test_public_entry_returns_the_same_whole_result_object(packet, monkeypatch):
    from equivalence import model_runtime_authority

    value = {"warning": "ACTUAL_LABELLED_WARNING", "corpora": [],
             "allFields": {"zero": 0, "false": False, "null": None, "unicode": "\ud800"}}
    calls = []
    monkeypatch.setattr(model_runtime_authority, "prepare_model_node_authority", lambda node: {"node": node})
    def actual(*args, **kwargs):
        calls.append((args, kwargs))
        return {"result": value, "dispatch": {}, "v4": {}}
    monkeypatch.setattr(launcher, "run_sdk_case", actual)
    result = launcher.run_host_turn_barrier_v4_case(packet["case"], node="LABELLED_NODE",
        runtime={}, reference_root="LABELLED_REFERENCE", evidence_directory=packet["path"].parent)
    assert result is value
    assert calls[0][1]["registered"] is False and calls[0][1]["timeout"] == 120


def test_launcher_rejects_widened_process_bound_before_any_process_or_state_creation(tmp_path):
    destination = tmp_path / "not-created"
    with pytest.raises(ValueError, match="120 seconds"):
        launcher.run_sdk_case(frozen.build_cases()[0], destination, node=None, node_authority={},
                             runtime={}, reference_root=None, timeout=121)
    assert not destination.exists()


def test_launcher_rejects_capture_reuse_without_starting_any_process(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "original"
    marker.write_bytes(b"RETAINED_BYTES")
    with pytest.raises(ValueError, match="new empty"):
        launcher.run_sdk_case(frozen.build_cases()[0], destination, node=None, node_authority={},
                             runtime={}, reference_root=None)
    assert marker.read_bytes() == b"RETAINED_BYTES"


@pytest.fixture
def transport(packet, tmp_path, monkeypatch):
    """Labelled process/qualification doubles, never valid original evidence."""
    state = {"contexts": [], "stdin": [], "stdout": None, "stderr": b"first\r\nsecond\rthird\n"}
    public = {"warning": "LABELLED_WARNING", "corpora": [], "unicode": "ışık 😀", "text": "a\r\nb"}

    class Process:
        pid = 12345
        returncode = 0

        def __init__(self, argv, **kwargs):
            assert kwargs.get("text", False) is False
            context_path = Path(argv[-1])
            self.context = startup.read_json(context_path)
            assert kwargs["cwd"] == self.context["mapping"]["cwd"]
            state["contexts"].append(self.context)
            self.path = context_path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def communicate(self, wire, *, timeout):
            assert isinstance(wire, bytes) and timeout == 120
            state["stdin"].append(wire)
            assert hashlib.sha256(wire).hexdigest() == self.context["requestSha256"]
            Path(self.context["mapping"]["workspace"]).mkdir()
            environment.write_exclusive(self.path.parent / "environment-before-exec.json", {
                "kind": "UNIT_NO_ORIGINAL_EXECUTION", "pid": self.pid, "ppid": os.getpid(),
                "initialArgv": self.context["initialArgv"], "execArgv": self.context["execArgv"],
                "context": launcher._seal(self.path),
            })
            output = json.dumps({"result": public, "raw": {"pid": self.pid, "ppid": os.getpid()}},
                                ensure_ascii=False, indent=2).replace("\n", "\r\n").encode() + b"\r\n"
            return (output if state["stdout"] is None else state["stdout"]), state["stderr"]

    def git_double(*args, prefix, **kwargs):
        stamp = str(time.monotonic_ns())
        proof = {"kind": "UNIT_GIT_PROOF_NO_ORIGINAL_EXECUTION"}
        environment.write_exclusive(prefix.with_suffix(".process.json"), {
            "kind": "UNIT_PROCESS_NO_ORIGINAL_EXECUTION", "startedAtNs": stamp,
            "finishedAtNs": str(time.monotonic_ns()),
        })
        environment.write_exclusive(prefix.with_suffix(".proof.json"), proof)
        return proof

    monkeypatch.setattr(launcher.subprocess, "Popen", Process)
    monkeypatch.setattr(launcher, "run_git_probe", git_double)
    monkeypatch.setattr(launcher, "validate_git_proof", lambda proof, *args, **kwargs: None)
    destination = tmp_path / "transport"
    try:
        yield {"state": state, "public": public, "destination": destination,
               "invoke": lambda: launcher.run_sdk_case(packet["case"], destination,
                   node=NODE, node_authority=packet["git"]["approvedNodeRuntime"],
                   runtime=packet["git"]["runtime"], reference_root=REFERENCE)}
    finally:
        for context in state["contexts"]:
            shutil.rmtree(context["mapping"]["executionRoot"])


def test_binary_transport_retains_crlf_and_exact_whole_public_result(transport):
    result = transport["invoke"]()
    root = transport["destination"]
    stdout, stderr = (root / "stdout.json").read_bytes(), (root / "stderr.log").read_bytes()
    assert b"\r\n" in stdout and stderr == b"first\r\nsecond\rthird\n"
    assert result["dispatch"]["stdout"] == stdout.decode("utf-8")
    assert result["dispatch"]["stderr"] == stderr.decode("utf-8")
    assert result["result"] == transport["public"]
    retained = json.loads((root / "python-raw.json").read_bytes())[0]
    assert retained["stdout"] == result["dispatch"]["stdout"]
    after = json.loads((root / "environment-after-exit.json").read_bytes())
    assert int(after["atNs"]) >= int(retained["finishedAtNs"])
    assert after["originalGitProof"]["kind"] == "UNIT_GIT_PROOF_NO_ORIGINAL_EXECUTION"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_invalid_utf8_is_retained_byte_exact_and_blocks_instead_of_replacement(transport, stream):
    value = b"ORIGINAL\r\n\xff\x80\n"
    transport["state"][stream] = value
    with pytest.raises(ValueError, match="strict UTF-8"):
        transport["invoke"]()
    root = transport["destination"]
    path = root / ("stdout.json" if stream == "stdout" else "stderr.log")
    assert path.read_bytes() == value
    retained = json.loads((root / "python-raw.json").read_bytes())[0]
    assert stream not in retained
    assert retained["hostV4"][stream + "DecodeError"]["name"] == "UnicodeDecodeError"
    assert retained["hostV4"][stream]["sha256"] == hashlib.sha256(value).hexdigest()
    assert not (root / "sdk-output.json").exists()
