"""Bind the default worker wire to its frozen original scheduling receipts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from equivalence.search_contract import _same_json
from equivalence.trust_worker_probe import _assert_synthetic_registry, _validate_native
from equivalence.trust_worker_profile import validate_worker_profile_input, worker_profile_public


PARENT_ARTIFACTS = frozenset({
    "dist/session-files-DVVT4Ngb.mjs", "dist/openclaw-runtime-session-cZ0ZaiUL.mjs",
    "dist/redact-BCoakatc.mjs", "dist/secret-redaction-registry-b2B9lcfy.mjs",
})
WORKER_ARTIFACTS = frozenset({
    "dist/config/sessions/session-transcript.worker.js", "dist/worker-task-server-CF3aSh39.mjs",
})
WORKER_PARENT_ARTIFACTS = frozenset({
    "dist/session-transcript-read-worker-runtime-D6t2ip5F.mjs", "dist/worker-task-pool-BQlnRNqZ.mjs",
    "dist/runtime-process-entrypoints-Bh4reDp0.mjs", "dist/runtime-worker-url-S0NIVxUR.mjs",
    "dist/worker-cpu-EKuz4_X-.mjs",
})
LOCAL_FILES = frozenset({"equivalence/trust-worker-profile-runtime.mjs",
                         "equivalence/trust-worker-runtime.mjs", "equivalence/get-contract-runtime.mjs"})


def validate_trust_worker_profile_raw(row, case, diagnostic, evidence_directory, *, runtime_root,
                                      bootstrap, release_by_pid, local_by_pid, process_parents, worker_imports):
    """Validate complete transport/owner identity without implementing retry or redaction."""
    from equivalence.runtime_oracle import ROOT, RuntimeOracleError

    def require(condition, message):
        if not condition:
            raise RuntimeOracleError(message)

    def same(left, right, message):
        require(_same_json(left, right), message)

    if row.get("ok") is not True:
        return
    try:
        value = case["input"]
        validate_worker_profile_input(value)
        require(isinstance(diagnostic, list) and len(diagnostic) == 1 and isinstance(diagnostic[0], dict),
                "Worker profiles require one complete original child observation")
        raw = diagnostic[0]
        require(set(raw) == {"kind", "fixtureBase", "coordinatorPid", "input", "child"}
                and raw["kind"] == "worker-profile", "The worker profile lost an original observation channel")
        same(raw["input"], value, "The worker profile changed its literal scheduling input")
        base = raw["fixtureBase"]
        require(isinstance(base, str) and Path(base).is_absolute() and Path(base).parent == evidence_directory
                and re.fullmatch(r"native-trust-worker-[A-Za-z0-9_-]+", Path(base).name),
                "The worker source escaped its exact owned fixture directory")
        coordinator, child = raw["coordinatorPid"], raw["child"]
        require(type(coordinator) is int and coordinator > 0 and isinstance(child, dict)
                and set(child) == {"request", "requestJson", "requestSha256", "argv", "environmentKeys", "pid",
                                   "exit", "stdout", "stderr", "observation"},
                "The original child lost a process, stream, request or complete observation receipt")
        pid = child["pid"]
        require(type(pid) is int and pid > 0 and pid != coordinator
                and process_parents.get(pid) == coordinator,
                "The worker experiment was not a genuine protected fresh child process")
        main_pids = {item["pid"] for item in bootstrap if item.get("isMainThread") is True}
        require({coordinator, pid} <= main_pids,
                "The worker coordinator or child bypassed its reviewed preload")
        require({str(ROOT / "equivalence/release-oracle.mjs"),
                 str(ROOT / "equivalence/trust-worker-profile-runtime.mjs"),
                 str(ROOT / "equivalence/get-contract-runtime.mjs")} <= local_by_pid.get(coordinator, set())
                and str(ROOT / "equivalence/trust-worker-runtime.mjs") in local_by_pid.get(pid, set()),
                "The genuine frozen experiment or full output codec did not execute in its actual process")
        require(PARENT_ARTIFACTS <= release_by_pid.get(pid, set()),
                "The complete original source and redaction owners did not execute in the experiment process")
        request = {"input": value, "runtimeRoot": str(runtime_root), "fixtureDirectory": str(Path(base) / "fixture")}
        same(child["request"], request, "The original experiment received another runtime, root or literal input")
        require(isinstance(child["requestJson"], str)
                and hashlib.sha256(child["requestJson"].encode()).hexdigest() == child["requestSha256"],
                "The original experiment request bytes lost their actual hash")
        same(json.loads(child["requestJson"]), request, "The original experiment request bytes contain another input")
        argv = child["argv"]
        require(isinstance(argv, list) and len(argv) == 3 and isinstance(argv[0], str) and Path(argv[0]).is_absolute()
                and argv[1:] == [str(ROOT / "equivalence/trust-worker-runtime.mjs"), str(Path(base) / "request.json")],
                "The original experiment used a different executable script or request capability")
        same(child["environmentKeys"], ["LANG", "MEMORY_EQ_RELEASE_CONTEXT", "NODE_OPTIONS", "PATH", "TZ"],
             "The protected child inherited extra ambient or omitted required preload capabilities")
        same(child["exit"], {"code": 0, "signal": None}, "The original worker experiment did not finish successfully")
        require(isinstance(child["stdout"], str) and isinstance(child["stderr"], str),
                "The actual worker process lost its complete output streams")
        observation = child["observation"]
        same(json.loads(child["stdout"]), observation, "The captured original worker stdout was replaced or repaired")
        required = {"scope", "filename", "source", "enumerated", "clock", "before", "after", "expected",
                    "observations", "mutations", "callbackObservations", "attempts"}
        require(isinstance(observation, dict) and required <= observation.keys()
                and set(observation) <= required | {"result", "error"},
                "The original worker observation lost or invented fields")
        _validate_native(observation, value, str(runtime_root))
        same(row["result"], worker_profile_public(observation, base),
             "The public worker envelope differs from complete actual source/error/transcript results")
        scope = {"agentId": "main", "sessionId": "worker-fixture", "sessionKey": "agent:main:dm:worker-fixture",
                 "storePath": str(Path(base) / "fixture/state/agents/main/sessions/sessions.json")}
        same(observation["scope"], scope, "The source owner used a different persisted session identity")
        expected_events = [
            {"type": "session", "version": 4, "id": scope["sessionId"],
             "timestamp": "1970-01-01T00:00:01.000Z", "cwd": "/fixture/work"},
            {"type": "message", "id": "user-1", "parentId": None, "timestamp": "1970-01-01T00:00:01.000Z",
             "message": {"role": "user", "content": "Remember " + value["secret"], "timestamp": 1000}},
        ]
        same(observation["before"], expected_events, "The original source lost its actual complete literal append records")
        dispatched = [item for item in observation["observations"] if item["event"] == "preparation-dispatch"]
        mutations = observation["mutations"]
        callbacks = observation["callbackObservations"]
        require(all(item.get("event") in {"worker-created", "preparation-dispatch", "actual-preparation-reply"}
                    for item in observation["observations"]), "The source trace invented another observation event")
        expected_count = 1 if value.get("observer") else min(value["mutations"], len(dispatched))
        require(len(mutations) == expected_count,
                "A declared genuine registry mutation was omitted or fabricated")
        for ordinal, mutation in enumerate(mutations, 1):
            require(mutation["ordinal"] == ordinal
                    and mutation["value"] == (value["secret"] if ordinal == 1 else "unrelated-worker-credential-2"),
                    "The original registry received another synthetic mutation or reply ordinal")
            _assert_synthetic_registry([mutation["value"]])
        if value.get("observer"):
            # The original timestamp reader treats the literal numeric message
            # timestamp 1000 as seconds. Keep its observed 1000000 unchanged.
            same(callbacks, [{"ordinal": 1, "message": expected_events[1]["message"], "observedAt": 1000000}],
                 "The actual live observer lost its complete message/time or execution order")
            require(not dispatched and observation["attempts"] == 0
                    and mutations[0].get("cut") == "transcript-callback",
                    "The live observer bypass falsely claimed SQL worker preparation or reply mutation")
            require(not [item for item in worker_imports if item.get("pid") == pid],
                    "The live observer path executed an unexpected worker")
        else:
            same(callbacks, [], "A SQL worker path invented a live observer callback")
            require(WORKER_PARENT_ARTIFACTS <= release_by_pid.get(pid, set()),
                    "The original worker pool, scheduling or URL owner did not execute")
            created = [item for item in observation["observations"] if item["event"] == "worker-created"]
            require(bool(created), "The original worker path did not create a genuine worker")
            for worker in created:
                thread = worker["threadId"]
                require(type(thread) is int and thread > 0
                        and {"pid": pid, "threadId": thread, "isMainThread": False} in bootstrap,
                        "The captured worker thread bypassed its exact child process preload")
                loaded = {item["path"] for item in worker_imports
                          if item.get("pid") == pid and item.get("threadId") == thread
                          and item.get("package") == "node_modules/openclaw"}
                require(WORKER_ARTIFACTS <= loaded,
                        "The actual worker entry and implementation task server did not execute in the same protected thread")
            first_snapshot = dispatched[0]["message"]["input"]["redaction"]
            _assert_synthetic_registry(first_snapshot["registeredSecretValues"])
            same(first_snapshot["registeredSecretValues"], [value["secret"]] if value.get("initiallyRegistered") else [],
                 "The actual worker snapshot contains another initial registry membership")
    except RuntimeOracleError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        raise RuntimeOracleError("Malformed or unauthenticated complete worker profile evidence") from error
