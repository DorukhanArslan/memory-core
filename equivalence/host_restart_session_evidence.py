"""Replay the complete restart family without repairing host observations.

These guards check recorded execution custody. Acceptance remains the harness's
atomic decision over all four authenticated, matching Native/SDK cases.
"""
from __future__ import annotations

import json
from pathlib import Path

from equivalence.host_restart_evidence import require
from equivalence.host_restart_publication_evidence import _validate_publication_capture
from equivalence.promotion_apply_family import differences


_OWNER_KEYS = ("ownerId", "storeId", "controllerId", "catalogId", "kitId", "agentId")


def _owner(record):
    identity = {key: record[key] for key in _OWNER_KEYS}
    ids = [identity[key] for key in _OWNER_KEYS[:-1]]
    require(all(type(value) is int and value > 0 for value in ids)
            and len(set(ids)) == len(ids), "The host lost its actual distinct owner objects")
    return identity


def _lifecycle(snapshot, *, closed=False):
    require(not snapshot["operationJournalTruncated"] and not snapshot["repairJournalTruncated"]
            and not snapshot["sessionReadJournalTruncated"], "The actual owner truncated publication or read custody")
    require(snapshot["operationCount"] == len(snapshot["operations"])
            and [row["id"] for row in snapshot["operations"]] == list(range(1, snapshot["operationCount"] + 1))
            and snapshot["repairCount"] == len(snapshot["repairs"])
            and snapshot["sessionReadAdmissionCount"] == len(snapshot["sessionReadAdmissions"])
            and [row["id"] for row in snapshot["sessionReadAdmissions"]]
            == list(range(1, snapshot["sessionReadAdmissionCount"] + 1)),
            "The actual owner's operation, repair or read journal lost entries")
    require(all(row["state"] in {"completed", "running"} for row in snapshot["operations"]),
            "The bounded host owner failed an actual index operation")
    if closed:
        require(snapshot["closed"] and not snapshot["closing"] and snapshot["activeOperations"] == 0
                and all(row["state"] == "completed" for row in snapshot["operations"]),
                "Close did not join the actual admitted index work")


def _controller(status, *, paths, closed=False):
    require(not status["jobsTruncated"] and status["jobCount"] == len(status["jobs"])
            and [row["id"] for row in status["jobs"]] == list(range(1, status["jobCount"] + 1)),
            "The actual session controller lost its job journal")
    require(status["notStarted"] is (not status["started"])
            and type(status["generation"]) is int and type(status["publishedGeneration"]) is int
            and 0 <= status["publishedGeneration"] <= status["generation"]
            and status["lastError"] is None,
            "Session publication state or physical generation custody changed")
    require(set(status["pendingPaths"]) <= paths, "A queued session target belongs to another agent or corpus")
    pending = None if not status["startupComplete"] else bool(
        status["pendingPaths"] or status["reconcilePending"] or status["activeJobs"])
    require(status["pending"] is pending, "The session controller concealed pending or unknown publication")
    if status["notStarted"]:
        require(not status["startupComplete"] and status["pending"] is None
                and status["jobCount"] == 0 and not status["activeJobs"],
                "Inert construction claimed known session readiness or launched work")
    else:
        require(status["pending"] is None or type(status["pending"]) is bool,
                "The controller invented a session readiness value")
    for job in status["jobs"]:
        require(job["reason"] in {"startup", "session-delta", "queued-session-delta", "queued-after-settlement", "explicit-reconcile"}
                and job["state"] in {"running", "completed"},
                "The host artificially flushed or failed the native session cadence")
        if "paths" in job:
            require(set(job["paths"]) <= paths, "The publisher claimed an undeclared session target")
        if "discovery" in job:
            discovery = job["discovery"]
            require(set(discovery["observed"]) <= paths and set(discovery["stalePaths"]) <= paths
                    and discovery["catalogRevisionBefore"] <= discovery["catalogRevisionAfter"],
                    "Startup discovery did not retain its actual admitted session corpus")
    if closed:
        require(status["closed"] and not status["closing"] and not status["activeJobs"]
                and not status["timerPending"] and status["inFlight"] is None
                and all(row["state"] == "completed" for row in status["jobs"]),
                "Controller close leaked physical work or flushed a future timer")


def _publisher_jobs(snapshot):
    """Bind completed queue jobs to unchanged actual scoped-store receipts."""
    status = snapshot["sessionPublication"]
    operations = [row for row in snapshot["operations"]
                  if row["name"] == "reindex-sources" and row["request"]["sources"] == ["sessions"]]
    completed = [job for job in status["jobs"] if job["state"] == "completed" and "returned" in job]
    require(len(operations) == len(completed), "Session queue and actual scoped publishers have different custody")
    for job, operation in zip(completed, operations):
        expected = None if job["reconcile"] else sorted(job["paths"])
        actual = operation["request"]["paths"]
        require((None if actual is None else sorted(actual)) == expected
                and operation["request"]["forceSources"] is False
                and operation["state"] == "completed"
                and operation["returned"] == job["returned"]
                and operation["revisionBefore"] == job["revisionBefore"]
                and operation["revisionAfter"] == job["revisionAfter"]
                and job["revisionAfter"] >= job["revisionBefore"],
                "A queue job was not published by its actual selected-session SQLite operation")


def _search(call, *, isolated):
    before, after = call["managedLifecycleBefore"], call["managedLifecycleAfter"]
    searches = [row for row in after["operations"] if row["id"] > before["operationCount"]
                and row["name"] == "search"]
    require(len(searches) == 1 and searches[0]["state"] == "completed"
            and searches[0]["query"] == call["arguments"]["query"],
            "A model search lost its actual admitted owner operation")
    search = searches[0]
    admissions = after["sessionReadAdmissions"][before["sessionReadAdmissionCount"]:]
    require(admissions and all(row["operationId"] == search["id"] and row["threadId"] == search["threadId"]
                               and type(row["revision"]) is int and row["revision"] > 0 for row in admissions),
            "Session startup bypassed the actual pinned model-search read generation")
    require(after["sessionPublication"]["started"], "The actual search did not admit its lazy controller")
    payload = call["observed"]["payload"]
    if not isolated:
        require(after["repairCount"] == before["repairCount"] and "warning" not in payload,
                "A warm reader replayed or invented an automatic repair")
        return
    require(after["repairCount"] == before["repairCount"] + 1, "The isolated cold search skipped its actual repair")
    repair = after["repairs"][-1]
    require(repair["searchOperationId"] == search["id"] and repair["reason"] == "search-bootstrap"
            and repair["force"] is True and repair["state"] == "completed"
            and repair["before"]["identity"]["status"] == "missing" and not repair["before"]["hasContent"]
            and repair["after"]["identity"]["status"] == "valid",
            "Cold bootstrap was not owned by the actual missing-index search")
    notice = after["automaticRebuildNotice"]
    require(repair["noticeSequenceBefore"] == before["automaticRebuildNotice"]["sequence"]
            and repair["noticeSequenceAfter"] == notice["sequence"] == repair["noticeSequenceBefore"] + 1
            and payload["warning"] == notice["warning"], "The cold warning did not follow its real repair request")
    publishers = [row for row in after["operations"] if row["name"] == "reindex"
                  and row["parentOperationId"] == search["id"]]
    require(len(publishers) == 1 and publishers[0]["request"] == {"force": True}
            and publishers[0]["returned"] == repair["returned"]
            and publishers[0]["revisionAfter"] == publishers[0]["revisionBefore"] + 1,
            "The repair is detached from its genuine subsequent full-index publication")


def _catalog_commits(acquired, turns, snapshots):
    """Bind postcommit notifications to original receipts and persisted rows."""
    appends = [append for turn in turns for append in turn["outcome"]["appends"]]
    changes = acquired["transcriptChanges"]
    require(len(changes) == len(appends) and changes,
            "The catalog lost actual postcommit notifications or transcript appends")
    snapshot = snapshots[-1]
    catalog = snapshot["catalog"]
    require(catalog["path"] == acquired["paths"]["catalog"] and catalog["kind"] == "sqlite",
            "The session owner borrowed a different physical catalog")
    tables = catalog["tables"]
    previous_revision = -1
    for change, append in zip(changes, appends):
        anchor = append["anchor"]
        require(append["appended"] and change["operation"] == "append-message"
                and change["agent_id"] == acquired["agentId"] == anchor["agentId"]
                and change["session_id"] == anchor["sessionId"]
                and change["session_key"] == anchor["sessionKey"]
                and change["store_path"] == anchor["storePath"] == acquired["paths"]["catalog"]
                and change["generation"] == anchor["generation"]
                and change["catalog_revision"] > previous_revision,
                "A catalog notification is detached from its actual append owner and generation")
        previous_revision = change["catalog_revision"]
        windows = [row for row in tables["memory_session_windows"]
                   if row["agent"] == change["agent_id"] and row["session_id"] == change["session_id"]]
        states = [row for row in tables["memory_session_catalog_state"] if row["agent"] == change["agent_id"]]
        require(len(windows) == len(states) == 1 and windows[0]["session_key"] == change["session_key"]
                and windows[0]["revision"] >= change["revision"]
                and windows[0]["mutation_at"] >= change["mutation_at_ms"]
                and states[0]["revision"] >= change["catalog_revision"],
                "The postcommit target revision is absent from its actual catalog SQL window")
        rows = [row for row in tables["memory_session_events"]
                if row["agent"] == anchor["agentId"] and row["session_id"] == anchor["sessionId"]
                # The SDK anchor stores an event-array index; its SQL carrier
                # starts at one, including the real initial session header.
                and row["seq"] == anchor["rawSeq"] + 1]
        require(len(rows) == 1, "The appended message anchor lost its real catalog event row")
        event = json.loads(rows[0]["event_json"])
        require(event["type"] == "message" and event["id"] == append["messageId"] == anchor["entryId"]
                and event["message"] == append["message"],
                "The committed catalog event differs from its original append result")
        readback = [row["continuation"] for row in snapshot["continuations"]
                    if row["continuation"] is not None
                    and row["entry"]["sessionId"] == anchor["sessionId"]]
        require(len(readback) == 1 and sum(item == event for item in readback[0]["events"]) == 1,
                "The actual continuation did not return its anchored committed message")


def _publication(status, *, sessions, paths):
    controller = status["controller"]
    _controller(controller, paths=paths)
    require(status["ready"] is (status["indexStatus"] == "ready"),
            "The public owner ready marker differs from its actual aggregate publication status")
    pending = status["sessionPending"]
    require(pending is None or type(pending) is bool, "The host invented a pending-session marker")
    if not sessions:
        require(pending is False, "The host invented a selected session publication domain")
    elif controller["pending"] is not False:
        require(pending is True or pending is controller["pending"],
                "The host concealed actual pending or unknown selected-session publication")
    if pending is not False:
        require(status["sessionIndexStatus"] != "ready" and status["indexStatus"] != "ready",
                "Pending or unknown sessions were reported as fully ready")
    if status["indexStatus"] == "ready":
        require(status["memoryIndexStatus"] == "ready" and pending is False,
                "The aggregate ready status omitted an unpublished source domain")
    require(status["memoryIndexStatus"] != "failed" and status["sessionIndexStatus"] != "failed"
            and status["indexStatus"] != "failed", "The bounded host publication actually failed")


def _markers(lifecycle):
    require(all(type(lifecycle[key]) is bool for key in ("needsMemoryIndex", "needsSessionIndex", "needsIndex"))
            and lifecycle["needsIndex"] is (lifecycle["needsMemoryIndex"] or lifecycle["needsSessionIndex"]),
            "Durable publication markers dropped a source or concealed pending index work")


def _turn_readiness(turn, *, sessions, paths):
    outcome, publication = turn["outcome"], turn["sessionPublicationAfterTurn"]
    _publication(publication, sessions=sessions, paths=paths)
    emitted = outcome["publication"]
    _publication(emitted, sessions=sessions, paths=paths)
    if outcome["index_status"] in {"ready", "pending"}:
        require(outcome["index_status"] == emitted["indexStatus"],
                "The public outcome changed its emission-time publication status")
    expected = (outcome["index_status"] == "ready" and not outcome["failures"] and not outcome["cancelled"]
                and outcome["memory_publication"] != "uncertain")
    require(turn["outcomeReady"] is bool(expected), "The actor changed the actual HostTurnOutcome.ready property")
    lifecycle = turn["lifecycleAfterTurn"]
    _markers(lifecycle)
    if outcome["index_status"] == "ready":
        require(not lifecycle["needsIndex"] and publication["indexStatus"] == "ready",
                "The managed runner claimed its eager ready barrier with pending publication")
    if lifecycle["needsIndex"]:
        require(outcome["index_status"] != "ready" and turn["outcomeReady"] is False,
                "A real durable pending marker was exposed as a ready outcome")
    if publication["sessionPending"] is not False:
        require(outcome["index_status"] != "ready" and not turn["outcomeReady"],
                "The completed turn exposed pending or unknown session publication as ready")
    if turn["session"] == "writer":
        require(lifecycle["needsMemoryIndex"] and lifecycle["needsIndex"]
                and outcome["index_status"] == "pending",
                "The cold producer discarded its genuinely deferred memory publication")
    if not sessions:
        require(not lifecycle["needsSessionIndex"], "A memory-only runner invented a selected session corpus")


def _durable_markers(snapshot, identity, *, sessions):
    tables = snapshot["catalog"]["tables"]
    for observed in snapshot["continuations"]:
        if observed["entry"] is None:
            continue
        lifecycle = observed["entry"]["sdkHostLifecycle"]
        _markers(lifecycle)
        continuation = observed["continuation"]
        require(continuation["entry"]["sdkHostLifecycle"] == lifecycle
                and continuation["instanceEntry"]["sdkHostLifecycle"] == lifecycle,
                "The pending marker differs across actual catalog continuation reads")
        nodes = [row for row in tables["memory_session_nodes"]
                 if row["session_key"] == identity[observed["session"]]["sessionKey"]]
        require(len(nodes) == 1 and json.loads(nodes[0]["entry_json"])["sdkHostLifecycle"] == lifecycle,
                "The pending marker was not persisted in its actual catalog SQL node")
        if sessions and not lifecycle["needsSessionIndex"]:
            session_id = identity[observed["session"]]["sessionId"]
            agent = nodes[0]["agent"]
            windows = [row for row in tables["memory_session_windows"]
                       if row["agent"] == agent and row["session_id"] == session_id]
            events = [row for row in tables["memory_session_events"]
                      if row["agent"] == agent and row["session_id"] == session_id]
            sources = [row for row in snapshot["published"]["sources"]
                       if row["source"] == "sessions" and row["path"] == f"sessions/{agent}/{session_id}.jsonl"]
            require(len(windows) == len(sources) == 1 and events,
                    "A cleared session marker has no actual published transcript source")
            mutation = windows[0]["mutation_at"]
            revision = str(int(mutation)) if isinstance(mutation, float) and mutation.is_integer() else str(mutation)
            size = sum(row["byte_size"] for row in events) + len(events) - 1
            require(sources[0]["hash"].startswith(f"sqlite:{revision}:") and sources[0]["size"] == size,
                    "A cleared session marker is not covered by the real current catalog mutation and byte size")


def validate_capture(case, raw, result, *, native):
    base = _validate_publication_capture(case, raw, result, native=native, session_managed=True)
    require(case["input"]["policy"]["indexLifecycle"] == "session-managed"
            and case["input"]["policy"]["runtimeIdentity"] == "openclaw-compatible",
            "The bounded session owner or runtime identity changed")
    if native:
        return {**base, "originalSessionRuntimeExecuted": True}
    _validate_sdk_owners(case, raw)
    return {**base, "sharedSessionOwnerCustodyPassed": True,
            "sessionPublicationCustodyPassed": True, "truthfulReadinessPassed": True}


def _validate_sdk_owners(case, raw):
    # The concrete shared-owner actor records are checked below independently of
    # the comparable public output, which contains no SDK lifecycle additions.
    identity = case["input"]["identity"]
    sessions = case["input"]["policy"]["rememberAcrossConversations"]
    for ordinal, child in enumerate(raw["phases"]):
        phase = child["observation"]["raw"]
        names = ["writer", "fresh"] if ordinal == 0 else ["restarted", "isolated"]
        require([row["sessionName"] for row in phase["opens"]] == names,
                "The host omitted an actual fresh session acquisition")
        agents = [identity["agentId"]] if ordinal == 0 else [identity["agentId"], identity["isolatedAgentId"]]
        acquisitions = phase["ownerAcquisitions"]
        require([row["agentId"] for row in acquisitions] == agents,
                "The host did not acquire exactly one actual owner per agent")
        by_agent = {row["agentId"]: row for row in acquisitions}
        for acquired in acquisitions:
            agent = acquired["agentId"]
            owner = _owner(acquired)
            root = Path(raw["fixtureBase"])
            state = root / "state/agents" / agent
            expected_paths = {"workspace": str(root / ("isolated-workspace" if agent == identity["isolatedAgentId"] else "workspace")),
                "catalog": str(state / "sessions/session-authority.sqlite"),
                "sessionStore": str(state / "sessions/sessions.json"),
                "index": str(state / "agent/openclaw-agent.sqlite")}
            require(acquired["paths"] == expected_paths, "The actual shared owner borrowed another physical corpus or database")
            selected = [name for name in names if (name == "isolated") == (agent == identity["isolatedAgentId"])]
            paths = {f"sessions/{agent}/{identity[name]['sessionId']}.jsonl"
                     for name in ("writer", "fresh", "restarted", "isolated")
                     if (name == "isolated") == (agent == identity["isolatedAgentId"])}
            construction = acquired["managedLifecycleAfterConstruction"]
            _lifecycle(construction)
            require(not construction["closed"] and construction["repairCount"] == 0
                    and construction["sessionReadAdmissionCount"] == 0,
                    "Owner construction repaired or read the index before actual host admission")
            _controller(construction["sessionPublication"], paths=paths)
            require(construction["sessionPublication"]["notStarted"], "Construction eagerly started session publication")
            _publication(acquired["publicationAfterConstruction"], sessions=sessions, paths=paths)
            opens = [row for row in phase["opens"] if row["agentId"] == agent]
            require([row["sessionName"] for row in opens] == selected
                    and all(_owner(row["sessionManagedOwner"]) == owner for row in opens)
                    and [row["ownerReused"] for row in opens] == [False] + [True] * (len(opens) - 1),
                    "Fresh chats replaced or borrowed the process's actual shared owner")
            for opened in opens:
                _lifecycle(opened["managedLifecycleAfterOpen"])
                require(opened["paths"] == expected_paths
                        and opened["managedLifecycleAfterOpen"]["workspace"] == expected_paths["workspace"]
                        and opened["managedLifecycleAfterOpen"]["indexPath"] == expected_paths["index"]
                        and opened["managedLifecycleAfterOpen"]["agentId"] == agent,
                        "The actual session owner has different physical workspace/index custody")
                expected = "missing" if opened["sessionName"] in {"writer", "isolated"} else "valid"
                require(opened["managedStatusAfterOpen"]["custom"]["indexIdentity"]["status"] == expected,
                        "The actual session acquisition silently rebuilt its index")
            closes = [row for row in phase["closeReceipts"] if row["owner"]["agentId"] == agent]
            require(len(closes) == 1, "The host must physically close each shared owner exactly once")
            close = closes[0]
            require(_owner(close["owner"]) == owner and close["sessions"] == selected
                    and close["returnedNone"] and not close["before"]["closed"]
                    and close["listenerDiagnosticsAfterClose"] == [],
                    "Close lost the shared owner, its sessions or postcommit listener failures")
            _lifecycle(close["after"], closed=True)
            _controller(close["after"]["sessionPublication"], paths=paths, closed=True)
            if ordinal != 0:
                require(all(job["reason"] != "explicit-reconcile" for job in close["after"]["sessionPublication"]["jobs"]),
                        "The restarted host manually drained its session publication cadence")
            _publisher_jobs(close["after"])
            _publication(close["publicationBefore"], sessions=sessions, paths=paths)
            _publication(close["publicationAfter"], sessions=sessions, paths=paths)
            turns = [turn for turn in phase["turns"] if turn["session"] in selected]
            snapshots = [row for row in phase["snapshots"] if row["session"] in selected]
            _catalog_commits(acquired, turns, snapshots)
        require(len(phase["closeReceipts"]) == len(acquisitions), "An owner close receipt was omitted or duplicated")
        for turn in phase["turns"]:
            agent = identity["isolatedAgentId"] if turn["session"] == "isolated" else identity["agentId"]
            require(agent in by_agent, "A turn borrowed another process owner")
            paths = {f"sessions/{agent}/{identity[name]['sessionId']}.jsonl"
                     for name in ("writer", "fresh", "restarted", "isolated")
                     if (name == "isolated") == (agent == identity["isolatedAgentId"])}
            _turn_readiness(turn, sessions=sessions, paths=paths)
            for call in turn["toolCalls"]:
                _lifecycle(call["managedLifecycleBefore"])
                _lifecycle(call["managedLifecycleAfter"])
                _controller(call["managedLifecycleBefore"]["sessionPublication"], paths=paths)
                _controller(call["managedLifecycleAfter"]["sessionPublication"], paths=paths)
                if call["name"] == "memory_search":
                    _search(call, isolated=turn["session"] == "isolated")
        for snapshot in phase["snapshots"]:
            _durable_markers(snapshot, identity, sessions=sessions)


def validate_pair(case, native_raw, sdk_raw, native_result, sdk_result):
    return {"native": validate_capture(case, native_raw, native_result, native=True),
            "sdk": validate_capture(case, sdk_raw, sdk_result, native=False),
            "structuralCustodyPassed": True, "differences": differences(native_result, sdk_result),
            "acceptancePointsAwarded": 0}


def replay_case(case, directory):
    directory = Path(directory)
    native = json.loads((directory / "evidence/native-raw.json").read_text())[0]
    sdk = json.loads((directory / "evidence/python-raw.json").read_text())[0]
    original = json.loads((directory / "stdout.json").read_text())["result"]
    implementation = json.loads((directory / "sdk-output.json").read_text())
    return validate_pair(case, native, sdk, original, implementation)
