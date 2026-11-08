"""Trusted session visibility and transcript lineage for memory retrieval.

Policy, live catalog facts and source readers belong to the host. Model tool
arguments cannot supply them. The implementation follows the pinned native
session-search-visibility and session-visibility policy owners.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import math
import re
from typing import Any, Protocol

from memory_core.bootstrap._js import js_trim
from memory_core.tools.common import MemoryToolError

_INCOGNITO = re.compile(r"^agent:[^:]+:(?:dashboard|subagent|internal-session-effects):incognito-[^:]+$")
_ACTIVE_MEMORY = re.compile(r":active-memory:[a-f0-9]{12}$", re.I)
_ARCHIVE = re.compile(
    r"^(?P<stem>.+)\.jsonl\.(?P<reason>reset|deleted)\."
    r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:\.\d{3})?Z(?:\.[0-9a-f]{32})?(?:\.zst)?$"
)
_ARCHIVE_REASON = re.compile(
    r"\.jsonl\.(reset|deleted)\.\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:\.\d{3})?Z(?:\.zst)?$"
)
_CHECKPOINT = re.compile(r"^.+\.checkpoint\.[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.jsonl$", re.I)


def _text(value: object) -> str:
    return js_trim(value) if isinstance(value, str) else ""


def normalize_session_agent_id(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", _text(value).lower()).strip("-")[:64]
    return normalized or "main"


def _agent_parts(key: str) -> tuple[str, str] | None:
    raw = _text(key)
    if raw[:6].lower() != "agent:":
        return None
    end = raw.find(":", 6)
    if end < 0:
        return None
    agent, rest = _text(raw[6:end]), raw[end + 1:]
    return (agent, rest) if agent and rest and not rest.startswith(":") else None


def resolve_session_agent_id(key: str, default_agent_id: str | None = None) -> str:
    parsed = _agent_parts(key)
    if parsed:
        return normalize_session_agent_id(parsed[0])
    if _text(key).lower().startswith("agent:"):
        raise MemoryToolError("Malformed agent session key; refusing default-agent resolution.")
    if _text(default_agent_id):
        return normalize_session_agent_id(default_agent_id)
    raise MemoryToolError(
        "Session key does not contain an agent id; resolve it with the configured default agent."
    )


def is_incognito_session_key(key: str) -> bool:
    return _INCOGNITO.fullmatch(_text(key).lower()) is not None


def _child_key(key: str) -> bool:
    parsed = _agent_parts(key)
    rest = parsed[1] if parsed else _text(key)
    return rest.lower().startswith(("subagent:", "acp:"))


@dataclass(frozen=True)
class SessionVisibilityPolicy:
    visibility: str | None = None
    sandbox_visibility: str = "spawned"
    agent_to_agent_enabled: bool = True
    agent_allow: Sequence[str] = ()
    main_key: str = "main"
    session_scope: str = "per-sender"
    default_agent_id: str = "main"
    configured_agent_ids: Sequence[str] = ()

    def effective_visibility(self, sandboxed: bool = False) -> str:
        value = _text(self.visibility).lower()
        visibility = value if value in {"self", "tree", "agent", "all"} else "all"
        return "tree" if sandboxed and self.sandbox_visibility == "spawned" else visibility

    def main_session_key(self, agent_id: str) -> str:
        if self.session_scope == "global":
            return "global"
        return f"agent:{normalize_session_agent_id(agent_id)}:{_text(self.main_key).lower() or 'main'}"


@dataclass(frozen=True)
class SessionOwnershipLookup:
    """Authoritative spawned-key lookup evidence, including a failed lookup."""

    keys: Sequence[str] = ()
    failure_kind: str | None = None


def _empty_catalog() -> Mapping[str, Mapping[str, Any]]:
    return {}


@dataclass(frozen=True)
class SessionVisibilityContext:
    policy: SessionVisibilityPolicy = field(default_factory=SessionVisibilityPolicy)
    load_catalog: Callable[[], Mapping[str, Mapping[str, Any]]] = _empty_catalog
    load_archives: Callable[[Sequence[str], str | None], Sequence[Mapping[str, Any]]] | None = None
    load_spawned_keys: Callable[[str], SessionOwnershipLookup] | None = None
    read_reset_cutoff: Callable[[str, str, str], Mapping[str, Any]] | None = None
    scoped_access: Callable[[str, str], str | None] | None = None

    @classmethod
    def from_catalog(
        cls, catalog: SessionCatalogReader, policy: SessionVisibilityPolicy | None = None,
    ) -> SessionVisibilityContext:
        """Bind policy to actual persisted catalog facts and source readers."""
        resolved = replace(
            policy or SessionVisibilityPolicy(), default_agent_id=catalog.agent_id,
            main_key=catalog.main_key, session_scope=catalog.session_scope,
            configured_agent_ids=policy.configured_agent_ids if policy and policy.configured_agent_ids else (catalog.agent_id,),
        )

        def archives(names: Sequence[str], agent_id: str | None) -> list[dict[str, Any]]:
            return [
                {"archiveName": archive.archive_name, "sessionId": archive.session_id,
                 "sessionKey": archive.session_key, "path": str(archive.path)}
                for archive in catalog.snapshot().archives
                if archive.archive_name in names and (not agent_id or archive.agent_id == normalize_session_agent_id(agent_id))
            ]

        def spawned(requester: str) -> SessionOwnershipLookup:
            now = catalog.now_ms()
            keys = []
            for key, entry in catalog.snapshot().entries.items():
                if key in {"unknown", "global"} or is_incognito_session_key(key):
                    continue
                if _retained_child_link(entry, now) and requester in {
                    _text(entry.get("spawnedBy")), _text(entry.get("parentSessionKey")),
                }:
                    keys.append(key)
                elif (_agent_parts(key) and _agent_parts(key)[1].startswith("dashboard:")
                      and _text(entry.get("parentSessionKey")) == requester):
                    keys.append(key)
            return SessionOwnershipLookup(tuple(keys))

        return cls(
            policy=resolved, load_catalog=lambda: catalog.snapshot().entries,
            load_archives=archives, load_spawned_keys=spawned,
            read_reset_cutoff=lambda agent, session, key: catalog.read_reset_cutoff(
                session, agent_id=agent, session_key=key,
            ),
        )


class SessionCatalogReader(Protocol):
    agent_id: str
    main_key: str
    session_scope: str

    def snapshot(self) -> Any: ...
    def now_ms(self) -> float: ...
    def read_reset_cutoff(self, session_id: str, *, agent_id: str, session_key: str) -> Mapping[str, Any]: ...
    def read_transcript(self, session_id: str, *, agent_id: str, session_key: str) -> Any: ...


def _positive_time(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _retained_child_link(entry: Mapping[str, Any], now: float) -> bool:
    if entry.get("status") in {"done", "failed", "interrupted", "killed", "timeout"} or _positive_time(entry.get("endedAt")):
        ended = entry["endedAt"] if _positive_time(entry.get("endedAt")) else entry.get("updatedAt")
        return _positive_time(ended) and now - ended <= 30 * 60_000
    return bool(entry.get("status") == "running" or _positive_time(entry.get("startedAt"))
                or (_positive_time(entry.get("updatedAt")) and now - entry["updatedAt"] <= 60 * 60_000))


def resolve_memory_search_source_policy(
    configured_sources: Sequence[str] | None = None, *,
    remember_across_conversations: bool = False, configured_session_memory: bool = False,
) -> dict[str, Any]:
    """Native source selection from already selected host memory policy facts."""
    def normalize(sources: Sequence[str] | None, sessions: bool) -> list[str]:
        result = []
        for source in sources or ("memory",):
            if (source == "memory" or (source == "sessions" and sessions)) and source not in result:
                result.append(source)
        return result or ["memory"]

    session_memory = remember_across_conversations or configured_session_memory
    search_sources = normalize(configured_sources, configured_session_memory or (
        remember_across_conversations and configured_sources is not None and "sessions" in configured_sources
    ))
    sources = normalize([*search_sources, "sessions"] if remember_across_conversations else configured_sources, session_memory)
    return {"sources": sources, "searchSources": search_sources, "sessionMemory": session_memory}


def _matches_agent_pattern(pattern: str, agent_id: str) -> bool:
    raw = _text(pattern)
    if not raw:
        return False
    if raw == "*":
        return True
    if "*" not in raw:
        return raw == agent_id
    parts = raw.lower().split("*")
    lower, position = agent_id.lower(), 0
    if parts[0]:
        if not lower.startswith(parts[0]):
            return False
        position = len(parts[0])
    end = len(lower) - len(parts[-1]) if parts[-1] else len(lower)
    if parts[-1] and (not lower.endswith(parts[-1]) or end < position):
        return False
    for part in filter(None, parts[1:-1]):
        index = lower.find(part, position)
        if index < 0 or index + len(part) > end:
            return False
        position = index + len(part)
    return True


def _a2a_allowed(policy: SessionVisibilityPolicy, requester: str, target: str) -> bool:
    if requester == target:
        return True
    return bool(policy.agent_to_agent_enabled and (
        not policy.agent_allow or (
            any(_matches_agent_pattern(pattern, requester) for pattern in policy.agent_allow)
            and any(_matches_agent_pattern(pattern, target) for pattern in policy.agent_allow)
        )
    ))


def _denied(reason: str, refs: list[str], fields: list[str], missing: list[str] | None = None) -> dict:
    return {"allowed": False, "status": "forbidden", "reasonCode": reason,
            "policyRefs": refs, "contextFieldsUsed": fields, "missingEvidence": missing or []}


def session_visibility_decision(
    row: Mapping[str, Any], *, policy: SessionVisibilityPolicy,
    requester_session_key: str, requester_agent_id: str | None = None,
    default_agent_id: str | None = None, main_session_key: str | None = None,
    visibility: str | None = None, action: str = "history",
    explicit_target_agent_ownership: bool = False,
) -> dict[str, Any]:
    """The native row-aware decision, preserving its complete denial evidence."""
    mode = visibility or policy.effective_visibility()
    requester = _text(requester_agent_id).lower() or resolve_session_agent_id(
        requester_session_key, default_agent_id,
    )
    target_key = row["key"]
    if is_incognito_session_key(target_key):
        return _denied("incognito_session", ["sessions.incognito"], ["targetSessionKey"])
    own_session = target_key in {requester_session_key, "current"}
    target = _text(row.get("agentId")).lower()
    if not target and (target_key == "current" or (target_key == requester_session_key and not _text(default_agent_id))):
        target = requester
    if not target:
        try:
            target = resolve_session_agent_id(target_key, default_agent_id)
        except MemoryToolError:
            return _denied("target_agent_ownership_unavailable", ["session.owner"],
                           ["requesterSessionKey", "targetSessionKey"], ["session.owner"])
    owned = any(row.get(key) == requester_session_key for key in ("ownerSessionKey", "spawnedBy", "parentSessionKey")) or (
        mode == "tree" and target == requester and requester_session_key == main_session_key
    )
    cross_agent = target != requester
    if not own_session and owned and (not cross_agent or _child_key(target_key)) and mode in {"tree", "all"}:
        return {"allowed": True}
    if cross_agent:
        denial = (
            _denied("agent_to_agent_disabled", ["tools.agentToAgent.enabled"], ["requesterAgentId", "targetAgentId"])
            if not policy.agent_to_agent_enabled else
            _denied("agent_to_agent_not_allowed", ["tools.agentToAgent.allow"], ["requesterAgentId", "targetAgentId"])
            if not _a2a_allowed(policy, requester, target) else None
        )
        if action == "status" and explicit_target_agent_ownership and denial:
            return denial
        if mode != "all":
            return _denied("cross_agent_visibility_restricted", ["tools.sessions.visibility"],
                           ["requesterAgentId", "targetAgentId", "visibility"])
        return denial or {"allowed": True}
    if mode == "self" and not own_session:
        return _denied("self_visibility_restricted", ["tools.sessions.visibility"],
                       ["requesterSessionKey", "targetSessionKey", "visibility"])
    if mode == "tree" and not own_session and not owned:
        return _denied("tree_visibility_restricted", ["tools.sessions.visibility"],
                       ["requesterSessionKey", "targetSessionKey", "requesterOwned", "visibility"])
    return {"allowed": True}


def _render_denial(decision: Mapping[str, Any], action: str, target: str) -> str:
    reason = decision["reasonCode"]
    prefix = "Session list" if action == "list" else f"Session {action}"
    if reason == "incognito_session":
        return f"Session not visible from session tools: {target}"
    if reason == "target_agent_ownership_unavailable":
        return f"{prefix} denied because target agent ownership is unavailable."
    if reason == "cross_agent_visibility_restricted":
        return f"{prefix} visibility is restricted. Set tools.sessions.visibility=all to allow cross-agent access; use tools.agentToAgent to restrict permitted agent pairs."
    if reason == "agent_to_agent_disabled":
        if action == "send":
            return "Agent-to-agent messaging is disabled. Set tools.agentToAgent.enabled=true to allow cross-agent sends."
        if action == "list":
            return "Agent-to-agent listing is disabled. Set tools.agentToAgent.enabled=true to allow cross-agent visibility."
        return f"Agent-to-agent {action} is disabled. Set tools.agentToAgent.enabled=true to allow cross-agent access."
    if reason == "agent_to_agent_not_allowed":
        word = "messaging" if action == "send" else "listing" if action == "list" else action
        return f"Agent-to-agent {word} denied by tools.agentToAgent.allow."
    if reason == "self_visibility_restricted":
        return f"{prefix} visibility is restricted to the current session (tools.sessions.visibility=self)."
    if reason == "tree_visibility_restricted":
        return f"{prefix} visibility is restricted to the current session tree (tools.sessions.visibility=tree)."
    kind = reason.removeprefix("session_ownership_lookup_failed_")
    suffix = (
        "spawned-session ownership lookup failed (transient); retry once, then ask the operator to inspect OpenClaw logs."
        if kind == "transient" else
        "spawned-session ownership lookup failed; ask the operator to check gateway configuration and credentials."
        if kind == "credentials" else
        "spawned-session ownership lookup failed; ask the operator to inspect OpenClaw logs."
    )
    return f"{prefix} denied because {suffix}"


def _spawned_lookup(context: SessionVisibilityContext, requester: str, mode: str, action: str) -> SessionOwnershipLookup | None:
    if action == "list" or mode not in {"tree", "all"}:
        return None
    try:
        result = context.load_spawned_keys(requester) if context.load_spawned_keys else None
        return result if isinstance(result, SessionOwnershipLookup) else SessionOwnershipLookup(failure_kind="unknown")
    except Exception as error:
        return SessionOwnershipLookup(failure_kind=getattr(error, "kind", "unknown"))


def _access_checker(
    context: SessionVisibilityContext, requester: str, agent_id: str,
    sandboxed: bool, *, action: str = "history",
) -> Callable[[str], dict[str, Any]]:
    policy = context.policy
    mode = policy.effective_visibility(sandboxed)
    main = policy.main_session_key(agent_id) if not sandboxed or policy.sandbox_visibility == "all" else None
    spawned = _spawned_lookup(context, requester, mode, action)

    def decide(target: str, *, owned: bool = False) -> dict[str, Any]:
        return session_visibility_decision(
            {"key": target, **({"spawnedBy": requester} if owned else {})}, policy=policy,
            requester_session_key=requester, requester_agent_id=agent_id,
            main_session_key=main, visibility=mode, action=action,
        )

    def check(target: str) -> dict[str, Any]:
        if is_incognito_session_key(target):
            decision = decide(target)
        else:
            if action != "list" and context.scoped_access is not None:
                try:
                    expected = _text(context.scoped_access(requester, target))
                    if expected:
                        return {"allowed": True, "expectedSessionId": expected}
                except Exception:
                    pass
            decision = decide(target, owned=bool(spawned and target in spawned.keys))
            if (not decision["allowed"] and spawned is not None and spawned.failure_kind
                    and target not in {requester, "current"} and decide(target, owned=True)["allowed"]):
                kind = spawned.failure_kind if spawned.failure_kind in {"transient", "credentials"} else "unknown"
                decision = _denied(f"session_ownership_lookup_failed_{kind}", ["tools.sessions.visibility"],
                                   ["requesterSessionKey", "targetSessionKey"], ["session.owner"])
        return decision if decision["allowed"] else {
            "allowed": False, "status": "forbidden", "error": _render_denial(decision, action, target),
        }

    return check


def resolve_session_tool_access(
    context: SessionVisibilityContext, *, requester_session_key: str,
    target_session_key: str, agent_id: str | None = None,
    sandboxed: bool = False, action: str = "history",
    target_agent_id: str | None = None, session_read_scope_key: str | None = None,
) -> dict[str, Any]:
    """Resolve source-history access with the native structured decision owner.

    Description and ownership evidence come from the current authoritative
    catalog. This is distinct from the rendered guard used by memory search.
    """
    # The prepared source-access owner takes an explicit requesterAgentId;
    # it does not repeat the search filter's strict requester/store selection.
    requester_agent = _text(agent_id).lower() or resolve_session_agent_id(
        requester_session_key, context.policy.default_agent_id,
    )
    target_agent = target_agent_id or resolve_session_agent_id(target_session_key, context.policy.default_agent_id)
    policy = context.policy
    mode = policy.effective_visibility(sandboxed)
    main = policy.main_session_key(requester_agent) if not sandboxed or policy.sandbox_visibility == "all" else None

    def decide(row: Mapping[str, Any], *, requester: str = requester_session_key, visibility: str = mode) -> dict:
        return session_visibility_decision(
            row, policy=policy, requester_session_key=requester, requester_agent_id=requester_agent,
            default_agent_id=target_agent, main_session_key=main, visibility=visibility, action=action,
            explicit_target_agent_ownership=_agent_parts(target_session_key) is None,
        )

    target = {"key": target_session_key, "agentId": target_agent}
    if session_read_scope_key:
        capped = decide(target, requester=session_read_scope_key, visibility="self")
        if not capped["allowed"]:
            return capped
    if not is_incognito_session_key(target_session_key) and context.scoped_access:
        try:
            expected = _text(context.scoped_access(requester_session_key, target_session_key))
            if expected:
                return {"allowed": True, "expectedSessionId": expected}
        except Exception:
            pass
    initial = decide(target)
    if initial["allowed"]:
        return initial
    owned = decide({**target, "spawnedBy": requester_session_key})
    if not owned["allowed"]:
        return initial
    if action == "history":
        entry = context.load_catalog().get(target_session_key)
        if entry is not None:
            described = decide({**entry, **target})
            if not described["allowed"]:
                return described
            expected = _text(entry.get("sessionId"))
            if expected:
                return {"allowed": True, "expectedSessionId": expected}
    lookup = _spawned_lookup(context, requester_session_key, mode, action)
    if lookup is not None and lookup.failure_kind:
        kind = lookup.failure_kind if lookup.failure_kind in {"transient", "credentials"} else "unknown"
        return _denied(f"session_ownership_lookup_failed_{kind}", ["tools.sessions.visibility"],
                       ["requesterSessionKey", "targetSessionKey"], ["session.owner"])
    return owned if lookup is not None and target_session_key in lookup.keys else initial


def read_visible_session_source(
    catalog: SessionCatalogReader, context: SessionVisibilityContext | None = None, *,
    requester_session_key: str, target_session_key: str, agent_id: str | None = None,
    sandboxed: bool = False, session_read_scope_key: str | None = None,
    target_agent_id: str | None = None,
) -> dict[str, Any]:
    """Authorize a current transcript identity, then read its complete persisted events."""
    context = context or SessionVisibilityContext.from_catalog(catalog)
    target_agent = target_agent_id or resolve_session_agent_id(target_session_key, catalog.agent_id)
    access = resolve_session_tool_access(
        context, requester_session_key=requester_session_key, target_session_key=target_session_key,
        agent_id=agent_id, target_agent_id=target_agent, sandboxed=sandboxed,
        session_read_scope_key=session_read_scope_key,
    )
    if not access["allowed"]:
        return {"access": access, "events": []}

    def current_identity() -> str:
        entry = catalog.snapshot().entries.get(target_session_key)
        expected = _text(access.get("expectedSessionId"))
        if expected and (entry is None or entry.get("sessionId") != expected or "archivedAt" in entry):
            raise MemoryToolError(f'Session "{target_session_key}" changed after access was granted.')
        return _text(entry.get("sessionId")) if entry else ""

    session_id = current_identity()
    if not session_id:
        return {"access": access, "events": []}
    transcript = catalog.read_transcript(session_id, agent_id=target_agent, session_key=target_session_key)
    current_identity()
    return {"access": access, "sessionId": session_id,
            "events": list(transcript.events) if transcript is not None else []}


def _primary_name(name: str) -> bool:
    return name.endswith(".jsonl") and not name.endswith(".trajectory.jsonl") and _CHECKPOINT.fullmatch(name) is None


def extract_transcript_identity_from_sessions_memory_hit(path: str) -> dict[str, Any] | None:
    normalized = path.replace("\\", "/")
    rest = normalized[len("sessions/"):] if normalized.startswith("sessions/") else normalized
    parts = [part for part in rest.split("/") if part]
    base = rest.rstrip("/").rsplit("/", 1)[-1]
    owner = normalize_session_agent_id(parts[0]) if normalized.startswith("sessions/") and len(parts) == 2 else None
    archive = _ARCHIVE.fullmatch(base)
    if archive and _primary_name(archive["stem"] + ".jsonl"):
        return {"stem": archive["stem"], **({"ownerAgentId": owner} if owner else {}), "archived": True}
    if base.endswith(".jsonl") and base[:-6]:
        return {"stem": base[:-6], **({"ownerAgentId": owner} if owner else {}), "archived": False}
    return None


def resolve_transcript_stem_to_session_keys(
    store: Mapping[str, Mapping[str, Any]], stem: str, archived_owner_agent_id: str | None = None,
) -> list[str]:
    file_name = stem if stem.endswith(".jsonl") else stem + ".jsonl"
    archive = _ARCHIVE.fullmatch(file_name)
    parsed_id = archive["stem"] if archive else file_name[:-6] if _primary_name(file_name) else None
    matches = [key for key, entry in store.items() if not is_incognito_session_key(key)
               and (entry.get("sessionId") == stem or (parsed_id and entry.get("sessionId") == parsed_id))]
    if matches or not _text(archived_owner_agent_id):
        return matches
    fallback = f"agent:{normalize_session_agent_id(archived_owner_agent_id)}:{stem}"
    return [] if is_incognito_session_key(fallback) else [fallback]


def _same_transcript(anchor: Mapping[str, Any] | None, candidate: Mapping[str, Any] | None) -> bool:
    return bool(anchor and candidate and (
        (_text(anchor.get("sessionId")) and _text(anchor.get("sessionId")) == _text(candidate.get("sessionId")))
        or (_text(anchor.get("sessionFile")) and _text(anchor.get("sessionFile")) == _text(candidate.get("sessionFile")))
    ))


class SessionAgentSelectionRequiredError(MemoryToolError):
    name = "AgentSelectionRequiredError"
    code = "AGENT_SELECTION_REQUIRED"

    def __init__(self, agent_ids: Sequence[str], session_agent: str, explicit_agent: str):
        self.agentIds = list(agent_ids)
        self.surface = "session agent resolution"
        self.hint = f'The agent-scoped session key belongs to "{session_agent}", not "{explicit_agent}".'
        super().__init__(f"Multiple agents are configured, but {self.surface} has no explicit owner. {self.hint}")


def _strict_requester_agent(key: str, agent_id: str | None, policy: SessionVisibilityPolicy) -> str:
    parsed = _agent_parts(key)
    if not parsed and _text(key).lower().startswith("agent:"):
        raise MemoryToolError("Malformed agent session key; refusing default-agent resolution.")
    explicit = re.sub(r"[^a-z0-9_-]+", "-", _text(agent_id).lower()).strip("-")[:64] if agent_id is not None else None
    if agent_id is not None and not explicit:
        raise MemoryToolError("Invalid explicit agent id; refusing default-agent resolution.")
    session_agent = normalize_session_agent_id(parsed[0]) if parsed else None
    if session_agent and explicit and session_agent != explicit:
        raise SessionAgentSelectionRequiredError(
            policy.configured_agent_ids or (policy.default_agent_id,), session_agent, explicit,
        )
    return session_agent or explicit or policy.default_agent_id


def resolve_memory_search_tool_agent(
    session_key: str | None, agent_id: str, policy: SessionVisibilityPolicy | None = None,
) -> str:
    """Resolve the trusted tool owner before any model arguments or corpus work.

    Native tool context selection precedes execution, independently of the
    result filter's legitimate early return for memory-only candidate lists.
    """
    return _strict_requester_agent(
        session_key or "", agent_id,
        policy or SessionVisibilityPolicy(default_agent_id=normalize_session_agent_id(agent_id)),
    )


def _private_conversation(agent_id: str, entry: Mapping[str, Any] | None, key: str) -> bool:
    if entry is None:
        return False
    lowered = _text(key).lower()
    delivery = entry.get("delivery")
    origin = delivery.get("origin") if isinstance(delivery, Mapping) and delivery.get("kind") == "external" else None
    chat_types = [value for value in (
        entry.get("chatType"), origin.get("chatType") if isinstance(origin, Mapping) else None,
    ) if value is not None]
    if any(value == "group" or value == "channel" for value in chat_types) or _ACTIVE_MEMORY.search(lowered):
        return False
    prefix = f"agent:{_text(agent_id).lower()}:"
    if lowered in {"global", prefix + "global"}:
        return False
    if lowered.startswith(prefix + "explicit:"):
        return bool(chat_types) and all(value == "direct" for value in chat_types)
    if ":group:" in lowered or ":channel:" in lowered or re.search(r":(?:active-memory|cron|heartbeat|hook|node|subagent)(?::|$)", lowered):
        return False
    return all(value == "direct" for value in chat_types) if chat_types else ":direct:" in lowered or ":dm:" in lowered


def filter_memory_search_hits_by_session_visibility(
    hits: Sequence[Mapping[str, Any]], *, context: SessionVisibilityContext | None = None,
    agent_id: str | None = None, requester_session_key: str | None = None,
    sandboxed: bool = False, conversation_recall: Mapping[str, Any] | None = None,
    trusted_agent_scope: bool = False,
) -> list[dict[str, Any]]:
    """Filter full candidate rows before the tool's source/limit/debug stages."""
    recall = conversation_recall
    if not any(hit.get("source") == "sessions" for hit in hits):
        return [] if recall and recall.get("corpus") == "sessions" else list(hits)
    context = context or SessionVisibilityContext()
    policy = context.policy
    mode = policy.effective_visibility(sandboxed)
    requester_agent = _strict_requester_agent(requester_session_key, agent_id, policy) if requester_session_key else None
    scoped_agent = _text(agent_id) or requester_agent
    guard = _access_checker(context, requester_session_key, requester_agent, sandboxed) if requester_session_key else None
    store = {key: value for key, value in context.load_catalog().items() if not is_incognito_session_key(key)}
    identities = [(hit, extract_transcript_identity_from_sessions_memory_hit(hit["path"]))
                  for hit in hits if hit.get("source") == "sessions"]
    archive_names = list(dict.fromkeys(
        hit["path"].replace("\\", "/").rsplit("/", 1)[-1]
        for hit, identity in identities if identity and identity["archived"]
    ))
    archives = context.load_archives(archive_names, scoped_agent) if context.load_archives else []
    archive_by_name = {entry["archiveName"]: entry for entry in archives}
    trusted = bool(trusted_agent_scope and scoped_agent and not requester_session_key and not recall)
    anchor = _text(recall.get("anchorSessionKey")) if recall else ""
    recall_agent = resolve_session_agent_id(anchor, policy.default_agent_id) if anchor else None
    anchor_entry = store.get(anchor)
    requester = _text(requester_session_key)
    trusted_requester = bool(anchor and (requester == anchor or (
        requester.startswith(anchor) and re.fullmatch(r":active-memory:[a-f0-9]{12}", requester[len(anchor):], re.I)
    )))
    authorized = bool(
        recall and not sandboxed and recall.get("scope") == "same-agent-private"
        and recall.get("corpus") in {"sessions", "configured"} and trusted_requester
        and _text(recall_agent).lower() == _text(scoped_agent).lower() and recall_agent
        and _private_conversation(recall_agent, anchor_entry, anchor)
        and all(key == anchor or not _same_transcript(anchor_entry, entry)
                or _private_conversation(recall_agent, entry, key) for key, entry in store.items())
    )
    if recall is not None and not authorized:
        return [hit for hit in hits if hit.get("source") != "sessions"] if recall.get("corpus") == "configured" else []

    def allowed(key: str, allow_anchor: bool) -> bool:
        if not recall or not anchor or not recall_agent:
            visible_key = f"agent:{scoped_agent}:global" if scoped_agent and policy.session_scope == "global" and _text(key).lower() == "global" else key
            return trusted or bool(guard and guard(visible_key)["allowed"])
        entry = store.get(key)
        if not allow_anchor and (key == anchor or _same_transcript(anchor_entry, entry)):
            return False
        if resolve_session_agent_id(key, policy.default_agent_id).lower() != recall_agent.lower():
            return False
        return _private_conversation(recall_agent, entry, key)

    result = []
    cutoff: Mapping[str, Any] | None = None
    for hit in hits:
        if hit.get("source") != "sessions":
            if not recall or recall.get("corpus") == "configured":
                result.append(hit)
            continue
        if not trusted and (not requester_session_key or (guard is None and not recall)):
            continue
        identity = extract_transcript_identity_from_sessions_memory_hit(hit["path"])
        if identity is None:
            continue
        reason_match = _ARCHIVE_REASON.search(hit["path"])
        archive_reason = reason_match[1] if reason_match else None
        if recall and archive_reason == "deleted":
            continue
        owner = _text(identity.get("ownerAgentId")).lower()
        scope = _text(scoped_agent).lower()
        if scope and owner and owner != scope:
            continue
        archive_name = hit["path"].replace("\\", "/").rsplit("/", 1)[-1]
        archived = archive_by_name.get(archive_name) if identity["archived"] else None
        archived_owner = identity.get("ownerAgentId") if identity["archived"] and owner and (not scope or owner == scope) else None
        keys = [archived["sessionKey"]] if archived and archived.get("sessionKey") else resolve_transcript_stem_to_session_keys(
            store, archived.get("sessionId", identity["stem"]) if archived else identity["stem"], archived_owner,
        )
        keys = [key for key in keys if not scope or (
            policy.session_scope == "global" and _text(key).lower() == "global"
        ) or resolve_session_agent_id(key, policy.default_agent_id).lower() == scope]
        if not keys:
            if not identity["archived"] and scope and owner == scope and mode in {"agent", "all"} and not recall:
                result.append(hit)
            continue
        allow_reset_anchor = False
        anchor_id = _text(anchor_entry.get("sessionId")) if anchor_entry else ""
        if recall and not identity["archived"] and recall_agent and anchor_id and identity["stem"] == anchor_id and owner == recall_agent.lower():
            if cutoff is None:
                try:
                    cutoff = context.read_reset_cutoff(recall_agent, anchor_id, anchor) if context.read_reset_cutoff else {"state": "invalid"}
                except Exception:
                    cutoff = {"state": "invalid"}
            allow_reset_anchor = cutoff.get("state") == "valid" and hit["endLine"] < cutoff["cutoffLine"]
        if recall:
            expanded = list(dict.fromkeys(keys))
            for key in keys:
                expanded.extend(candidate for candidate, entry in store.items()
                                if candidate not in expanded and _same_transcript(store.get(key), entry))
            permitted = all(allowed(key, archive_reason == "reset" or allow_reset_anchor) for key in expanded)
        else:
            permitted = any(allowed(key, False) for key in keys)
        if permitted:
            result.append(hit)
    return result
