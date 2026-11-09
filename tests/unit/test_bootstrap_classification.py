"""Real filesystem identity and persisted trust feed automatic bootstrap selection."""
import pytest

from memory_core.bootstrap import (
    OPENCLAW_COMPAT_LAYOUT,
    UnsupportedBootstrapMemoryRuntimeError,
    build_workspace_context,
    classify_workspace_memory_paths,
    filter_bootstrap_files,
    load_workspace_bootstrap_files,
)
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore


def _write(root, relative, text):
    filename = root / relative
    filename.parent.mkdir(parents=True, exist_ok=True)
    filename.write_text(text)


def _record(store, root, relative, origin="untrusted"):
    text = (root / relative).read_text()
    store.record_write(workspace_dir=root, relative_path=relative, content_before=text,
        content_after=text, origin_class=origin, observed_at=1794182400000)


def _loaded(root):
    return load_workspace_bootstrap_files(root, OPENCLAW_COMPAT_LAYOUT)


def test_physical_paths_use_the_existing_default_and_system_classifiers(tmp_path):
    for name in ("USER.md", "MEMORY.md", "DREAMS.md", "memory/.dreams/internal.md", "misc.txt"):
        _write(tmp_path, name, "Actual file bytes")
    classified = classify_workspace_memory_paths(tmp_path,
        ["USER.md", "MEMORY.md", "DREAMS.md", "memory/.dreams/internal.md", "misc.txt", "missing.md", "."])
    assert [item["originClass"] for item in classified] == ["agent", "agent", "system", "system", "untrusted", "untrusted", "untrusted"]


def test_actual_recorded_quarantine_excludes_memory_and_preserves_file_order(tmp_path):
    root = tmp_path / "workspace"
    for name in ("AGENTS.md", "SOUL.md", "USER.md", "MEMORY.md"):
        _write(root, name, "Actual " + name)
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    _record(store, root, "MEMORY.md")
    _record(store, root, "USER.md", "agent")
    files = _loaded(root)
    selected = filter_bootstrap_files(files, root=root, layout=OPENCLAW_COMPAT_LAYOUT,
        config={}, artifact_provenance=store)
    assert [file.name for file in selected] == [file.name for file in files if file.name != "MEMORY.md"]
    assert classify_workspace_memory_paths(root, ["USER.md", "MEMORY.md"], artifact_provenance=store) == [
        {"relativePath": "USER.md", "originClass": "agent"},
        {"relativePath": "MEMORY.md", "originClass": "untrusted"},
    ]


def test_changed_file_bytes_do_not_erase_a_recorded_quarantine(tmp_path):
    _write(tmp_path, "MEMORY.md", "Previously quarantined")
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    _record(store, tmp_path, "MEMORY.md")
    _write(tmp_path, "MEMORY.md", "Different bytes that do not grant trust")
    assert classify_workspace_memory_paths(tmp_path, ["MEMORY.md"], artifact_provenance=store)[0]["originClass"] == "untrusted"


def test_workspace_alias_reads_the_same_real_trust_namespace(tmp_path):
    root = tmp_path / "physical"
    _write(root, "USER.md", "Private owner instructions")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    _record(store, root, "USER.md")
    assert classify_workspace_memory_paths(alias, ["USER.md"], artifact_provenance=store)[0]["originClass"] == "untrusted"


def test_realpath_escape_and_missing_paths_never_gain_the_agent_default(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    _write(tmp_path, "outside.md", "Outside bytes")
    (root / "USER.md").symlink_to(tmp_path / "outside.md")
    result = classify_workspace_memory_paths(root, ["USER.md", "../outside.md", "missing.md"])
    assert all(item["originClass"] == "untrusted" for item in result)
    files = filter_bootstrap_files(_loaded(root), root=root, config={})
    assert "USER.md" not in [file.name for file in files]


def test_canonical_file_target_uses_its_own_recorded_relative_path(tmp_path):
    _write(tmp_path, "memory/real.md", "Actual quarantined target")
    (tmp_path / "USER.md").symlink_to(tmp_path / "memory/real.md")
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    _record(store, tmp_path, "memory/real.md")
    assert classify_workspace_memory_paths(tmp_path, ["USER.md"], artifact_provenance=store)[0]["originClass"] == "untrusted"


def test_disabled_search_does_not_disable_the_provenance_owner(tmp_path):
    _write(tmp_path, "MEMORY.md", "Quarantined memory")
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    _record(store, tmp_path, "MEMORY.md")
    selected = filter_bootstrap_files(_loaded(tmp_path), root=tmp_path,
        config={"memory": {"search": {"enabled": False}}}, artifact_provenance=store)
    assert "MEMORY.md" not in [file.name for file in selected]


@pytest.mark.parametrize("plugins", [
    {"enabled": False}, {"slots": {"memory": "none"}},
    {"deny": [" MEMORY-CORE "]}, {"entries": {"memory-core": {"enabled": False}}},
])
def test_fresh_explicitly_unavailable_runtime_does_not_invent_classifications(tmp_path, plugins):
    _write(tmp_path, "MEMORY.md", "Owner-controlled memory")
    files = _loaded(tmp_path)
    assert filter_bootstrap_files(files, root=tmp_path, config={"plugins": plugins}) == files


def test_unimplemented_plugin_runtime_is_not_a_fake_builtin(tmp_path):
    _write(tmp_path, "MEMORY.md", "Owner-controlled memory")
    with pytest.raises(UnsupportedBootstrapMemoryRuntimeError, match="different-memory-runtime"):
        filter_bootstrap_files(_loaded(tmp_path), root=tmp_path,
            config={"plugins": {"slots": {"memory": "different-memory-runtime"}}})


@pytest.mark.parametrize("context_mode", ["full", "lightweight"])
def test_actual_store_failure_excludes_candidates_before_later_context_filters(tmp_path, context_mode):
    for name in ("AGENTS.md", "USER.md", "MEMORY.md"):
        _write(tmp_path, name, "Actual " + name)
    path = tmp_path / "corrupt.sqlite"
    path.write_bytes(b"Actual invalid SQLite bytes")
    warnings = []
    selected = filter_bootstrap_files(_loaded(tmp_path), root=tmp_path, context_mode=context_mode,
        config={}, artifact_provenance=MemoryArtifactProvenanceStore(path), warn=warnings.append)
    assert not {"USER.md", "MEMORY.md"} & {file.name for file in selected}
    assert len(warnings) == 1 and warnings[0].startswith("excluding automatic memory context: ")
    if context_mode == "lightweight":
        assert selected == []


def test_complete_workspace_context_uses_the_same_real_provenance_store(tmp_path):
    _write(tmp_path, "AGENTS.md", "Visible project rules")
    _write(tmp_path, "MEMORY.md", "Quarantined data must not be injected")
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    _record(store, tmp_path, "MEMORY.md")
    context = build_workspace_context(tmp_path, layout=OPENCLAW_COMPAT_LAYOUT, artifact_provenance=store)
    assert "Visible project rules" in context.prompt_text
    assert "Quarantined data must not be injected" not in context.prompt_text
    assert "MEMORY.md" not in [file.name for file in context.bootstrap_files]


def test_public_host_turn_shares_the_writer_and_index_trust_store(tmp_path):
    from memory_core import FeatureFlags, HostKit, Memory, MemoryConfig, SessionState

    _write(tmp_path, "AGENTS.md", "Visible host instructions")
    _write(tmp_path, "MEMORY.md", "Quarantined text must stay out of the real host prompt")
    store = MemoryArtifactProvenanceStore(tmp_path / "trust.sqlite")
    _record(store, tmp_path, "MEMORY.md")
    memory = Memory.from_workspace(tmp_path, initialize=False, reindex=False, artifact_provenance=store,
        config=MemoryConfig(tmp_path, flags=FeatureFlags(vector_search=False)))
    kit = HostKit(memory, layout=OPENCLAW_COMPAT_LAYOUT)
    turn = kit.before_turn(SessionState.new(session_key="agent:main:main", session_id="bootstrap-test"),
        ensure=False, offer_tools=False)
    assert "Visible host instructions" in turn.system_prompt
    assert "Quarantined text must stay out" not in turn.system_prompt
