"""Session admission and visibility fixtures passed to actual production owners."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from equivalence.get_contract import map_get_fixture_paths
from equivalence.importance_project import _logical_published
from equivalence.search_contract import decode_search_tool_envelope


_SOURCE_PROFILE = (
    "Actual admission-policy and manager-indexability owners over the same host metadata. "
    "These isolated helpers do not prove corpus persistence, indexed search, session "
    "visibility or source-history authorization. Existing 79 raw transcript projection "
    "cases remain unchanged and gain no additional credit."
)
_POLICY = (
    "Complete owner results without field projection, ordering repair, score tolerance or "
    "fixture-computed admission/visibility decisions. Python named fields map mechanically "
    "to the native host protocol; optional absent properties remain absent. Runtime raw "
    "catalog, source reads and complete tool envelopes are retained independently."
)
_FLOW_PROFILE = (
    "Real persisted catalog/transcript mutations, corpus enumeration, manager admission, "
    "provider-none SQLite publication, complete memory-search tools and current-key source "
    "history access. No expected hits, visible-key sets or admission flags are supplied. "
    "Both owners receive includeContentRevision:false; revision-enabled discovery is not "
    "claimed. Literal reset-boundary records are inputs to the genuine transcript writer, "
    "without a new/reset hook or generated lifecycle-event claim. The declared logical "
    "published view preserves source/path/ranges/text/recall/provenance/timestamps; complete "
    "private SQL stays in raw evidence, with no binary database interchange claim. The "
    "reviewed exact owned-fixture-prefix codec applies after full wire validation. Existing "
    "79 transcript-filter fixtures and their credit remain unchanged."
)


def build_session_contract_cases() -> list[dict[str, Any]]:
    """Begin with direct owners; integrated persisted-corpus cases are added separately."""
    cases: list[dict[str, Any]] = []

    def add(name: str, kind: str, **arguments: Any) -> None:
        cases.append({"id": f"session-contract-{name}", "requirement": "sessions.corpus-admission",
                      "operation": "session-contract-helper-runtime" if kind == "admission-policy" else "session-contract",
                      "covers": [], "input": {"kind": kind, **deepcopy(arguments)},
                      "driverScope": _SOURCE_PROFILE, "normalizationPolicy": _POLICY})

    policy_configs = (
        ("absent", None), ("empty", {}), ("missing-exclusions", {"memoryPolicy": {}}),
        ("invalid-exclusions", {"memoryPolicy": {"excludeSessions": []}}),
        ("empty-lists", {"memoryPolicy": {"excludeSessions": {
            "channels": [], "chatTypes": [], "hookExternalContentSources": [],
        }}}),
        ("trimmed-channel-list", {"memoryPolicy": {"excludeSessions": {"channels": [" slack ", "", "\ufeffmatrix\u00a0"]}}}),
        ("duplicate-channel-facts", {"memoryPolicy": {"excludeSessions": {"channels": ["slack", "slack", "Slack"]}}}),
        ("ignore-nonstrings", {"memoryPolicy": {"excludeSessions": {"channels": [None, False, 3, {}, "slack"]}}}),
        ("all-policy-fields", {"memoryPolicy": {"excludeSessions": {
            "channels": ["slack"], "chatTypes": ["direct", "group", "channel"], "hookExternalContentSources": ["webhook"],
        }}}),
        ("wrong-list-type", {"memoryPolicy": {"excludeSessions": {"channels": "slack", "chatTypes": ["group"]}}}),
    )
    add("admission-policy-matrix", "admission-policy", configs=[config for _name, config in policy_configs])
    for remember in (False, True):
        for configured in (False, True):
            for name, sources in (("default", None), ("memory", ["memory"]), ("sessions", ["sessions"]),
                                  ("empty", []), ("ordered-duplicates", ["sessions", "memory", "sessions"])):
                add(f"source-policy-{int(remember)}-{int(configured)}-{name}", "source-policy", params={
                    "rememberAcrossConversations": remember, "configuredSessionMemory": configured,
                    **({"configuredSources": sources} if sources is not None else {}),
                })

    for name, entry, archived_key in (
        ("unclassified", {}, None), ("interactive", {"sessionKind": "interactive"}, None),
        ("unknown", {"sessionKind": "unknown"}, None), ("subagent", {"sessionKind": "subagent"}, None),
        ("cron-kind", {"sessionKind": "cron"}, None), ("heartbeat-kind", {"sessionKind": "heartbeat"}, None),
        ("dream-generated", {"generatedByDreamingNarrative": True}, None),
        ("cron-generated", {"generatedByCronRun": True}, None),
        ("explicit-false-flags", {"generatedByDreamingNarrative": False, "generatedByCronRun": False}, None),
        ("empty-line-provenance", {"lineProvenance": []}, None),
        ("all-system-lines", {"lineProvenance": [{"originClass": "system"}, {"originClass": "system"}]}, None),
        ("mixed-line-trust", {"lineProvenance": [{"originClass": "system"}, {"originClass": "owner"}]}, None),
        ("untrusted-lines", {"lineProvenance": [{"originClass": "untrusted"}]}, None),
        ("archive-dreaming-key", {}, "agent:main:dreaming-narrative-fixture"),
        ("archive-cron-key", {}, "agent:main:cron:fixture:run:one"),
        ("archive-heartbeat-key", {}, "agent:main:main:heartbeat"),
        ("ordinary-archive-key", {}, "agent:main:telegram:direct:42"),
    ):
        add(f"indexable-{name}", "indexable", entry=entry,
            **({"archivedSessionKey": archived_key} if archived_key is not None else {}))
    from equivalence.session_visibility_fixtures import build_visibility_flows

    for flow in [*_build_admission_flows(), *build_visibility_flows()]:
        cases.append({
            "id": f"session-contract-{flow['name']}", "requirement": flow["requirement"],
            "operation": "session-contract-runtime",
            "covers": [flow["requirement"] + ".outcomes", *(
                [flow["requirement"] + ".boundaries"]
                if flow["requirement"] == "sessions.corpus-admission" or flow["name"] in {
                    "compressed-deleted-archive-delete-and-forget",
                    "visibility-private-recall-persisted-reset-cutoff",
                } else []
            )],
            "input": deepcopy(flow["input"]),
            "driverScope": _FLOW_PROFILE,
            "normalizationPolicy": _POLICY + " The existing complete JSON text-carrier codec verifies "
            "original text against details before decoding. Exact owned fixture root aliases only; "
            "private SQL schemas are retained independently while the declared complete logical "
            "publication view is compared. Node builtin Date-only mocks control wall clock; "
            "setTimeout, performance and actual workers remain real.",
        })
    return cases


def run_session_contract(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict[str, Any]:
    """Invoke actual owners, retaining input and result field presence."""
    value = deepcopy(arguments)
    if evidence_directory is not None:
        evidence_directory = Path(evidence_directory)
    if value["kind"] == "admission-policy":
        from memory_core.consolidation.session_ingestion import resolve_admission_policy

        def render(config):
            policy = resolve_admission_policy(config)
            return None if policy is None else {
                "hookExternalContentSources": list(policy.hook_external_content_sources),
                "channels": list(policy.channels), "chatTypes": list(policy.chat_types),
            }

        if "configs" in value:
            result = {"policies": [render(config) for config in value["configs"]]}
        else:
            policy = render(value.get("pluginConfig"))
            result = {"policy": policy} if policy is not None else {}
        if evidence_directory is not None:
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(
                json.dumps([{"result": result}], ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        return {"provider": "none", **result}
    if value["kind"] == "indexable":
        from memory_core.session_corpus import is_memory_session_indexable

        return {"indexable": is_memory_session_indexable(value["entry"], value.get("archivedSessionKey"))}
    if value["kind"] == "source-policy":
        from memory_core.session_visibility import resolve_memory_search_source_policy

        params = value["params"]
        return {"policy": resolve_memory_search_source_policy(
            params.get("configuredSources"), remember_across_conversations=params["rememberAcrossConversations"],
            configured_session_memory=params["configuredSessionMemory"],
        )}
    if value["kind"] in {"runtime", "flow"}:
        return _run_session_runtime(value, evidence_directory=evidence_directory)
    raise ValueError(f"Unsupported session-contract operation: {value['kind']}")


def _run_session_runtime(value: dict[str, Any], *, evidence_directory: Path | None) -> dict[str, Any]:
    from memory_core.config import MemoryConfig
    from memory_core.consolidation.session_ingestion import (
        SessionCorpusEntry, resolve_admission_policy, session_exclusion_reason,
        session_ingestion_source_from_corpus,
    )
    from memory_core.flags import FeatureFlags
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_corpus import MemoryCoreSessionCorpus
    from memory_core.session_visibility import (
        SessionVisibilityContext, SessionVisibilityPolicy, read_visible_session_source,
        resolve_memory_search_source_policy,
    )
    from memory_core.tools.memory_search import MemorySearchToolContext
    from memory_core.tools.search_factory import create_memory_search_tool
    from memory_core.workspace import MemoryWorkspace

    if value.get("includeContentRevision", False) is not False:
        raise ValueError("This paired profile selects the real includeContentRevision:false option")
    now = value["nowMs"]
    settings = value.get("config", {})
    agent = value.get("agentId", "main")
    source_policy = resolve_memory_search_source_policy(
        settings.get("sources", ["memory", "sessions"]),
        remember_across_conversations=settings.get("rememberAcrossConversations", True),
        configured_session_memory=settings.get("configuredSessionMemory", True),
    )
    with tempfile.TemporaryDirectory(prefix="memory-session-contract-") as temporary:
        root = Path(temporary)
        workspace, state = root / "workspace", root / "state"
        workspace.mkdir()
        state.mkdir()
        catalogs: dict[str, MemorySessionCatalog] = {}
        raw: dict[str, Any] = {"fixtureBase": str(root), "constructorSkipped": False, "managerFixture": False,
                               "sessionWrites": [], "snapshots": [], "catalogRequests": [],
                               "pythonEnvelopes": [], "queryErrors": [], "reads": [],
                               "lifecycle": [], "archiveWrites": [], "managerAcquisitions": [],
                               "queryOwners": []}

        def catalog_for(identifier: str) -> MemorySessionCatalog:
            if identifier not in catalogs:
                mode = settings.get("sessionStore", "canonical")
                store_path = (state / "shared" / "sessions.json" if mode == "shared" else
                              state / "custom" / identifier / "sessions.json" if mode == "custom-template" else
                              state / "agents" / identifier / "sessions" / "sessions.json")
                catalog_path = store_path.parent / "session-authority.sqlite"
                session_settings = settings.get("session", {})
                catalogs[identifier] = MemorySessionCatalog(
                    catalog_path, agent_id=identifier, store_path=store_path, shared_store=mode == "shared",
                    main_key=session_settings.get("mainKey", "main"), session_scope=session_settings.get("scope", "per-sender"),
                    default_agent_id=agent, clock_ms=lambda: now,
                )
            return catalogs[identifier]

        def seed(item: dict[str, Any]) -> None:
            target = catalog_for(item.get("agentId", agent))
            metadata = {"updatedAt": now, **deepcopy(item["entry"])}
            target.upsert_session(item["sessionKey"], metadata)
            if "events" in item:
                target.replace_events(metadata["sessionId"], item["events"], session_key=item["sessionKey"])
            for participant in item.get("participants", []):
                target.record_participant(item["sessionKey"], {
                    **deepcopy(participant), "promptedAt": participant.get("promptedAt", now),
                    "sessionAgentId": target.agent_id,
                })
            persisted = target.read_transcript(metadata["sessionId"], session_key=item["sessionKey"])
            raw["sessionWrites"].append({"agentId": target.agent_id, "sessionKey": item["sessionKey"],
                                         "entry": metadata, "events": deepcopy(item.get("events")),
                                         "readBack": target.get_session_entry(item["sessionKey"]),
                                         "storedEntries": target.snapshot().entries,
                                         "transcript": list(persisted.events) if persisted is not None else None,
                                         "participantRecords": target.list_participants(item["sessionKey"])})

        def owned_file(base: Path, relative: str) -> Path:
            path = Path(relative)
            if path.is_absolute() or ".." in relative.replace("\\", "/").split("/"):
                raise ValueError("Fixture paths must remain in their owned root")
            return base / path

        for relative, text in value.get("files", {}).items():
            filename = owned_file(workspace, relative)
            filename.parent.mkdir(parents=True, exist_ok=True)
            filename.write_text(text, encoding="utf-8")
            os.utime(filename, ns=(now * 1_000_000, now * 1_000_000))
        for item in value.get("sessions", []):
            seed(item)
        def seed_archive(archive: dict[str, Any]) -> None:
            target = catalog_for(archive.get("agentId", agent))
            filename = owned_file(target.store_path.parent, archive["name"])
            filename.parent.mkdir(parents=True, exist_ok=True)
            payload = (bytes(archive["compressedBytes"]) if "compressedBytes" in archive else
                       ("\n".join(json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                                   for event in archive["events"]) + "\n").encode("utf-8"))
            filename.write_bytes(payload)
            os.utime(filename, ns=(now * 1_000_000, now * 1_000_000))
            identity = archive.get("identity")
            if identity is not None:
                target.record_archive(archive["name"], identity["sessionId"],
                                      session_key=identity.get("sessionKey"), path=filename)
            raw["archiveWrites"].append({"filename": str(filename), "bytes": list(payload),
                                         "identity": deepcopy(identity)})

        for archive in value.get("archives", []):
            seed_archive(archive)

        catalog = catalog_for(agent)
        corpus = MemoryCoreSessionCorpus(state, agent_id=agent, catalog=catalog,
                                        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
        policy_options = settings.get("tools", {}).get("agentToAgent", {})
        visibility = SessionVisibilityPolicy(
            visibility=settings.get("visibility", "agent"),
            sandbox_visibility=settings.get("sandboxVisibility", "spawned"),
            agent_to_agent_enabled=policy_options.get("enabled", True), agent_allow=policy_options.get("allow", ()),
            configured_agent_ids=settings.get("agentIds", [agent]),
        )
        owners: dict[str, tuple[Any, Any, Any, Any]] = {}

        def owner_for(identifier: str):
            if identifier not in owners:
                owner_catalog = catalog_for(identifier)
                owner_root = workspace if identifier == agent else workspace / identifier
                owner_root.mkdir(parents=True, exist_ok=True)
                owner_config = MemoryConfig(
                    workspace_dir=owner_root, agent_id=identifier,
                    store_path=state / "agents" / identifier / "agent" / "openclaw-agent.sqlite",
                    session_search="sessions" in source_policy["searchSources"],
                    search_max_results=200, search_min_score=0,
                    flags=FeatureFlags(vector_search=False, text_search=True, mmr=False, temporal_decay=False),
                )
                owner_store = SQLiteMemoryStore(owner_config, None)
                owner_workspace = MemoryWorkspace(
                    owner_root, openclaw_state_dir=state, agent_id=identifier,
                    session_catalog=owner_catalog, index_sources=source_policy["sources"],
                )
                owner_context = SessionVisibilityContext.from_catalog(owner_catalog, visibility)
                owners[identifier] = owner_config, owner_store, owner_workspace, owner_context
                raw["managerAcquisitions"].append({"agentId": identifier, "workspaceDir": str(owner_workspace.root),
                                                   "dbPath": str(owner_config.resolved_store_path())})
            return owners[identifier]

        config, store, memory_workspace, context = owner_for(agent)
        admission_policy = resolve_admission_policy(value.get("pluginConfig"))
        outputs = []
        for step in value.get("steps", [{"label": "initial"}]):
            for item in step.get("sessions", []):
                seed(item)
            for item in step.get("replaceEvents", []):
                target = catalog_for(item.get("agentId", agent))
                target.replace_events(item["sessionId"], item["events"], session_key=item.get("sessionKey"))
            for archive in step.get("archives", []):
                seed_archive(archive)
            for item in step.get("deleteSessions", []):
                if item.get("archiveTranscript"):
                    raise ValueError("Generated archival lifecycle actions require a production lifecycle owner")
                catalog_for(item.get("agentId", agent)).remove_session(item["sessionKey"])
                raw["lifecycle"].append({"operation": "delete", "request": deepcopy(item)})
            for identifier in step.get("forgetSessions", []):
                catalog.tombstone_session(identifier if isinstance(identifier, str) else identifier["sessionId"])
                raw["lifecycle"].append({"operation": "tombstone", "session": deepcopy(identifier)})
            store.reindex(memory_workspace)
            options = {"includeContentRevision": False, "includeRetainedSqlite": value.get("includeRetainedSqlite", False)}
            raw["catalogRequests"].append({"agentId": agent, **options})
            entries = corpus.discover_entries(include_content_revision=False,
                                              include_retained_sqlite=options["includeRetainedSqlite"])
            admitted = corpus.discover_admitted_entries()
            files = {(str(item.abs_path), item.session_id, item.artifact_kind): item for item in corpus.discover_files()}
            source_entries = []
            for entry in admitted:
                file = files[(entry["sessionFile"], entry["sessionId"], entry["artifactKind"])]
                full_entry = corpus.read_source_entry(file)
                source_entries.append({"source": deepcopy(entry), "entry": full_entry,
                                       "resetRecallCutoff": corpus.read_index_entry(file).reset_recall_cutoff})
            queries = []
            for query in step.get("queries", []):
                query_agent = query.get("agentId", agent)
                query_config, query_store, query_workspace, query_context = owner_for(query_agent)
                if query_agent != agent:
                    query_store.reindex(query_workspace)
                raw["queryOwners"].append({"queryId": query["id"], "agentId": query_agent,
                                           "workspaceDir": str(query_workspace.root),
                                           "published": query_store.read_published_index()})
                candidates = query_store.search(query["query"], max_results=query.get("maxResults", 200),
                                                min_score=query.get("minScore", 0), sources={"sessions"})
                tool_context = MemorySearchToolContext(
                    clock=lambda: now, session_visibility=query_context, source_policy=source_policy,
                    sandboxed=query.get("sandboxed"), conversation_recall=query.get("conversationRecall"),
                )
                tool = create_memory_search_tool(
                    query_config, query_store, context=tool_context, agent_session_key=query.get("requesterSessionKey"),
                    conversation_recall=query.get("conversationRecall"), runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                )
                output = {"id": query["id"], "candidates": [row.to_payload() for row in candidates]}
                try:
                    envelope = tool.execute(query["id"], {"query": query["query"], "maxResults": query.get("maxResults", 200),
                                                         "minScore": query.get("minScore", 0), "corpus": query.get("corpus", "sessions")})
                    output["result"] = decode_search_tool_envelope(envelope)
                    raw["pythonEnvelopes"].append({"label": step["label"], "queryId": query["id"],
                                                    "pythonEnvelope": deepcopy(envelope)})
                except Exception as error:
                    output["error"] = _session_error(error)
                    raw["queryErrors"].append({"label": step["label"], "queryId": query["id"],
                                                "error": deepcopy(output["error"]), "private": deepcopy(vars(error))})
                queries.append(output)
            reads = []
            for request in step.get("reads", []):
                target_agent = request.get("targetAgentId", agent)
                try:
                    read = read_visible_session_source(
                        catalog_for(target_agent), context, requester_session_key=request["requesterSessionKey"],
                        target_session_key=request["targetSessionKey"], agent_id=request.get("requesterAgentId"),
                        target_agent_id=request.get("targetAgentId"), sandboxed=request.get("sandboxed", False),
                        session_read_scope_key=request.get("sessionReadScopeKey"),
                    )
                    reads.append({"id": request["id"], **read})
                except Exception as error:
                    reads.append({"id": request["id"], "error": _session_error(error)})
                raw["reads"].append({"label": step["label"], **deepcopy(reads[-1])})
            decisions = []
            for entry in entries:
                source = session_ingestion_source_from_corpus(SessionCorpusEntry(
                    agent_id=entry["agentId"], session_id=entry["sessionId"], session_file=entry["sessionFile"],
                    session_key=entry.get("sessionKey"), session_kind=entry.get("sessionKind"),
                    artifact_kind=entry["artifactKind"], transcript_source=entry.get("transcriptSource", "file"),
                    store_path=entry.get("storePath"), updated_at_ms=entry.get("updatedAtMs"),
                    generated_by_dreaming_narrative=entry.get("generatedByDreamingNarrative", False),
                    generated_by_cron_run=entry.get("generatedByCronRun", False),
                ))
                if source is None:
                    decisions.append({"source": None})
                    continue
                payload = {"agentId": source.agent_id, "absolutePath": source.absolute_path, "foreign": source.foreign,
                           "sessionPath": source.session_path, "stateKey": source.state_key, "scope": source.scope,
                           "buildOptions": dict(source.build_options),
                           **({"sessionOrigin": dict(source.session_origin)} if source.session_origin is not None else {}),
                           **({"legacyScope": source.legacy_scope} if source.legacy_scope is not None else {})}
                reason = session_exclusion_reason(source, admission_policy, set(catalog.snapshot().forgotten_session_ids),
                                                  load_session_metadata=catalog.load_session_metadata)
                decisions.append({"source": payload, **({"reason": reason} if reason is not None else {})})
            index_sources = [{"path": row["path"], "source": row["source"]}
                             for row in store.read_published_index()["sources"]]
            snapshot = {"label": step["label"], "catalog": entries, "admitted": admitted, "sourceEntries": source_entries,
                        "published": _logical_published(store), "indexSources": index_sources,
                        "queries": queries, "reads": reads, "ingestionDecisions": decisions,
                        "participantRecords": catalog.list_participants()}
            outputs.append(snapshot)
            raw["snapshots"].append({**deepcopy(snapshot), "fullSql": store.read_published_index(),
                                      "sessionSql": {key: _catalog_sql(owner) for key, owner in catalogs.items()}})
        if evidence_directory is not None:
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(
                json.dumps([raw], ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8",
            )
        return map_get_fixture_paths({"provider": "none", "steps": outputs}, root)


def _catalog_sql(catalog) -> dict[str, Any]:
    with catalog._connect() as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {table: [dict(row) for row in db.execute('SELECT * FROM "' + table.replace('"', '""') + '"')]
                for table in tables}


def _session_error(error: BaseException) -> dict[str, Any]:
    result = {"name": getattr(error, "name", type(error).__name__), "message": str(error)}
    for field in ("code", "status", "agentIds", "surface", "hint"):
        if hasattr(error, field):
            result[field] = deepcopy(getattr(error, field))
    return result


def _build_admission_flows() -> list[dict[str, Any]]:
    now = 1_790_000_000_000

    def event(identifier: str, text: str, *, system: bool = False) -> dict[str, Any]:
        message = {"role": "user", "content": text, "timestamp": now,
                   "__openclaw": {"senderIsOwner": not system}}
        if system:
            message["provenance"] = {"kind": "internal_system"}
        return {"type": "message", "id": identifier, "message": message}

    def session(key: str, identifier: str, *, agent: str = "main", events=None, **entry):
        return {"agentId": agent, "sessionKey": key,
                "entry": {"sessionId": identifier, "updatedAt": now, "chatType": "direct", **entry},
                "events": deepcopy(events) if events is not None else [event(identifier + "-one", f"Cobalt {identifier} fact.")]}

    def query(identifier: str, **fields):
        return {"id": identifier, "query": "Cobalt", "corpus": "sessions", "minScore": 0,
                "requesterSessionKey": "agent:main:direct:bob", **fields}

    def flow(name: str, sessions: list[dict], steps: list[dict], **options):
        return {"name": name, "requirement": "sessions.corpus-admission", "input": {
            "kind": "flow", "nowMs": now, "includeContentRevision": False, "agentId": "main",
            "config": {"visibility": "agent", "sources": ["memory", "sessions"], "agentIds": ["main", "peer"],
                       **options.pop("config", {})},
            "files": {"MEMORY.md": "Cobalt workspace fact.\n"}, "sessions": sessions, "steps": steps,
            **options,
        }}

    classified = [
        session("agent:main:direct:bob", "bob"),
        session("agent:main:discord:group:room", "group", chatType="group", channel="discord"),
        session("agent:main:subagent:child", "child", spawnedBy="agent:main:direct:bob"),
        session("agent:main:cron:job:run:one", "cron"),
        session("agent:main:direct:heartbeat", "heartbeat", heartbeatIsolatedBaseSessionKey="agent:main:direct:bob"),
        session("agent:main:dreaming-narrative-fixture", "dream"),
        session("agent:main:hook:external", "hook", hookExternalContentSource="webhook"),
        session("agent:main:direct:plugin", "plugin", pluginOwnerId="example-plugin"),
        session("agent:main:dashboard:incognito-hidden", "incognito-hidden"),
        session("agent:main:direct:system-only", "system-only", events=[event("system-one", "Cobalt system operation.", system=True)]),
        session("agent:main:direct:mixed", "mixed", events=[event("mixed-system", "Cobalt system operation.", system=True),
                                                            event("mixed-owner", "Cobalt owner conversation.")]),
    ]
    classified[0]["participants"] = [
        {"identity": {"type": "agent", "id": "peer"}},
        {"identity": {"type": "agent", "id": "peer"}, "promptedAt": now + 1},
    ]
    flows = [flow("catalog-classification-and-real-line-provenance", classified,
                  [{"label": "classified-index", "queries": [query("eligible-sources")], "reads": [
                      {"id": "incognito-self-history", "requesterSessionKey": "agent:main:dashboard:incognito-hidden",
                       "targetSessionKey": "agent:main:dashboard:incognito-hidden"},
                      {"id": "incognito-other-history", "requesterSessionKey": "agent:main:direct:bob",
                       "targetSessionKey": "agent:main:dashboard:incognito-hidden"},
                  ]}],
                  pluginConfig={"memoryPolicy": {"excludeSessions": {
                      "channels": ["discord"], "chatTypes": ["group"],
                      "hookExternalContentSources": ["webhook"],
                  }}})]
    retained, rollovers = [], []
    for suffix, metadata in (("ordinary", {}), ("plugin", {"pluginOwnerId": "example-plugin"}),
                             ("hook", {"hookExternalContentSource": "webhook"}), ("acp", {"acp": {"mode": "persistent"}})):
        key = f"agent:main:direct:{suffix}"
        retained.append(session(key, suffix + "-old", **metadata))
        rollovers.extend([
            {"sessionKey": key, "entry": {"sessionId": suffix + "-old", "chatType": "direct"}},
            session(key, suffix + "-current"),
        ])
    retained.append(session("agent:main:direct:bob", "bob"))
    flows.append(flow("catalog-retained-window-metadata-gates", retained,
                      [{"label": "initial-provenance-captured", "queries": [query("before-omission-and-rollover")]},
                       {"label": "metadata-omitted-before-rollover", "sessions": rollovers,
                        "queries": [query("current-index-only")],
                        "reads": [{"id": "current-after-rollover", "requesterSessionKey": "agent:main:direct:bob",
                                   "targetSessionKey": "agent:main:direct:ordinary"}]}],
                      includeRetainedSqlite=True))
    flows.append(flow("catalog-shared-store-owner-boundary", [
        session("agent:main:direct:bob", "bob"),
        session("agent:peer:direct:foreign-row", "foreign-row", agent="peer"),
        session("agent:peer:direct:peer", "peer", agent="peer"),
        session("legacy-unscoped", "legacy"),
    ], [{"label": "shared-store", "queries": [query("selected-owner"),
                                                  query("peer-owner", agentId="peer", requesterSessionKey="agent:peer:direct:peer")]}],
        config={"sessionStore": "shared"}))
    recall = {"scope": "same-agent-private", "anchorSessionKey": "agent:main:direct:bob", "corpus": "sessions"}
    flows.append(flow("catalog-custom-store-remember-only-source-policy", [
        session("agent:main:direct:bob", "bob"), session("agent:main:direct:alice", "alice"),
    ], [{"label": "remembered-index-with-memory-only-query", "queries": [
        query("ordinary-memory-query", corpus="all"), query("explicit-disabled-sessions"),
        query("trusted-remembered-session-query", conversationRecall=recall),
    ]}], config={"sessionStore": "custom-template", "sources": ["memory"],
                 "rememberAcrossConversations": True, "configuredSessionMemory": False}))
    return [*flows, *_build_archive_flows()]


def _build_archive_flows() -> list[dict[str, Any]]:
    from base64 import b64decode

    now = 1_790_000_000_000
    bob, alice = "agent:main:direct:bob", "agent:main:direct:alice"
    recall = {"scope": "same-agent-private", "anchorSessionKey": bob, "corpus": "sessions"}

    def session(key, identifier, text):
        return {"sessionKey": key, "entry": {"sessionId": identifier, "chatType": "direct", "updatedAt": now},
                "events": [{"type": "message", "id": identifier + "-one", "message": {
                    "role": "user", "timestamp": now, "content": text, "__openclaw": {"senderIsOwner": True},
                }}]}

    def query(identifier, **fields):
        return {"id": identifier, "query": "Cobalt", "minScore": 0, "corpus": "sessions",
                "requesterSessionKey": bob, **fields}

    def read(identifier, key):
        return {"id": identifier, "requesterSessionKey": bob, "targetSessionKey": key}

    def flow(name, sessions, archive, steps, *, legacy_stem, requirement="sessions.visibility-lineage"):
        legacy = {"name": f"{legacy_stem}.jsonl.{archive['identity']['reason']}.2026-11-09T00-00-00.000Z.zst",
                  "compressedBytes": deepcopy(archive["compressedBytes"])}
        return {"name": name, "requirement": requirement, "input": {
            "kind": "flow", "nowMs": now, "includeContentRevision": False, "includeRetainedSqlite": True,
            "agentId": "main", "config": {"visibility": "all", "sources": ["memory", "sessions"]},
            "files": {"MEMORY.md": "Cobalt workspace fact.\n"},
            "sessions": sessions, "archives": [archive, legacy], "steps": steps,
        }}

    reset_bytes = 'KLUv/SCxRQQA8sgcHmBnnANtNdskMVvkCBqVTQwIdDpxiiGMhmjkCHIMYIPneb7kJuevCVCAPHLXRiXr3vA4jEw4ZKs0zxyuokhk2YpNlAAmnLz3PVxGBcTBkNwUtXqFrZHzuiSYdtKhsdencYYRrFRORpiRP6BUrzj5rWDtBAYAmxGjLFwMVwKrAEbRAgdTDw=='
    deleted_bytes = 'KLUv/SC1TQQAEgkdHnC3zQEtwprJoraIpjRKEqWoCNBBAn2Fibzk/f8uDoOmaZ7oIutxCXgA+oV/S2oK7/I4fEzAZJueXsFUhSZTVxTbkkAmjLz4xVQ+BcTBgOyQtO8IWx/rX9JSzSBMY33fvowrjEBpMvJiPv5Aeu+Ike8K1kwGAEEjvFXIAa6EVgGQoiUPph4='
    reset = {"name": "bob-prior.jsonl.reset.2026-11-09T00-00-00.000Z.11111111111141118111111111111111.zst",
             "compressedBytes": list(b64decode(reset_bytes)), "identity": {
                 "sessionId": "bob-prior", "sessionKey": bob, "reason": "reset",
                 "generation": "11111111111141118111111111111111", "createdAt": 1_794_182_400_000,
             }}
    deleted = {"name": "alice-prior.jsonl.deleted.2026-11-09T00-00-00.000Z.22222222222242228222222222222222.zst",
               "compressedBytes": list(b64decode(deleted_bytes)), "identity": {
                   "sessionId": "alice-prior", "sessionKey": alice, "reason": "deleted",
                   "generation": "22222222222242228222222222222222", "createdAt": 1_794_182_400_000,
               }}
    return [
        flow("compressed-reset-archive-forget-and-current-incarnation", [
            session(bob, "bob-prior", "Cobalt prior bob generation."),
            session(bob, "bob", "Cobalt current bob generation."),
            session(alice, "alice", "Cobalt current alice conversation."),
        ], reset, [
            {"label": "compressed-reset-source", "queries": [
                query("reset-ordinary"), query("reset-private-recall", conversationRecall=recall),
            ], "reads": [read("current-before-forget", bob)]},
            {"label": "forgotten-reset-identity", "forgetSessions": ["bob-prior"], "queries": [
                query("reset-after-forget"), query("private-after-forget", conversationRecall=recall),
            ], "reads": [read("current-source-survives-forget", bob)]},
            {"label": "current-incarnation-replaced", "sessions": [
                session(bob, "bob-next", "Cobalt newest bob generation."),
            ], "queries": [query("after-incarnation-change")],
             "reads": [read("new-current-incarnation", bob)]},
        ], legacy_stem="bob", requirement="sessions.corpus-admission"),
        flow("compressed-deleted-archive-delete-and-forget", [
            session(alice, "alice-prior", "Cobalt prior alice generation."),
            session(alice, "alice", "Cobalt current alice generation."),
            session(bob, "bob", "Cobalt current bob conversation."),
        ], deleted, [
            {"label": "compressed-deleted-source", "queries": [
                query("deleted-ordinary"), query("deleted-private-recall", conversationRecall=recall),
            ], "reads": [read("current-alice-before-delete", alice)]},
            {"label": "current-key-deleted", "deleteSessions": [{"sessionKey": alice}],
             "queries": [query("after-current-delete"), query("private-after-delete", conversationRecall=recall)],
             "reads": [read("deleted-current-key", alice)]},
            {"label": "forgotten-deleted-archive", "forgetSessions": ["alice-prior"],
             "queries": [query("after-deleted-archive-forget")], "reads": [read("source-after-forget", alice)]},
        ], legacy_stem="alice"),
    ]
