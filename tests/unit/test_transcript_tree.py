"""Source-backed port tests for OpenClaw src/config/sessions/transcript-tree.ts.

Fixtures mirror upstream transcript-tree.test.ts at OpenClaw HEAD 4c42815348
(leaf navigation controls added by upstream commit 1a002c2d9d).
"""

from memory_core.transcript_tree import (
    UNSET,
    is_session_transcript_leaf_control,
    parse_session_transcript_tree_entry,
    scan_session_transcript_tree,
    select_session_transcript_leaf_controlled_path,
    select_session_transcript_tree_path_nodes,
)


def test_recognizes_only_valid_leaf_controls():
    assert is_session_transcript_leaf_control(
        {"type": "leaf", "id": "leaf-control", "parentId": "old-tail", "targetId": None}
    )
    # Missing targetId is invalid: only an explicit null clears the leaf.
    assert not is_session_transcript_leaf_control(
        {"type": "leaf", "id": "leaf-control", "parentId": "old-tail"}
    )


def test_treats_leaf_controls_as_navigation_to_their_target():
    parsed = parse_session_transcript_tree_entry(
        {
            "type": "leaf",
            "id": "leaf-control",
            "parentId": "inactive-tail",
            "targetId": "active-tail",
        }
    )

    assert parsed is not None
    assert parsed.id == "leaf-control"
    assert parsed.parent_id == "active-tail"
    assert parsed.leaf_id == "active-tail"
    assert parsed.append_parent_id == "active-tail"
    assert parsed.append_mode is None


def test_resolves_distinct_opaque_append_parent_from_leaf_control():
    entries = [
        {"type": "message", "id": "active-tail", "parentId": None},
        {"type": "metadata", "id": "plugin-metadata", "parentId": "active-tail"},
        {
            "type": "leaf",
            "id": "leaf-control",
            "parentId": "inactive-tail",
            "targetId": "active-tail",
            "appendParentId": "plugin-metadata",
        },
    ]

    tree = scan_session_transcript_tree(entries)

    assert tree.leaf_id == "active-tail"
    assert tree.append_parent_id == "plugin-metadata"
    assert select_session_transcript_leaf_controlled_path(entries) == entries[:1]


def test_does_not_let_later_opaque_rows_replace_visible_leaf():
    entries = [
        {"type": "message", "id": "active-root", "parentId": None},
        {"type": "message", "id": "side-entry", "parentId": "active-root"},
        {
            "type": "leaf",
            "id": "leaf-control",
            "parentId": "side-entry",
            "targetId": "active-root",
        },
        {"type": "metadata", "id": "plugin-metadata", "parentId": "side-entry"},
    ]

    tree = scan_session_transcript_tree(entries)

    assert tree.leaf_id == "active-root"
    assert tree.append_parent_id == "plugin-metadata"
    assert select_session_transcript_leaf_controlled_path(entries) == [entries[0]]


def test_supports_explicit_navigation_to_an_empty_branch():
    entries = [
        {"type": "message", "id": "old-tail", "parentId": None},
        {
            "type": "leaf",
            "id": "leaf-control",
            "parentId": "old-tail",
            "targetId": None,
            "appendParentId": "old-tail",
        },
    ]

    tree = scan_session_transcript_tree(entries)

    assert tree.leaf_id is None
    assert tree.append_parent_id == "old-tail"
    assert select_session_transcript_leaf_controlled_path(entries) == []


def test_selects_active_path_after_side_rows_and_later_active_appends():
    entries = [
        {"type": "message", "id": "active-root", "parentId": None},
        {"type": "message", "id": "side-entry", "parentId": "active-root"},
        {
            "type": "leaf",
            "id": "leaf-control",
            "parentId": "side-entry",
            "targetId": "active-root",
        },
        {"type": "message", "id": "active-tail", "parentId": "active-root"},
        {"type": "metadata", "id": "unlinked-metadata"},
    ]

    assert select_session_transcript_leaf_controlled_path(entries) == [
        entries[0],
        entries[3],
    ]


def test_normalizes_continuations_parented_to_an_omitted_leaf_marker():
    active_tail = {"type": "message", "id": "active-tail", "parentId": "active-leaf"}
    entries = [
        {"type": "message", "id": "active-root", "parentId": None},
        {"type": "message", "id": "side-entry", "parentId": "active-root"},
        {
            "type": "leaf",
            "id": "active-leaf",
            "parentId": "side-entry",
            "targetId": "active-root",
        },
        active_tail,
    ]

    tree = scan_session_transcript_tree(entries)

    assert tree.by_id["active-tail"].parent_id == "active-root"
    assert select_session_transcript_leaf_controlled_path(entries) == [
        entries[0],
        {**active_tail, "parentId": "active-root"},
    ]


def test_normalizes_parentless_continuations_after_chained_leaf_markers():
    active_tail = {"type": "message", "id": "active-tail"}
    entries = [
        {"type": "message", "id": "active-root", "parentId": None},
        {
            "type": "leaf",
            "id": "first-leaf",
            "parentId": "active-root",
            "targetId": "active-root",
        },
        {
            "type": "leaf",
            "id": "second-leaf",
            "parentId": "first-leaf",
            "targetId": "first-leaf",
        },
        active_tail,
    ]

    tree = scan_session_transcript_tree(entries)

    assert tree.by_id["active-tail"].parent_id == "active-root"
    assert select_session_transcript_leaf_controlled_path(entries) == [
        entries[0],
        {**active_tail, "parentId": "active-root"},
    ]


def test_keeps_reachable_active_suffix_when_older_parent_is_missing():
    entries = [
        {"type": "message", "id": "active-tail", "parentId": "missing-parent"},
        {
            "type": "leaf",
            "id": "leaf-control",
            "parentId": "inactive-tail",
            "targetId": "active-tail",
        },
    ]

    assert select_session_transcript_leaf_controlled_path(entries) == [entries[0]]


def test_normalizes_parentless_canonical_rows_before_applying_leaf_control():
    entries = [
        {"type": "message", "id": "root", "message": {"role": "user", "content": "root"}},
        {"type": "message", "id": "active", "message": {"role": "assistant", "content": "active"}},
        {"type": "leaf", "id": "active-leaf", "parentId": "side", "targetId": "active"},
    ]

    tree = scan_session_transcript_tree(entries)

    assert tree.by_id["root"].parent_id is None
    assert tree.by_id["active"].parent_id == "root"
    assert select_session_transcript_leaf_controlled_path(entries) == [
        {**entries[0], "parentId": None},
        {**entries[1], "parentId": "root"},
    ]


def test_selects_visible_and_disjoint_append_paths_independently():
    entries = [
        {"type": "custom", "id": "visible", "parentId": None},
        {"type": "metadata", "id": "append-root", "parentId": None},
        {
            "type": "leaf",
            "id": "active-leaf",
            "parentId": "append-root",
            "targetId": "visible",
            "appendParentId": "append-root",
        },
    ]

    tree = scan_session_transcript_tree(entries)

    visible_path = select_session_transcript_tree_path_nodes(tree, tree.leaf_id)
    append_path = select_session_transcript_tree_path_nodes(tree, tree.append_parent_id)
    assert [node.id for node in visible_path] == ["visible"]
    assert [node.id for node in append_path] == ["append-root"]


def test_keeps_selected_history_when_canonical_row_uses_disjoint_raw_cursor():
    entries = [
        {"type": "custom", "id": "visible", "parentId": None},
        {"type": "custom", "id": "inactive", "parentId": None},
        {"type": "metadata", "id": "append-root", "parentId": "inactive"},
        {
            "type": "leaf",
            "id": "active-leaf",
            "parentId": "inactive",
            "targetId": "visible",
            "appendParentId": "append-root",
            "appendMode": "side",
        },
        {"type": "custom", "id": "continued", "parentId": "append-root"},
    ]

    tree = scan_session_transcript_tree(entries)

    assert tree.by_id["continued"].parent_id == "visible"
    assert select_session_transcript_leaf_controlled_path(entries) == [
        entries[0],
        {**entries[4], "parentId": "visible"},
    ]


def test_preserves_side_ancestry_after_explicit_side_append_leaf():
    entries = [
        {"type": "custom", "id": "visible", "parentId": None},
        {"type": "custom", "id": "side-one", "parentId": "visible"},
        {
            "type": "leaf",
            "id": "first-leaf",
            "parentId": "side-one",
            "targetId": "visible",
            "appendParentId": "side-one",
            "appendMode": "side",
        },
        {"type": "custom", "id": "side-two", "parentId": "side-one", "appendMode": "side"},
    ]

    tree = scan_session_transcript_tree(entries)

    assert tree.leaf_id == "visible"
    assert tree.append_parent_id == "side-two"
    assert tree.by_id["side-two"].parent_id == "side-one"
    assert select_session_transcript_leaf_controlled_path(entries) == [entries[0]]


def test_invalid_leaf_control_is_transparent_and_does_not_navigate():
    entries = [
        {"type": "message", "id": "root", "parentId": None},
        {
            "type": "leaf",
            "id": "broken-leaf",
            "parentId": "root",
            "targetId": "unknown-target",
        },
        {"type": "message", "id": "tail", "parentId": "root"},
    ]

    tree = scan_session_transcript_tree(entries)

    assert tree.has_invalid_leaf_control is True
    # Invalid controls do not update navigation and do not count as leaf
    # controls, so readers keep legacy flat behavior.
    assert tree.has_leaf_control is False
    assert tree.leaf_id == "tail"
    assert tree.by_id["broken-leaf"].leaf_id is UNSET
    assert select_session_transcript_leaf_controlled_path(entries) is None


def test_transcripts_without_leaf_controls_keep_legacy_flat_reading():
    entries = [
        {"type": "message", "id": "a", "parentId": None},
        {"type": "message", "id": "b", "parentId": "a"},
    ]

    assert select_session_transcript_leaf_controlled_path(entries) is None
