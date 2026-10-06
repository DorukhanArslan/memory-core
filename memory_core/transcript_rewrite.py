"""Transcript rewrite at v2026.9.6: branch from the first rewritten message and re-append the suffix.

Ports ``rewriteTranscriptEntriesInSessionManager``
(``src/agents/embedded-agent-runner/transcript-rewrite.ts``) over :class:`TranscriptSessionManager`,
an in-memory port of the parts of upstream's ``SessionManager`` the rewrite drives: the entry
navigation (``session-entry-navigation.ts``: ``byId``, opaque leaf controls, logical parents,
reset-boundary crossing, labels, ``getBranch``), the append methods (``session-manager-entries.ts``),
``branch``/``resetLeaf``/``branchWithSummary``, ``appendLeafControl`` and
``prepareTranscriptRewrite`` with its commit (``session-manager.ts``).

Deviations from upstream (see docs/gap2-transcript-notes.md):

* no persistence target: no SQLite store, bounded-context views, mutation fences, write admission
  or sidecar "pending input" relocation (``withSessionPendingInputRelocation`` is a pass-through
  when no pending input owns the entry, which is the in-memory case);
* ``appendMessage`` does not apply assistant delivery directives (``applyAssistantDeliveryDirectives``
  strips reply/audio/TTS tags in place). A host that needs that passes ``prepare_message``;
* the rewrite is synchronous (upstream awaits the async metadata appends);
* ids are random UUIDs and timestamps ISO strings, as upstream.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from memory_core.bootstrap._js import js_json_stringify, js_trim, js_truthy, js_utf8_encode
from memory_core.compaction_replay import strip_compaction_replay_checkpoint


class _Undefined:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug repr only
        return "UNDEFINED"


#: JS ``undefined``: an absent field, distinct from JSON ``null`` (``None``).
UNDEFINED: Any = _Undefined()

_NEWLINES_RE = re.compile(r"[\r\n]+")

_SIDE_CANONICAL_TYPES = frozenset(
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


def _truthy(value: Any) -> bool:
    """JS truthiness where ``undefined`` is falsy."""

    return value is not UNDEFINED and js_truthy(value)


def _strip_undefined(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_undefined(v) for k, v in value.items() if v is not UNDEFINED}
    if isinstance(value, (list, tuple)):
        return [None if v is UNDEFINED else _strip_undefined(v) for v in value]
    return value


def _canonical(entry: Mapping[str, Any]) -> dict[str, Any]:
    """``canonicalizeSessionEntry``: the JSON round trip every appended entry takes."""

    return json.loads(js_json_stringify(_strip_undefined(dict(entry))))


def _is_side_append_entry(record: Mapping[str, Any]) -> bool:
    return record.get("type") in _SIDE_CANONICAL_TYPES and record.get("appendMode") == "side"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _new_id() -> str:
    return str(uuid.uuid4())


def _parse_leaf(record: Any) -> dict[str, Any] | None:
    """``parseOpaqueLeafEntry`` for the leaf controls this manager writes."""

    if not isinstance(record, Mapping) or record.get("type") != "leaf":
        return None
    out: dict[str, Any] = {
        "id": record["id"],
        "parentId": record.get("parentId"),
        "targetId": record.get("targetId"),
    }
    if "appendParentId" in record:
        out["appendParentId"] = record["appendParentId"]
    if record.get("appendMode") == "side":
        out["appendMode"] = "side"
    return out


class TranscriptSessionManager:
    """In-memory session manager: append API, branch navigation and the rewrite preparation."""

    def __init__(
        self,
        cwd: str = ".",
        *,
        prepare_message: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.cwd = cwd
        self._prepare_message = prepare_message
        self.session_id = _new_id()
        self.file_entries: list[dict[str, Any]] = [
            {
                "type": "session",
                "version": 3,
                "id": self.session_id,
                "timestamp": _now_iso(),
                "cwd": cwd,
            }
        ]
        self.opaque_file_entries: list[dict[str, Any]] = []
        self._clear_navigation()
        self.pending_deliberate_append = False

    # --- navigation state (SessionEntryNavigation) ---------------------------------------

    def _clear_navigation(self) -> None:
        self.by_id: dict[str, dict[str, Any]] = {}
        self.opaque_parents_by_id: dict[str, str | None] = {}
        self.logical_parents_by_id: dict[str, str | None] = {}
        self.invalid_leaf_control_ids: set[str] = set()
        self.labels_by_id: dict[str, str] = {}
        self.leaf_id: str | None = None
        self.append_parent_id: str | None = None
        self.append_mode: str | None = None
        self._latest_reset_id: str | None = None
        self._reset_descendant_ids: set[str] = set()

    _VIEW_FIELDS = (
        "session_id",
        "file_entries",
        "opaque_file_entries",
        "by_id",
        "opaque_parents_by_id",
        "logical_parents_by_id",
        "invalid_leaf_control_ids",
        "labels_by_id",
        "leaf_id",
        "append_parent_id",
        "append_mode",
        "pending_deliberate_append",
    )

    def _capture_view(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self._VIEW_FIELDS}

    def _adopt_view(self, view: Mapping[str, Any]) -> None:
        for name in self._VIEW_FIELDS:
            setattr(self, name, view[name])

    def _resolve_canonical_parent_id(self, parent_id: str | None) -> str | None:
        """``resolveSessionCanonicalParentId``: walk opaque (leaf control) links to an entry."""

        seen: set[str] | None = None
        current = parent_id
        while current and current not in self.by_id:
            if seen is not None and current in seen:
                return None
            if seen is None:
                seen = set()
            seen.add(current)
            current = self.opaque_parents_by_id.get(current)
        return current

    def _resolve_opaque_leaf_target_id(self, target_id: str | None) -> str | None:
        if target_id is None or target_id in self.by_id:
            return target_id
        return self._resolve_canonical_parent_id(target_id)

    def _resolve_opaque_append_parent_id(self, parent_id: str | None) -> str | None:
        if parent_id is None or parent_id in self.by_id or parent_id in self.opaque_parents_by_id:
            return parent_id
        return self._resolve_canonical_parent_id(parent_id)

    def _resolve_opaque_leaf_control(self, leaf: dict[str, Any]) -> dict[str, Any] | None:
        def is_known(ref: str | None) -> bool:
            return (
                ref is None
                or ref in self.by_id
                or (ref in self.opaque_parents_by_id and ref not in self.invalid_leaf_control_ids)
            )

        if not is_known(leaf["targetId"]) or (
            "appendParentId" in leaf and not is_known(leaf["appendParentId"])
        ):
            return None
        leaf_id = self._resolve_opaque_leaf_target_id(leaf["targetId"])
        out: dict[str, Any] = {
            "leafId": leaf_id,
            "appendParentId": (
                leaf_id
                if "appendParentId" not in leaf
                else self._resolve_opaque_append_parent_id(leaf["appendParentId"])
            ),
        }
        if leaf.get("appendMode"):
            out["appendMode"] = "side"
        return out

    def _append_opaque_navigation_record(self, record: Any) -> None:
        leaf = _parse_leaf(record)
        if leaf is None:
            return
        state = self._resolve_opaque_leaf_control(leaf)
        if state is None:
            self.invalid_leaf_control_ids.add(leaf["id"])
            self.opaque_parents_by_id[leaf["id"]] = self._resolve_opaque_append_parent_id(
                leaf["parentId"]
            )
            return
        crosses_reset = self._latest_reset_id is not None and (
            state["leafId"] is None or state["leafId"] not in self._reset_descendant_ids
        )
        effective = (
            {"leafId": self.leaf_id, "appendParentId": self.leaf_id} if crosses_reset else state
        )
        self.opaque_parents_by_id[leaf["id"]] = effective["leafId"]
        if (
            self._latest_reset_id is not None
            and effective["leafId"] is not None
            and effective["leafId"] in self._reset_descendant_ids
        ):
            self._reset_descendant_ids.add(leaf["id"])
        self.leaf_id = effective["leafId"]
        self.append_parent_id = effective["appendParentId"]
        self.append_mode = effective.get("appendMode")

    def _append_canonical_navigation_entry(self, entry: dict[str, Any]) -> None:
        if entry["type"] == "label" and entry["targetId"] not in self.by_id:
            self.opaque_parents_by_id[entry["id"]] = self._resolve_canonical_parent_id(
                entry["parentId"]
            )
            return
        side = _is_side_append_entry(entry)
        parent_id = entry.get("parentId")
        crosses_reset = (
            self._latest_reset_id is not None
            and not side
            and (parent_id is None or parent_id not in self._reset_descendant_ids)
        )
        if (
            crosses_reset
            or "parentId" not in entry
            or (not side and parent_id == self.append_parent_id and self.leaf_id != self.append_parent_id)
        ):
            self.logical_parents_by_id[entry["id"]] = self.leaf_id
        self.by_id[entry["id"]] = entry
        if entry["type"] == "reset":
            self._latest_reset_id = entry["id"]
            self._reset_descendant_ids.clear()
            self._reset_descendant_ids.add(entry["id"])
        else:
            logical_parent = (
                self.logical_parents_by_id[entry["id"]]
                if entry["id"] in self.logical_parents_by_id
                else parent_id
            )
            if (
                self._latest_reset_id is not None
                and logical_parent is not None
                and logical_parent in self._reset_descendant_ids
            ):
                self._reset_descendant_ids.add(entry["id"])
        self.append_parent_id = entry["id"]
        if side:
            self.append_mode = "side"
        else:
            self.leaf_id = entry["id"]
            self.append_mode = None
        if entry["type"] == "label":
            if entry.get("label"):
                self.labels_by_id[entry["targetId"]] = entry["label"]
            else:
                self.labels_by_id.pop(entry["targetId"], None)

    def _build_index(self) -> None:
        """``buildIndex``: rebuild every navigation fact from the stored entries."""

        self._clear_navigation()
        self.pending_deliberate_append = False
        opaque_index = 0
        for index in range(len(self.file_entries) + 1):
            while (
                opaque_index < len(self.opaque_file_entries)
                and self.opaque_file_entries[opaque_index]["index"] == index
            ):
                self._append_opaque_navigation_record(self.opaque_file_entries[opaque_index]["record"])
                opaque_index += 1
            entry = self.file_entries[index] if index < len(self.file_entries) else None
            if entry is None or entry["type"] == "session":
                continue
            self._append_canonical_navigation_entry(entry)
        self._latest_reset_id = None
        self._reset_descendant_ids.clear()

    def _resolve_entry_parent_id(self, entry: Mapping[str, Any]) -> str | None:
        if entry["id"] in self.logical_parents_by_id:
            return self.logical_parents_by_id[entry["id"]]
        return self._resolve_canonical_parent_id(entry["parentId"])

    def _normalize_entry_parent(self, entry: dict[str, Any]) -> dict[str, Any]:
        parent_id = self._resolve_entry_parent_id(entry)
        normalized = entry if parent_id == entry["parentId"] else {**entry, "parentId": parent_id}
        if normalized["parentId"] == normalized["id"]:
            normalized = {**normalized, "parentId": None}
        return normalized

    def get_branch(self, from_id: str | None = None) -> list[dict[str, Any]]:
        path: list[dict[str, Any]] = []
        seen: set[str] = set()
        current = from_id if from_id is not None else self.leaf_id
        while current and current not in seen:
            seen.add(current)
            entry = self.by_id.get(current)
            if entry is not None:
                normalized = self._normalize_entry_parent(entry)
                path.append(normalized)
                current = normalized["parentId"]
            else:
                current = self.opaque_parents_by_id.get(current)
        path.reverse()
        return path

    def get_entries(self) -> list[dict[str, Any]]:
        return [
            self._normalize_entry_parent(entry)
            for entry in self.file_entries
            if entry["type"] != "session" and entry["id"] in self.by_id
        ]

    def get_leaf_id(self) -> str | None:
        return self.leaf_id

    def get_append_parent_id(self) -> str | None:
        return self.append_parent_id

    def get_append_mode(self) -> str | None:
        return self.append_mode

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        entry = self.by_id.get(entry_id)
        return self._normalize_entry_parent(entry) if entry is not None else None

    def get_label(self, entry_id: str) -> str | None:
        return self.labels_by_id.get(entry_id)

    # --- appends (SessionManagerEntries) ---------------------------------------------------

    def _append_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        canonical = _canonical(entry)
        # In memory there is no store to adopt from: the entry joins the loaded view directly.
        if (
            not _is_side_append_entry(canonical)
            and canonical["parentId"] == self.append_parent_id
            and self.leaf_id != self.append_parent_id
        ):
            self.logical_parents_by_id[canonical["id"]] = self.leaf_id
        self.file_entries.append(canonical)
        self.by_id[canonical["id"]] = canonical
        self.append_parent_id = canonical["id"]
        if _is_side_append_entry(canonical):
            self.append_mode = "side"
        else:
            self.leaf_id = canonical["id"]
            self.append_mode = None
        self.pending_deliberate_append = False
        return canonical

    def _base(self, entry_type: str, parent_id: Any = UNDEFINED) -> dict[str, Any]:
        return {
            "type": entry_type,
            "id": _new_id(),
            "parentId": self.append_parent_id if parent_id is UNDEFINED else parent_id,
            "timestamp": _now_iso(),
        }

    def append_message(self, message: dict[str, Any]) -> str:
        if self._prepare_message is not None and message.get("role") == "assistant":
            self._prepare_message(message)
        return self._append_entry({**self._base("message"), "message": message})["id"]

    def append_compaction(
        self,
        summary: str,
        first_kept_entry_id: Any,
        tokens_before: Any,
        details: Any = UNDEFINED,
        from_hook: Any = UNDEFINED,
        metadata: Mapping[str, Any] | None = None,
        tokens_after: Any = UNDEFINED,
    ) -> str:
        entry: dict[str, Any] = {
            **self._base("compaction"),
            "summary": summary,
            "firstKeptEntryId": first_kept_entry_id,
            "tokensBefore": tokens_before,
            "tokensAfter": tokens_after,
            "details": details,
            "fromHook": from_hook,
        }
        if metadata is not None and (
            _truthy(metadata.get("runId", UNDEFINED)) or _truthy(metadata.get("itemId", UNDEFINED))
        ):
            entry["__openclaw"] = dict(metadata)
        return self._append_entry(entry)["id"]

    def append_reset_boundary(self, reason: Any, first_kept_entry_id: Any = None) -> str:
        entry = {**self._base("reset"), "reason": reason}
        if _truthy(first_kept_entry_id):
            entry["firstKeptEntryId"] = first_kept_entry_id
        return self._append_entry(entry)["id"]

    def append_thinking_level_change(self, thinking_level: Any) -> str:
        return self._append_entry(
            {**self._base("thinking_level_change"), "thinkingLevel": thinking_level}
        )["id"]

    def append_model_change(self, provider: Any, model_id: Any) -> str:
        return self._append_entry(
            {**self._base("model_change"), "provider": provider, "modelId": model_id}
        )["id"]

    def append_custom_entry(self, custom_type: Any, data: Any = UNDEFINED) -> str:
        return self._append_entry(
            {**self._base("custom"), "customType": custom_type, "data": data}
        )["id"]

    def append_session_info(self, name: str) -> str:
        cleaned = js_trim(_collapse_newlines(name))
        return self._append_entry({**self._base("session_info"), "name": cleaned})["id"]

    def append_custom_message_entry(
        self, custom_type: Any, content: Any, display: Any, details: Any = UNDEFINED
    ) -> str:
        return self._append_entry(
            {
                **self._base("custom_message"),
                "customType": custom_type,
                "content": content,
                "display": display,
                "details": details,
            }
        )["id"]

    def append_label_change(self, target_id: str, label: Any) -> str:
        if target_id not in self.by_id:
            raise KeyError(f"Entry {target_id} not found")
        entry = self._append_entry(
            {**self._base("label"), "targetId": target_id, "label": label}
        )
        if _truthy(label):
            self.labels_by_id[target_id] = entry["label"]
        else:
            self.labels_by_id.pop(target_id, None)
        return entry["id"]

    def _resolve_branch_target_id(self, branch_from_id: str) -> Any:
        if branch_from_id in self.by_id:
            return branch_from_id
        if branch_from_id in self.opaque_parents_by_id:
            return self._resolve_canonical_parent_id(branch_from_id)
        return UNDEFINED

    def branch(self, branch_from_id: str) -> None:
        target = self._resolve_branch_target_id(branch_from_id)
        if target is UNDEFINED:
            raise KeyError(f"Entry {branch_from_id} not found")
        self.leaf_id = target
        self.append_parent_id = target
        self.append_mode = None
        self.pending_deliberate_append = True

    def reset_leaf(self) -> None:
        self.leaf_id = None
        self.append_parent_id = None
        self.append_mode = None
        self.pending_deliberate_append = True

    def branch_with_summary(
        self,
        branch_from_id: str | None,
        summary: Any,
        details: Any = UNDEFINED,
        from_hook: Any = UNDEFINED,
    ) -> str:
        target = None if branch_from_id is None else self._resolve_branch_target_id(branch_from_id)
        if target is UNDEFINED:
            raise KeyError(f"Entry {branch_from_id} not found")
        entry = {
            **self._base("branch_summary", target),
            "fromId": target if target is not None else "root",
            "summary": summary,
            "details": details,
            "fromHook": from_hook,
        }
        return self._append_entry(entry)["id"]

    # --- leaf controls ---------------------------------------------------------------------

    def _create_leaf_control(
        self, parent_id: str | None, append_parent_id: Any = UNDEFINED, append_mode: str | None = None
    ) -> dict[str, Any]:
        append_parent = self.append_parent_id if append_parent_id is UNDEFINED else append_parent_id
        entry: dict[str, Any] = {
            "type": "leaf",
            "id": _new_id(),
            "parentId": parent_id,
            "timestamp": _now_iso(),
            "targetId": self.leaf_id,
        }
        if append_parent != self.leaf_id:
            entry["appendParentId"] = append_parent
        if append_mode:
            entry["appendMode"] = append_mode
        return entry

    def _remember_leaf_control(self, leaf: dict[str, Any]) -> None:
        self.opaque_file_entries.append({"index": len(self.file_entries), "record": leaf})
        self.opaque_parents_by_id[leaf["id"]] = leaf["targetId"]

    def append_leaf_control(
        self, *, target_id: str | None, append_parent_id: str | None, append_mode: str | None = None
    ) -> dict[str, Any]:
        if target_id is not None and target_id not in self.by_id:
            raise KeyError(f"Entry {target_id} not found")
        if (
            append_parent_id is not None
            and append_parent_id not in self.by_id
            and append_parent_id not in self.opaque_parents_by_id
        ):
            raise KeyError(f"Append parent {append_parent_id} not found")
        previous_leaf_id = self.leaf_id
        self.leaf_id = target_id
        entry = self._create_leaf_control(self.append_parent_id, append_parent_id, append_mode)
        self.leaf_id = previous_leaf_id
        self._remember_leaf_control(entry)
        self.leaf_id = target_id
        self.append_parent_id = append_parent_id
        self.append_mode = append_mode
        self.pending_deliberate_append = False
        return entry

    def get_persisted_entries(self) -> list[dict[str, Any]]:
        """``getPersistedEntries``: stored entries and leaf controls in file order.

        Appends (and remembers) a trailing leaf control when the stored order does not already
        end on the live leaf and append cursor.
        """

        previous = 0
        for opaque in self.opaque_file_entries:
            opaque["index"] = max(previous, min(opaque["index"], len(self.file_entries)))
            previous = opaque["index"]
        entries: list[dict[str, Any]] = []
        opaque_index = 0
        for index in range(len(self.file_entries) + 1):
            while (
                opaque_index < len(self.opaque_file_entries)
                and self.opaque_file_entries[opaque_index]["index"] == index
            ):
                entries.append(self.opaque_file_entries[opaque_index]["record"])
                opaque_index += 1
            if index < len(self.file_entries):
                entries.append(self.file_entries[index])
        while opaque_index < len(self.opaque_file_entries):
            entries.append(self.opaque_file_entries[opaque_index]["record"])
            opaque_index += 1
        persisted_leaf_id: str | None = None
        persisted_append_parent_id: str | None = None
        raw_tail_id: str | None = None
        for entry in entries:
            leaf = _parse_leaf(entry)
            if leaf is not None:
                raw_tail_id = leaf["id"]
                if leaf["id"] in self.invalid_leaf_control_ids:
                    continue
                target = self._resolve_opaque_leaf_target_id(leaf["targetId"])
                persisted_leaf_id = target
                persisted_append_parent_id = (
                    target
                    if "appendParentId" not in leaf
                    else self._resolve_opaque_append_parent_id(leaf["appendParentId"])
                )
                continue
            if entry["type"] in _SIDE_CANONICAL_TYPES:
                persisted_leaf_id = entry["id"]
                persisted_append_parent_id = entry["id"]
                raw_tail_id = entry["id"]
        if persisted_leaf_id != self.leaf_id or persisted_append_parent_id != self.append_parent_id:
            leaf_entry = self._create_leaf_control(raw_tail_id, self.append_parent_id, None)
            self._remember_leaf_control(leaf_entry)
            entries.append(leaf_entry)
        return entries

    # --- rewrite preparation ---------------------------------------------------------------

    def prepare_transcript_rewrite(self) -> PreparedTranscriptRewrite:
        """Prepare off-store; publish the suffix and adopt memory at the commit edge."""

        prepared = TranscriptSessionManager(self.cwd, prepare_message=self._prepare_message)
        prepared._adopt_view(copy.deepcopy(self._capture_view()))
        initial_entry_count = len(prepared.file_entries)

        def commit(rewritten_entry_ids: Mapping[str, str]) -> None:
            entries = [e for e in prepared.file_entries[initial_entry_count:] if e["type"] != "session"]
            for source_id in rewritten_entry_ids:
                if source_id not in self.by_id:
                    raise KeyError("Transcript rewrite source is not in the loaded view")
            # A maintenance branch may cross a reset. Side entries preserve its explicit
            # ancestry; ordinary appends would normalize onto the old leaf.
            for entry in entries:
                entry["appendMode"] = "side"
            prepared._build_index()
            prepared.opaque_parents_by_id.update(self.opaque_parents_by_id)
            prepared.logical_parents_by_id.update(self.logical_parents_by_id)
            if entries:
                prepared.append_leaf_control(target_id=entries[-1]["id"], append_parent_id=entries[-1]["id"])
            self._adopt_view(prepared._capture_view())

        return PreparedTranscriptRewrite(session_manager=prepared, commit=commit)


def _collapse_newlines(value: str) -> str:
    """``name.replace(/[\\r\\n]+/g, " ")``."""

    return _NEWLINES_RE.sub(" ", value)


@dataclass
class PreparedTranscriptRewrite:
    session_manager: TranscriptSessionManager
    commit: Callable[[Mapping[str, str]], None]


@dataclass(frozen=True)
class TranscriptRewriteResult:
    """``TranscriptRewriteResult`` (context-engine/types.ts)."""

    changed: bool
    bytes_freed: int
    rewritten_entries: int
    reason: str | None = None


def _remap_entry_id(entry_id: Any, rewritten_entry_ids: Mapping[str, str]) -> str | None:
    if not _truthy(entry_id):
        return None
    return rewritten_entry_ids.get(entry_id, entry_id)


def _strip_stale_prefix_replay(message: Any) -> Any:
    if isinstance(message, Mapping) and message.get("role") == "assistant":
        return strip_compaction_replay_checkpoint(message)
    return message


def _find_transcript_rewrite_matches(
    branch: Sequence[Mapping[str, Any]], replacements_by_id: Mapping[str, Any]
) -> tuple[list[int], int]:
    matched: list[int] = []
    bytes_freed = 0
    for index, entry in enumerate(branch):
        if entry.get("type") != "message":
            continue
        replacement = replacements_by_id.get(entry["id"], UNDEFINED)
        if replacement is UNDEFINED or replacement is None:
            continue
        original_json = js_json_stringify(entry["message"])
        replacement_json = js_json_stringify(replacement)
        if original_json == replacement_json:
            continue
        matched.append(index)
        bytes_freed += max(
            0, len(js_utf8_encode(original_json)) - len(js_utf8_encode(replacement_json))
        )
    return matched, bytes_freed


def _append_branch_entry(
    session_manager: TranscriptSessionManager,
    entry: Mapping[str, Any],
    rewritten_entry_ids: Mapping[str, str],
) -> str:
    entry_type = entry.get("type")
    if entry_type == "message":
        message = _strip_stale_prefix_replay(entry["message"])
        return session_manager.append_message(message)
    if entry_type == "compaction":
        identity = entry.get("__openclaw")
        remapped = _remap_entry_id(entry.get("firstKeptEntryId"), rewritten_entry_ids)
        metadata: dict[str, Any] = {
            "runId": identity.get("runId", UNDEFINED) if isinstance(identity, Mapping) else UNDEFINED,
            **(identity if isinstance(identity, Mapping) else {}),
        }
        return session_manager.append_compaction(
            entry.get("summary", UNDEFINED),
            remapped if remapped is not None else entry.get("firstKeptEntryId", UNDEFINED),
            entry.get("tokensBefore", UNDEFINED),
            entry.get("details", UNDEFINED),
            entry.get("fromHook", UNDEFINED),
            metadata,
            entry.get("tokensAfter", UNDEFINED),
        )
    if entry_type == "reset":
        first_kept = entry.get("firstKeptEntryId")
        if _truthy(first_kept):
            remapped = _remap_entry_id(first_kept, rewritten_entry_ids)
            first_kept = remapped if remapped is not None else first_kept
        else:
            first_kept = None
        return session_manager.append_reset_boundary(entry.get("reason", UNDEFINED), first_kept)
    if entry_type == "thinking_level_change":
        return session_manager.append_thinking_level_change(entry.get("thinkingLevel", UNDEFINED))
    if entry_type == "model_change":
        return session_manager.append_model_change(
            entry.get("provider", UNDEFINED), entry.get("modelId", UNDEFINED)
        )
    if entry_type == "custom":
        return session_manager.append_custom_entry(
            entry.get("customType", UNDEFINED), entry.get("data", UNDEFINED)
        )
    if entry_type == "custom_message":
        return session_manager.append_custom_message_entry(
            entry.get("customType", UNDEFINED),
            entry.get("content", UNDEFINED),
            entry.get("display", UNDEFINED),
            entry.get("details", UNDEFINED),
        )
    if entry_type == "session_info":
        return session_manager.append_session_info(entry["name"] if entry.get("name") else "")
    if entry_type == "branch_summary":
        return session_manager.branch_with_summary(
            _remap_entry_id(entry.get("parentId"), rewritten_entry_ids),
            entry.get("summary", UNDEFINED),
            entry.get("details", UNDEFINED),
            entry.get("fromHook", UNDEFINED),
        )
    target = entry.get("targetId")
    remapped = _remap_entry_id(target, rewritten_entry_ids)
    return session_manager.append_label_change(
        remapped if remapped is not None else target, entry.get("label", UNDEFINED)
    )


def rewrite_transcript_entries_in_session_manager(
    *,
    session_manager: TranscriptSessionManager,
    replacements: Iterable[Mapping[str, Any]],
    preserve_replacement_compaction_replay: bool = False,
) -> TranscriptRewriteResult:
    """Safely rewrite message entries on the active branch.

    Branches from the first rewritten message's parent and re-appends the suffix: replaced
    messages with their replacement, every other entry as a fresh copy with ids remapped
    (``firstKeptEntryId``, label targets and branch-summary parents follow the new ids). A
    prefix-bound compaction replay checkpoint is stripped from every re-appended assistant message
    (the explicit replacements keep theirs only with ``preserve_replacement_compaction_replay``).
    ``replacements`` items carry ``entryId`` and ``message``; blank ids are ignored.
    """

    replacements_by_id: dict[str, Any] = {}
    for replacement in replacements:
        entry_id = replacement.get("entryId")
        if not isinstance(entry_id, str) or len(js_trim(entry_id)) == 0:
            continue
        message = replacement.get("message")
        replacements_by_id[entry_id] = (
            message if preserve_replacement_compaction_replay else _strip_stale_prefix_replay(message)
        )
    if not replacements_by_id:
        return TranscriptRewriteResult(False, 0, 0, "no replacements requested")

    active_branch = session_manager.get_branch()
    if not active_branch:
        return TranscriptRewriteResult(False, 0, 0, "empty session")

    matched, bytes_freed = _find_transcript_rewrite_matches(active_branch, replacements_by_id)
    if not matched:
        return TranscriptRewriteResult(False, 0, 0, "no changed matching message entries")

    rewrite = session_manager.prepare_transcript_rewrite()
    rewrite_manager = rewrite.session_manager
    branch = rewrite_manager.get_branch()
    if len(branch) != len(active_branch) or any(
        entry["id"] != active_branch[index]["id"] for index, entry in enumerate(branch)
    ):
        raise RuntimeError("Session transcript changed before rewrite preparation")

    first_matched_index = matched[0]
    first_matched_entry = branch[first_matched_index]
    if first_matched_entry.get("type") != "message":
        return TranscriptRewriteResult(False, 0, 0, "invalid first rewrite target")

    if not first_matched_entry.get("parentId"):
        rewrite_manager.reset_leaf()
    else:
        rewrite_manager.branch(first_matched_entry["parentId"])

    rewritten_entry_ids: dict[str, str] = {}
    for entry in branch[first_matched_index:]:
        replacement = (
            replacements_by_id.get(entry["id"], UNDEFINED) if entry.get("type") == "message" else UNDEFINED
        )
        if replacement is UNDEFINED or replacement is None:
            new_entry_id = _append_branch_entry(rewrite_manager, entry, rewritten_entry_ids)
        else:
            new_entry_id = rewrite_manager.append_message(replacement)
        rewritten_entry_ids[entry["id"]] = new_entry_id

    rewrite.commit(rewritten_entry_ids)
    return TranscriptRewriteResult(True, bytes_freed, len(matched))


__all__ = [
    "UNDEFINED",
    "PreparedTranscriptRewrite",
    "TranscriptRewriteResult",
    "TranscriptSessionManager",
    "rewrite_transcript_entries_in_session_manager",
]
