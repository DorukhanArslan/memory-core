"""Literal scripted-model and trusted registry inputs for actual turn-trust owners."""
from __future__ import annotations

from copy import deepcopy


NOW = 1_794_268_800_000
PROFILE = (
    "Actual original AgentLoop with literal no-provider responses and registered before-tool "
    "callbacks; one original sticky taint state is reused across explicitly controlled attempts. "
    "The actual native coding writer and SDK provenance writer execute real filesystem mutations; "
    "their outer registered write tool returns the same full literal payload. Complete outer "
    "returns/errors, emitted messages, live trust, artifact records and persisted session/source "
    "provenance are compared after a fresh-process reopen. The source taint owner is one exact "
    "authenticated dependency-free upstream TypeScript module; other native owners use the "
    "pinned published runtime. No provider request, automatic retry policy, native coding-tool "
    "presentation, loop-diagnostic hash or full host-turn barrier is claimed."
)
POLICY = (
    "No trust result or provenance decision is supplied. Registry source classification, "
    "owner identity, clocks and scripted response bodies are common literal inputs. Exact "
    "owned fixture-prefix aliases are the only path codec. Complete original native outcome "
    "observations and inner coding-tool results remain in raw evidence; SDK actual outcomes "
    "remain raw as well. No field dropping, hash fabrication, error rewriting, sorting repair "
    "or score tolerance is used at the declared comparison boundary."
)


def _assistant(content, stop_reason="stop"):
    return {"role": "assistant", "content": content, "api": "openai-completions", "provider": "openai",
            "model": "fixture-trust-model", "stopReason": stop_reason, "timestamp": NOW,
            "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0,
                      "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}}


def _call(identifier, name, arguments):
    return _assistant([{"type": "toolCall", "id": identifier, "name": name, "arguments": arguments}], "toolUse")


def _prompt(text, owner):
    return {"role": "user", "content": [{"type": "text", "text": text}], "timestamp": NOW,
            "__openclaw": {"senderIsOwner": owner}}


def build_turn_trust_cases():
    write_result = {"content": [{"type": "text", "text": "The fixture memory write completed.", "preserved": 7}],
                    "details": {"changed": True, "nested": {"kept": [False, None, "full"]}},
                    "outerOnly": {"preserve": "the complete actual registered return"}}
    base = {"kind": "turn-trust", "nowMs": NOW, "agentId": "main", "sessionId": "trust-session",
            "sessionKey": "agent:main:dm:trust", "writeResult": write_result,
            "tools": [{"name": "web_fixture", "resultContentSource": "network",
                       "result": {"content": [{"type": "text", "text": "External cedar preference."}],
                                  "details": {"source": "fixture-network", "nested": [1, True, None]},
                                  "outerOnly": {"network": "preserve"}}},
                      {"name": "local_fixture", "result": {"content": [{"type": "text", "text": "Local owner fact."}],
                                                              "details": {"source": "fixture-local"}}},
                      {"name": "network_failure", "resultContentSource": "network",
                       "error": {"name": "Error", "message": "Declared network fixture failure.", "code": "FIXTURE_NETWORK"}}]}
    network = {**base, "turns": [
        {"id": "network-turn", "senderIsOwner": True,
         "prompt": _prompt("Read the external preference, then save it.", True), "attempts": [
             {"id": "before-retry", "responses": [_call("web-call", "web_fixture", {"query": "cedar"})]},
             {"id": "after-retry", "responses": [
                 _call("tainted-write", "write_memory", {"path": "memory/2026-11-10.md", "content": "External cedar preference."}),
                 _assistant([{"type": "text", "text": "The external preference was saved."}]),
             ]},
         ]},
        {"id": "new-clean-turn", "senderIsOwner": True,
         "presentationObservations": [{"toolName": "host_presentation", "argsHash": "", "resultHash": "",
             "resultContentSource": "network", "presentationOnly": True,
             "terminalPresentation": "Fixture presentation update."}],
         "prompt": _prompt("A new owner turn writes two local notes.", True), "attempts": [
             {"id": "clean-attempt", "responses": [
                 _call("local-read", "local_fixture", {}),
                 _call("same-file-write", "write_memory", {"path": "memory/2026-11-10.md", "content": "Later owner note on an already quarantined file."}),
                 _call("new-file-write", "write_memory", {"path": "memory/clean.md", "content": "A clean owner note in a new file."}),
                 _assistant([{"type": "text", "text": "Both local notes were written."}]),
             ]},
         ]},
    ]}
    failure = {**base, "turns": [
        {"id": "non-owner-turn", "senderIsOwner": False,
         "prompt": _prompt("Save this non-owner request.", False), "attempts": [
             {"id": "local-only", "responses": [
                 _call("non-owner-local", "local_fixture", {}),
                 _call("non-owner-write", "write_memory", {"path": "memory/non-owner.md", "content": "A note requested by a non-owner."}),
                 _assistant([{"type": "text", "text": "The non-owner note was written."}]),
             ]},
         ]},
        {"id": "network-error-turn", "senderIsOwner": True,
         "prompt": _prompt("Try the external tool, then save a recovery note.", True), "attempts": [
             {"id": "failed-source", "responses": [_call("failed-network", "network_failure", {"query": "cedar"})]},
             {"id": "retry-after-error", "responses": [
                 _call("error-write", "write_memory", {"path": "memory/error.md", "content": "A recovery note after a network execution error."}),
                 _assistant([{"type": "text", "text": "The recovery note was written."}]),
             ]},
         ]},
    ]}
    cases = []
    for name, value in (("network-retry-new-turn", network), ("owner-and-network-error", failure)):
        for turn in value["turns"]:
            for attempt in turn["attempts"]:
                for index, response in enumerate(attempt["responses"]):
                    # Original ensureToolTurnIdentity accepts caller-provided
                    # model response identities before any tool execution.
                    response["turnId"] = f"{name}:{turn['id']}:{attempt['id']}:{index}"
        cases.append({"id": "turn-trust-" + name, "requirement": "trust.configured-redaction",
                      "operation": "turn-trust-runtime", "covers": [], "input": deepcopy(value),
                      "driverScope": PROFILE, "normalizationPolicy": POLICY})
    return cases
