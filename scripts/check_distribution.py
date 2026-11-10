"""Build and exercise both distributions outside the checkout (requires uv and dev tools)."""

from __future__ import annotations

import ast
from email import message_from_bytes
from email.message import Message
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

from packaging.markers import Marker
from packaging.requirements import Requirement

from memory_core.project_name import DIST_NAME, PACKAGE_NAME

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ("LICENSE.openclaw", "LICENSE.unicode")


def validate_files(files: set[str], *, kind: str) -> None:
    """Validate normalized file names without extracting an untrusted archive."""
    required = {f"{PACKAGE_NAME}/__init__.py", f"{PACKAGE_NAME}/py.typed"}
    if kind == "sdist":
        # Hatch always includes its VCS ignore file in an sdist.
        # https://hatch.pypa.io/latest/plugins/builder/sdist/#default-file-selection
        allowed_root = {"pyproject.toml", "README.md", "CHANGELOG.md", "PKG-INFO",
                        ".gitignore", *NOTICES}
        required |= {"pyproject.toml", *NOTICES}
    elif kind == "wheel":
        allowed_root = set()
        for notice in NOTICES:
            matches = {p for p in files if p.endswith(f".dist-info/licenses/{notice}")}
            if len(matches) != 1:
                raise ValueError(f"Missing artifact file: {notice}")
            required |= matches
    else:
        raise ValueError(f"Unknown artifact kind: {kind}")
    for name in files:
        path = PurePosixPath(name)
        core_file = (
            path.parts[0] == PACKAGE_NAME
            and (name.endswith(".py") or name == f"{PACKAGE_NAME}/py.typed")
        )
        wheel_metadata = (
            kind == "wheel" and len(path.parts) >= 2
            and path.parts[0].endswith(".dist-info")
            and "/".join(path.parts[1:]) in {
                "METADATA", "WHEEL", "RECORD", *(f"licenses/{notice}" for notice in NOTICES),
            }
        )
        if ".." in path.parts or path.is_absolute() or not (
            core_file or wheel_metadata or name in allowed_root
        ):
            raise ValueError(f"Unexpected artifact file: {name}")
    for name in sorted(required - files):
        raise ValueError(f"Missing artifact file: {name}")


def validate_metadata(metadata: Message, *, name: str, version: str) -> None:
    for key, expected in (("Name", name), ("Version", version), ("Requires-Python", ">=3.11")):
        if metadata.get(key) != expected:
            raise ValueError(f"{key}: expected {expected!r}, got {metadata.get(key)!r}")
    if set(metadata.get_all("License-File", [])) != set(NOTICES):
        raise ValueError("Missing upstream License-File metadata")
    if set(metadata.get_all("Provides-Extra", [])) != {"demo", "langgraph"}:
        raise ValueError("Unexpected optional extras")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    def dependency(spec: str, extra: str | None = None) -> str:
        requirement = Requirement(spec)
        if extra is not None:
            marker = f"extra == '{extra}'"
            if requirement.marker is not None:
                marker = f"({requirement.marker}) and {marker}"
            requirement.marker = Marker(marker)
        return str(requirement)

    expected = {dependency(spec) for spec in project["dependencies"]}
    for extra, specs in project["optional-dependencies"].items():
        expected.update(dependency(spec, extra) for spec in specs)
    actual = {dependency(spec) for spec in metadata.get_all("Requires-Dist", [])}
    if actual != expected:
        raise ValueError(f"Artifact dependencies differ from declaration: {actual ^ expected}")


def inspect_distribution(artifact: Path, *, version: str) -> None:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            files = {p for p in archive.namelist() if not p.endswith("/")}
            validate_files(files, kind="wheel")
            metadata_path = next(p for p in files if p.endswith(".dist-info/METADATA"))
            metadata = archive.read(metadata_path)
            notices = {name: archive.read(next(p for p in files if p.endswith("/" + name))) for name in NOTICES}
    else:
        with tarfile.open(artifact) as archive:
            members = {p.name: p for p in archive.getmembers() if not p.isdir()}
            prefix = f"{PACKAGE_NAME}-{version}/"
            if not all(p.startswith(prefix) and member.isfile() for p, member in members.items()):
                raise ValueError("Unexpected sdist root or non-regular file")
            validate_files({p.removeprefix(prefix) for p in members}, kind="sdist")
            metadata = archive.extractfile(members[prefix + "PKG-INFO"]).read()
            notices = {name: archive.extractfile(members[prefix + name]).read() for name in NOTICES}
    validate_metadata(message_from_bytes(metadata), name=DIST_NAME, version=version)
    if any(content != (ROOT / name).read_bytes() for name, content in notices.items()):
        raise ValueError("Upstream license notice changed in artifact")


# This program runs with -I from scratch, using only the installed artifact and core deps.
# The text fixture is shared with tests/unit/test_host_kit_dispatch.py.
SMOKE = '''
import asyncio
from dataclasses import replace
import importlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import pkgutil
import sqlite3
import sys
import tempfile
import tomllib

package_name, dist_name, version, checkout = sys.argv[1:]
core = importlib.import_module(package_name)
assert core.__version__ == importlib.metadata.version(dist_name) == version
assert Path(checkout).resolve() not in Path(core.__file__).resolve().parents
assert Path(core.__file__).with_name("py.typed").is_file()
for name in core.__all__:
    getattr(core, name)
for module in pkgutil.walk_packages(core.__path__, core.__name__ + "."):
    importlib.import_module(module.name)
for optional in ("fastapi", "jinja2", "uvicorn", "langgraph", "langchain_core", "openai"):
    assert importlib.util.find_spec(optional) is None, optional

with tempfile.TemporaryDirectory() as scratch:
    root = Path(scratch)
    flags = core.FeatureFlags(vector_search=False, temporal_decay=False)
    kit = core.HostKit.open(root, config=core.MemoryConfig(workspace_dir=root, flags=flags))
    kit.memory.workspace.append_daily_memory(
        "memory/2026-09-25.md", "- The zephyrquartz project is paused."
    )
    kit.memory.store.reindex(kit.memory.workspace)
    state = core.SessionState.new(session_key="agent:main:main", session_id="s1")
    turn = kit.before_turn(state)
    found = kit.dispatch("memory_search", {"query": "zephyrquartz"}, session=turn.session)
    assert [hit["path"] for hit in found["results"]] == ["memory/2026-09-25.md"], found
    retrieved = kit.dispatch("memory_get", {"path": "memory/2026-09-25.md"}, session=turn.session)
    assert retrieved["status"] == "ok", retrieved
    assert retrieved["text"].strip() == "- The zephyrquartz project is paused.", retrieved
    record = kit.after_turn(turn.session, transcript=(), usage=core.TurnUsage(1, 1))
    assert record.session.session_id == "s1" and record.flush is None
    catalog_module = importlib.import_module(package_name + ".session_catalog")
    visibility = importlib.import_module(package_name + ".session_visibility")
    catalog = catalog_module.MemorySessionCatalog(root / "sessions.sqlite")
    catalog.upsert_session("agent:main:dm:alice", {"sessionId": "alice", "chatType": "direct"})
    catalog.append_events("alice", [{"type": "message", "message": {
        "role": "user", "content": "Cedar archive authority example",
    }}])
    authority = visibility.SessionVisibilityContext.from_catalog(
        catalog, visibility.SessionVisibilityPolicy(visibility="self"),
    )
    session_root = root / "session-workspace"
    memory = core.Memory.from_workspace(
        session_root, config=core.MemoryConfig(workspace_dir=session_root, flags=flags),
        session_catalog=catalog, session_visibility=authority,
    )
    hits = memory.search("Cedar", corpus="sessions", min_score=0,
                         agent_session_key="agent:main:dm:alice")["results"]
    assert [hit["path"] for hit in hits] == ["sessions/main/alice.jsonl"], hits
    assert memory.search("Cedar", corpus="sessions", min_score=0)["results"] == []
    durable_key = "agent:main:dm:durable"
    catalog.upsert_session(durable_key, {"sessionId": "durable", "chatType": "direct"})
    user = {"role": "user", "content": "Remember kumquat tea.", "idempotencyKey": "consumer-first-turn"}
    first = catalog.append_message("durable", user, session_key=durable_key,
                                   event_id="consumer-user", cwd=str(session_root))
    catalog.append_message("durable", {"role": "assistant", "content": [
        {"type": "text", "text": "The preference is saved."},
    ]}, session_key=durable_key, event_id="consumer-assistant", cwd=str(session_root))
    reopened = catalog_module.MemorySessionCatalog(catalog.path)
    continuation = reopened.read_continuation("durable", session_key=durable_key)
    assert [message["role"] for message in continuation["llmMessages"]] == ["user", "assistant"]
    assert continuation["llmMessages"][0]["content"] == "Remember kumquat tea."
    replay = reopened.append_message("durable", user, session_key=durable_key, event_id="consumer-retry")
    assert replay["appended"] is False and replay["anchor"]["generation"] == first["anchor"]["generation"]
    assert len(reopened.read_transcript("durable", session_key=durable_key).events) == 3
    trust_module = importlib.import_module(package_name + ".turn_trust")
    dispatch_module = importlib.import_module(package_name + ".turn_tool_dispatch")
    provenance_module = importlib.import_module(package_name + ".consolidation.artifact_provenance")
    ledger = provenance_module.MemoryArtifactProvenanceStore(root / "artifact-consumer.sqlite")
    trust = trust_module.TurnTrust("consumer-turn", sender_is_owner=True)
    observer = trust.write_observer(store=ledger, mutation_root=session_root, workspace_dir=session_root,
                                    session_id="durable", session_key=durable_key, now=lambda: 1000)
    dispatcher = dispatch_module.TurnToolDispatcher(trust, [dispatch_module.TurnTool(
        "lookup", lambda _call_id, _arguments: {"content": [{"type": "text", "text": "External note"}],
                                               "extra": {"preserved": True}},
        result_content_source="network",
    )])
    assert not trust.is_tainted()
    assert dispatcher.dispatch("lookup", {}, tool_call_id="consumer-lookup")["extra"] == {"preserved": True}
    assert trust.is_tainted()
    target = session_root / "memory/consumer-turn.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    observer.write(absolute_path=target, content_before="", content_after="External note",
                   commit=lambda: target.write_text("External note", encoding="utf-8"))
    assert ledger.read(workspace_dir=session_root, relative_path="memory/consumer-turn.md").origin_class == "untrusted"
    stamped = trust.stamp_assistant({"role": "assistant", "content": [{"type": "text", "text": "Saved"}]})
    reopened.append_message("durable", stamped, session_key=durable_key, event_id="consumer-tainted")
    restored = catalog_module.MemorySessionCatalog(catalog.path).read_continuation("durable", session_key=durable_key)
    assert restored["llmMessages"][-1]["__openclaw"]["turnTainted"] is True
    data = json.dumps({"type": "message", "message": {"role": "user", "content": "Cedar"}}).encode()
    if sys.version_info >= (3, 14):
        from compression import zstd
        compressed = zstd.compress(data)
    else:
        import zstandard
        compressed = zstandard.ZstdCompressor().compress(data)
    archive = root / "source.jsonl.reset.2026-11-09T00-00-00Z.zst"
    archive.write_bytes(compressed)
    codec = importlib.import_module(package_name + ".session_archive_codec")
    assert codec.read_session_transcript_bytes(archive) == data
    discovery = importlib.import_module(package_name + ".workspace")
    extra = root / "notes"
    extra.mkdir()
    (extra / "😀.md").write_text("Supplementary filename")
    (extra / "é.md").write_text("One UTF-16 unit")
    files = discovery.list_memory_files(root, [{"path": "notes", "pattern": "??.md"}])
    assert [p.name for p in files if p.parent == extra] == ["😀.md"]
    (extra / "𞛀.md").write_text("Unicode 17 letter")
    files = discovery.list_memory_files(root, [{"path": "notes", "pattern": "[[:alpha:]].md"}])
    assert {p.name for p in files if p.parent == extra} == {"é.md", "𞛀.md"}
    mismatch = root / "another-workspace"
    try:
        core.Memory.from_workspace(mismatch, config=kit.memory.config)
    except ValueError as error:
        assert "different workspace" in str(error)
    else:
        raise AssertionError("A configured workspace owner must not rebind another workspace")
    assert not mismatch.exists()

    async def lifecycle_consumer():
        runner = core.HostSessionRunner.open(root, catalog=catalog,
            config=core.MemoryConfig(workspace_dir=root, flags=flags),
            session=core.SessionState.new(session_key="agent:main:dm:installed-lifecycle",
                                          session_id="installed-lifecycle"))

        def record_call(turn, identifier, name, arguments):
            turn.record_message({"role": "assistant", "content": [{"type": "toolCall",
                "id": identifier, "name": name, "arguments": arguments}]})

        async def save(turn):
            arguments = {"text": "The lifecycleonyx project is ready."}
            record_call(turn, "save", "append_daily_note", arguments)
            receipt = await turn.dispatch_async("save", "append_daily_note", arguments)
            assert receipt["status"] == "ok"
            turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "Saved."}]})
            return core.HostModelResult(core.TurnUsage(20, 3))

        async def recall(turn):
            arguments = {"query": "lifecycleonyx", "corpus": "memory", "minScore": 0}
            record_call(turn, "recall", "memory_search", arguments)
            receipt = await turn.dispatch_async("recall", "memory_search", arguments)
            assert any("lifecycleonyx" in hit["snippet"] for hit in receipt["results"])
            turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "Recalled."}]})

        first = await runner.run_turn("Remember lifecycleonyx.", execute=save)
        assert first.ready and first.memory_writes_committed and first.index_status == "ready"
        assert first.memory_publication == "committed"
        second = await runner.run_turn("Find lifecycleonyx.", execute=recall)
        assert second.ready and second.index_status == "ready"
        assert second.memory_publication == "none"
        restored = catalog_module.MemorySessionCatalog(catalog.path).read_continuation(
            "installed-lifecycle", session_key="agent:main:dm:installed-lifecycle")
        assert len(restored["events"]) == 9
        assert restored["instanceEntry"]["sdkHostLifecycle"]["needsIndex"] is False
        assert "pendingMemoryPublication" not in restored["instanceEntry"]["sdkHostLifecycle"]

    asyncio.run(lifecycle_consumer())
    managed_module = importlib.import_module(package_name + ".host.managed_index")
    managed_root = root / "managed-cold"
    managed_config = core.MemoryConfig(workspace_dir=managed_root, flags=flags, session_search=False)
    cold_memory = core.Memory.from_workspace(managed_root, config=managed_config,
        initialize=False, reindex=False,
        source_policy=visibility.resolve_memory_search_source_policy(["memory"]))
    cold_memory.workspace.append_daily_memory("memory/2026-11-09.md", "- The managedcedar project is ready.")
    managed_store = managed_module.ManagedSQLiteMemoryStore(managed_config, cold_memory.workspace)
    managed_kit = core.HostKit(replace(cold_memory, store=managed_store), now_ms=lambda: 1794182400000)
    assert managed_store.index_identity()["status"] == "missing"
    managed_result = managed_kit.dispatch("memory_search", {"query": "managedcedar", "minScore": 0}, session=state)
    assert managed_result["results"], managed_result
    assert managed_result["results"][0]["path"] == "memory/2026-11-09.md"
    assert managed_result["warning"] == managed_store.lifecycle_snapshot()["automaticRebuildNotice"]["warning"]
    assert managed_store.lifecycle_snapshot()["repairCount"] == 1
    repeated = managed_kit.dispatch("memory_search", {"query": "managedcedar", "minScore": 0}, session=state)
    assert "warning" not in repeated
    managed_store.close()
    assert managed_store.closed and managed_store.lifecycle_snapshot()["activeOperations"] == 0
    publication_module = importlib.import_module(package_name + ".host.session_publication")
    workspace_module = importlib.import_module(package_name + ".workspace")
    queued_root = root / "queued-sessions"
    queued_catalog = catalog_module.MemorySessionCatalog(root / "queued-catalog.sqlite",
        clock_ms=lambda: 1794182400000)
    queued_workspace = workspace_module.MemoryWorkspace(queued_root, session_catalog=queued_catalog,
        index_sources=("memory", "sessions"))
    queued_workspace.append_daily_memory("memory/2026-11-09.md", "- The queuedcedar project is ready.")
    queued_config = core.MemoryConfig(workspace_dir=queued_root, flags=flags)
    queued_store = managed_module.ManagedSQLiteMemoryStore(queued_config, queued_workspace)
    queued_store.reindex(queued_workspace)
    publication = publication_module.SessionPublicationController(queued_store, queued_workspace, queued_catalog)
    queued_store.bind_session_publication(publication)
    try:
        assert publication.status()["notStarted"] is True
        assert queued_store.search("queuedcedar", sources={"memory"})
        assert publication.wait_idle(timeout=5)
        queued_catalog.upsert_session("agent:main:queued", {"sessionId": "queued", "updatedAt": 1794182400000})
        queued_catalog.append_message("queued", {"role": "user", "content": "Remember the queuedjuniper preference."},
            session_key="agent:main:queued", event_id="queued:1", now_ms=1794182400000)
        assert publication.status()["pending"] is True
        queued_store.reindex_sources(queued_workspace, sources={"memory"})
        assert not queued_store.search("queuedjuniper", sources={"sessions"})
        publication.flush(timeout=5)
        assert queued_store.search("queuedjuniper", sources={"sessions"})
        assert queued_store.lifecycle_snapshot()["sessionReadAdmissionCount"] >= 3
    finally:
        queued_store.close()
    assert publication.status()["closed"] is True
    managed_host_module = importlib.import_module(package_name + ".host.managed_session")
    host_root = root / "managed-host"
    host_catalog = catalog_module.MemorySessionCatalog(root / "managed-host-catalog.sqlite",
        clock_ms=lambda: 1794182400000)
    host_config = core.MemoryConfig(workspace_dir=host_root, flags=flags, session_search=True)
    host_policy = visibility.resolve_memory_search_source_policy(["memory"],
        remember_across_conversations=True, configured_session_memory=False)
    host_options = {"config": host_config, "source_policy": host_policy,
        "initialize": False, "now_ms": lambda: 1794182400000}
    host = managed_host_module.ManagedHostSession.open(host_root, catalog=host_catalog, **host_options)

    async def managed_host_consumer(owner, *, save_first):
        async def save(turn):
            args = {"text": "The installedmanagedmaple preference is cedar tea."}
            turn.record_message({"role": "assistant", "content": [{"type": "toolCall", "id": "save", "name": "append_daily_note", "arguments": args}]})
            result = await turn.dispatch_async("save", "append_daily_note", args)
            assert result["status"] == "ok"
            turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "Saved."}]})

        async def recall(turn):
            args = {"query": "installedmanagedmaple", "corpus": "memory", "minScore": 0}
            turn.record_message({"role": "assistant", "content": [{"type": "toolCall", "id": "recall", "name": "memory_search", "arguments": args}]})
            result = await turn.dispatch_async("recall", "memory_search", args)
            assert result["results"] and "cedar tea" in result["results"][0]["snippet"]
            turn.record_message({"role": "assistant", "content": [{"type": "text", "text": result["results"][0]["snippet"]}]})

        if save_first:
            writer = owner.runner(core.SessionState.new(session_key="agent:main:managed-writer", session_id="managed-writer"))
            saved = await writer.run_turn("Remember installedmanagedmaple.", execute=save)
            assert saved.transcript_committed and saved.memory_writes_committed
            assert saved.index_status == "pending" and not saved.ready and not saved.failures
            assert owner.store.index_identity()["status"] == "missing"
            owner.reindex(force=True)
        name = "managed-fresh" if save_first else "managed-reopened"
        reader = owner.runner(core.SessionState.new(session_key="agent:main:" + name, session_id=name))
        assert reader.kit is owner.kit
        recalled = await reader.run_turn("Find the stored preference.", execute=recall)
        assert recalled.transcript_committed and not recalled.failures

    try:
        asyncio.run(managed_host_consumer(host, save_first=True))
    finally:
        host.close()
    reopened_catalog = catalog_module.MemorySessionCatalog(host_catalog.path,
        clock_ms=lambda: 1794182400000)
    reopened_host = managed_host_module.ManagedHostSession.open(host_root, catalog=reopened_catalog, **host_options)
    try:
        asyncio.run(managed_host_consumer(reopened_host, save_first=False))
    finally:
        reopened_host.close()
    natural_root = root / "on-search-host"
    natural_catalog = catalog_module.MemorySessionCatalog(root / "on-search-catalog.sqlite")
    natural_config = core.MemoryConfig(workspace_dir=natural_root, flags=flags, session_search=False)
    natural_host = managed_host_module.ManagedHostSession.open(natural_root, catalog=natural_catalog,
        config=natural_config, source_policy=visibility.resolve_memory_search_source_policy(["memory"]),
        memory_publication="on-search")

    async def natural_publication_consumer():
        runner = natural_host.runner(core.SessionState.new(
            session_key="agent:main:installed-on-search", session_id="installed-on-search"))
        async def invoke(name, args, identifier):
            observed = []
            async def model(turn):
                turn.record_message({"role": "assistant", "content": [{"type": "toolCall",
                    "id": identifier, "name": name, "arguments": args}]})
                observed.append(await turn.dispatch_async(identifier, name, args))
                turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "Done."}]})
            outcome = await runner.run_turn(identifier, execute=model)
            assert outcome.transcript_committed and not outcome.failures
            return outcome, observed[0]
        saved, _ = await invoke("add_memory_entry", {"section": "Facts",
            "text": "My seed fact is installedsearchseedcedar."}, "seed-save")
        assert saved.memory_writes_committed and saved.index_status == "pending"
        _, seed = await invoke("memory_search", {"query": "installedsearchseedcedar", "minScore": 0}, "seed-read")
        assert seed["results"]
        updated, _ = await invoke("add_memory_entry", {"section": "Facts",
            "text": "My new fact is installedsearchnewquince."}, "new-save")
        assert updated.memory_writes_committed and updated.index_status == "pending"
        _, immediate = await invoke("memory_search", {"query": "installedsearchnewquince", "minScore": 0}, "immediate-read")
        assert immediate["results"] == []

    try:
        asyncio.run(natural_publication_consumer())
    finally:
        natural_host.close()
    with sqlite3.connect(natural_config.resolved_store_path()) as published:
        assert published.execute("SELECT COUNT(*) FROM chunks WHERE text LIKE ?",
                                 ("%installedsearchnewquince%",)).fetchone()[0] > 0
    background_root = root / "background-maintenance-host"
    background_catalog = catalog_module.MemorySessionCatalog(root / "background-maintenance-catalog.sqlite",
        clock_ms=lambda: 1794182400000)
    background_config = core.MemoryConfig(workspace_dir=background_root, flags=flags, session_search=False)
    background_host = managed_host_module.ManagedHostSession.open(background_root, catalog=background_catalog,
        config=background_config, source_policy=visibility.resolve_memory_search_source_policy(["memory"]),
        memory_publication="on-search", maintenance="background", now_ms=lambda: 1794182400000)

    async def background_maintenance_consumer():
        runner = background_host.runner(core.SessionState.new(
            session_key="agent:main:installed-background", session_id="installed-background"))
        written, aborted = asyncio.Event(), asyncio.Event()
        deliveries = []

        async def deliver(outcome):
            deliveries.append(outcome.turn_id)

        async def first_model(turn):
            turn.record_message({"role": "assistant", "content": "Acknowledged."})
            return core.HostModelResult(core.TurnUsage(176000, 3))

        async def flush(turn):
            args = {"path": turn.flush_request.target,
                    "content": "The installedbackgroundsaffron preference is cedar tea.\\n"}
            turn.record_message({"role": "assistant", "content": [{"type": "toolCall",
                "id": "background-save", "name": "write", "arguments": args}]})
            result = await turn.dispatch_async("background-save", "write", args)
            assert result["status"] == "ok" and result["action"] == "appended"
            written.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                aborted.set()

        async def next_model(turn):
            assert aborted.is_set()
            assert background_host.maintenance_status()["jobs"][0]["settled"]
            turn.record_message({"role": "assistant", "content": "Next question admitted."})
            return core.HostModelResult(core.TurnUsage(20, 3))

        try:
            first = await runner.run_turn("Retain the preference.", execute=first_model, execute_flush=flush,
                                          request_id="background-first", deliver=deliver)
            assert first.flush is None
            await asyncio.wait_for(written.wait(), 5)
            following = await runner.run_turn("Ask the next question.", execute=next_model,
                                              request_id="background-next", deliver=deliver)
            assert not following.failures and deliveries == [first.turn_id, following.turn_id]
            job = background_host.maintenance_status()["jobs"][0]
            assert job["state"] == "cancelled" and job["outcome"]["memory_writes_committed"]
            source = next(background_root.glob("memory/*.md"))
            assert source.read_text().count("installedbackgroundsaffron") == 1
            json.dumps(background_host.maintenance_status())
        finally:
            await background_host.aclose()

    asyncio.run(background_maintenance_consumer())
print("installed core imports and FTS host lifecycle passed")
print("installed session authority and compressed archive consumers passed")
print("installed durable append, continuation and replay consumers passed")
print("installed real dispatch, live write provenance and stored turn trust consumers passed")
print("installed extra discovery, Unicode facts and workspace owner consumers passed")
print("installed serialized save, immediate recall and reopened context consumers passed")
print("installed managed cold bootstrap, live notice, warm recall and physical close consumer passed")
print("installed selected-source publication, committed session queue and read-generation consumers passed")
print("installed managed shared-host save, pending readiness and reopened recall consumer passed")
print("installed opt-in natural save, pinned warm read and background publication consumer passed")
print("installed optional maintenance write, real cancellation, next admission and delivery consumer passed")
'''


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> None:
    version_tree = ast.parse((ROOT / PACKAGE_NAME / "__init__.py").read_text(encoding="utf-8"))
    version = next(
        ast.literal_eval(node.value)
        for node in version_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    )
    # Avoid inheriting editable-package search paths into artifact consumers.
    env = dict(os.environ)
    for name in ("PYTHONPATH", "MYPYPATH", "UV_PROJECT", "UV_PROJECT_ENVIRONMENT"):
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix=f"{DIST_NAME}-distribution-") as scratch:
        work = Path(scratch)
        dist = work / "dist"
        _run(["uv", "build", str(ROOT), "--python", sys.executable, "--out-dir", str(dist)],
             cwd=work, env=env)
        wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ValueError(f"Expected one wheel and one sdist, got {wheels + sdists}")
        artifacts = wheels + sdists
        smoke = work / "smoke.py"
        smoke.write_text(SMOKE, encoding="utf-8")
        for i, artifact in enumerate(artifacts):
            inspect_distribution(artifact, version=version)
            venv = work / f"install-{i}"
            _run(["uv", "venv", "--no-project", "--python", sys.executable, str(venv)],
                 cwd=work, env=env)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            _run(["uv", "pip", "install", "--python", str(python), str(artifact)], cwd=work, env=env)
            _run(["uv", "pip", "check", "--python", str(python)], cwd=work, env=env)
            _run([str(python), "-I", str(smoke), PACKAGE_NAME, DIST_NAME, version, str(ROOT)],
                 cwd=work, env=env)
            _run([sys.executable, str(ROOT / "tests/typing/check_consumer.py"),
                  "--python-executable", str(python)], cwd=work, env=env)
            print(f"PASS {artifact.name}: contents, notice, metadata, core install, API types", flush=True)


if __name__ == "__main__":
    main()
