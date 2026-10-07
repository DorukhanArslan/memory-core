"""OpenClaw session transcript tree navigation (src/config/sessions/transcript-tree.ts).

Since OpenClaw commit 1a002c2d9d, session transcript JSONL can contain
``type:"leaf"`` navigation controls and ``appendMode:"side"`` side-branch
entries. Readers resolve the active leaf path instead of trusting file order;
transcripts without leaf controls keep their legacy flat rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


class _Unset:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug repr only
        return "UNSET"


#: Mirrors TypeScript ``undefined`` where ``None`` already means JSON ``null``.
UNSET = _Unset()

_CANONICAL_SESSION_ENTRY_TYPES = frozenset(
    {
        "message",
        "thinking_level_change",
        "model_change",
        "compaction",
        "reset",
        "branch_summary",
        "custom",
        "custom_message",
        "label",
        "session_info",
    }
)


@dataclass(frozen=True, kw_only=True)
class SessionTranscriptTreeEntry:
    id: str
    parent_id: str | None
    leaf_id: str | None | _Unset
    append_parent_id: str | None
    append_mode: str | None = None


@dataclass(frozen=True, kw_only=True)
class SessionTranscriptTreeNode(SessionTranscriptTreeEntry):
    entry: Any
    index: int


@dataclass(frozen=True, kw_only=True)
class SessionTranscriptTree:
    nodes: list[SessionTranscriptTreeNode]
    by_id: dict[str, SessionTranscriptTreeNode]
    leaf_id: str | None
    append_parent_id: str | None
    has_leaf_control: bool
    has_leaf_update: bool
    has_explicit_leaf_update: bool
    has_invalid_leaf_control: bool


def _read_non_empty_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def is_canonical_session_transcript_entry(record: Any) -> bool:
    return isinstance(record, dict) and record.get("type") in _CANONICAL_SESSION_ENTRY_TYPES


def is_session_transcript_side_append_entry(record: Any) -> bool:
    return is_canonical_session_transcript_entry(record) and record.get("appendMode") == "side"


def is_session_transcript_leaf_control(record: Any) -> bool:
    return (
        isinstance(record, dict)
        and record.get("type") == "leaf"
        and parse_session_transcript_tree_entry(record) is not None
    )


def parse_session_transcript_tree_entry(record: Any) -> SessionTranscriptTreeEntry | None:
    """Parse one parent-linked transcript row.

    Leaf rows are navigation controls: they select ``targetId`` as the active
    leaf, and descendants that reference the marker continue through that same
    target.
    """
    if not isinstance(record, dict) or record.get("type") == "session" or "parentId" not in record:
        return None
    entry_id = _read_non_empty_string(record.get("id"))
    raw_parent_id = record["parentId"]
    parent_id = None if raw_parent_id is None else _read_non_empty_string(raw_parent_id)
    if not entry_id or (raw_parent_id is not None and parent_id is None):
        return None
    if record.get("type") == "leaf":
        # Only an explicit null clears the leaf; a missing targetId is invalid.
        if "targetId" not in record:
            target_id: str | None | _Unset = UNSET
        else:
            raw_target_id = record["targetId"]
            target_id = (
                None if raw_target_id is None else (_read_non_empty_string(raw_target_id) or UNSET)
            )
        if "appendParentId" not in record:
            append_parent_id = target_id
        else:
            raw_append_parent_id = record["appendParentId"]
            append_parent_id = (
                None
                if raw_append_parent_id is None
                else (_read_non_empty_string(raw_append_parent_id) or UNSET)
            )
        append_mode = (
            UNSET
            if "appendMode" not in record
            else ("side" if record["appendMode"] == "side" else None)
        )
        if isinstance(target_id, _Unset) or isinstance(append_parent_id, _Unset) or append_mode is None:
            return None
        return SessionTranscriptTreeEntry(
            id=entry_id,
            parent_id=target_id,
            leaf_id=target_id,
            append_parent_id=append_parent_id,
            append_mode="side" if append_mode == "side" else None,
        )
    is_side = record.get("appendMode") == "side"
    return SessionTranscriptTreeEntry(
        id=entry_id,
        parent_id=parent_id,
        leaf_id=(
            entry_id if is_canonical_session_transcript_entry(record) and not is_side else UNSET
        ),
        append_parent_id=entry_id,
        append_mode="side" if is_side else None,
    )


def _parse_parentless_canonical_entry(
    record: Any, parent_id: str | None
) -> SessionTranscriptTreeEntry | None:
    if not is_canonical_session_transcript_entry(record) or "parentId" in record:
        return None
    entry_id = _read_non_empty_string(record.get("id"))
    if not entry_id:
        return None
    is_side = record.get("appendMode") == "side"
    return SessionTranscriptTreeEntry(
        id=entry_id,
        parent_id=parent_id,
        leaf_id=UNSET if is_side else entry_id,
        append_parent_id=entry_id,
        append_mode="side" if is_side else None,
    )


def _resolve_canonical_parent_id(
    parent_id: str | None, by_id: dict[str, SessionTranscriptTreeNode]
) -> str | None:
    seen: set[str] = set()
    current_id = parent_id
    while current_id is not None:
        if current_id in seen:
            return current_id
        seen.add(current_id)
        parent = by_id.get(current_id)
        if parent is None or not is_session_transcript_leaf_control(parent.entry):
            return current_id
        # Leaf controls are omitted from selected paths, so descendants must
        # point through the marker to its normalized visible parent.
        current_id = parent.parent_id
    return None


def scan_session_transcript_tree(entries: list[Any]) -> SessionTranscriptTree:
    """Resolve transcript navigation state in file order.

    Current-version transcripts can contain parentless canonical rows written
    by older appenders. Treat those rows as a linear continuation of the
    current append cursor so a later leaf control can still address their full
    history.
    """
    nodes: list[SessionTranscriptTreeNode] = []
    by_id: dict[str, SessionTranscriptTreeNode] = {}
    leaf_id: str | None = None
    append_parent_id: str | None = None
    has_leaf_control = False
    has_leaf_update = False
    has_explicit_leaf_update = False
    has_invalid_leaf_control = False
    invalid_leaf_control_ids: set[str] = set()
    # OpenClaw scanSessionTranscriptNavigation: a reset fences later navigation
    # and active appends to descendants of the latest reset boundary.
    latest_reset_id: str | None = None
    reset_descendant_ids: set[str] = set()

    for index, entry in enumerate(entries):
        explicit_tree_entry = parse_session_transcript_tree_entry(entry)
        if (
            latest_reset_id is not None
            and leaf_id is not None
            and explicit_tree_entry is not None
            and not isinstance(explicit_tree_entry.leaf_id, _Unset)
            and is_session_transcript_leaf_control(entry)
            and (
                explicit_tree_entry.leaf_id is None
                or explicit_tree_entry.leaf_id not in reset_descendant_ids
            )
        ):
            explicit_tree_entry = replace(
                explicit_tree_entry,
                parent_id=leaf_id,
                leaf_id=leaf_id,
                append_parent_id=leaf_id,
            )

        def _is_known_leaf_reference(ref_id: str | None) -> bool:
            return ref_id is None or (ref_id in by_id and ref_id not in invalid_leaf_control_ids)

        invalid_leaf_control = (
            explicit_tree_entry is not None
            and not isinstance(explicit_tree_entry.leaf_id, _Unset)
            and is_session_transcript_leaf_control(entry)
            and (
                not _is_known_leaf_reference(explicit_tree_entry.leaf_id)
                or not _is_known_leaf_reference(explicit_tree_entry.append_parent_id)
            )
        )
        if invalid_leaf_control:
            assert explicit_tree_entry is not None
            has_invalid_leaf_control = True
            invalid_leaf_control_ids.add(explicit_tree_entry.id)
            raw_parent_id = entry.get("parentId") if isinstance(entry, dict) else None
            node = SessionTranscriptTreeNode(
                id=explicit_tree_entry.id,
                parent_id=raw_parent_id,
                leaf_id=UNSET,
                append_parent_id=append_parent_id,
                append_mode=explicit_tree_entry.append_mode,
                entry=entry,
                index=index,
            )
            # Invalid controls are transparent structural markers. Descendants
            # can repair through their raw parent, but navigation state does
            # not change.
            nodes.append(node)
            by_id[node.id] = node
            continue

        tree_entry = explicit_tree_entry or _parse_parentless_canonical_entry(entry, leaf_id)
        if tree_entry is not None and is_canonical_session_transcript_entry(entry):
            canonical_parent_is_stale = (
                explicit_tree_entry is not None
                and tree_entry.parent_id is not None
                and tree_entry.parent_id not in by_id
                and leaf_id is not None
            )
            crosses_reset_boundary = (
                latest_reset_id is not None
                and tree_entry.append_mode != "side"
                and (
                    tree_entry.parent_id is None
                    or tree_entry.parent_id not in reset_descendant_ids
                )
            )
            if (
                crosses_reset_boundary
                or (tree_entry.append_mode != "side" and canonical_parent_is_stale)
                or (
                    explicit_tree_entry is not None
                    and tree_entry.append_mode != "side"
                    and tree_entry.parent_id == append_parent_id
                    and leaf_id != append_parent_id
                )
            ):
                logical_parent_id = leaf_id
            else:
                logical_parent_id = tree_entry.parent_id
            normalized_parent_id = _resolve_canonical_parent_id(logical_parent_id, by_id)
            if normalized_parent_id != tree_entry.parent_id:
                # The raw cursor can belong to plugin metadata, an inactive
                # branch, or an omitted leaf marker. Keep physical append state
                # separate from the visible ancestry consumed by readers.
                tree_entry = replace(tree_entry, parent_id=normalized_parent_id)
        if tree_entry is None:
            continue
        node = SessionTranscriptTreeNode(
            id=tree_entry.id,
            parent_id=tree_entry.parent_id,
            leaf_id=tree_entry.leaf_id,
            append_parent_id=tree_entry.append_parent_id,
            append_mode=tree_entry.append_mode,
            entry=entry,
            index=index,
        )
        nodes.append(node)
        by_id[node.id] = node
        if isinstance(entry, dict) and entry.get("type") == "reset":
            latest_reset_id = node.id
            reset_descendant_ids.clear()
            reset_descendant_ids.add(node.id)
        elif latest_reset_id is not None and node.parent_id in reset_descendant_ids:
            reset_descendant_ids.add(node.id)
        append_parent_id = node.append_parent_id
        if not isinstance(node.leaf_id, _Unset):
            leaf_id = node.leaf_id
            has_leaf_update = True
            if explicit_tree_entry is not None:
                has_explicit_leaf_update = True
        if is_session_transcript_leaf_control(entry):
            has_leaf_control = True

    return SessionTranscriptTree(
        nodes=nodes,
        by_id=by_id,
        leaf_id=leaf_id,
        append_parent_id=append_parent_id,
        has_leaf_control=has_leaf_control,
        has_leaf_update=has_leaf_update,
        has_explicit_leaf_update=has_explicit_leaf_update,
        has_invalid_leaf_control=has_invalid_leaf_control,
    )


def select_session_transcript_tree_path_nodes(
    tree: SessionTranscriptTree, leaf_id: str | None
) -> list[SessionTranscriptTreeNode]:
    """Select one normalized path, retaining a reachable suffix after missing ancestors."""
    if leaf_id is None:
        return []
    path: list[SessionTranscriptTreeNode] = []
    seen: set[str] = set()
    current_id: str | None = leaf_id
    while current_id:
        if current_id in seen:
            return []
        seen.add(current_id)
        current = tree.by_id.get(current_id)
        if current is None:
            break
        if not is_session_transcript_leaf_control(current.entry):
            path.insert(0, current)
        current_id = current.parent_id
    return path


def _select_session_transcript_active_entries(
    entries: list[Any], tree: SessionTranscriptTree
) -> list[Any]:
    """OpenClaw selectSessionTranscriptActiveEntries: retain the reset/compaction boundary."""
    if not tree.has_explicit_leaf_update:
        return list(entries)
    active_path = select_session_transcript_tree_path_nodes(tree, tree.leaf_id)
    active_entries = [entries[node.index] for node in active_path]
    first_active_index = active_path[0].index if active_path else 0
    for index in range(first_active_index - 1, -1, -1):
        record = entries[index]
        if not isinstance(record, dict) or record.get("type") not in {"compaction", "reset"}:
            continue
        if record["type"] == "reset":
            reset_id = _read_non_empty_string(record.get("id"))
            first_kept_entry_id = _read_non_empty_string(record.get("firstKeptEntryId"))
            if reset_id and first_kept_entry_id:
                reset_path = select_session_transcript_tree_path_nodes(tree, reset_id)
                for kept_start, node in enumerate(reset_path):
                    if node.id == first_kept_entry_id:
                        retained_reset_path = [
                            entries[retained.index] for retained in reset_path[kept_start:]
                        ]
                        return [*retained_reset_path, *active_entries]
        return [record, *active_entries]
    return active_entries


def select_session_transcript_leaf_controlled_path(entries: list[Any]) -> list[Any] | None:
    """Select the effective branch only when the transcript contains leaf controls.

    Legacy flat readers can keep their existing behavior when this returns
    ``None``. Once navigation controls exist, returning the selected path keeps
    side branches out of prompts and indexes even after later active-branch
    appends.
    """
    tree = scan_session_transcript_tree(entries)
    if not tree.has_leaf_control:
        return None
    selected: list[Any] = []
    for entry in _select_session_transcript_active_entries(entries, tree):
        node = (
            tree.by_id.get(_read_non_empty_string(entry.get("id")) or "")
            if isinstance(entry, dict)
            else None
        )
        if (
            node is None
            or not isinstance(entry, dict)
            or ("parentId" in entry and entry["parentId"] == node.parent_id)
        ):
            selected.append(entry)
            continue
        # Consumers rebuild context from the selected entries, so preserve the
        # logical ancestry normalized while scanning disjoint append cursors.
        selected.append({**entry, "parentId": node.parent_id})
    return selected


def select_visible_transcript_events(events: list[Any]) -> list[Any]:
    """Port of ``selectVisibleTranscriptEvents`` (transcript-visible-events.ts).

    The events on the active visible branch in path order. Without a visible
    path, a transcript with leaf controls selects nothing and a flat transcript
    keeps every event.
    """
    tree = scan_session_transcript_tree(events)
    path = select_session_transcript_tree_path_nodes(tree, tree.leaf_id)
    if path:
        return [node.entry for node in path]
    return [] if tree.has_leaf_control else list(events)
