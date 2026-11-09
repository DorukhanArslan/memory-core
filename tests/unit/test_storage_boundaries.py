"""Real filesystem/index regressions at selected workspace ownership boundaries."""
import pytest

from memory_core import Memory, MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core._memory_glob import matches_posix_glob
from memory_core.workspace import MemoryWorkspace, list_memory_files


def test_direct_workspace_cannot_reuse_another_config_owner_or_overwrite_its_index(tmp_path):
    alice, bob = tmp_path / 'alice', tmp_path / 'bob'
    alice.mkdir()
    (alice / 'MEMORY.md').write_text('Cobalt belongs to Alice.\n')
    shared = MemoryConfig(workspace_dir=alice, flags=FeatureFlags(vector_search=False))
    first = Memory.from_workspace(alice, config=shared, initialize=False)
    with pytest.raises(ValueError, match='different workspace'):
        Memory.from_workspace(bob, config=shared)
    assert not bob.exists()
    assert first.get('MEMORY.md')['text'] == 'Cobalt belongs to Alice.'
    assert first.search('Cobalt', min_score=0)['results']
    assert shared.workspace_dir == alice


def test_workspace_binding_preserves_matching_external_index_override(tmp_path):
    root, index = tmp_path / 'workspace', tmp_path / 'host-state' / 'custom.sqlite'
    root.mkdir()
    (root / 'MEMORY.md').write_text('Cobalt belongs to this workspace.\n')
    config = MemoryConfig(workspace_dir=root, store_path=index, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False)
    assert memory.store.path == index
    assert index.exists()
    assert memory.search('Cobalt', min_score=0)['results']


def test_workspace_binding_compares_resolved_identity_without_rewriting_host_configuration(tmp_path):
    root, alias = tmp_path / 'workspace', tmp_path / 'alias'
    root.mkdir()
    alias.symlink_to(root, target_is_directory=True)
    config = MemoryConfig(workspace_dir=alias, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False)
    assert memory.workspace.root == root
    assert memory.config is config
    assert config.workspace_dir == alias


def test_extra_discovery_is_a_real_public_workspace_option_with_order_and_root_deduplication(tmp_path):
    for relative in ('MEMORY.md', 'memory/default.md', 'notes/a.md', 'notes/deep/b.md', 'notes/z.md'):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Cobalt\n')
    files = MemoryWorkspace(tmp_path).discover_memory_files(extra_paths=[
        'notes/z.md', {'path': 'notes', 'pattern': '**/*.md'}, 'memory',
    ])
    assert [file.rel_path for file in files] == [
        'MEMORY.md', 'memory/default.md', 'notes/z.md', 'notes/a.md', 'notes/deep/b.md',
    ]


def test_extra_pattern_union_keeps_actual_hidden_file_glob_semantics(tmp_path):
    directory = tmp_path / 'notes'
    directory.mkdir()
    for name in ('a.md', 'b.md', 'c.md', '.hidden.md'):
        (directory / name).write_text(name)
    result = list_memory_files(tmp_path, [
        {'path': 'notes', 'pattern': '@(a|b).md'}, {'path': './notes', 'pattern': '.*.md'},
    ])
    assert [path.name for path in result] == ['.hidden.md', 'a.md', 'b.md']


def test_extra_symlink_root_callback_keeps_original_root_and_skips_descendant_links(tmp_path):
    root = tmp_path / 'notes'
    root.mkdir()
    (root / 'real.md').write_text('real')
    (root / 'alias.md').symlink_to(root / 'real.md')
    alias = tmp_path / 'alias'
    alias.symlink_to(root, target_is_directory=True)
    skipped = []
    assert list_memory_files(tmp_path, ['alias', 'notes'], on_skipped_symlink_root=skipped.append) == [root / 'real.md']
    assert skipped == [alias]


def test_multimodal_option_only_expands_explicit_extra_root_discovery(tmp_path):
    for relative in ('memory/default.png', 'media/image.PNG', 'media/sound.MP3', 'media/note.md'):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture bytes')
    settings = {'enabled': True, 'modalities': ['image'], 'maxFileBytes': 1}
    assert [path.relative_to(tmp_path).as_posix() for path in list_memory_files(tmp_path, ['media'], settings)] == [
        'media/image.PNG', 'media/note.md',
    ]


@pytest.mark.parametrize('name,pattern,expected', [
    ('😀.md', '?.md', False), ('😀.md', '??.md', True),
    ('a.md', 'sub/../*.md', True), ('a.md', './*.md', False),
    ('a999.md', 'a{1..1100}.md', True), ('𞛀.md', '[[:alpha:]].md', True),
    ('a.md', '[:alpha:].md', True), ('α.md', '[:alpha:].md', False),
    ('α.md', '[a[:alpha:]].md', True), ('α.md', '[[:ascii:][:alpha:]].md', True),
])
def test_retained_actual_node_glob_counterexamples_keep_their_original_string_semantics(name, pattern, expected):
    assert matches_posix_glob(name, pattern) is expected
