from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from memory_core.bootstrap import (
    MEMORY_CORE_WORKSPACE_LAYOUT,
    OPENCLAW_PIN_LAYOUT,
    initialize_agent_workspace,
    trim_bootstrap_content,
)
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.live import (
    IDENTITY_FILE_ORDER,
    IdentityLoadError,
    JsonlTraceSink,
    LIVE_TURN_COMPLETED,
    LIVE_TURN_FAILED,
    LIVE_TURN_STARTED,
    LiveSDKConfig,
    LiveIdentity,
    LiveIdentityStore,
    LiveTurnContext,
    LiveTurnEvent,
    PROVIDER_EVENT,
    SENTENCE,
    SESSION_SUMMARY_COMPLETED,
    SESSION_SUMMARY_FAILED,
    SESSION_SUMMARY_SKIPPED,
    SESSION_SUMMARY_STARTED,
    SubjectMemory,
    TEXT_DELTA,
)
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY


def _abs(root: Path, name: str) -> str:
    return f"{os.path.abspath(root)}/{name}"


def test_identity_loader_renders_project_context_through_bootstrap(tmp_path: Path):
    root = tmp_path / "workspace"
    initialize_agent_workspace(
        root,
        templates={
            "AGENTS.md": "You are a support voice agent.\n",
            "SOUL.md": "Speak briefly.\n",
            "USER.md": "Subject profile.\n",
        },
        seed_bootstrap=False,
    )

    identity = LiveIdentity.from_dir(root)

    # Empty seeded files (TOOLS, IDENTITY, PROACTIVE_PREFERENCES, HEARTBEAT) are
    # not injected; the rest render in upstream Project Context order.
    assert identity.sections == (
        (_abs(root, "AGENTS.md"), "You are a support voice agent."),
        (_abs(root, "SOUL.md"), "Speak briefly."),
        (_abs(root, "USER.md"), "Subject profile."),
    )
    assert identity.to_prompt_section() == "\n".join(
        [
            "## Workspace Files (injected)",
            "These user-editable files are loaded by memory-core and included below in Project Context.",
            "# Project Context",
            "The following project context files have been loaded:",
            "SOUL.md: persona/tone. Follow it unless higher-priority instructions override.",
            f"## {_abs(root, 'AGENTS.md')}",
            "You are a support voice agent.",
            f"## {_abs(root, 'SOUL.md')}",
            "Speak briefly.",
            f"## {_abs(root, 'USER.md')}",
            "Subject profile.",
        ]
    )
    assert "loaded by OpenClaw" in identity.to_prompt_section(OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    assert identity.warnings == ()
    assert identity.truncated is False


def test_identity_loader_marks_missing_layout_files_like_upstream(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "AGENTS.md").write_text("Rules.", encoding="utf-8")

    identity = LiveIdentity.from_dir(identity_dir, path_style="relative")

    assert dict(identity.sections) == {
        "AGENTS.md": "Rules.",
        "SOUL.md": f"[MISSING] Expected at: {_abs(identity_dir, 'SOUL.md')}",
        "IDENTITY.md": f"[MISSING] Expected at: {_abs(identity_dir, 'IDENTITY.md')}",
        "USER.md": f"[MISSING] Expected at: {_abs(identity_dir, 'USER.md')}",
        "TOOLS.md": f"[MISSING] Expected at: {_abs(identity_dir, 'TOOLS.md')}",
        "HEARTBEAT.md": f"[MISSING] Expected at: {_abs(identity_dir, 'HEARTBEAT.md')}",
    }
    # The extension file has no upstream counterpart: absent, it renders nothing,
    # so the default layout matches the pin layout for an upstream-shaped workspace.
    pin = LiveIdentity.from_dir(identity_dir, layout=OPENCLAW_PIN_LAYOUT, path_style="relative")
    assert pin.to_prompt_section() == identity.to_prompt_section()


def test_identity_loader_keeps_agent_memory_out_by_default(tmp_path: Path):
    root = tmp_path / "workspace"
    initialize_agent_workspace(root, templates={"AGENTS.md": "Rules.\n"}, seed_bootstrap=False)
    (root / "MEMORY.md").write_text("Operator-only fact.", encoding="utf-8")

    default = LiveIdentity.from_dir(root, path_style="relative")
    with_memory = LiveIdentity.from_dir(root, path_style="relative", include_agent_memory=True)

    assert [path for path, _ in default.sections] == ["AGENTS.md"]
    assert "Operator-only fact." not in default.to_prompt_section()
    assert [path for path, _ in with_memory.sections] == ["AGENTS.md", "MEMORY.md"]
    assert "MEMORY.md: durable user preferences" in with_memory.to_prompt_section()


def test_identity_loader_enforces_required_files(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "AGENTS.md").write_text("You are a support voice agent.", encoding="utf-8")

    try:
        LiveIdentity.from_dir(identity_dir, required_files=["AGENTS.md", "SOUL.md"])
    except IdentityLoadError as exc:
        assert "SOUL.md" in str(exc)
    else:
        raise AssertionError("expected missing required identity file error")


def _assert_required_file_rejected(identity_dir: Path, name: str) -> None:
    try:
        LiveIdentity.from_dir(identity_dir, required_files=[name])
    except IdentityLoadError as exc:
        assert name in str(exc)
    else:
        raise AssertionError(f"expected {name} to fail the required-file check")


def test_identity_loader_rejects_required_files_the_guarded_read_refuses(tmp_path: Path):
    # Present on disk but rendered as "[MISSING]" by the guarded read: the
    # required-file check fails closed instead of injecting the marker.
    hardlinked = tmp_path / "hardlinked"
    hardlinked.mkdir()
    (hardlinked / "AGENTS.md").write_text("rules", encoding="utf-8")
    os.link(hardlinked / "AGENTS.md", tmp_path / "AGENTS-link.md")
    _assert_required_file_rejected(hardlinked, "AGENTS.md")

    oversized = tmp_path / "oversized"
    oversized.mkdir()
    (oversized / "SOUL.md").write_bytes(b"s" * (2 * 1024 * 1024 + 1))
    _assert_required_file_rejected(oversized, "SOUL.md")

    escaping = tmp_path / "escaping"
    escaping.mkdir()
    (tmp_path / "outside.md").write_text("outside", encoding="utf-8")
    (escaping / "USER.md").symlink_to(tmp_path / "outside.md")
    _assert_required_file_rejected(escaping, "USER.md")

    accepted = tmp_path / "accepted"
    accepted.mkdir()
    (accepted / "AGENTS.md").write_text("rules", encoding="utf-8")
    identity = LiveIdentity.from_dir(accepted, required_files=["AGENTS.md"], path_style="relative")
    assert dict(identity.sections)["AGENTS.md"] == "rules"


def test_identity_loader_can_reject_unknown_markdown_files(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "AGENTS.md").write_text("You are a support voice agent.", encoding="utf-8")
    (identity_dir / "RANDOM.md").write_text("Unexpected.", encoding="utf-8")

    try:
        LiveIdentity.from_dir(identity_dir, unknown_files="error")
    except IdentityLoadError as exc:
        assert "RANDOM.md" in str(exc)
    else:
        raise AssertionError("expected unknown identity file error")


def test_identity_loader_strict_mode_accepts_layout_and_known_workspace_files(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    for name in (*MEMORY_CORE_WORKSPACE_LAYOUT.load_order, "BOOT.md", "DREAMS.md"):
        (identity_dir / name).write_text(f"{name} text", encoding="utf-8")
    for folder in ("user", "workspace", "memory", "skills", "subjects", "notes.md"):
        (identity_dir / folder).mkdir()
    (identity_dir / "memory" / "2026-09-26.md").write_text("daily", encoding="utf-8")

    identity = LiveIdentity.from_dir(identity_dir, unknown_files="error", path_style="relative")

    injected = [path for path, _ in identity.sections]
    assert "BOOT.md" not in injected and "DREAMS.md" not in injected
    assert "MEMORY.md" not in injected
    assert "PROACTIVE_PREFERENCES.md" in injected


def test_identity_loader_truncates_with_upstream_markers(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "SOUL.md").write_text("S" * 1000, encoding="utf-8")
    (identity_dir / "USER.md").write_text("U" * 200, encoding="utf-8")

    identity = LiveIdentity.from_dir(identity_dir, max_chars_per_file=300, path_style="relative")
    compact = LiveIdentity.from_dir(identity_dir, max_chars_per_file=80, path_style="relative")

    soul = dict(identity.sections)["SOUL.md"]
    assert soul == trim_bootstrap_content("S" * 1000, "SOUL.md", 300).content
    assert "\n[...truncated, read SOUL.md for full content...]\n" in soul
    assert "…(truncated SOUL.md: kept " in soul
    assert "[truncated]" not in soul
    assert len(soul) <= 300
    assert dict(identity.sections)["USER.md"] == "U" * 200
    assert dict(compact.sections)["USER.md"] == trim_bootstrap_content("U" * 200, "USER.md", 80).content
    assert "[…truncated " in dict(compact.sections)["USER.md"]
    assert identity.truncated is True
    assert identity.warnings == (
        "workspace bootstrap file SOUL.md is 1000 chars (limit 300); truncating in injected context",
    )
    assert identity.to_prompt_section().startswith(
        "## Bootstrap Context Notice\n[Bootstrap truncation warning]"
    )


def test_identity_loader_defaults_to_upstream_caps(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "USER.md").write_text("u" * 25_000, encoding="utf-8")

    default = LiveIdentity.from_dir(identity_dir, path_style="relative")
    unset = LiveIdentity.from_dir(
        identity_dir, max_chars_per_file=None, total_max_chars=0, path_style="relative"
    )
    store = LiveIdentityStore(identity_dir)

    assert store.max_chars_per_file == 20_000
    assert store.total_max_chars == 60_000
    for identity in (default, unset):
        user = dict(identity.sections)["USER.md"]
        assert len(user) <= 20_000
        assert "…(truncated USER.md: kept " in user


def test_identity_loader_follows_bootstrap_pending_unless_overridden(tmp_path: Path):
    root = tmp_path / "workspace"
    initialize_agent_workspace(
        root, templates={"AGENTS.md": "Rules.\n", "BOOTSTRAP.md": "Ask for the operator name.\n"}
    )

    pending = LiveIdentity.from_dir(root, path_style="relative")
    overridden = LiveIdentity.from_dir(root, path_style="relative", bootstrap_mode="none")

    assert pending.to_prompt_section().startswith(
        "## Bootstrap Pending\n"
        "BOOTSTRAP.md is included below in Project Context; follow it before replying normally."
    )
    assert "BOOTSTRAP.md" in dict(pending.sections)
    assert overridden.bootstrap_text == ""
    assert "BOOTSTRAP.md" not in dict(overridden.sections)


def test_identity_file_order_is_a_compatibility_view_of_the_default_layout():
    assert tuple(name for name, _ in IDENTITY_FILE_ORDER) == MEMORY_CORE_WORKSPACE_LAYOUT.load_order
    assert all(name == title for name, title in IDENTITY_FILE_ORDER)


def test_identity_store_caches_until_reload(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    path = identity_dir / "AGENTS.md"
    path.write_text("First identity.", encoding="utf-8")
    store = LiveIdentityStore(identity_dir)

    first = store.load()
    path.write_text("Second identity.", encoding="utf-8")
    cached = store.load()
    reloaded = store.reload()

    assert first.to_prompt_section() == cached.to_prompt_section()
    assert "First identity." in cached.to_prompt_section()
    assert "Second identity." in reloaded.to_prompt_section()


def test_subject_memory_uses_separate_workspace_per_subject(tmp_path: Path):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)

    result = memory.record_session_summary(
        session_id="session_1",
        transcript="User wants evening delivery.",
        summary_llm=lambda messages: "- Subject prefers evening delivery.",
        now_ms=1_788_526_800_000,
        timezone="Europe/Istanbul",
    )

    assert result.wrote is True
    assert result.path == "memory/2026-09-04.md"
    assert (
        tmp_path / "subjects" / "subj_123" / "memory" / "2026-09-04.md"
    ).read_text(encoding="utf-8") == "- Subject prefers evening delivery.\n"
    assert not (tmp_path / "memory" / "2026-09-04.md").exists()


def test_subject_memory_can_use_custom_namespace(tmp_path: Path):
    memory = SubjectMemory.open(
        workspace_dir=tmp_path,
        subject_id="subj_123",
        namespace="accounts",
        reindex=False,
    )

    result = memory.record_session_summary(
        session_id="session_1",
        transcript="User wants evening delivery.",
        summary_llm=lambda messages: "- Subject prefers evening delivery.",
        now_ms=1_788_526_800_000,
        timezone="Europe/Istanbul",
    )

    assert result.wrote is True
    assert (tmp_path / "accounts" / "subj_123" / result.path).exists()


def test_subject_memory_can_use_custom_path_builder(tmp_path: Path):
    memory = SubjectMemory.open(
        workspace_dir=tmp_path,
        subject_id="subj_123",
        subject_path_builder=lambda root, subject_id: root / "tenants" / "default" / subject_id,
        reindex=False,
    )

    result = memory.record_session_summary(
        session_id="session_1",
        transcript="User wants evening delivery.",
        summary_llm=lambda messages: "- Subject prefers evening delivery.",
        now_ms=1_788_526_800_000,
        timezone="Europe/Istanbul",
    )

    assert result.wrote is True
    assert (tmp_path / "tenants" / "default" / "subj_123" / result.path).exists()


def test_subject_memory_rebases_a_shared_config_onto_each_subject(tmp_path: Path):
    # One MemoryConfig reused for every subject used to point all of them at
    # root/.memory-core/main.sqlite: reindexing one subject deleted the other's chunks,
    # and memory_get read from the root instead of the subject directory.
    shared = MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False))
    alice = SubjectMemory.open(
        workspace_dir=tmp_path, subject_id="alice", config=shared, reindex=False
    )
    bob = SubjectMemory.open(workspace_dir=tmp_path, subject_id="bob", config=shared, reindex=False)
    alice.memory.workspace.append_daily_memory("memory/2026-09-04.md", "- Alice prefers tulips.")
    bob.memory.workspace.append_daily_memory("memory/2026-09-04.md", "- Bob prefers orchids.")

    alice.memory.store.reindex(alice.memory.workspace)
    bob.memory.store.reindex(bob.memory.workspace)

    def paths(memory: SubjectMemory, query: str) -> list[str]:
        return [hit["path"] for hit in memory.memory.search(query)["results"]]

    assert shared.workspace_dir == tmp_path
    assert alice.memory.config.workspace_dir == tmp_path / "subjects" / "alice"
    assert bob.memory.config.resolved_store_path() == (
        tmp_path / "subjects" / "bob" / ".memory-core" / "main.sqlite"
    )
    assert not (tmp_path / ".memory-core").exists()
    assert paths(alice, "tulips") == ["memory/2026-09-04.md"]
    assert paths(alice, "orchids") == []
    assert paths(bob, "orchids") == ["memory/2026-09-04.md"]
    assert paths(bob, "tulips") == []
    assert "Alice prefers tulips." in alice.memory.get("memory/2026-09-04.md")["text"]
    assert "Bob prefers orchids." in bob.memory.get("memory/2026-09-04.md")["text"]


def test_subject_memory_rebases_or_rejects_a_shared_store_path(tmp_path: Path):
    flags = FeatureFlags(vector_search=False)
    inside_root = MemoryConfig(
        workspace_dir=tmp_path, store_path=tmp_path / "index" / "live.sqlite", flags=flags
    )
    alice = SubjectMemory.open(
        workspace_dir=tmp_path, subject_id="alice", config=inside_root, reindex=False
    )
    assert alice.memory.config.resolved_store_path() == (
        tmp_path / "subjects" / "alice" / "index" / "live.sqlite"
    )

    own_store = tmp_path / "subjects" / "bob" / "custom.sqlite"
    bob = SubjectMemory.open(
        workspace_dir=tmp_path,
        subject_id="bob",
        config=MemoryConfig(workspace_dir=tmp_path, store_path=own_store, flags=flags),
        reindex=False,
    )
    assert bob.memory.config.resolved_store_path() == own_store

    outside = MemoryConfig(
        workspace_dir=tmp_path / "state", store_path=tmp_path / "shared.sqlite", flags=flags
    )
    try:
        SubjectMemory.open(workspace_dir=tmp_path / "state", subject_id="carol", config=outside)
    except ValueError as exc:
        assert "store_path" in str(exc)
    else:
        raise AssertionError("expected a store_path outside the workspace to be rejected")
    assert not (tmp_path / "state" / "subjects" / "carol").exists()


def test_record_session_summary_writes_only_durable_structured_entries(tmp_path: Path):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")

    result = memory.record_session_summary(
        session_id="session_1",
        transcript="Transcript with durable preference.",
        summary_llm=lambda messages: json.dumps(
            {
                "durable_facts": ["Subject moved to the premium plan."],
                "preferences": ["Subject prefers evening delivery."],
                "follow_ups": ["Send updated invoice."],
                "policy_suggestions": ["Consider changing the global refund policy."],
            }
        ),
        now_ms=1_788_526_800_000,
        timezone="Europe/Istanbul",
        trace_sink=trace_sink,
    )

    memory_text = (
        tmp_path / "subjects" / "subj_123" / "memory" / "2026-09-04.md"
    ).read_text(encoding="utf-8")
    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result.wrote is True
    assert result.path == "memory/2026-09-04.md"
    assert result.durable_facts == ("Subject moved to the premium plan.",)
    assert result.preferences == ("Subject prefers evening delivery.",)
    assert result.follow_ups == ("Send updated invoice.",)
    assert "Subject moved to the premium plan." in memory_text
    assert "Subject prefers evening delivery." in memory_text
    assert "Send updated invoice." in memory_text
    assert "global refund policy" not in memory_text
    assert [record["type"] for record in records] == [
        SESSION_SUMMARY_STARTED,
        SESSION_SUMMARY_COMPLETED,
    ]


def test_record_session_summary_ignores_unknown_structured_fields(tmp_path: Path):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")

    result = memory.record_session_summary(
        session_id="session_1",
        transcript="Transcript with policy idea only.",
        summary_llm=lambda messages: json.dumps(
            {"policy_suggestions": ["Tighten escalation policy."]}
        ),
        trace_sink=trace_sink,
    )

    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result.wrote is False
    assert not list((tmp_path / "subjects" / "subj_123" / "memory").glob("*.md"))
    assert [record["type"] for record in records] == [
        SESSION_SUMMARY_STARTED,
        SESSION_SUMMARY_SKIPPED,
    ]


def test_record_session_summary_traces_failure_before_reraising(tmp_path: Path):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")

    def failing_summary(messages):
        raise RuntimeError("summary provider down")

    try:
        memory.record_session_summary(
            session_id="session_1",
            transcript="Transcript.",
            summary_llm=failing_summary,
            trace_sink=trace_sink,
        )
    except RuntimeError as exc:
        assert "summary provider down" in str(exc)
    else:
        raise AssertionError("expected summary failure to be re-raised")

    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["type"] == SESSION_SUMMARY_FAILED
    assert records[-1]["data"]["error"] == "summary provider down"


def test_async_record_session_summary_accepts_awaitable_summary_llm(tmp_path: Path):
    async def async_summary(messages):
        return json.dumps({"preferences": ["Subject prefers SMS updates."]})

    async def run_summary():
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")
        return await memory.async_record_session_summary(
            session_id="session_1",
            transcript="Subject asks for SMS updates.",
            summary_llm=async_summary,
            trace_sink=trace_sink,
        )

    result = asyncio.run(run_summary())
    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result.wrote is True
    assert result.preferences == ("Subject prefers SMS updates.",)
    assert records[-1]["type"] == SESSION_SUMMARY_COMPLETED


def test_prepare_live_turn_wraps_workflow_state_as_openclaw_runtime_context(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "AGENTS.md").write_text("You are a voice support agent.", encoding="utf-8")
    identity = LiveIdentity.from_dir(identity_dir)
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)

    prepared = memory.prepare_live_turn(
        LiveTurnContext(
            subject_id="subj_123",
            session_id="session_1",
            user_utterance="Adresimi değiştirmek istiyorum.",
            workflow_state={
                "workflow_id": "address_change",
                "current_step": "verify_identity",
                "pending_steps": ["verify_identity", "collect_new_address"],
            },
        ),
        identity=identity,
        openclaw_compatible=True,
    )

    assert prepared.messages[0]["role"] == "system"
    assert "You are a voice support agent." in prepared.messages[0]["content"]
    assert "files are loaded by OpenClaw and included below" in prepared.messages[0]["content"]
    assert OPENCLAW_COMPAT_RUNTIME_IDENTITY.runtime_context_begin in prepared.messages[0]["content"]
    assert "workflow_id: address_change" in prepared.messages[0]["content"]
    assert "current_step: verify_identity" in prepared.messages[0]["content"]
    assert prepared.messages[-1] == {
        "role": "user",
        "content": "Adresimi değiştirmek istiyorum.",
    }


def test_prepare_live_turn_places_workspace_files_before_recall(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    initialize_agent_workspace(
        identity_dir, templates={"AGENTS.md": "Verify first.\n"}, seed_bootstrap=False
    )
    identity = LiveIdentity.from_dir(identity_dir)
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)

    prepared = memory.prepare_live_turn(
        LiveTurnContext(subject_id="subj_123", session_id="session_1", user_utterance="Merhaba"),
        identity=identity,
    )

    system = prepared.messages[0]["content"]
    assert system.startswith(
        "## Workspace Files (injected)\n"
        "These user-editable files are loaded by memory-core and included below in Project Context.\n"
        "# Project Context\n"
    )
    assert "OpenClaw" not in system
    assert system.index("Verify first.") < system.index("## Session")


def test_stream_live_turn_emits_sentence_events_for_tts(tmp_path: Path):
    async def llm_stream(messages):
        assert any("Active workflow" in message["content"] for message in messages)
        for chunk in ["Tabii, ", "yardımcı olayım. ", "Önce kimliğinizi doğrulayalım."]:
            yield chunk

    async def collect_events() -> list[LiveTurnEvent]:
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        events: list[LiveTurnEvent] = []
        async for event in memory.stream_live_turn(
            LiveTurnContext(
                subject_id="subj_123",
                session_id="session_1",
                user_utterance="Adresimi değiştirmek istiyorum.",
                workflow_state={"workflow_id": "address_change"},
            ),
            llm=llm_stream,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert [event.type for event in events] == [
        "live_turn_started",
        "memory_recall_completed",
        "prompt_assembled",
        "text_delta",
        "text_delta",
        "sentence",
        "text_delta",
        "sentence",
        "live_turn_completed",
    ]
    assert [event.text for event in events if event.type == "sentence"] == [
        "Tabii, yardımcı olayım.",
        "Önce kimliğinizi doğrulayalım.",
    ]
    assert events[-1].data["assistant_text"] == (
        "Tabii, yardımcı olayım. Önce kimliğinizi doğrulayalım."
    )


def test_stream_live_turn_writes_append_only_trace_events(tmp_path: Path):
    async def llm_stream(messages):
        for chunk in ["Tamam."]:
            yield chunk

    async def collect_events() -> list[LiveTurnEvent]:
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")
        events: list[LiveTurnEvent] = []
        async for event in memory.stream_live_turn(
            LiveTurnContext(
                subject_id="subj_123",
                session_id="session_1",
                user_utterance="Selam.",
                workflow_state={"workflow_id": "greeting"},
            ),
            llm=llm_stream,
            trace_sink=trace_sink,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())
    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert [record["type"] for record in records] == [event.type for event in events]
    assert records[0]["data"] == {"subject_id": "subj_123", "session_id": "session_1"}
    assert records[-1]["data"]["assistant_text"] == "Tamam."


def test_live_event_type_constants_are_exported():
    assert LIVE_TURN_STARTED == "live_turn_started"
    assert TEXT_DELTA == "text_delta"
    assert PROVIDER_EVENT == "provider_event"
    assert SENTENCE == "sentence"
    assert LIVE_TURN_COMPLETED == "live_turn_completed"
    assert LIVE_TURN_FAILED == "live_turn_failed"
    assert SESSION_SUMMARY_STARTED == "session_summary_started"
    assert SESSION_SUMMARY_COMPLETED == "session_summary_completed"
    assert SESSION_SUMMARY_SKIPPED == "session_summary_skipped"
    assert SESSION_SUMMARY_FAILED == "session_summary_failed"


def _collect_until_failure(stream) -> tuple[list[LiveTurnEvent], BaseException | None]:
    async def run():
        events: list[LiveTurnEvent] = []
        try:
            async for event in stream:
                events.append(event)
        except Exception as exc:
            return events, exc
        return events, None

    return asyncio.run(run())


def _trace_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_stream_live_turn_yields_failure_before_reraising(tmp_path: Path):
    async def failing_stream(messages):
        yield "Basladim. "
        raise RuntimeError("provider disconnected")

    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    trace_path = tmp_path / "trace" / "session_1.jsonl"
    events, error = _collect_until_failure(
        memory.stream_live_turn(
            LiveTurnContext(subject_id="subj_123", session_id="session_1", user_utterance="Selam."),
            llm=failing_stream,
            trace_sink=JsonlTraceSink(trace_path),
        )
    )

    assert isinstance(error, RuntimeError)
    assert str(error) == "provider disconnected"
    assert events[-1] == LiveTurnEvent(
        LIVE_TURN_FAILED,
        data={
            "error_type": "RuntimeError",
            "error": "provider disconnected",
            "assistant_text": "Basladim.",
        },
    )
    records = _trace_records(trace_path)
    assert [record["type"] for record in records] == [event.type for event in events]
    assert records[-1]["data"] == events[-1].data


def test_stream_live_turn_yields_failure_on_subject_mismatch(tmp_path: Path):
    def unused_llm(messages):
        raise AssertionError("the LLM must not run for a mismatched subject")

    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    trace_path = tmp_path / "trace" / "session_1.jsonl"
    context = LiveTurnContext(subject_id="subj_999", session_id="session_1", user_utterance="Hi.")
    events, error = _collect_until_failure(
        memory.stream_live_turn(context, llm=unused_llm, trace_sink=JsonlTraceSink(trace_path))
    )

    assert isinstance(error, ValueError)
    assert "subject_id mismatch" in str(error)
    assert [event.type for event in events] == [LIVE_TURN_STARTED, LIVE_TURN_FAILED]
    assert events[-1].data == {
        "error_type": "ValueError",
        "error": "live turn subject_id mismatch: expected subj_123, got subj_999",
        "assistant_text": "",
    }
    assert [record["type"] for record in _trace_records(trace_path)] == [
        LIVE_TURN_STARTED,
        LIVE_TURN_FAILED,
    ]

    async def stop_at_failure() -> list[str]:
        seen: list[str] = []
        async for event in memory.stream_live_turn(context, llm=unused_llm):
            seen.append(event.type)
            if event.type == LIVE_TURN_FAILED:
                break
        return seen

    # A consumer that stops at the failure event closes the stream without the re-raise.
    assert asyncio.run(stop_at_failure()) == [LIVE_TURN_STARTED, LIVE_TURN_FAILED]


def test_stream_live_turn_passes_through_provider_events(tmp_path: Path):
    async def provider_stream(messages):
        yield {"type": "tool_call", "name": "lookup_order", "arguments": {"id": "ord_1"}}
        yield {"delta": "Siparisinizi kontrol ediyorum."}

    async def collect_events() -> list[LiveTurnEvent]:
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")
        events: list[LiveTurnEvent] = []
        async for event in memory.stream_live_turn(
            LiveTurnContext(
                subject_id="subj_123",
                session_id="session_1",
                user_utterance="Siparisim nerede?",
            ),
            llm=provider_stream,
            trace_sink=trace_sink,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())
    provider_events = [event for event in events if event.type == PROVIDER_EVENT]
    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert provider_events == [
        LiveTurnEvent(
            PROVIDER_EVENT,
            data={"type": "tool_call", "name": "lookup_order", "arguments": {"id": "ord_1"}},
        )
    ]
    assert any(event.type == TEXT_DELTA for event in events)
    assert any(record["type"] == PROVIDER_EVENT for record in records)


def test_stream_live_turn_accepts_sdk_config_defaults(tmp_path: Path):
    async def llm_stream(messages):
        assert "BEGIN_OPENCLAW_INTERNAL_CONTEXT" in messages[0]["content"]
        yield "Tamam."

    async def collect_events() -> list[LiveTurnEvent]:
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")
        config = LiveSDKConfig(openclaw_compatible=True, trace_sink=trace_sink)
        events: list[LiveTurnEvent] = []
        async for event in memory.stream_live_turn(
            LiveTurnContext(
                subject_id="subj_123",
                session_id="session_1",
                user_utterance="Selam.",
            ),
            llm=llm_stream,
            config=config,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert events[-1].type == LIVE_TURN_COMPLETED
    assert (tmp_path / "trace" / "session_1.jsonl").exists()


def test_identity_file_names_alias_stays_exported():
    from memory_core.live import IDENTITY_FILE_NAMES

    assert IDENTITY_FILE_NAMES == frozenset(MEMORY_CORE_WORKSPACE_LAYOUT.load_order)
