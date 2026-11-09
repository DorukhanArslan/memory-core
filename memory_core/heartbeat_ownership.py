"""Private durable monitor catalog validation for FileAutomationStore.

This is state ownership only. It models neither monitor cadence nor scheduler
execution, and shares the automation store's existing atomic transaction.
"""
from __future__ import annotations

from typing import Any

from memory_core.heartbeat_scratch import (
    HeartbeatMonitorOwner, HeartbeatScratchState, HeartbeatScratchWrite,
    apply_heartbeat_scratch_write, assert_heartbeat_scratch_content,
)

CATALOG_KEY = "heartbeatOwnership"
MAX_COUNTER = 2**53 - 1
MAX_CLOCK_MS = 8_640_000_000_000_000


def bounded_integer(value: object, *, clock: bool = False, minimum: int = 0) -> int:
    bound = MAX_CLOCK_MS if clock else MAX_COUNTER
    if (isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > bound):
        raise ValueError("heartbeat ownership contains an invalid clock or counter")
    return value


def identity(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("heartbeat ownership identities must be non-empty strings")
    return value


def empty_catalog() -> dict[str, Any]:
    return {"version": 1, "agents": {}, "owners": {}, "scratch": {}}


def validate_catalog(data: dict[str, Any]) -> None:
    if CATALOG_KEY not in data:
        return
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("unsupported automation store version for heartbeat ownership")
    value = data[CATALOG_KEY]
    if (not isinstance(value, dict) or set(value) != {"version", "agents", "owners", "scratch"}
            or type(value["version"]) is not int or value["version"] != 1
            or any(not isinstance(value[key], dict) for key in ("agents", "owners", "scratch"))):
        raise ValueError("invalid persisted heartbeat ownership catalog")
    for agent, ref in value["agents"].items():
        identity(agent)
        if not isinstance(ref, dict) or set(ref) != {"jobId", "generation"}:
            raise ValueError("invalid persisted heartbeat monitor reference")
        job_id = identity(ref["jobId"])
        generation = bounded_integer(ref["generation"], minimum=1)
        owner = value["owners"].get(job_id)
        if not isinstance(owner, dict) or owner.get("agentId") != agent or owner.get("generation") != generation:
            raise ValueError("heartbeat monitor reference has no matching durable owner")
    generations = set()
    for job_id, owner in value["owners"].items():
        identity(job_id)
        if not isinstance(owner, dict) or set(owner) != {"agentId", "generation", "active"} or type(owner["active"]) is not bool:
            raise ValueError("invalid persisted heartbeat monitor owner")
        agent = identity(owner["agentId"])
        generation = bounded_integer(owner["generation"], minimum=1)
        if (agent, generation) in generations:
            raise ValueError("heartbeat owner generations collide within an agent")
        generations.add((agent, generation))
        ref = value["agents"].get(agent)
        if not isinstance(ref, dict) or generation > ref["generation"]:
            raise ValueError("heartbeat owner generation is not retained by its agent")
        if owner["active"] and ref != {"jobId": job_id, "generation": generation}:
            raise ValueError("heartbeat owner is active outside its current agent binding")
    for job_id, row in value["scratch"].items():
        if job_id not in value["owners"] or not isinstance(row, dict):
            raise ValueError("persisted heartbeat scratch has no known job owner")
        if set(row) - {"content", "revision", "updatedAtMs", "sourceSha256"} or "content" not in row or "revision" not in row:
            raise ValueError("invalid persisted heartbeat scratch row")
        bounded_integer(row["revision"], minimum=1)
        content = row["content"]
        if content is not None:
            if not isinstance(content, str) or "updatedAtMs" not in row:
                raise ValueError("invalid persisted heartbeat scratch content")
            assert_heartbeat_scratch_content(content)
            bounded_integer(row["updatedAtMs"], clock=True)
        elif "updatedAtMs" in row:
            bounded_integer(row["updatedAtMs"], clock=True)
        if "sourceSha256" in row and (content is None or not isinstance(row["sourceSha256"], str) or not row["sourceSha256"]):
            raise ValueError("invalid persisted heartbeat scratch provenance")


def catalog(data: dict[str, Any], *, create=False) -> dict[str, Any]:
    value = data.get(CATALOG_KEY)
    if value is None:
        value = empty_catalog()
        if create:
            data[CATALOG_KEY] = value
    return value


def job_state(data: dict[str, Any], agent_id: str, job_id: str) -> HeartbeatScratchState:
    value = catalog(data)
    owner = value["owners"].get(job_id)
    if owner is not None and owner["agentId"] != agent_id:
        raise ValueError("heartbeat job belongs to a different agent")
    return HeartbeatScratchState.from_json(value["scratch"].get(job_id))


def agent_job(data: dict[str, Any], agent_id: str) -> str | None:
    ref = catalog(data)["agents"].get(agent_id)
    return ref["jobId"] if ref is not None else None


def active_owner(data: dict[str, Any], agent_id: str) -> HeartbeatMonitorOwner | None:
    value = catalog(data)
    job_id = agent_job(data, agent_id)
    owner = value["owners"].get(job_id)
    if owner is None or not owner["active"]:
        return None
    return HeartbeatMonitorOwner(agent_id, job_id, owner["generation"])


def put_job_state(data: dict[str, Any], job_id: str, state: HeartbeatScratchState) -> None:
    value = catalog(data, create=True)
    row = state.to_row()
    if row is None:
        value["scratch"].pop(job_id, None)
    else:
        value["scratch"][job_id] = row


def write_owned(
    data: dict[str, Any], agent_id: str, job_id: str | None, content: str | None, *,
    now_ms: int, expected_revision: int | None, expected_owner_generation: int | None,
    source_sha256: str | None,
) -> tuple[HeartbeatScratchWrite, bool]:
    # The public caller checks content before loading the file. The pure write
    # rule also checks it, preserving the native size-before-CAS ordering.
    state = job_state(data, agent_id, job_id) if job_id is not None else HeartbeatScratchState()
    owner = active_owner(data, agent_id)
    if expected_revision is not None:
        bounded_integer(expected_revision)
    if expected_owner_generation is not None:
        bounded_integer(expected_owner_generation, minimum=1)
    if (owner is None or owner.job_id != job_id or
            (expected_owner_generation is not None and owner.generation != expected_owner_generation)):
        return HeartbeatScratchWrite(False, state.current_revision, reason="revision-conflict"), False
    if expected_revision is not None and expected_revision != state.current_revision:
        return HeartbeatScratchWrite(False, state.current_revision, reason="revision-conflict"), False
    # Revision and clock bounds are checked before any replacement is committed.
    bounded_integer(now_ms, clock=True)
    if state.current_revision == MAX_COUNTER:
        raise ValueError("heartbeat scratch revision cannot exceed the safe integer range")
    new_state, result = apply_heartbeat_scratch_write(state, content, now_ms=now_ms,
        expected_revision=expected_revision, source_sha256=source_sha256)
    changed = new_state is not state
    if changed:
        put_job_state(data, job_id, new_state)
    return result, changed
