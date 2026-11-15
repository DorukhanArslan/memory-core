"""Labelled replay packets only: no original Git helper or host executes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from equivalence import host_turn_barrier_v4_environment as environment
from equivalence import host_turn_barrier_v4_evidence as evidence
import test_host_turn_barrier_v4_sdk as sdk_doubles


def wire(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def write(path, value):
    path.write_text(wire(value) + "\n", encoding="utf-8")


@pytest.fixture
def git_packet(tmp_path, monkeypatch):
    # Reuse the explicitly labelled /tmp/no-Git unit filesystem double. Its
    # runtime contains copied original helper BYTES, never executed code. The
    # synthetic PID/timing/call receipts cannot qualify as original evidence.
    owner = sdk_doubles.packet.__wrapped__(tmp_path, monkeypatch)
    packet = next(owner)
    try:
        context = deepcopy(packet["git"])
        context_path = Path(packet["context"]["gitContextPath"])
        authority = environment.git_source_authority(context_path, context)
        helper = authority["helper"]
        proof = {
            "kind": "host-turn-barrier-v4-original-git-probe",
            "node": deepcopy(context["approvedNodeRuntime"]),
            "sourceAuthority": authority,
            "paths": deepcopy(context["paths"]),
            "results": {"cwd": None, "workspace": None},
            "pid": 731, "ppid": 729,
            "cwd": context["paths"]["cwd"],
            "environment": deepcopy(context["expectedEnvironment"]),
            "argv": [context["approvedNodeRuntime"]["execPath"], context["probe"]["path"],
                     str(context_path)],
            "execArgv": [],
            "calls": [{"role": role, "arguments": [context["paths"][role]], "result": None,
                       "startedAtNs": str(110 + index * 20),
                       "finishedAtNs": str(120 + index * 20),
                       "functionRef": "original-findGitRoot-export-t"}
                      for index, role in enumerate(("cwd", "workspace"))],
            "loads": [{"event": "load", "url": Path(helper["absolutePath"]).as_uri(),
                       **{key: helper[key] for key in
                          ("package", "path", "absolutePath", "sha256")}}],
            "acceptancePointsAwarded": 0,
        }
        process = {
            "kind": "host-turn-barrier-v4-git-probe-process",
            "argv": deepcopy(proof["argv"]), "cwd": proof["cwd"],
            "environment": deepcopy(proof["environment"]), "stdin": wire(context["paths"]),
            "pid": proof["pid"], "coordinatorPid": proof["ppid"],
            "startedAtNs": "100", "finishedAtNs": "190",
            "actualExitObserved": True, "actualReturnCode": 0,
            "stdout": wire(proof) + "\n", "stderr": "LABELLED_UNEXECUTED_STREAM\r\n",
        }
        yield {
            "capture": Path(packet["mapping"]["captureRoot"]),
            "context_path": context_path, "context": context,
            "mapping": packet["mapping"], "proof": proof, "process": process,
            # Keep approved authority independent of all mutable captured data.
            "approved_node": deepcopy(context["approvedNodeRuntime"]),
            "approved_runtime": deepcopy(context["runtime"]),
            "reference": sdk_doubles.REFERENCE, "parent_pid": proof["ppid"],
        }
    finally:
        owner.close()


def retain(packet, *, phase="before", renew_authority=False, sync_stdout=True):
    write(packet["context_path"], packet["context"])
    if renew_authority:
        packet["proof"]["sourceAuthority"] = environment.git_source_authority(
            packet["context_path"], packet["context"])
    if sync_stdout:
        packet["process"]["stdout"] = wire(packet["proof"]) + "\n"
    write(packet["capture"] / f"git-{phase}.proof.json", packet["proof"])
    write(packet["capture"] / f"git-{phase}.process.json", packet["process"])


def consume(packet, phase="before"):
    return evidence.git_capture(packet["capture"], phase, packet["context_path"],
        packet["mapping"], node=packet["approved_node"], runtime=packet["approved_runtime"],
        reference=packet["reference"], parent_pid=packet["parent_pid"])


@pytest.mark.parametrize("phase", ["before", "after"])
def test_complete_original_git_replay_binds_all_calls_imports_and_process_receipts(git_packet, phase):
    retain(git_packet, phase=phase)
    proof, entered, returned = consume(git_packet, phase)
    assert proof == git_packet["proof"]
    assert (entered, returned) == (100, 190)
    assert proof["calls"][1]["arguments"] == [git_packet["mapping"]["workspace"]]
    assert proof["loads"][0]["sha256"] == environment.GIT_HELPER_SHA256
    assert git_packet["process"]["stderr"] == "LABELLED_UNEXECUTED_STREAM\r\n"


@pytest.mark.parametrize("attack", [
    "omitted", "extra", "reordered", "argument", "role", "result", "function",
    "call_extra_field", "call_before_process", "call_after_process", "call_reversed",
    "calls_overlap", "negative_tick", "fractional_tick", "boolean_tick", "unicode_tick",
])
def test_git_call_replay_rejects_changed_ownership_result_function_or_chronology(git_packet, attack):
    calls = git_packet["proof"]["calls"]
    if attack == "omitted":
        calls.pop()
    elif attack == "extra":
        calls.append(deepcopy(calls[-1]))
    elif attack == "reordered":
        calls.reverse()
    elif attack == "argument":
        calls[0]["arguments"] = [git_packet["mapping"]["state"]]
    elif attack == "role":
        calls[0]["role"] = "workspace"
    elif attack == "result":
        calls[0]["result"] = False
    elif attack == "function":
        calls[0]["functionRef"] = "same-result-counterfeit-function"
    elif attack == "call_extra_field":
        calls[0]["predictedResult"] = None
    elif attack == "call_before_process":
        calls[0]["startedAtNs"] = "99"
    elif attack == "call_after_process":
        calls[1]["finishedAtNs"] = "191"
    elif attack == "call_reversed":
        calls[0]["finishedAtNs"] = "109"
    elif attack == "calls_overlap":
        calls[1]["startedAtNs"] = "119"
    else:
        calls[0]["startedAtNs"] = {
            "negative_tick": "-1", "fractional_tick": "110.0",
            "boolean_tick": True, "unicode_tick": "١١٠",
        }[attack]
    retain(git_packet)
    with pytest.raises(ValueError):
        consume(git_packet)


@pytest.mark.parametrize("attack", [
    "git_found", "coherent_git_found", "cwd", "environment", "argv", "exec_argv",
    "pid", "boolean_pid", "ppid", "node", "helper_source", "reference_source",
    "function_source", "probe_source", "context_source", "credit", "boolean_credit",
])
def test_git_proof_rejects_changed_actual_identity_source_or_null_result(git_packet, attack):
    proof = git_packet["proof"]
    if attack in {"git_found", "coherent_git_found"}:
        proof["results"]["workspace"] = git_packet["mapping"]["state"]
        if attack == "coherent_git_found":
            proof["calls"][1]["result"] = proof["results"]["workspace"]
    elif attack == "cwd":
        proof["cwd"] = git_packet["mapping"]["state"]
    elif attack == "environment":
        proof["environment"]["NODE_OPTIONS"] = "--import=counterfeit"
    elif attack == "argv":
        proof["argv"][1] = "/counterfeit-probe.mjs"
    elif attack == "exec_argv":
        proof["execArgv"] = ["--import=counterfeit"]
    elif attack == "pid":
        proof["pid"] += 1
    elif attack == "boolean_pid":
        proof["pid"] = True
    elif attack == "ppid":
        proof["ppid"] += 1
    elif attack == "node":
        proof["node"]["sha256"] = "0" * 64
    elif attack == "function_source":
        proof["sourceAuthority"]["helper"]["functionSourceSha256"] = "0" * 64
    elif attack.endswith("_source"):
        key = {"helper_source": "helper", "reference_source": "reference",
               "probe_source": "probe", "context_source": "context"}[attack]
        proof["sourceAuthority"][key]["sha256"] = "0" * 64
    elif attack == "credit":
        proof["acceptancePointsAwarded"] = 1
    else:
        proof["acceptancePointsAwarded"] = False
    retain(git_packet)
    with pytest.raises(ValueError):
        consume(git_packet)


@pytest.mark.parametrize("attack", [
    "kind", "no_exit", "nonzero_exit", "boolean_exit", "timeout", "error", "pid",
    "coordinator", "cwd", "environment", "argv", "stdin", "stdout", "equal_time",
    "reverse_time", "negative_tick",
])
def test_git_process_rejects_detached_or_unfinished_os_execution(git_packet, attack):
    process = git_packet["process"]
    if attack == "kind":
        process["kind"] = "LABELLED_FOREIGN_PROCESS"
    elif attack == "no_exit":
        process["actualExitObserved"] = 1
    elif attack == "nonzero_exit":
        process["actualReturnCode"] = 2
    elif attack == "boolean_exit":
        process["actualReturnCode"] = False
    elif attack == "timeout":
        process["timedOut"] = True
    elif attack == "error":
        process["error"] = "original helper unavailable"
    elif attack == "pid":
        process["pid"] += 1
    elif attack == "coordinator":
        process["coordinatorPid"] += 1
    elif attack == "cwd":
        process["cwd"] = git_packet["mapping"]["state"]
    elif attack == "environment":
        process["environment"]["TZ"] = "Europe/Istanbul"
    elif attack == "argv":
        process["argv"] = ["/counterfeit/node", *process["argv"][1:]]
    elif attack == "stdin":
        process["stdin"] = wire({"cwd": "foreign", "workspace": "foreign"})
    elif attack == "stdout":
        process["stdout"] = wire({"kind": "LABELLED_UNBOUND_RESULT"})
    elif attack == "equal_time":
        process["finishedAtNs"] = process["startedAtNs"]
    elif attack == "reverse_time":
        process["startedAtNs"] = "200"
    else:
        process["startedAtNs"] = "-100"
    retain(git_packet, sync_stdout=attack != "stdout")
    with pytest.raises(ValueError):
        consume(git_packet)


@pytest.mark.parametrize("attack", [
    "omitted", "unloaded_helper", "too_many", "source_hash", "unknown_source", "package",
    "path", "event", "extra_field", "url_scheme", "url_authority", "url_path",
    "url_query", "url_fragment",
])
def test_git_transitive_loads_must_belong_to_independently_approved_actual_files(git_packet, attack):
    loads = git_packet["proof"]["loads"]
    if attack == "omitted":
        loads.clear()
    elif attack == "unloaded_helper":
        loads[0]["event"] = "resolve-native"
    elif attack == "too_many":
        loads *= 513
    elif attack == "source_hash":
        loads[0]["sha256"] = "0" * 64
    elif attack == "unknown_source":
        loads[0]["absolutePath"] = "/counterfeit/fs-safe.mjs"
    elif attack == "package":
        loads[0]["package"] = "foreign-runtime"
    elif attack == "path":
        loads[0]["path"] = "dist/counterfeit.mjs"
    elif attack == "event":
        loads[0]["event"] = "predicted-load"
    elif attack == "extra_field":
        loads[0]["expectedResult"] = None
    else:
        uri = loads[0]["url"]
        loads[0]["url"] = {
            "url_scheme": uri.replace("file:", "https:", 1),
            "url_authority": uri.replace("file:///", "file://foreign/", 1),
            "url_path": "file:///counterfeit/helper.mjs",
            "url_query": uri + "?counterfeit=1", "url_fragment": uri + "#counterfeit",
        }[attack]
    retain(git_packet)
    with pytest.raises(ValueError):
        consume(git_packet)


@pytest.mark.parametrize("attack", ["foreign_key", "node_options", "PATH", "LANG", "TZ"])
def test_coherent_git_environment_rewrite_cannot_supply_its_own_approved_environment(git_packet, attack):
    key = {"foreign_key": "FOREIGN", "node_options": "NODE_OPTIONS"}.get(attack, attack)
    git_packet["context"]["expectedEnvironment"][key] = "LABELLED_COUNTERFEIT"
    git_packet["proof"]["environment"] = deepcopy(git_packet["context"]["expectedEnvironment"])
    git_packet["process"]["environment"] = deepcopy(git_packet["context"]["expectedEnvironment"])
    retain(git_packet, renew_authority=True)
    with pytest.raises(ValueError):
        consume(git_packet)


@pytest.mark.parametrize("attack", ["extra", "schema", "boolean_schema", "kind", "paths", "contract"])
def test_coherent_git_context_still_requires_exact_frozen_probe_protocol(git_packet, attack):
    context = git_packet["context"]
    if attack == "extra":
        context["expectedResult"] = None
    elif attack == "schema":
        context["schemaVersion"] = 2
    elif attack == "boolean_schema":
        context["schemaVersion"] = True
    elif attack == "kind":
        context["kind"] = "LABELLED_FOREIGN_CONTEXT"
    elif attack == "paths":
        context["paths"]["workspace"] = context["paths"]["cwd"]
        git_packet["proof"]["paths"] = deepcopy(context["paths"])
        git_packet["proof"]["calls"][1]["arguments"] = [context["paths"]["workspace"]]
        git_packet["process"]["stdin"] = wire(context["paths"])
    else:
        context["contractSha256"] = "0" * 64
    retain(git_packet, renew_authority=True)
    with pytest.raises(ValueError):
        consume(git_packet)


def test_coherent_captured_runtime_relabel_cannot_replace_independently_approved_table(git_packet):
    context = git_packet["context"]
    context["runtime"]["packages"][0]["location"] = "LABELLED_COUNTERFEIT_RUNTIME"
    git_packet["proof"]["loads"][0]["package"] = "LABELLED_COUNTERFEIT_RUNTIME"
    retain(git_packet, renew_authority=True)
    assert git_packet["proof"]["sourceAuthority"]["helper"]["package"] == "LABELLED_COUNTERFEIT_RUNTIME"
    assert git_packet["approved_runtime"]["packages"][0]["location"] != "LABELLED_COUNTERFEIT_RUNTIME"
    with pytest.raises(ValueError):
        consume(git_packet)


def test_coherent_captured_node_relabel_cannot_replace_independently_approved_node(git_packet):
    git_packet["context"]["approvedNodeRuntime"]["sha256"] = "0" * 64
    git_packet["proof"]["node"] = deepcopy(git_packet["context"]["approvedNodeRuntime"])
    retain(git_packet, renew_authority=True)
    with pytest.raises(ValueError):
        consume(git_packet)


@pytest.mark.parametrize("carrier", ["stdout", "stdin", "proof_file", "process_file", "context_file"])
def test_git_replay_rejects_duplicate_json_in_every_context_result_and_transport_carrier(git_packet, carrier):
    retain(git_packet)
    if carrier in {"stdout", "stdin"}:
        key = "kind" if carrier == "stdout" else "cwd"
        current = git_packet["process"][carrier]
        git_packet["process"][carrier] = "{" + wire(key) + ':"duplicate",' + current[1:]
        write(git_packet["capture"] / "git-before.process.json", git_packet["process"])
    else:
        path, key = {
            "proof_file": (git_packet["capture"] / "git-before.proof.json", "kind"),
            "process_file": (git_packet["capture"] / "git-before.process.json", "kind"),
            "context_file": (git_packet["context_path"], "kind"),
        }[carrier]
        current = path.read_text(encoding="utf-8")
        path.write_text("{" + wire(key) + ':"duplicate",' + current[1:], encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        consume(git_packet)
