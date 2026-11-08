"""Literal persisted host inputs for integrated session visibility comparisons.

No expected hit lists, access decisions or projected corpus rows are supplied.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


_NOW = 1_790_000_000_000
_ALICE = "agent:main:direct:alice"
_BOB = "agent:main:direct:bob"
_PEER = "agent:peer:direct:carol"
_CHILD = "agent:main:subagent:child"


def _event(identity: str, text: str, *, owner: bool = True, tainted: bool = False) -> dict:
    return {"type": "message", "id": identity, "message": {
        "role": "user", "content": text,
        "__openclaw": {"senderIsOwner": owner, "turnTainted": tainted},
    }}


def _session(key: str, identity: str, *, agent: str = "main", events: list | None = None,
             **metadata: Any) -> dict:
    return {"agentId": agent, "sessionKey": key,
            "entry": {"sessionId": identity, "chatType": "direct", "updatedAt": _NOW,
                      **deepcopy(metadata)},
            "events": deepcopy(events) if events is not None else [
                _event(identity + "-one", f"Cobalt private {identity} conversation."),
            ]}


def _query(identity: str, requester: str | None = _BOB, **options: Any) -> dict:
    return {"id": identity, "query": "Cobalt", "corpus": "sessions", "minScore": 0,
            **({"requesterSessionKey": requester} if requester is not None else {}), **options}


def _read(identity: str, target: str, *, requester: str = _BOB, **options: Any) -> dict:
    return {"id": identity, "requesterSessionKey": requester, "targetSessionKey": target,
            **options}


def _flow(name: str, visibility: str, sessions: list[dict], steps: list[dict],
          **settings: Any) -> dict:
    return {"name": name, "requirement": "sessions.visibility-lineage", "input": {
        "kind": "flow", "nowMs": _NOW, "includeContentRevision": False, "agentId": "main",
        "files": {"MEMORY.md": "Cobalt workspace fact.\n"},
        "config": {"visibility": visibility, "sources": ["memory", "sessions"],
                   "agentIds": ["main", "peer"], **deepcopy(settings)},
        "sessions": sessions, "steps": steps,
    }}


def build_visibility_flows() -> list[dict[str, Any]]:
    """Drive actual persisted metadata, queries and current-key source reads."""
    flows = []
    flows.append(_flow("visibility-self-and-missing-requester", "self", [
        _session(_ALICE, "alice"),
        _session(_BOB, "bob", events=[_event("bob-one", "Cobalt private bob conversation.", owner=False)]),
        _session("agent:main:discord:group:room", "group", chatType="group"),
    ], [{"label": "authorized-window", "queries": [
        _query("self-small-limit", maxResults=1),
        _query("missing-requester", None),
        _query("memory-without-requester", None, corpus="memory"),
    ], "reads": [_read("self-source", _BOB), _read("other-source-denied", _ALICE)]}]))

    flows.append(_flow("visibility-tree-persisted-lineage", "tree", [
        _session(_ALICE, "alice"), _session(_BOB, "bob"),
        _session(_CHILD, "child", spawnedBy=_BOB, parentSessionKey=_BOB,
                 status="running", startedAt=_NOW - 1_000),
        _session("agent:main:subagent:grandchild", "grandchild", spawnedBy=_CHILD,
                 parentSessionKey=_CHILD, status="running", startedAt=_NOW - 500),
        _session("agent:main:subagent:unrelated", "unrelated", spawnedBy=_ALICE,
                 status="running", startedAt=_NOW - 500),
    ], [
        {"label": "live-lineage", "queries": [_query("ordinary-tree"), _query("sandbox-tree", sandboxed=True)],
         "reads": [_read("child-history", _CHILD),
                   _read("unrelated-history", "agent:main:subagent:unrelated")]},
        {"label": "retained-child-expired", "sessions": [{
            "sessionKey": _CHILD, "entry": {"sessionId": "child", "chatType": "direct",
                "spawnedBy": _BOB, "parentSessionKey": _BOB, "status": "done",
                "endedAt": _NOW - 1_800_001},
        }], "queries": [_query("tree-after-child-expiry"), _query("sandbox-after-child-expiry", sandboxed=True)]},
    ]))

    flows.append(_flow("visibility-agent-owner-and-misbound-requester", "agent", [
        _session(_ALICE, "alice"), _session(_BOB, "bob"),
        _session(_PEER, "carol", agent="peer"),
    ], [{"label": "scoped-agents", "queries": [
        _query("agent-local-results"),
        _query("misbound-requester", _PEER),
        _query("memory-only-misbound-early-return", _PEER, corpus="memory"),
    ], "reads": [_read("agent-peer-history", _PEER, targetAgentId="peer"),
                 _read("agent-own-history", _ALICE)]}]))

    flows.append(_flow("visibility-all-a2a-disabled-and-sandbox-ceiling", "all", [
        _session(_ALICE, "alice"), _session(_BOB, "bob"),
        _session(_PEER, "carol", agent="peer"),
        _session(_CHILD, "child", spawnedBy=_BOB, status="running", startedAt=_NOW - 1_000),
    ], [{"label": "ordinary-and-sandbox", "queries": [
        _query("all-local-results"), _query("sandbox-all-clamped", sandboxed=True),
    ], "reads": [_read("disabled-peer-history", _PEER, targetAgentId="peer"),
                 _read("sandbox-child-history", _CHILD, sandboxed=True),
                 _read("sandbox-peer-conversation", _ALICE, sandboxed=True)]}],
        tools={"agentToAgent": {"enabled": False}}))

    recall = {"scope": "same-agent-private", "corpus": "sessions", "anchorSessionKey": _BOB}
    configured_recall = {**recall, "corpus": "configured"}
    alice_shared = "agent:main:discord:group:alice-alias"
    bob_shared = "agent:main:discord:group:bob-alias"
    flows.append(_flow("visibility-private-recall-all-aliases", "all", [
        _session(_ALICE, "alice", events=[
            _event("alice-one", "Cobalt private alice conversation.", tainted=True),
        ]),
        _session(_BOB, "bob"), _session(_PEER, "carol", agent="peer"),
    ], [
        {"label": "private-anchor", "queries": [
            _query("ordinary-all"),
            _query("private-recall", conversationRecall=recall),
            _query("trusted-auxiliary-recall", _BOB + ":active-memory:012345abcdef", conversationRecall=recall),
            _query("malformed-auxiliary-recall", _BOB + ":active-memory:012345abcde", conversationRecall=recall),
            _query("wrong-private-requester", _ALICE, conversationRecall=recall),
            _query("configured-private-recall", corpus="all", conversationRecall=configured_recall),
            _query("peer-owned-manager", _PEER, agentId="peer"),
        ], "reads": [_read("enabled-peer-history", _PEER, targetAgentId="peer")]},
        {"label": "candidate-shared-alias", "sessions": [{
            "sessionKey": alice_shared, "entry": {"sessionId": "alice", "chatType": "group"},
        }], "queries": [_query("ordinary-any-visible-alias"),
                         _query("private-all-alias-check", conversationRecall=recall)]},
        {"label": "candidate-alias-removed", "deleteSessions": [{"sessionKey": alice_shared}],
         "queries": [_query("private-recall-after-alias-removal", conversationRecall=recall)]},
        {"label": "anchor-shared-alias", "sessions": [{
            "sessionKey": bob_shared, "entry": {"sessionId": "bob", "chatType": "group"},
        }], "queries": [_query("shared-anchor-sessions", conversationRecall=recall),
                         _query("shared-anchor-configured", corpus="all", conversationRecall=configured_recall)]},
    ], tools={"agentToAgent": {"enabled": True, "allow": ["m*", "p*"]}}))

    before = _event("bob-before", "Cobalt earlier private anchor context.")
    kept = _event("bob-kept", "Cobalt retained private anchor context.")
    flows.append(_flow("visibility-private-recall-persisted-reset-cutoff", "all", [
        _session(_ALICE, "alice"), _session(_BOB, "bob", events=[before, kept]),
    ], [
        {"label": "before-reset-boundary", "queries": [_query("anchor-before-reset", conversationRecall=recall)],
         "reads": [_read("source-before-reset", _BOB)]},
        {"label": "valid-persisted-reset-boundary", "replaceEvents": [{
            "sessionKey": _BOB, "sessionId": "bob", "events": [
                before, kept, {"type": "reset", "id": "boundary-one", "firstKeptEntryId": "bob-kept"},
            ],
        }], "queries": [_query("anchor-after-reset", conversationRecall=recall)],
         "reads": [_read("source-after-reset", _BOB)]},
        {"label": "invalid-persisted-reset-boundary", "replaceEvents": [{
            "sessionKey": _BOB, "sessionId": "bob", "events": [
                before, kept, {"type": "reset", "id": "boundary-two", "firstKeptEntryId": "missing-entry"},
            ],
        }], "queries": [_query("anchor-invalid-reset", conversationRecall=recall)],
         "reads": [_read("source-invalid-reset", _BOB)]},
    ]))
    return flows
