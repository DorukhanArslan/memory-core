"""Current-turn trust derived from actual trusted tool-outcome observations.

The sticky transition ports ``createAgentTurnTaintState``. Writer provenance
uses the live resolver used by ``createOpenClawCodingTools``. The JSON carrier
is an SDK host facility: a retry may restore the SAME turn; a new turn starts
with a new identity and clean state. Model arguments never carry this authority.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _taint_metadata(message: Mapping[str, Any]) -> dict[str, Any]:
    metadata = message.get("__openclaw")
    if not isinstance(metadata, Mapping):
        return {}
    return {**({"resultContentSource": "network"} if metadata.get("resultContentSource") == "network" else {}),
            **({"turnTainted": True} if metadata.get("turnTainted") is True else {})}


def with_assistant_turn_taint(message: dict[str, Any], tainted: bool) -> dict[str, Any]:
    """Stamp the agent-core assistant boundary, preserving the untainted object."""
    if not tainted:
        return message
    return {**message, "__openclaw": {**_taint_metadata(message), "turnTainted": True}}


def is_active_turn_tainted(messages) -> bool:
    """Read the actual current transcript turn; a user boundary ends older taint."""
    for message in reversed(messages):
        if message.get("role") == "user":
            return False
        metadata = _taint_metadata(message)
        if metadata.get("turnTainted") is True or metadata.get("resultContentSource") == "network":
            return True
    return False


class TurnTrust:
    """One host-owned turn, shared by all its attempts and its write observers."""

    def __init__(self, turn_id: str, *, sender_is_owner: bool | None = None,
                 initially_tainted: bool = False) -> None:
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError("turn_id must identify one actual host turn")
        if not isinstance(initially_tainted, bool):
            raise TypeError("initially_tainted must be a boolean")
        self._turn_id = turn_id
        self.sender_is_owner = sender_is_owner
        self._tainted = initially_tainted

    @property
    def turn_id(self) -> str:
        return self._turn_id

    @property
    def sender_is_owner(self) -> bool | None:
        return self._sender_is_owner

    @sender_is_owner.setter
    def sender_is_owner(self, value: bool | None) -> None:
        if value is not None and not isinstance(value, bool):
            raise TypeError("sender_is_owner must be a trusted boolean or None")
        self._sender_is_owner = value

    def observe(self, observation: Mapping[str, Any]) -> None:
        """Consume a host outcome, never a model-supplied trust assertion."""
        if not observation.get("presentationOnly") and observation.get("resultContentSource") == "network":
            self._tainted = True

    def is_tainted(self) -> bool:
        return self._tainted

    def resolve_origin_class(self) -> str:
        """Read current ownership and sticky taint at the instant of each write."""
        return "untrusted" if self.sender_is_owner is False or self.is_tainted() else "agent"

    def stamp_assistant(self, message: dict[str, Any]) -> dict[str, Any]:
        if message.get("role") != "assistant":
            raise ValueError("Only assistant messages pass the assistant provenance boundary")
        return with_assistant_turn_taint(message, self.is_tainted())

    def write_observer(self, *, store, mutation_root, workspace_dir, session_id=None,
                       session_key=None, now=None, resolve_path=None):
        from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver

        return MemoryWriteProvenanceObserver(
            store=store, mutation_root=mutation_root, workspace_dir=workspace_dir,
            resolve_origin_class=self.resolve_origin_class, session_id=session_id,
            session_key=session_key, now=now, resolve_path=resolve_path,
        )

    def to_json(self) -> dict[str, Any]:
        """Trusted host checkpoint for continuation of this exact turn only."""
        return {"turnId": self.turn_id, "senderIsOwner": self.sender_is_owner, "tainted": self.is_tainted()}

    @classmethod
    def from_json(cls, data: Mapping[str, Any], *, expected_turn_id: str) -> TurnTrust:
        if (not isinstance(data, Mapping) or set(data) != {"turnId", "senderIsOwner", "tainted"}
                or data.get("turnId") != expected_turn_id or not isinstance(data.get("tainted"), bool)
                or (data.get("senderIsOwner") is not None and not isinstance(data["senderIsOwner"], bool))):
            raise ValueError("A trusted turn checkpoint must belong to this exact host turn")
        return cls(expected_turn_id, sender_is_owner=data["senderIsOwner"], initially_tainted=data["tainted"])

