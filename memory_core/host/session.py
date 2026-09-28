"""The per-session value a host stores next to its own session record (docs/host_kit.md).

``SessionState.entry`` is the subset of upstream's ``SessionEntry`` that ``memory_core.memory_flush``
reads (``sessionId``, ``compactionCount``, ``totalTokens``, ``totalTokensFresh``,
``totalTokensVersion``, ``memoryFlush``). The kit never mutates a state: every entry point
returns a new copy, and each state holds its own deep copy of the entry behind a read-only view.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from memory_core.bootstrap.files import SESSION_KINDS, SessionKind
from memory_core.memory_flush import SESSION_TOTAL_TOKENS_VERSION


@dataclass(frozen=True)
class TurnUsage:
    """Token usage of a turn's last model call, as the provider reported it.

    ``prompt_tokens`` becomes the session's fresh total (upstream ``totalTokens``);
    ``completion_tokens`` the last output tokens the flush gate adds to it.
    """

    prompt_tokens: int | None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class SessionState:
    """One session's memory state: its key, id, kind and flush-gate entry.

    ``session_key`` stays the same across ``/new`` (upstream ``sessionKey``); ``session_id``
    changes (upstream ``sessionId``). ``seen_truncation_signatures`` and
    ``completed_bootstrap_turn`` carry the bootstrap truncation warning and the
    ``continuation-skip`` state from turn to turn.
    """

    session_key: str
    session_id: str
    kind: SessionKind = "main"
    entry: Mapping[str, Any] = field(default_factory=dict)
    last_output_tokens: int | None = None
    seen_truncation_signatures: tuple[str, ...] = ()
    completed_bootstrap_turn: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.session_key, str) or not isinstance(self.session_id, str):
            raise TypeError("session_key and session_id must be strings")
        if self.kind not in SESSION_KINDS:
            raise ValueError(f"unknown session kind: {self.kind!r}")
        if not isinstance(self.entry, Mapping):
            raise TypeError("entry must be a mapping")
        object.__setattr__(self, "entry", MappingProxyType(copy.deepcopy(dict(self.entry))))
        object.__setattr__(
            self, "seen_truncation_signatures", tuple(self.seen_truncation_signatures)
        )

    @classmethod
    def new(cls, *, session_key: str, session_id: str, kind: SessionKind = "main") -> SessionState:
        """A session's first state: a fresh entry in compaction cycle 0."""
        return cls(
            session_key=session_key,
            session_id=session_id,
            kind=kind,
            entry={"sessionId": session_id, "compactionCount": 0},
        )

    def after_compaction(self, *, tokens_after: int | float | None = None) -> SessionState:
        """The state after the host compacted the session's history (next compaction cycle).

        Port of the token part of upstream ``incrementCompactionCount``
        (``projectCompactionAccountingPatch``, src/config/sessions/session-entry-projection.ts:91-131):
        ``compactionCount`` grows by one and the output tokens are cleared; ``tokens_after`` (a
        finite number of at least 0) becomes the fresh total, otherwise the total goes stale.
        """
        entry = copy.deepcopy(dict(self.entry))
        count = entry.get("compactionCount")
        entry["compactionCount"] = (0 if count is None else count) + 1
        if (
            isinstance(tokens_after, int | float)
            and not isinstance(tokens_after, bool)
            and math.isfinite(tokens_after)
            and tokens_after >= 0
        ):
            entry["totalTokens"] = math.floor(tokens_after)
            entry["totalTokensFresh"] = True
            entry["totalTokensVersion"] = SESSION_TOTAL_TOKENS_VERSION
        else:
            entry["totalTokensFresh"] = False
            entry.pop("totalTokensVersion", None)
        return replace(self, entry=entry, last_output_tokens=None)

    def to_json(self) -> dict[str, Any]:
        return {
            "sessionKey": self.session_key,
            "sessionId": self.session_id,
            "kind": self.kind,
            "entry": copy.deepcopy(dict(self.entry)),
            "lastOutputTokens": self.last_output_tokens,
            "seenTruncationSignatures": list(self.seen_truncation_signatures),
            "completedBootstrapTurn": self.completed_bootstrap_turn,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SessionState:
        """Read :meth:`to_json` output; ``ValueError`` for a field of the wrong type."""
        signatures = data.get("seenTruncationSignatures", [])
        output = data.get("lastOutputTokens")
        completed = data.get("completedBootstrapTurn", False)
        if not isinstance(signatures, list) or not all(isinstance(s, str) for s in signatures):
            raise ValueError("seenTruncationSignatures must be a list of strings")
        if output is not None and (isinstance(output, bool) or not isinstance(output, int)):
            raise ValueError("lastOutputTokens must be an integer or null")
        if not isinstance(completed, bool):
            raise ValueError("completedBootstrapTurn must be a boolean")
        try:
            return cls(
                session_key=data["sessionKey"],
                session_id=data["sessionId"],
                kind=data.get("kind", "main"),
                entry=data.get("entry", {}),
                last_output_tokens=output,
                seen_truncation_signatures=tuple(signatures),
                completed_bootstrap_turn=completed,
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"not a session state: {exc}") from exc


def apply_turn_usage(session: SessionState, usage: TurnUsage | None) -> SessionState:
    """The session after a completed turn: its token snapshot from the provider's usage.

    A positive ``prompt_tokens`` becomes a fresh v1 total (upstream persists the run's prompt
    usage as ``totalTokens`` with ``totalTokensFresh`` and ``totalTokensVersion``); without one
    the total goes stale, so the flush gate reports ``missing_tokens``. ``completion_tokens``
    becomes ``last_output_tokens``. No estimate is invented.
    """
    entry = copy.deepcopy(dict(session.entry))
    prompt = usage.prompt_tokens if usage is not None else None
    completion = usage.completion_tokens if usage is not None else None
    if _is_count(prompt) and prompt > 0:
        entry["totalTokens"] = prompt
        entry["totalTokensFresh"] = True
        entry["totalTokensVersion"] = SESSION_TOTAL_TOKENS_VERSION
    else:
        entry["totalTokensFresh"] = False
    return replace(
        session, entry=entry, last_output_tokens=completion if _is_count(completion) else None
    )


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
