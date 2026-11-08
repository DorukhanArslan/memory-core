"""Labelled protocol fixtures exercise authority checks, never session parity."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from equivalence import session_admission_runtime_bindings as bindings
from equivalence.get_contract import map_get_fixture_paths
from equivalence.release_runtime import ReleaseRuntimeError, validate_release_sources
from equivalence.runtime_oracle import (
    ROOT,
    ReleaseOracleExecution,
    RuntimeOracleError,
)
from equivalence.search_contract import decode_search_tool_envelope
from test_runtime_oracle_transport import (
    _bootstrap,
    _evidence,
    _load,
    _trace,
    transport as transport,
)


ALICE = "agent:main:direct:alice"
BOB = "agent:main:direct:bob"
NOW = 1_790_000_000_000


@pytest.fixture
def session_transport(transport):
    previous, original, case, result = transport
    config = deepcopy(original)
    package = config["packages"][0]
    existing = {row["path"] for row in package["files"]}
    for relative in bindings.COMPILED_HASHES:
        if relative not in existing:
            content = ("// Labelled session transport artifact: " + relative + "\n").encode()
            path = Path(config["runtimeRoot"]) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            package["files"].append(
                {"path": relative, "sha256": hashlib.sha256(content).hexdigest()}
            )
    case["operation"] = "session-contract-runtime"
    case["input"] = {
        "kind": "flow",
        "agentId": "main",
        "nowMs": NOW,
        "config": {"agentIds": ["main", "peer"], "visibility": "self"},
        "sessions": [
            {
                "sessionKey": ALICE,
                "entry": {"sessionId": "alice", "chatType": "direct"},
                "events": [
                    {
                        "type": "message",
                        "id": "one",
                        "message": {
                            "role": "user",
                            "content": "Cobalt literal source.",
                            "__openclaw": {"senderIsOwner": True},
                        },
                    }
                ],
            }
        ],
        "steps": [
            {
                "label": "first",
                "queries": [
                    {"id": "allowed", "query": "Cobalt", "requesterSessionKey": ALICE},
                    {"id": "misbound", "query": "Cobalt", "requesterSessionKey": "agent:peer:main"},
                ],
                "reads": [
                    {
                        "id": "self",
                        "requesterSessionKey": ALICE,
                        "targetSessionKey": ALICE,
                        "sessionReadScopeKey": ALICE,
                    },
                    {"id": "denied", "requesterSessionKey": BOB, "targetSessionKey": ALICE},
                ],
            }
        ],
    }
    with ReleaseOracleExecution(config, previous.adapter_hashes) as execution:
        yield execution, config, case, result


def _config(base):
    return {
        "agents": {
            "defaults": {"workspace": str(base / "workspace")},
            "list": [{"id": "main", "default": True}, {"id": "peer"}],
        },
        "logging": {"level": "silent", "consoleLevel": "silent", "file": str(base / "native.log")},
        "session": {"maintenance": {"mode": "warn"}},
        "tools": {"sessions": {"visibility": "self"}},
        "memory": {
            "search": {
                "enabled": True,
                "provider": "none",
                "fallback": "none",
                "sources": ["memory", "sessions"],
                "rememberAcrossConversations": True,
                "experimental": {"sessionMemory": True},
                "store": {"vector": {"enabled": False}},
                "sync": {"onSessionStart": False, "onSearch": False, "watch": False},
                "query": {
                    "minScore": 0,
                    "maxResults": 200,
                    "hybrid": {"temporalDecay": {"enabled": False}},
                },
            }
        },
    }


def _records(execution, case, result):
    """A non-executing labelled transcript of the protocol, not expected behavior."""
    directory = execution.evidence_directory / hashlib.sha256(case["id"].encode()).hexdigest()
    base = directory / "native-session-fixture-LABELLED"
    config = _config(base)
    store = str(base / "state/agents/main/sessions/sessions.json")
    events = deepcopy(case["input"]["sessions"][0]["events"])
    source = {
        "agentId": "main",
        "artifactKind": "active-session",
        "sessionFile": ALICE,
        "sessionId": "alice",
        "sessionKey": ALICE,
        "transcriptSource": "sqlite",
        "storePath": store,
        "updatedAtMs": NOW,
        "sessionKind": "interactive",
    }
    provenance = {
        "originClass": "owner",
        "sessionKind": "interactive",
        "observedAt": NOW,
        "supersedesKey": None,
    }
    hit = {
        "path": "sessions/main/alice.jsonl",
        "source": "sessions",
        "startLine": 1,
        "endLine": 1,
        "score": 0.9,
        "snippet": "Cobalt literal source.",
        "provenance": provenance,
        "opaque": {"values": [None, False, 0]},
    }
    details = {
        "results": [hit],
        "provider": "none",
        "opaque": ["keep", None],
        "debug": {"candidateHits": 1, "withheldHits": 0, "searchWindow": 1, "hits": 1},
    }
    envelope = {
        "content": [{"type": "text", "text": json.dumps(details, indent=2)}],
        "details": details,
        "opaqueEnvelope": [False, None],
    }
    failure = {
        "name": "AgentSelectionRequiredError",
        "code": "AGENT_SELECTION_REQUIRED",
        "message": "Literal misbound requester error",
        "agentIds": ["main", "peer"],
        "surface": "session agent resolution",
        "hint": "Keep complete owner evidence",
    }
    denied = {
        "allowed": False,
        "status": "forbidden",
        "reasonCode": "self_visibility_restricted",
        "policyRefs": ["tools.sessions.visibility"],
        "contextFieldsUsed": ["requesterSessionKey", "targetSessionKey", "visibility"],
        "missingEvidence": [],
    }
    reads = [
        {"id": "self", "access": {"allowed": True}, "sessionId": "alice", "events": events},
        {"id": "denied", "access": denied, "events": []},
    ]
    sql = {
        "chunks": [
            {
                "id": "native-chunk",
                "path": hit["path"],
                "source": "sessions",
                "start_line": 1,
                "end_line": 1,
                "text": "User: Cobalt literal source.",
                "hash": "literal-index-hash",
                "model": "fts-only",
                "updated_at": NOW,
                "embedding": {},
                "embeddingHex": "",
            }
        ],
        "sources": [
            {
                "id": 1,
                "path": hit["path"],
                "source": "sessions",
                "hash": "literal-source-hash",
                "mtime": NOW,
                "size": 170,
            }
        ],
        "provenance": [
            {
                "chunk_id": "native-chunk",
                "origin_class": "owner",
                "session_kind": "interactive",
                "observed_at": NOW,
                "supersedes_key": None,
            }
        ],
        "recall": [
            {"chunk_id": "native-chunk", "importance": None, "triggers": None, "project_key": None}
        ],
        "fts": [
            {
                "id": "native-chunk",
                "path": hit["path"],
                "source": "sessions",
                "start_line": 1,
                "end_line": 1,
                "text": "User: Cobalt literal source.",
                "model": "fts-only",
            }
        ],
    }
    snapshot = {
        "label": "first",
        "catalog": [source],
        "admitted": [source],
        "sourceEntries": [
            {
                "source": source,
                "entry": {
                    "path": hit["path"],
                    "absPath": ALICE,
                    "mtimeMs": NOW,
                    "revisionMs": NOW + 1,
                    "size": 170,
                    "hash": "literal-source-hash",
                    "content": "User: Cobalt literal source.",
                    "lineMap": [1],
                    "messageTimestampsMs": [0],
                    "lineProvenance": [provenance],
                    "sessionKind": "interactive",
                },
                "resetRecallCutoff": {"state": "absent"},
            }
        ],
        "published": [
            {
                "path": hit["path"],
                "source": "sessions",
                "startLine": 1,
                "endLine": 1,
                "text": "User: Cobalt literal source.",
                "importance": None,
                "triggers": None,
                "projectKey": None,
                "provenance": provenance,
            }
        ],
        "indexSources": [{"path": hit["path"], "source": "sessions"}],
        "queries": [
            {"id": "allowed", "candidates": [hit], "result": decode_search_tool_envelope(envelope)},
            {"id": "misbound", "candidates": [hit], "error": failure},
        ],
        "reads": reads,
        "ingestionDecisions": [{"source": None}],
        "participantRecords": {},
    }
    raw = {
        "fixtureBase": str(base),
        "constructorSkipped": False,
        "managerFixture": False,
        "clock": {
            "owner": "node:test",
            "apis": ["Date"],
            "nowMs": NOW,
            "dateConstructorReplaced": True,
            "setTimeoutUnchanged": True,
        },
        "config": config,
        "sessionWrites": [
            {
                "target": {
                    "agentId": "main",
                    "sessionKey": ALICE,
                    "sessionId": "alice",
                    "storePath": store,
                },
                "events": events,
                "participants": [],
                "participantRecords": {},
                "readBack": {
                    "updatedAt": NOW,
                    "sessionId": "alice",
                    "chatType": "direct",
                    "delivery": {"kind": "none"},
                },
                "transcript": events,
                "storage": {
                    "incognito": False,
                    "databasePath": str(base / "state/agents/main/openclaw-agent.sqlite"),
                    "pathExists": True,
                },
            }
        ],
        "gatewayRequests": [],
        "lifecycle": [],
        "archiveWrites": [],
        "mutations": [],
        "snapshots": [
            {
                **snapshot,
                "fullSql": sql,
                "sessionSql": {
                    "session_nodes": {
                        "columns": [{"name": "session_key"}, {"name": "entry_json"}],
                        "rows": [{"session_key": ALICE, "entry_json": {"sessionId": "alice"}}],
                    },
                    **{
                        table: {"columns": [{"name": "session_id"}], "rows": []}
                        for table in (
                            "session_windows",
                            "transcript_events",
                            "session_participants",
                            "session_transcript_archives",
                            "memory_session_tombstones",
                        )
                    },
                },
            }
        ],
        "managerAcquisitions": [{"agentId": "main", "status": {"backend": "builtin"}}],
        "catalogRequests": [
            {"agentId": "main", "includeContentRevision": False, "includeRetainedSqlite": False}
        ],
        "nativeEnvelopes": [{"step": "first", "queryId": "allowed", "nativeEnvelope": envelope}],
        "queryErrors": [
            {"step": "first", "queryId": "misbound", "error": failure, "stack": "raw native stack"}
        ],
        "reads": [{"step": "first", **value} for value in reads],
        "queryRequests": [],
        "readRequests": [],
    }
    for query in case["input"]["steps"][0]["queries"]:
        raw["queryRequests"].append(
            {
                "step": "first",
                "queryId": query["id"],
                "toolOptions": {
                    "config": deepcopy(config),
                    "agentId": "main",
                    "agentSessionKey": query["requesterSessionKey"],
                },
                "parameters": {
                    "query": query["query"],
                    "maxResults": 200,
                    "minScore": 0,
                    "corpus": "sessions",
                },
            }
        )
    for request, outcome in zip(case["input"]["steps"][0]["reads"], reads, strict=True):
        observation = {
            "step": "first",
            "readId": request["id"],
            "input": deepcopy(request),
            "guard": {
                "action": "history",
                "requesterAgentId": "main",
                "requesterSessionKey": request["requesterSessionKey"],
                "targetAgentId": "main",
                "targetSessionKey": request["targetSessionKey"],
                "requesterOwned": False,
                "mainSessionKey": "agent:main:main",
                "visibility": "self",
                "a2aPolicy": {"enabled": True},
            },
        }
        if "sessionReadScopeKey" in request:
            observation["guard"]["sessionReadScopeKey"] = request["sessionReadScopeKey"]
        if "sessionId" in outcome:
            observation["reader"] = {
                "agentId": "main",
                "sessionKey": request["targetSessionKey"],
                "sessionId": outcome["sessionId"],
                "storePath": store,
            }
        raw["readRequests"].append(observation)
    result["results"][0]["result"] = {
        "provider": "none",
        "steps": [map_get_fixture_paths(snapshot, str(base))],
    }
    return [raw]


def _events(execution, config):
    local = [
        {
            "event": "load",
            "pid": 111,
            "threadId": 0,
            "kind": "oracle",
            "path": str((ROOT / "equivalence" / name).resolve()),
            "sha256": execution._locals[str((ROOT / "equivalence" / name).resolve())],
        }
        for name in (
            "release-oracle.mjs",
            "session-contract-runtime.mjs",
            "search-contract-runtime.mjs",
            "get-contract-runtime.mjs",
        )
    ]
    return [
        _bootstrap(execution, 0),
        *local,
        *[_load(config, relative, 0) for relative in bindings.COMPILED_HASHES],
    ]


def _install(execution, config, case, raw):
    _trace(execution, 0, _events(execution, config))
    _trace(
        execution,
        1,
        [
            _bootstrap(execution, 1),
            *[_load(config, name, 1) for name in bindings.MEMORY_INDEX_WORKER_ARTIFACTS],
        ],
    )
    return _evidence(execution, case, raw)


def test_complete_session_protocol_preserves_all_raw_private_and_public_records(session_transport):
    execution, config, case, result = session_transport
    raw = _records(execution, case, result)
    _install(execution, config, case, raw)
    before = deepcopy(result)
    answer = execution.collect(result, [case])
    assert result == before
    assert answer["results"] == result["results"]
    assert answer["runtimeDiagnostics"][0]["rawSnapshots"] == raw
    assert answer["releaseTrace"]["protectedWorkerThreads"] == 1
    assert answer["releaseTrace"]["networkFetchDenied"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "custom-date",
        "changed-timers",
        "wrong-now",
        "wrong-clock-apis",
        "constructor-skipped",
        "manager-fixture",
        "outside-fixture",
        "missing-config",
        "permissive-config",
        "provider-config",
        "source-config",
        "missing-acquisition",
        "wrong-manager-owner",
        "missing-catalog-request",
        "wrong-revision-option",
        "missing-snapshot",
        "public-source-dropped",
        "raw-source-dropped",
        "provenance-lost",
        "source-hash-changed",
        "published-row-missing",
        "sql-chunk-missing",
        "sql-provenance-lost",
        "sql-source-missing",
        "nonempty-vector",
        "native-envelope-missing",
        "native-envelope-field-lost",
        "raw-carrier-mismatch",
        "error-code-lost",
        "query-id-duplicate",
        "query-request-missing",
        "query-requester-widened",
        "query-permissive-config",
        "read-output-missing",
        "read-events-lost",
        "read-request-missing",
        "read-requester-widened",
        "read-scope-removed",
        "read-guard-missing",
        "read-identity-swapped",
        "read-call-missing",
        "sql-fts-lost",
        "sql-fts-text-changed",
        "session-table-lost",
        "session-record-column-lost",
        "session-write-lost",
        "session-write-owner-swapped",
        "session-write-events-changed",
        "session-readback-lost",
        "session-participants-lost",
        "session-storage-lost",
        "session-storage-outside-fixture",
        "session-storage-sentinel-misclassified",
        "session-storage-private-disk",
        "session-storage-private-corpus",
        "unobserved-rewrite",
    ],
)
def test_session_raw_or_public_observation_cannot_be_dropped_rewritten_or_detached(
    session_transport, mutation
):
    execution, config, case, result = session_transport
    raw = _records(execution, case, result)
    observation = raw[0]
    snapshot = observation["snapshots"][0]
    public = result["results"][0]["result"]["steps"][0]
    if mutation == "custom-date":
        observation["clock"]["owner"] = "fixture-date"
    elif mutation == "changed-timers":
        observation["clock"]["setTimeoutUnchanged"] = False
    elif mutation == "wrong-now":
        observation["clock"]["nowMs"] += 1
    elif mutation == "wrong-clock-apis":
        observation["clock"]["apis"].append("setTimeout")
    elif mutation == "constructor-skipped":
        observation["constructorSkipped"] = True
    elif mutation == "manager-fixture":
        observation["managerFixture"] = True
    elif mutation == "outside-fixture":
        observation["fixtureBase"] = "/tmp/native-session-fixture-FORGED"
    elif mutation == "missing-config":
        del observation["config"]
    elif mutation == "permissive-config":
        observation["config"]["tools"]["sessions"]["visibility"] = "all"
    elif mutation == "provider-config":
        observation["config"]["memory"]["search"]["provider"] = "remote"
    elif mutation == "source-config":
        observation["config"]["memory"]["search"]["sources"] = ["memory"]
    elif mutation == "missing-acquisition":
        observation["managerAcquisitions"] = []
    elif mutation == "wrong-manager-owner":
        observation["managerAcquisitions"][0]["agentId"] = "peer"
    elif mutation == "missing-catalog-request":
        observation["catalogRequests"] = []
    elif mutation == "wrong-revision-option":
        observation["catalogRequests"][0]["includeContentRevision"] = True
    elif mutation == "missing-snapshot":
        observation["snapshots"] = []
    elif mutation == "public-source-dropped":
        public["sourceEntries"] = []
    elif mutation == "raw-source-dropped":
        snapshot["sourceEntries"] = []
    elif mutation == "provenance-lost":
        del public["published"][0]["provenance"]["observedAt"]
    elif mutation == "source-hash-changed":
        public["sourceEntries"][0]["entry"]["hash"] = "forged-hash"
    elif mutation == "published-row-missing":
        public["published"] = []
    elif mutation == "sql-chunk-missing":
        snapshot["fullSql"]["chunks"] = []
    elif mutation == "sql-provenance-lost":
        snapshot["fullSql"]["provenance"] = []
    elif mutation == "sql-source-missing":
        snapshot["fullSql"]["sources"] = []
    elif mutation == "nonempty-vector":
        snapshot["fullSql"]["chunks"][0]["embeddingHex"] = "abcd"
    elif mutation == "native-envelope-missing":
        observation["nativeEnvelopes"] = []
    elif mutation == "native-envelope-field-lost":
        del observation["nativeEnvelopes"][0]["nativeEnvelope"]["opaqueEnvelope"]
    elif mutation == "raw-carrier-mismatch":
        observation["nativeEnvelopes"][0]["nativeEnvelope"]["content"][0]["text"] = "{}"
    elif mutation == "error-code-lost":
        del public["queries"][1]["error"]["code"]
    elif mutation == "query-id-duplicate":
        observation["nativeEnvelopes"].append(deepcopy(observation["nativeEnvelopes"][0]))
    elif mutation == "query-request-missing":
        observation["queryRequests"] = []
    elif mutation == "query-requester-widened":
        observation["queryRequests"][0]["toolOptions"]["agentSessionKey"] = BOB
    elif mutation == "query-permissive-config":
        observation["queryRequests"][0]["toolOptions"]["config"]["tools"]["sessions"][
            "visibility"
        ] = "all"
    elif mutation == "read-output-missing":
        observation["reads"] = []
    elif mutation == "read-events-lost":
        public["reads"][0]["events"] = []
    elif mutation == "read-request-missing":
        observation["readRequests"] = []
    elif mutation == "read-requester-widened":
        observation["readRequests"][0]["input"]["requesterSessionKey"] = BOB
    elif mutation == "read-scope-removed":
        observation["readRequests"][0]["guard"].pop("sessionReadScopeKey")
    elif mutation == "read-guard-missing":
        observation["readRequests"][0].pop("guard")
    elif mutation == "read-identity-swapped":
        observation["readRequests"][0]["reader"]["sessionId"] = "another-incarnation"
    elif mutation == "read-call-missing":
        observation["readRequests"][0].pop("reader")
    elif mutation == "sql-fts-lost":
        snapshot["fullSql"]["fts"] = []
    elif mutation == "sql-fts-text-changed":
        snapshot["fullSql"]["fts"][0]["text"] = "Fabricated source"
    elif mutation == "session-table-lost":
        snapshot["sessionSql"].pop("session_windows")
    elif mutation == "session-record-column-lost":
        snapshot["sessionSql"]["session_nodes"]["rows"][0].pop("entry_json")
    elif mutation == "session-write-lost":
        observation["sessionWrites"] = []
    elif mutation == "session-write-owner-swapped":
        observation["sessionWrites"][0]["target"]["agentId"] = "peer"
    elif mutation == "session-write-events-changed":
        observation["sessionWrites"][0]["events"] = []
    elif mutation == "session-readback-lost":
        observation["sessionWrites"][0].pop("readBack")
    elif mutation == "session-participants-lost":
        observation["sessionWrites"][0].pop("participantRecords")
    elif mutation == "session-storage-lost":
        observation["sessionWrites"][0].pop("storage")
    elif mutation == "session-storage-outside-fixture":
        observation["sessionWrites"][0]["storage"]["databasePath"] = "/outside/openclaw-agent.sqlite"
    elif mutation == "session-storage-sentinel-misclassified":
        observation["sessionWrites"][0]["storage"]["databasePath"] = observation["fixtureBase"] + "/incognito-openclaw-agent.sqlite"
    elif mutation in {"session-storage-private-disk", "session-storage-private-corpus"}:
        observation["sessionWrites"][0]["storage"].update(
            incognito=True,
            databasePath=observation["fixtureBase"] + "/incognito-openclaw-agent.sqlite",
            pathExists=mutation == "session-storage-private-disk",
        )
    else:
        case["input"]["steps"][0]["replaceEvents"] = [
            {
                "sessionKey": ALICE,
                "sessionId": "alice",
                "events": [],
            }
        ]
    _install(execution, config, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


@pytest.mark.parametrize(
    "missing", [*bindings.FLOW_ARTIFACTS, "adapter", "envelope-codec", "path-codec", "bootstrap"]
)
def test_real_session_profile_requires_every_actual_manager_corpus_visibility_and_transport_owner(
    session_transport, missing
):
    execution, config, case, result = session_transport
    raw = _records(execution, case, result)
    events = _events(execution, config)
    if missing in bindings.COMPILED_HASHES:
        events = [event for event in events if event.get("path") != missing]
    elif missing == "bootstrap":
        events = events[1:]
    else:
        name = {
            "adapter": "session-contract-runtime.mjs",
            "envelope-codec": "search-contract-runtime.mjs",
            "path-codec": "get-contract-runtime.mjs",
        }[missing]
        events = [event for event in events if not event.get("path", "").endswith("/" + name)]
    _install(execution, config, case, raw)
    _trace(execution, 0, events)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "generic-only",
        "wrapper-only",
        "implementation-only",
        "split-threads",
        "main-only",
        "unprotected",
    ],
)
def test_session_index_cannot_borrow_incidental_or_split_worker_authority(
    session_transport, mutation
):
    execution, config, case, result = session_transport
    raw = _records(execution, case, result)
    _install(execution, config, case, raw)
    wrapper, implementation = bindings.MEMORY_INDEX_WORKER_ARTIFACTS
    worker = [_bootstrap(execution, 1)]
    if mutation == "none":
        (execution.trace_directory / "111-1.jsonl").unlink()
    elif mutation == "generic-only":
        _trace(execution, 1, worker + [_load(config, "dist/labelled-console-worker.mjs", 1)])
    elif mutation == "wrapper-only":
        _trace(execution, 1, worker + [_load(config, wrapper, 1)])
    elif mutation == "implementation-only":
        _trace(execution, 1, worker + [_load(config, implementation, 1)])
    elif mutation == "split-threads":
        _trace(execution, 1, worker + [_load(config, wrapper, 1)])
        _trace(execution, 2, [_bootstrap(execution, 2), _load(config, implementation, 2)])
    elif mutation == "main-only":
        (execution.trace_directory / "111-1.jsonl").unlink()
    else:
        _trace(execution, 1, [_load(config, wrapper, 1), _load(config, implementation, 1)])
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


def test_session_helper_transport_needs_only_its_actual_helper_and_keeps_all_config_outputs(
    session_transport,
):
    execution, config, case, result = session_transport
    case["operation"] = "session-contract-helper-runtime"
    case["input"] = {
        "kind": "admission-policy",
        "configs": [None, {}, {"memoryPolicy": {"excludeSessions": {"channels": ["discord"]}}}],
    }
    policies = [
        {"provider": "none"},
        {"provider": "none"},
        {
            "provider": "none",
            "policy": {"channels": ["discord"], "chatTypes": [], "hookExternalContentSources": []},
        },
    ]
    result["results"][0]["result"] = {"provider": "none", "policies": policies}
    raw = [{"result": {"policies": deepcopy(policies)}}]
    events = [
        event
        for event in _events(execution, config)
        if event.get("kind") == "oracle"
        or event.get("path") in bindings.HELPER_ARTIFACTS
        or event.get("event") == "bootstrap"
    ]
    _trace(execution, 0, events)
    _evidence(execution, case, raw)
    answer = execution.collect(result, [case])
    assert answer["releaseTrace"]["protectedWorkerThreads"] == 0
    assert answer["runtimeDiagnostics"][0]["rawSnapshots"] == raw
    raw[0]["result"]["policies"].pop()
    _evidence(execution, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


@pytest.mark.parametrize(
    "operation,kind",
    [("session-contract-runtime", "admission-policy"), ("session-contract-helper-runtime", "flow")],
)
def test_session_helper_cannot_impersonate_whole_flow_or_vice_versa(
    session_transport, operation, kind
):
    execution, config, case, result = session_transport
    raw = _records(execution, case, result)
    case["operation"] = operation
    case["input"]["kind"] = kind
    _install(execution, config, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


def test_compiled_helper_entry_never_relaxes_default_manager_or_arbitrary_artifact_authority(
    session_transport,
):
    _, config, _, _ = session_transport
    owner = bindings.HELPER_ARTIFACTS[0]
    observed = _load(config, owner, 0)
    source = {key: observed[key] for key in ("package", "path", "sha256")}
    validate_release_sources(config, [source], required_entry=owner)
    with pytest.raises(ReleaseRuntimeError, match="required real runtime entry"):
        validate_release_sources(config, [source])
    arbitrary = _load(config, "dist/labelled-console-worker.mjs", 0)
    source = {key: arbitrary[key] for key in ("package", "path", "sha256")}
    with pytest.raises(ReleaseRuntimeError, match="reviewed runtime entry"):
        validate_release_sources(config, [source], required_entry=arbitrary["path"])


def _conditional_evidence(execution, case, result, kind):
    raw = _records(execution, case, result)
    observation = raw[0]
    if kind == "gateway":
        case["input"]["gateway"] = True
        observation["gatewayRequests"] = [
            {"method": "sessions.list", "params": {"spawnedBy": ALICE}}
        ]
    elif kind == "participants":
        supplied = {"identity": {"type": "profile", "id": "labelled-person"}}
        case["input"]["sessions"][0]["participants"] = [supplied]
        record = {**supplied, "firstPromptedAt": NOW, "lastPromptedAt": NOW, "promptCount": 1}
        records = {ALICE: [record]}
        observation["sessionWrites"][0]["participants"] = [None]
        observation["sessionWrites"][0]["participantRecords"] = deepcopy(records)
        observation["snapshots"][0]["participantRecords"] = deepcopy(records)
        result["results"][0]["result"]["steps"][0]["participantRecords"] = deepcopy(records)
    else:
        name = "old.jsonl.reset.2026-11-09T00-00-00.000Z"
        events = deepcopy(case["input"]["sessions"][0]["events"])
        supplied = {"name": name, "events": events}
        encoded = {
            "type": "Buffer",
            "data": list((json.dumps(events[0], separators=(",", ":")) + "\n").encode()),
        }
        filename = str(Path(observation["fixtureBase"]) / "state/agents/main/sessions" / name)
        actual = {"filename": filename, "bytes": encoded}
        if kind == "archive-persist":
            identity = {
                "sessionId": "old",
                "sessionKey": ALICE,
                "reason": "reset",
                "generation": "labelled-recorded-generation",
            }
            supplied["identity"] = identity
            descriptor = {
                "archiveName": name,
                "bytes": encoded,
                "createdAt": NOW,
                "encoding": "identity",
                "sha256": hashlib.sha256(bytes(encoded["data"])).hexdigest(),
            }
            actual = {
                "filename": filename,
                "descriptor": descriptor,
                "plan": {
                    "agentId": "main",
                    "sessionId": "old",
                    "reason": "reset",
                    "archive": descriptor,
                    "snapshot": {"sessionKey": ALICE, "generation": "labelled-recorded-generation"},
                },
                "rows": [
                    {
                        "session_id": "old",
                        "session_key": ALICE,
                        "generation": "labelled-recorded-generation",
                        "archive_name": name,
                    }
                ],
            }
        case["input"]["archives"] = [supplied]
        observation["archiveWrites"] = [actual]
    return raw


@pytest.mark.parametrize("kind", ["gateway", "participants", "archive-read", "archive-persist"])
def test_conditional_owner_protocols_retain_their_original_host_requests(session_transport, kind):
    execution, config, case, result = session_transport
    raw = _conditional_evidence(execution, case, result, kind)
    _install(execution, config, case, raw)
    answer = execution.collect(result, [case])
    assert answer["runtimeDiagnostics"][0]["rawSnapshots"] == raw


@pytest.mark.parametrize(
    "kind,missing",
    [
        *(("gateway", owner) for owner in bindings.HOSTED_GATEWAY_ARTIFACTS),
        *(("participants", owner) for owner in bindings.PARTICIPANT_ARTIFACTS),
        *(("archive-read", owner) for owner in bindings.ARCHIVE_READ_ARTIFACTS),
        *(("archive-persist", owner) for owner in bindings.ARCHIVE_PERSIST_ARTIFACTS),
    ],
)
def test_conditional_gateway_archive_and_participant_execution_requires_its_actual_owners(
    session_transport, kind, missing
):
    execution, config, case, result = session_transport
    raw = _conditional_evidence(execution, case, result, kind)
    _install(execution, config, case, raw)
    events = [event for event in _events(execution, config) if event.get("path") != missing]
    _trace(execution, 0, events)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-plan",
        "owner",
        "session-id",
        "reason",
        "generation",
        "session-key",
        "encoding",
        "digest",
        "bytes",
        "omitted",
    ],
)
def test_archive_registry_plan_cannot_change_the_original_owner_generation_or_bytes(
    session_transport, mutation
):
    execution, config, case, result = session_transport
    raw = _conditional_evidence(execution, case, result, "archive-persist")
    archive = raw[0]["archiveWrites"][0]
    if mutation == "missing-plan":
        archive.pop("plan")
    elif mutation == "owner":
        archive["plan"]["agentId"] = "peer"
    elif mutation == "session-id":
        archive["plan"]["sessionId"] = "unrelated"
    elif mutation == "reason":
        archive["plan"]["reason"] = "deleted"
    elif mutation == "generation":
        archive["plan"]["snapshot"]["generation"] = "another-recorded-generation"
    elif mutation == "session-key":
        archive["plan"]["snapshot"]["sessionKey"] = BOB
    elif mutation == "encoding":
        archive["descriptor"]["encoding"] = "zstd"
    elif mutation == "digest":
        archive["descriptor"]["sha256"] = "0" * 64
    elif mutation == "bytes":
        archive["descriptor"]["bytes"]["data"] = [0]
    else:
        raw[0]["archiveWrites"] = []
    _install(execution, config, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


def test_requested_gateway_lookup_cannot_claim_success_without_an_actual_request(session_transport):
    execution, config, case, result = session_transport
    raw = _conditional_evidence(execution, case, result, "gateway")
    raw[0]["gatewayRequests"] = []
    _install(execution, config, case, raw)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])
