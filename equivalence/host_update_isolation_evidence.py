"""Custody checks for the closed host update/isolation family.

``validate_result`` checks one engine's public result against invariants that
follow from the frozen literal alone. Equality between the two engines' public
results is the harness's job.

``validate_capture`` binds that public result to the same engine's raw capture.
It never repairs, reorders or drops an observed field, and it refuses a capture
that lacks a required receipt. On both engines it requires:

* Process custody. Three distinct processes; the producer host finished before
  the updating host started; each host received exactly its own phase with the
  declared identity, clock, policy and owned directory; the recorded input
  digest and output stream are the ones that host consumed and produced.
* Read dataflow. Every read ran in a fresh session whose first model input
  holds only its declared prompt. It dispatched the declared generic search and
  took the source read's range from the first actual hit. The public search,
  source read and reply equal the dispatched tool results and the model-visible
  messages. The returned text is that line range of the source bytes that were
  current when the read ran.
* Save and update dispatch. Both sources were absent and were created by the
  producer tool with the declared bytes. The update was one dispatch of the
  update tool. A declared refusal carries the engine's own hard-link cause.
* Publications. Each explicit forced publication record equals its public
  outcome. A failed one left the engine reporting its real error until the
  final publication succeeded.
* The declared real fault window, the source-metadata receipts, the resolved
  memory-only source policy, one separate owner per agent, no other agent's
  fact in a source or index, and complete close receipts.

Limits that a reader must not infer past:

* Original owner artifacts are authenticated as loaded modules by the trace
  validation in ``host_update_isolation_native``. Nothing here adds to that.
  The original tool-identity flags read below are receipts written by the
  authenticated actor, not independent proof.
* The engine-specific receipts (write and update tool results, refusal texts,
  ``afterWriteError``, turn outcomes, operation journals) are custody only.
  They are never compared between engines.
* On the SDK the host's real system prompt embeds the agent's own current
  ``MEMORY.md`` as project context. The original actor drives a bare agent loop
  with an empty system prompt. The guard requires that the SDK embedding is
  exactly that agent's source as it was when the session opened, and that
  nothing else in a first model input carries a saved fact. Scripted replies
  are bound to actual tool results on both engines.
* In the publication-failure literal the SDK's own refresh inside the update
  tool has already failed, with the same error, when the explicit forced
  publication fails. The guard requires both journal entries in that order
  before the stale read. The compared stale payload cannot tell them apart.
* The pinned original resolves on-search and watch synchronization as enabled
  whatever is configured, and the guard requires that resolved state. Only the
  explicit publications are bound here and compared.
* The pinned original also resolves hybrid temporal decay and MMR as enabled,
  and the guard requires that state too. The SDK owner runs with temporal decay
  off. ``MEMORY.md`` is an undated source that the original does not decay and
  every compared search has at most one hit, so ranking is not exercised here.
* That a host's process input carries no fact outside its own phase is a
  property of the frozen literal, which the exact request check then enforces.
* The original prints the refused path through a helper that replaces its
  process's home directory by ``~`` when the fixture lies below it, as in a
  checkout under a hosted runner's home. The guard accepts that spelling while
  it still shows this run's own fixture directory. No compared field carries an
  absolute path.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from equivalence.host_update_isolation import validate_case

ROOT = Path(__file__).resolve().parents[1]
EMPTY_ANSWER = "No source-backed memory found."
HARD_LINK = "source-hard-link-during-update"
SIDECAR = "index-publication-sidecar-symlink"
STALE_ERROR = "unable to open database file"
SOURCE = "MEMORY.md"
NATIVE_REFUSAL = "Hardlinked path is not allowed under sandbox root"
SDK_REFUSAL = "MEMORY.md has more than one hard link"
NATIVE_PUBLICATION = {"reason": "host-update-isolation-producer-publication", "force": True}
SEARCH_OPTIONS = {"maxResults": 5, "minScore": 0, "corpus": "memory"}
RESOLVED_POLICY = {"sources": ["memory"], "searchSources": ["memory"], "sessionMemory": False}
SDK_ENVIRONMENT = ["LANG", "OPENCLAW_HOME", "OPENCLAW_STATE_DIR", "PATH", "PYTHONPATH", "TZ"]
_SENTENCES = ("My drink preference is now ", "My drink preference is ", "My bicycle lock code is ")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _hex(text):
    return text.encode("utf-8").hex()


def expected_sources(case):
    """Source bytes implied by the literal alone: the update either commits or leaves every byte."""
    produce, update = case["input"]["phases"]
    fault = update.get("fault", {}).get("operation")
    before = produce["save"]["content"]
    require(before.count(update["update"]["old"]) == 1, "The literal's superseded entry must occur exactly once")
    after = before if fault == HARD_LINK else before.replace(update["update"]["old"], update["update"]["new"])
    isolated = produce["isolatedSave"]["content"]
    return {"before": before, "after": after, "isolated": isolated, "fault": fault}


def _source(text):
    return {"path": "MEMORY.md", "kind": "file", "text": text, "hex": _hex(text)}


def _validate_read(read, session, query):
    require(isinstance(read, dict) and set(read) == {"session", "query", "search", "get", "answer"}
            and read["session"] == session and read["query"] == query, "A declared read is missing or reassigned")
    search = read["search"]
    require(isinstance(search, dict) and isinstance(search.get("results"), list), "A read retained no complete search payload")
    if search["results"]:
        hit = search["results"][0]
        get = read["get"]
        require(isinstance(get, dict) and get.get("path") == hit.get("path") and get.get("from") == hit.get("startLine"),
                "The source read did not follow the actual first search hit")
        expected = get["text"] if isinstance(get.get("text"), str) and get["text"] else json.dumps(
            get, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        require(read["answer"] == expected, "The reply was not derived from the actual source read")
    else:
        require(read["get"] is None and read["answer"] == EMPTY_ANSWER, "An empty search must yield the declared empty reply")
    return search


def _clean_empty(search):
    """An empty result of a search that really ran: nothing found and nothing withheld, disabled or failed."""
    debug = search.get("debug")
    return (set(search) == {"results", "provider", "citations", "debug"} and search["results"] == []
            and isinstance(debug, dict) and debug.get("hits") == 0 and debug.get("candidateHits") == 0
            and debug.get("withheldHits") == 0)


def validate_result(case, result):
    """Engine-independent invariants of one public result; equality between engines is the harness's job."""
    validate_case(case)
    expected = expected_sources(case)
    fault = expected["fault"]
    produce, update = case["input"]["phases"]
    main, isolated = case["input"]["identity"]["agentId"], case["input"]["identity"]["isolatedAgentId"]
    require(isinstance(result, dict) and set(result) == {"provider", "phases"} and result["provider"] == "none"
            and isinstance(result["phases"], list) and len(result["phases"]) == 2, "The public result is not the declared two-host shape")
    first, second = result["phases"]
    require(set(first) == {"label", "publications", "reads", "source", "isolatedSource"} and first["label"] == "produce",
            "The producer host returned an undeclared shape")
    require(set(second) == {"label", "update", "publications", "reads", "source", "isolatedSource"} and second["label"] == "update",
            "The updating host returned an undeclared shape")
    require(first["source"] == _source(expected["before"]) and first["isolatedSource"] == _source(expected["isolated"]),
            "The producer host did not leave the declared corpus bytes")
    require(second["source"] == _source(expected["after"]) and second["isolatedSource"] == _source(expected["isolated"]),
            "The updating host did not leave the declared current bytes or changed another agent's source")
    require(first["publications"] == [{"agentId": main, "stage": "produce", "failed": False, "error": None},
                                      {"agentId": isolated, "stage": "produce", "failed": False, "error": None}],
            "The producer publications differ from the declared lifecycle")
    final = {"agentId": main, "stage": "final", "failed": False, "error": None}
    faulted = {"agentId": main, "stage": "faulted", "failed": True, "error": STALE_ERROR}
    require(second["publications"] == ([faulted, final] if fault == SIDECAR else [final]),
            "The update publications differ from the declared lifecycle or real failure")
    committed = fault != HARD_LINK
    require(second["update"] == {"committed": committed,
            "answer": update["update"]["ack"] if committed else update["update"]["failureAck"]},
            "The update report differs from the actual outcome")
    reads = first["reads"]
    require(len(reads) == 3, "The producer host must return its three declared reads")
    declared = (("before", produce["recall"]), ("supersededBefore", produce["supersededRecall"]),
                ("isolatedBefore", produce["recall"]))
    require(produce["supersededRecall"] == update["recalls"]["superseded"],
            "The positive control must use the query that is later required to find nothing")
    for read, (session, instruction) in zip(reads, declared):
        search = _validate_read(read, session, instruction["query"])
        require("stale" not in search and "warning" not in search and len(search["results"]) >= 1,
                "A producer read was stale or empty")
    require(update["update"]["old"] in reads[0]["answer"] and update["update"]["old"] in reads[1]["answer"]
            and update["update"]["old"] in reads[1]["search"]["results"][0]["snippet"]
            and produce["isolatedSave"]["entries"][0]["text"] in reads[2]["answer"],
            "The producer reads did not return each agent's own saved preference")
    reads = second["reads"]
    names = (["stale"] if fault == SIDECAR else []) + ["current", "superseded", "unrelated", "isolated"]
    require(len(reads) == len(names), "The updating host must return exactly its declared reads")
    recalls = update["recalls"]
    current_text = update["update"]["new"] if committed else update["update"]["old"]
    for read, session in zip(reads, names):
        instruction = recalls["current" if session == "stale" else session]
        search = _validate_read(read, session, instruction["query"])
        if session == "stale":
            require(search.get("stale") is True and STALE_ERROR in search.get("warning", "")
                    and isinstance(search.get("action"), str), "The failed publication was not reported by the next search")
            require(search["results"] and update["update"]["old"] in search["results"][0]["snippet"]
                    and update["update"]["new"] in read["answer"],
                    "The stale read must show the superseded index hit and the committed current source")
            continue
        require("stale" not in search and "warning" not in search, "A read after the final publication still reported staleness")
        if session == "current":
            require(current_text in read["answer"] and (not committed or update["update"]["old"] not in read["answer"]),
                    "The current answer differs from the committed source")
        elif session == "superseded":
            # The producer host showed that this query finds the entry. After a committed update it must
            # find nothing in a search that really ran; after a refused update it must still be served.
            require(_clean_empty(search) if committed else update["update"]["old"] in read["answer"],
                    "The superseded entry's retrievability differs from the committed source")
        elif session == "unrelated":
            require(produce["save"]["entries"][1]["text"] in read["answer"], "The unrelated fact was not retained")
        else:
            require(read == first["reads"][2] | {"session": "isolated"},
                    "The independent agent's read changed after the other agent's update")
    return True


def _wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text(message):
    content = message.get("content", [])
    return content if isinstance(content, str) else "".join(
        item["text"] for item in content if item.get("type") == "text")


def _decode(message):
    """The JSON a memory tool result carries; its text and its complete details must agree."""
    payload = json.loads(_text(message))
    require("details" in message and payload == message["details"],
            "Model-visible JSON differs from the complete tool details")
    return payload


def _tool_messages(messages, name):
    return [item for item in messages if item.get("role") == "toolResult" and item.get("toolName") == name]


def _token(text):
    for prefix in _SENTENCES:
        if text.startswith(prefix) and text.endswith(".") and len(text) > len(prefix) + 1:
            return text[len(prefix):-1]
    raise ValueError("A saved entry no longer has a declared sentence form")


def saved_tokens(case):
    """The distinctive value of each saved fact. A session may obtain one only from its prompt or its own tools."""
    produce, update = case["input"]["phases"]
    tokens = {"old": _token(update["update"]["old"]), "new": _token(update["update"]["new"]),
              "unrelated": _token(produce["save"]["entries"][1]["text"]),
              "isolated": _token(produce["isolatedSave"]["entries"][0]["text"])}
    require(len(set(tokens.values())) == 4, "The saved facts cannot be told apart")
    return tokens


def _plan(case):
    """Each host's declared sessions in execution order, with the source bytes each one opens and runs on."""
    value = case["input"]
    produce, update = value["phases"]
    expected = expected_sources(case)
    main, other = value["identity"]["agentId"], value["identity"]["isolatedAgentId"]

    def item(session, kind, agent, instruction, opened, current):
        return {"session": session, "kind": kind, "agent": agent, "instruction": instruction,
                "opened": opened, "current": current}

    first = [item("writer", "save", main, produce["save"], None, expected["before"]),
             item("isolatedWriter", "save", other, produce["isolatedSave"], None, expected["isolated"]),
             item("before", "recall", main, produce["recall"], expected["before"], expected["before"]),
             item("supersededBefore", "recall", main, produce["supersededRecall"], expected["before"], expected["before"]),
             item("isolatedBefore", "recall", other, produce["recall"], expected["isolated"], expected["isolated"])]
    second = [item("updater", "update", main, update["update"], expected["before"], expected["after"])]
    for name in (["stale"] if expected["fault"] == SIDECAR else []) + ["current", "superseded", "unrelated"]:
        second.append(item(name, "recall", main, update["recalls"]["current" if name == "stale" else name],
                           expected["after"], expected["after"]))
    second.append(item("isolated", "recall", other, update["recalls"]["isolated"],
                       expected["isolated"], expected["isolated"]))
    return first, second


def _first_input(item, tokens, messages, rest, *, native):
    """Only the declared prompt may carry a saved fact into a session's first model input."""
    prompt = item["instruction"]["prompt"]
    require(len(messages) == 1 and messages[0].get("role") == "user"
            and messages[0]["content"] == ([{"type": "text", "text": prompt}] if native else prompt),
            "A fresh session's first model input must hold only its own declared prompt")
    carried = _wire([rest, {key: value for key, value in messages[0].items() if key != "content"}])
    require(all(token not in carried for token in tokens.values()),
            "A saved fact reached a first model input outside the declared prompt")
    if item["kind"] == "recall" and item["session"] not in ("supersededBefore", "superseded"):
        require(all(token not in prompt and token not in item["instruction"]["query"] for token in tokens.values()),
                "A generic reader was given a saved fact in its prompt or query")


def _read_custody(public, item, calls, terminal, assistant, policy):
    """Bind one public read to its dispatched tools, model-visible results and current source bytes."""
    query = item["instruction"]["query"]
    names = ["memory_search", "memory_get"] if public["get"] is not None else ["memory_search"]
    require([call["name"] for call in calls] == names, "The real read tool sequence differs from its public result")
    require(calls[0]["arguments"] == {"query": query, **SEARCH_OPTIONS}, "Search was not the declared generic source query")
    found = _tool_messages(terminal, "memory_search")
    require(len(found) == 1 and _decode(found[0]) == public["search"] == calls[0]["payload"],
            "The public search differs from the dispatched result or the model-visible message")
    for hit in public["search"]["results"]:
        require(hit.get("path") == SOURCE and hit.get("source") == "memory"
                and hit["provenance"]["observedAt"] == policy["sourceMtimeMs"],
                "A hit does not come from the declared source at its declared physical timestamp")
    read = _tool_messages(terminal, "memory_get")
    if public["get"] is None:
        require(read == [], "A source read was dispatched without a public result")
        expected = EMPTY_ANSWER
    else:
        hit, payload = public["search"]["results"][0], public["get"]
        require(calls[1]["arguments"] == {"path": hit["path"], "from": hit["startLine"],
                                          "lines": hit["endLine"] - hit["startLine"] + 1, "corpus": "memory"},
                "The source read range did not come from the actual first search hit")
        require(len(read) == 1 and _decode(read[0]) == payload == calls[1]["payload"],
                "The public source read differs from the dispatched result or the model-visible message")
        require(payload.get("status") == "ok", "The source read failed")
        selected = item["current"].splitlines()[payload["from"] - 1:payload["from"] - 1 + payload["lines"]]
        backed = "\n".join(selected)
        if payload.get("truncated"):
            backed += f"\n\n[More content available. Use from={payload['nextFrom']} to continue.]"
        require(payload["text"] == backed,
                "The returned text is not the line range of the source that was current when the read ran")
        expected = payload["text"]
    require(public["answer"] == expected == _text(assistant), "The reply did not come from the actual tool result")


def _own_corpus(indexed, current, tokens):
    """A published index holds exactly the saved facts of its own agent's current source."""
    require(all((token in indexed) is (token in current) for token in tokens.values()),
            "A published index holds another agent's fact or does not reflect its own current source")


def native_refusal_names_source(reason, workspace):
    """Whether the original's hard-link refusal names this run's workspace and its source.

    The release prints both paths through one helper. It replaces the home directory of
    its process by ``~`` when a path lies below it, and leaves other paths absolute.
    The absolute message names the paths exactly. The home-relative one is accepted only
    while it still shows the fixture directory that this run created and its workspace,
    so the replaced home is a proper ancestor of that directory. A text relative to the
    fixture directory itself would name nothing of this run, and no run can print it.
    """
    source = f"{workspace}/{SOURCE}"
    if reason == f"{NATIVE_REFUSAL} ({workspace}): {source}":
        return True
    opening, closing = f"{NATIVE_REFUSAL} (~", "): ~"
    if not isinstance(reason, str) or not reason.startswith(opening + "/") or closing not in reason:
        return False
    below_home, _, shown = reason[len(opening):].partition(closing)
    # One home directory, a proper ancestor of the fixture directory, was replaced in both paths.
    home = workspace[:-len(below_home)]
    return (shown == f"{below_home}/{SOURCE}" and workspace.endswith(below_home) and below_home.count("/") >= 2
            and (home == "" or home.startswith("/") and not home.endswith("/")))


def _public_publications(records):
    return [{"agentId": entry["agentId"], "stage": entry["stage"], "failed": entry["failed"],
             "error": entry["error"]["message"] if entry["failed"] else None} for entry in records]


def _snapshot_labels(ordinal):
    return ["after-real-writes-and-explicit-publication" if ordinal == 0 else "after-update-and-explicit-publication",
            "after-active-recall"]


def _native_phase(case, raw, record, phase, public, ordinal, plan, tokens):
    value = case["input"]
    identity, policy, base = value["identity"], value["policy"], raw["fixtureBase"]
    expected = expected_sources(case)
    fault = expected["fault"]
    main, other = identity["agentId"], identity["isolatedAgentId"]
    workspace = {main: base + "/workspace", other: base + "/isolated-workspace"}
    database = {agent: f"{base}/state/agents/{agent}/agent/openclaw-agent.sqlite" for agent in (main, other)}
    require(phase["kind"] == "host-update-isolation-phase" and phase["label"] == record["label"]
            and phase["executable"] == record["executable"] and phase["stdin"] == record["stdin"]
            and record["ppid"] == raw["coordinatorPid"] and len(record["argv"]) == 1
            and record["argv"][0].endswith("/host-update-isolation-phase-cli.mjs"),
            "The original host process is not the protected phase actor of this coordinator")
    require(phase["config"] == raw["config"] and raw["config"]["agents"]["entries"] == {
                main: {"workspace": workspace[main]}, other: {"workspace": workspace[other]}},
            "The original hosts did not share the coordinator's two-workspace configuration")
    require(phase["clock"]["dateConstructorReplaced"] is True and phase["clock"]["setTimeoutUnchanged"] is True
            and phase["clock"]["nowMs"] == value["nowMs"],
            "The host clock control differs from the declared Date-only control")
    resolved = phase["resolvedMemorySearch"]
    require([owner["agentId"] for owner in resolved] == [main, other],
            "Both original owners must resolve their source policy")
    for owner in resolved:
        config = owner["config"]
        require(config["sources"] == RESOLVED_POLICY["sources"] and config["searchSources"] == RESOLVED_POLICY["searchSources"]
                and config["experimental"]["sessionMemory"] is RESOLVED_POLICY["sessionMemory"]
                and config["provider"] == "none" and config["store"]["databasePath"] == database[owner["agentId"]],
                "The original resolver used another source policy or database")
        require(all(config["sync"][key] is True for key in ("onSessionStart", "onSearch", "watch")),
                "The pinned original no longer resolves its automatic synchronization as enabled")
        query = config["query"]
        require(query["maxResults"] == SEARCH_OPTIONS["maxResults"] and query["minScore"] == SEARCH_OPTIONS["minScore"]
                and query["hybrid"]["temporalDecay"]["enabled"] is True and query["hybrid"]["mmr"]["enabled"] is True,
                "The pinned original no longer resolves its declared query limits or its ranking defaults")

    sessions, loops, factories = phase["sessions"], phase["loops"], phase["toolFactoryCalls"]
    labels = [item["session"] for item in plan]
    require([entry["label"] for entry in sessions] == labels == [entry["label"] for entry in loops]
            and [entry["label"] for entry in factories] == labels,
            "The original host ran other sessions than its declared ones")
    reads, appended, producers = iter(public["reads"]), 0, []
    for item, session, loop, factory in zip(plan, sessions, loops, factories):
        agent, declared = item["agent"], identity[item["session"]]
        scope = {"agentId": agent, "storePath": f"{base}/state/agents/{agent}/sessions/sessions.json",
                 "sessionKey": declared["sessionKey"], "sessionId": declared["sessionId"]}
        require(session["scope"] == scope == loop["scope"] and loop["kind"] == item["kind"],
                "A session used another identity, agent or store than declared")
        require(session["initialEvents"] == [] and loop["initialMessages"] == []
                and scope["sessionKey"] not in session["loadedStore"],
                "A declared fresh session inherited earlier history")
        persisted = session["persistence"]
        require(len(persisted) == len(loop["messages"])
                and all(entry["method"] == "appendSessionTranscriptMessageByIdentityStrict"
                        and entry["result"]["kind"] == "result" and entry["result"]["result"]["appended"] is True
                        and entry["versionAfter"] == entry["versionBefore"] + 1 for entry in persisted)
                and persisted[0]["result"]["result"]["anchor"]["rawSeq"] == 1
                and persisted[0]["result"]["result"]["effectiveParentId"] is None,
                "The original host did not commit exactly this session's own loop messages")
        appended += len(persisted)
        first = loop["modelCalls"][0]
        require(set(first["context"]) == {"systemPrompt", "messages", "tools"}
                and [call["ordinal"] for call in loop["modelCalls"]] == list(range(len(loop["modelCalls"]))),
                "The recorded model calls are not this loop's complete ordered calls")
        _first_input(item, tokens, first["context"]["messages"],
                     {"model": first["model"], "options": first["options"],
                      "systemPrompt": first["context"]["systemPrompt"], "tools": first["context"]["tools"]}, native=True)
        calls = []
        for event in loop["toolEvents"]:
            requests = [block for call in loop["modelCalls"] for block in call["response"]["content"]
                        if block.get("type") == "toolCall" and block.get("id") == event["toolCallId"]]
            require(len(requests) == 1 and requests[0]["name"] == event["toolName"]
                    and event["type"] == "tool_execution_end" and event["executionStarted"] is True,
                    "A tool result has no unique real model request or its execution never started")
            calls.append({"name": event["toolName"], "arguments": requests[0]["arguments"], "event": event})
        require(len(loop["modelCalls"]) == len(calls) + 1,
                "The loop made model calls that its tool results do not explain")
        terminal, assistant = loop["modelCalls"][-1]["context"]["messages"], loop["messages"][-1]
        names = [tool["name"] for tool in loop["tools"]]
        if item["kind"] == "recall":
            require(names == ["memory_search", "memory_get"] == factory["names"]
                    and factory.get("originalToolObjectsPassedToAgentLoop") is True,
                    "A reader was not given exactly the two original memory tools")
            require(all(call["event"]["isError"] is False for call in calls), "A real memory tool dispatch failed")
            _read_custody(next(reads), item, [{**call, "payload": _decode(call["event"]["result"])} for call in calls],
                          terminal, assistant, policy)
            continue
        tool = "write" if item["kind"] == "save" else "edit"
        require(names == [tool] and tool in factory["names"]
                and factory.get("originalToolObjectPassedToAgentLoop") is True
                and len(calls) == 1 and calls[0]["name"] == tool,
                "A producer was not one dispatch of its original coding tool")
        event = calls[0]["event"]
        shown = _tool_messages(terminal, tool)
        require(len(shown) == 1 and shown[0]["content"] == event["result"]["content"]
                and shown[0].get("isError") is event["isError"],
                "The model-visible producer result differs from the dispatched one")
        producers.append((item, event))
        if item["kind"] == "save":
            require(calls[0]["arguments"] == {"path": SOURCE, "content": item["instruction"]["content"]}
                    and event["isError"] is False and event["result"]["details"].get("created") is True
                    and _text(assistant) == item["instruction"]["ack"],
                    "The original write tool did not create the declared source from an absent file")
            continue
        refused = fault == HARD_LINK
        require(calls[0]["arguments"] == {"path": SOURCE, "edits": [
                    {"oldText": item["instruction"]["old"], "newText": item["instruction"]["new"]}]}
                and event["isError"] is refused and _text(assistant) == public["update"]["answer"],
                "The original edit dispatch differs from the declared update or its outcome")
        if refused:
            reason = _text(event["result"])
            # The refused text is kept, bounded, so that a rejection can be diagnosed from the report.
            require(native_refusal_names_source(reason, workspace[agent]),
                    f"The original refusal is not the declared hard-link refusal of this source: {reason[:400]!r}")
        else:
            require(event["result"]["details"].get("changed") is True, "The original edit reported no committed change")

    outcomes = phase["toolOutcomes"]
    require([(entry["session"], entry["observation"]["toolName"]) for entry in outcomes]
            == [(item["session"], event["toolName"]) for item, event in producers]
            and all(entry["observation"]["resultHash"].startswith("error:") is event["isError"]
                    for entry, (_, event) in zip(outcomes, producers)),
            "The original runtime's own tool outcomes differ from the recorded producer results")
    committed = [(item, event) for item, event in producers if event["isError"] is False]
    metadata, seconds = phase["sourceMetadataSetup"], policy["sourceMtimeMs"] / 1000
    require(len(metadata) == len(committed), "Source metadata was not set exactly once after each committed producer write")
    for receipt, (item, event) in zip(metadata, committed):
        filename, before, after = f"{workspace[item['agent']]}/{SOURCE}", receipt["before"], receipt["after"]
        require(receipt["operation"] == "set-source-mtime" and receipt["agentId"] == item["agent"]
                and receipt["trigger"] == event and before["kind"] == after["kind"] == "file"
                and before["absolutePath"] == after["absolutePath"] == filename
                and before["sha256"] == after["sha256"] == _sha(item["current"]) and after["nlink"] == 1
                and after["mtimeMs"] == policy["sourceMtimeMs"] and receipt["calls"] == [
                    {"operation": "utimesSync", "arguments": [filename, seconds, seconds], "returnedUndefined": True}],
                "The source metadata receipt changed source bytes or is not the declared timestamp operation")

    records = phase["publications"]
    require(_public_publications(records) == public["publications"],
            "The public publication outcomes differ from the original publication records")
    runtime, retained = Path(record["request"]["runtimeRoot"]).as_uri() + "/", {}
    for entry in records:
        agent, status = entry["agentId"], entry["statusAfter"]
        require(entry["operation"] == "sync" and entry["request"] == NATIVE_PUBLICATION
                and status["workspaceDir"] == workspace[agent] and status["dbPath"] == database[agent]
                and status["sources"] == ["memory"] and entry["statusBefore"].get("lastSyncError") == retained.get(agent),
                "An original publication was not the declared forced rebuild of that agent's own index")
        if entry["failed"]:
            require(runtime in entry["error"].get("stack", "")
                    and status.get("lastSyncError") == STALE_ERROR and status.get("dirty") is True,
                    "The failed publication was not raised and retained by the original runtime")
            retained[agent] = STALE_ERROR
        else:
            require(entry.get("returnedUndefined") is True and "lastSyncError" not in status
                    and status.get("dirty") is False and status["custom"]["indexIdentity"]["status"] == "valid",
                    "A successful original publication left its index dirty, failed or unowned")
            retained.pop(agent, None)

    mutations = phase["mutations"]
    if ordinal == 0 or fault is None:
        require(mutations == [], "An undeclared filesystem mutation was performed")
    elif fault == HARD_LINK:
        source, linked = f"{workspace[main]}/{SOURCE}", base + "/retained-source-link.md"
        require([entry["stage"] for entry in mutations] == ["before-update-tool", "after-update-tool"]
                and all(entry["operation"] == fault and side["absolutePath"] == source and side["kind"] == "file"
                        and side["sha256"] == _sha(expected["before"])
                        for entry in mutations for side in (entry["before"], entry["after"]))
                and [entry[side]["nlink"] for entry in mutations for side in ("before", "after")] == [1, 2, 2, 1]
                and mutations[0]["calls"] == [
                    {"operation": "linkSync", "arguments": [source, linked], "returnedUndefined": True}]
                and mutations[1]["calls"] == [
                    {"operation": "unlinkSync", "arguments": [linked], "returnedUndefined": True}],
                "The declared real hard-link refusal window was not observed")
    else:
        sidecar, retired = database[main] + ".reindex-lock.sqlite", base + "/retired-reindex-lock.sqlite"
        target = base + "/missing-sidecar-directory/lock"
        require([entry["stage"] for entry in mutations] == ["before-update", "after-stale-read"]
                and all(entry["operation"] == fault and entry["sidecar"] == sidecar for entry in mutations)
                and mutations[0]["before"]["kind"] == "file" and mutations[0]["after"]["kind"] == "symlink"
                and mutations[0]["after"]["target"] == target and mutations[1]["before"]["kind"] == "symlink"
                and mutations[1]["before"]["target"] == target and mutations[1]["after"]["kind"] == "file"
                and mutations[1]["after"]["sha256"] == mutations[0]["before"]["sha256"]
                and mutations[0]["calls"] == [
                    {"operation": "renameSync", "arguments": [sidecar, retired], "returnedUndefined": True},
                    {"operation": "symlinkSync", "arguments": [target, sidecar], "returnedUndefined": True}]
                and mutations[1]["calls"] == [
                    {"operation": "unlinkSync", "arguments": [sidecar], "returnedUndefined": True},
                    {"operation": "renameSync", "arguments": [retired, sidecar], "returnedUndefined": True}],
                "The declared real publication-sidecar fault window was not observed")

    current = {main: expected["before"] if ordinal == 0 else expected["after"], other: expected["isolated"]}
    snapshots = phase["snapshots"]
    require([entry["label"] for entry in snapshots] == _snapshot_labels(ordinal)
            and [owner["agentId"] for owner in snapshots[-1]["memory"]] == [main, other],
            "The original host retained other snapshots than its declared ones")
    for snapshot in snapshots:
        require(snapshot["source"] == _source(current[main]) and snapshot["isolatedSource"] == _source(current[other]),
                "A snapshot shows other source bytes than the declared current ones")
        for owner in snapshot["memory"]:
            agent, status = owner["agentId"], owner["status"]
            chunks = next(table["rows"] for table in owner["index"] if table["name"] == "memory_index_chunks")
            require(agent in current and status["workspaceDir"] == workspace[agent] and status["dbPath"] == database[agent]
                    and status["sources"] == ["memory"]
                    and all(chunk["source"] == "memory" and chunk["path"] == SOURCE for chunk in chunks),
                    "An original owner indexed another workspace, database or source")
            _own_corpus(_wire([chunk["text"] for chunk in chunks]), current[agent], tokens)

    require([(entry["operation"], entry["completed"]) for entry in phase["closeReceipts"]]
            == [("closeAllMemoryIndexManagers", True), ("closeOpenClawAgentDatabasesAsync", True)],
            "The original host resources did not close completely")
    versions = phase["transcriptUpdateVersions"]
    require(versions["afterClose"] - versions["beforeRegistration"] == len(phase["transcriptUpdates"]) == appended,
            "Committed transcript notifications do not match the sessions' own commits")
    require([(entry["operation"], entry["agentId"]) for entry in phase["maintenance"]]
            == [("MemoryIndexManager.get", main), ("MemoryIndexManager.get", other)],
            "The original host performed maintenance beyond acquiring its two managers")


def _sdk_metadata(receipts, workspace, current, policy):
    instant = str(policy["sourceMtimeMs"] * 1_000_000)
    require(isinstance(receipts, list) and len(receipts) == 1,
            "A committed SDK write retained no single source-metadata receipt")
    before, after = receipts[0]["before"], receipts[0]["after"]
    require(receipts[0]["operation"] == "os.utime" and receipts[0]["path"] == f"{workspace}/{SOURCE}"
            and receipts[0]["arguments"] == {"ns": [instant, instant]} and receipts[0]["returnedNone"] is True
            and before["source"] == after["source"] == _source(current)
            and all(before["stat"][key] == after["stat"][key] for key in ("dev", "ino", "mode", "nlink", "size"))
            and after["stat"]["nlink"] == 1 and after["stat"]["mtimeNs"] == instant,
            "The source metadata receipt changed source bytes or is not the declared timestamp operation")


def _sdk_journal(journal, location, records, queries, stale):
    """The store's own operation journal: the recorded publications and declared reads, in order, and no repair."""
    require(journal["workspace"] == location["workspace"] and journal["indexPath"] == location["index"]
            and journal["operationJournalTruncated"] is False and journal["repairJournalTruncated"] is False
            and journal["repairs"] == [] and journal["repairCount"] == 0
            and journal["lastSyncError"] is None and "memoryScopeSyncFailure" not in journal,
            "The SDK store repaired itself, lost journal entries or still retained a failure at close")
    operations = [entry for entry in journal["operations"] if entry["name"] != "status"]
    whole = [entry for entry in operations if entry["name"] == "reindex"]
    require(len(whole) == len(records) and all(
                entry["request"] == {"force": True} and entry["state"] == ("failed" if record["failed"] else "completed")
                and (not record["failed"] or entry["error"]["message"] == record["error"]["message"])
                for entry, record in zip(whole, records)),
            "The store journal does not show exactly the recorded forced publications")
    searches = [entry for entry in operations if entry["name"] == "search"]
    require([entry.get("query") for entry in searches] == queries
            and all(entry["state"] == "completed" for entry in searches),
            "The store journal does not show exactly the declared reads")
    order = [(entry["name"], entry["state"]) for entry in operations]
    failed = [entry for entry in operations if entry["state"] != "completed"]
    if stale:
        # The update tool's own refresh, then the explicit forced publication, both fail before the
        # stale read; that turn's own publication fails too, and only then the final one succeeds.
        require(order[:5] == [("reindex-sources", "failed"), ("reindex", "failed"), ("search", "completed"),
                              ("reindex-sources", "failed"), ("reindex", "completed")]
                and len(failed) == 3 and all(entry["error"]["message"] == STALE_ERROR for entry in failed),
                "The store journal does not place the failed forced publication before the stale read")
    else:
        published = [index for index, (name, _) in enumerate(order) if name == "reindex"]
        first_read = next((index for index, (name, _) in enumerate(order) if name == "search"), len(order))
        require(failed == [] and (not published or published[-1] < first_read),
                "The store journal shows a failure or a read before the explicit publication")


def _sdk_phase(case, raw, record, phase, public, ordinal, plan, tokens):
    value = case["input"]
    identity, policy, base = value["identity"], value["policy"], raw["fixtureBase"]
    expected = expected_sources(case)
    fault = expected["fault"]
    main, other = identity["agentId"], identity["isolatedAgentId"]
    locations = {agent: {"workspace": base + ("/workspace" if agent == main else "/isolated-workspace"),
                         "catalog": f"{base}/state/agents/{agent}/sessions/session-authority.sqlite",
                         "sessionStore": f"{base}/state/agents/{agent}/sessions/sessions.json",
                         "index": f"{base}/state/agents/{agent}/agent/openclaw-agent.sqlite"} for agent in (main, other)}
    # The interpreter may add LC_CTYPE itself when it coerces a C locale; nothing else may appear.
    require(phase["kind"] == "host-update-isolation" and phase["label"] == record["label"]
            and phase["implementationRoot"] == str(ROOT)
            and record["argv"][1:] == ["-m", "equivalence.host_update_isolation_phase_cli"]
            and record["environmentKeys"] == SDK_ENVIRONMENT
            and sorted(set(phase["environmentKeys"]) - {"LC_CTYPE"}) == SDK_ENVIRONMENT,
            "The SDK host process is not the protected phase actor of this worktree in its declared environment")
    require(phase["policyResolution"] == {"input": policy, "result": RESOLVED_POLICY},
            "The SDK did not resolve the declared memory-only source policy")
    order, owners = list(dict.fromkeys(item["agent"] for item in plan)), {}
    require([entry["agentId"] for entry in phase["ownerAcquisitions"]] == order,
            "The SDK host opened other owners than its declared agents")
    for entry in phase["ownerAcquisitions"]:
        agent, config = entry["agentId"], entry["config"]
        require(entry["paths"] == locations[agent] and config["workspace_dir"] == locations[agent]["workspace"]
                and config["store_path"] == locations[agent]["index"] and config["agent_id"] == agent
                and config["session_search"] is RESOLVED_POLICY["sessionMemory"]
                and config["flags"]["vector_search"] is False
                and config["search_max_results"] == SEARCH_OPTIONS["maxResults"]
                and config["search_min_score"] == SEARCH_OPTIONS["minScore"],
                "An SDK owner used another workspace, index or source policy than declared")
        owners[agent] = {key: entry[key] for key in ("ownerId", "storeId", "controllerId", "catalogId", "kitId", "agentId")}
    require(all(len({owner[key] for owner in owners.values()}) == len(owners)
                for key in ("ownerId", "storeId", "catalogId")), "Two agents shared one SDK owner, store or catalog")

    opens, turns = phase["opens"], phase["turns"]
    labels = [item["session"] for item in plan]
    require([entry["sessionName"] for entry in opens] == labels == [entry["session"] for entry in turns],
            "The SDK host ran other sessions than its declared ones")
    reads, seen = iter(public["reads"]), set()
    for item, opened, turn in zip(plan, opens, turns):
        agent, declared, outcome = item["agent"], identity[item["session"]], turn["outcome"]
        require(opened["agentId"] == agent and opened["paths"] == locations[agent]
                and opened["sessionManagedOwner"] == owners[agent] and opened["ownerReused"] is (agent in seen)
                and opened["session"]["sessionKey"] == declared["sessionKey"]
                and opened["session"]["sessionId"] == declared["sessionId"],
                "A session used another identity or did not use its agent's one shared owner")
        seen.add(agent)
        require(opened["sourceBefore"] == ({"path": SOURCE, "kind": "missing"} if item["opened"] is None
                                           else _source(item["opened"]))
                and opened["managedStatusAfterOpen"].get("lastSyncError")
                == (STALE_ERROR if item["session"] == "stale" else None),
                "A session opened on other source bytes or another index state than the declared ones")
        first = outcome["appends"][0]
        require(turn["kind"] == item["kind"] and outcome["transcript_committed"] is True
                and outcome["cancelled"] is False and first["appended"] is True
                and first["effectiveParentId"] is None and first["anchor"]["rawSeq"] == 1
                and first["anchor"]["sessionId"] == declared["sessionId"] and first["anchor"]["agentId"] == agent,
                "A turn was cancelled, left uncommitted or continued earlier history")
        initial = turn["modelInput"]
        require(set(initial) == {"systemPrompt", "runtimeContext", "tools", "messages"}
                and turn["terminalInput"]["systemPrompt"] == initial["systemPrompt"],
                "The recorded model input is not this turn's complete input")
        prompt = initial["systemPrompt"]
        if item["opened"] is not None:
            marker = f"## {locations[agent]['workspace']}/{SOURCE}\n"
            embedded = marker + item["opened"].rstrip("\n")
            require(prompt.endswith(embedded) and prompt.count(marker) == 1,
                    "The SDK project context is not exactly the agent's own source as the session opened")
            prompt = prompt[:-len(embedded)]
        _first_input(item, tokens, initial["messages"], {"systemPrompt": prompt,
                     "runtimeContext": initial["runtimeContext"], "tools": initial["tools"]}, native=False)
        calls = []
        for call in turn["toolCalls"]:
            observed = call["observed"]
            require(call["returned"] == observed["payload"] == _decode(observed["message"])
                    and observed["message"].get("toolName") == call["name"]
                    and observed["message"].get("toolCallId") == call["id"]
                    and call["assistant"]["content"] == [
                        {"type": "toolCall", "id": call["id"], "name": call["name"], "arguments": call["arguments"]}],
                    "An SDK tool return differs from its model-visible result or its recorded request")
            calls.append({"name": call["name"], "arguments": call["arguments"], "payload": observed["payload"],
                          "failed": observed["message"].get("isError")})
        failures = [(entry["phase"], entry["message"], entry["committed"]) for entry in outcome["failures"]]
        if item["kind"] == "recall":
            require(all(call["failed"] is False for call in calls), "A real memory tool dispatch failed")
            _read_custody(next(reads), item, calls, turn["terminalInput"]["messages"], turn["assistant"], policy)
            require(failures == ([("publication", STALE_ERROR, True)] if item["session"] == "stale" else [])
                    and outcome["memory_writes_committed"] is False,
                    "A reader's turn outcome differs from the declared lifecycle")
            continue
        if item["kind"] == "save":
            entries = item["instruction"]["entries"]
            require([call["name"] for call in calls] == ["add_memory_entry"] * len(entries)
                    and [call["arguments"] for call in calls] == [
                        {"section": entry["section"], "text": entry["text"]} for entry in entries]
                    and all(call["failed"] is False and call["payload"].get("status") == "ok"
                            and call["payload"].get("path") == SOURCE for call in calls)
                    and outcome["memory_writes_committed"] is True and failures == []
                    and _text(turn["assistant"]) == item["instruction"]["ack"],
                    "The SDK producer was not the declared committed curated additions")
            _sdk_metadata(turn.get("sourceMetadata"), locations[agent]["workspace"], item["current"], policy)
            continue
        refused, instruction = fault == HARD_LINK, item["instruction"]
        require(len(calls) == 1 and calls[0]["name"] == "replace_memory_entry"
                and calls[0]["arguments"] == {"old": instruction["old"], "new": instruction["new"]}
                and calls[0]["failed"] is refused and outcome["memory_writes_committed"] is (not refused)
                and _text(turn["assistant"]) == public["update"]["answer"],
                "The SDK update was not one curated replacement with the declared outcome")
        payload = calls[0]["payload"]
        if refused:
            require(payload.get("status") == "error" and SDK_REFUSAL in payload.get("error", "")
                    and failures == [("tool", payload["error"], False)] and "sourceMetadata" not in turn,
                    "The SDK refusal is not the declared hard-link refusal of an uncommitted write")
        else:
            require(payload.get("status") == "ok" and payload.get("path") == SOURCE
                    and payload.get("afterWriteError") == (STALE_ERROR if fault == SIDECAR else None)
                    and failures == ([("tool-index", STALE_ERROR, True)] if fault == SIDECAR else [])
                    and (outcome["index_status"] == "failed") is (fault == SIDECAR),
                    "The committed SDK write misreported its own index refresh")
            _sdk_metadata(turn.get("sourceMetadata"), locations[agent]["workspace"], item["current"], policy)

    records = phase["publications"]
    require(_public_publications(records) == public["publications"],
            "The public publication outcomes differ from the SDK publication records")
    current = {main: expected["before"] if ordinal == 0 else expected["after"], other: expected["isolated"]}
    for entry in records:
        agent, before, after, status = entry["agentId"], entry["publishedBefore"], entry["publishedAfter"], entry["statusAfter"]
        source = [row for row in after["sources"] if row["path"] == SOURCE]
        require(entry["operation"] == "ManagedHostSession.reindex" and entry["request"] == {"force": True}
                and len(source) == 1 and source[0]["source"] == "memory"
                and source[0]["mtime"] == policy["sourceMtimeMs"],
                "An SDK publication was not the declared forced rebuild of the declared source")
        if entry["failed"]:
            require(after == before and source[0]["hash"] == _sha(expected["before"])
                    and status.get("lastSyncError") == STALE_ERROR,
                    "The failed SDK publication changed the published index or was not retained by its status")
        else:
            require(type(entry["returned"]) is int and entry["returned"] == len(after["sources"])
                    and after["revision"] == before["revision"] + 1 and source[0]["hash"] == _sha(current[agent])
                    and "lastSyncError" not in status and status["custom"]["indexIdentity"]["status"] == "valid",
                    "A successful SDK publication did not publish the current source as the next revision")

    mutations = phase["mutations"]
    if ordinal == 0 or fault is None:
        require(mutations == [], "An undeclared filesystem mutation was performed")
    elif fault == HARD_LINK:
        source = f"{locations[main]['workspace']}/{SOURCE}"
        require([entry["stage"] for entry in mutations] == ["before-update-tool", "after-update-tool"]
                and all(entry["operation"] == fault and side["absolutePath"] == source and side["kind"] == "file"
                        and side["sha256"] == _sha(expected["before"])
                        for entry in mutations for side in (entry["before"], entry["after"]))
                and [entry[side]["nlink"] for entry in mutations for side in ("before", "after")] == [1, 2, 2, 1],
                "The declared real hard-link refusal window was not observed")
    else:
        sidecar, target = locations[main]["index"] + "-journal", base + "/missing-sidecar-directory/journal"
        require([entry["stage"] for entry in mutations] == ["before-update", "after-stale-read"]
                and all(entry["operation"] == fault and entry["sidecar"] == sidecar for entry in mutations)
                and mutations[0]["before"]["kind"] == "missing" and mutations[0]["after"]["kind"] == "symlink"
                and mutations[0]["after"]["target"] == target and mutations[1]["before"]["kind"] == "symlink"
                and mutations[1]["before"]["target"] == target and mutations[1]["after"]["kind"] == "missing",
                "The declared real publication-sidecar fault window was not observed")

    snapshots = phase["snapshots"]
    require([entry["label"] for entry in snapshots] == _snapshot_labels(ordinal)
            and [owner["agentId"] for owner in snapshots[-1]["owners"]] == order,
            "The SDK host retained other snapshots than its declared ones")
    for snapshot in snapshots:
        for owner in snapshot["owners"]:
            agent, chunks = owner["agentId"], owner["published"]["chunks"]
            source = [row for row in owner["published"]["sources"] if row["path"] == SOURCE]
            require(agent in current and owner["source"] == _source(current[agent])
                    and len(source) == 1 and source[0]["hash"] == _sha(current[agent])
                    and all(chunk["source"] == "memory" and chunk["path"] == SOURCE for chunk in chunks),
                    "A snapshot shows another source or an index that is not that agent's current source")
            _own_corpus(_wire([chunk["text"] for chunk in chunks]), current[agent], tokens)

    require(phase["settlement"] == [{"session": label, "activeTurn": False, "outstandingBlockingSources": 0}
                                    for label in labels], "The SDK host left an active turn or blocking producer")
    receipts = phase["closeReceipts"]
    require([entry["owner"] for entry in receipts] == [owners[agent] for agent in order],
            "The SDK host did not close exactly its own owners")
    for entry in receipts:
        agent = entry["owner"]["agentId"]
        require(entry["sessions"] == [item["session"] for item in plan if item["agent"] == agent]
                and entry["returnedNone"] is True and entry["before"]["closed"] is False
                and entry["after"]["closed"] is True and entry["after"]["activeOperations"] == 0,
                "An SDK owner did not close after exactly its own sessions")
        _sdk_journal(entry["before"], locations[agent], [item for item in records if item["agentId"] == agent],
                     [item["instruction"]["query"] for item in plan if item["kind"] == "recall" and item["agent"] == agent],
                     ordinal == 1 and agent == main and fault == SIDECAR)
    require(phase["result"] == public, "The SDK host's retained result differs from the one it returned")


def _capture(case, raw, result, native):
    value = case["input"]
    tokens = saved_tokens(case)
    require(raw.get("kind") == "host-update-isolation" and raw.get("input") == value,
            "The capture does not belong to this exact literal")
    records = raw["children"] if native else raw["phases"]
    require([entry["label"] for entry in records] == ["produce", "update"]
            and len({raw["coordinatorPid"], *(entry["pid"] for entry in records)}) == 3,
            "The capture requires a coordinator and two distinct sequential host processes")
    require(int(records[0]["startedAtNs"]) < int(records[0]["finishedAtNs"])
            < int(records[1]["startedAtNs"]) < int(records[1]["finishedAtNs"]),
            "The producer host had not exited before the updating host started")
    base = raw["fixtureBase"]
    require(isinstance(base, str) and base.startswith("/") and not base.endswith("/"),
            "The hosts had no owned absolute fixture directory")
    for ordinal, (record, plan) in enumerate(zip(records, _plan(case))):
        request = record["request"]
        declared = {"directory": base, "identity": value["identity"], "nowMs": value["nowMs"],
                    "phase": value["phases"][ordinal], "sourcePath": value["source"], "policy": value["policy"]}
        if native:
            require(isinstance(request.get("runtimeRoot"), str) and request["runtimeRoot"].startswith("/")
                    and request["runtimeRoot"] == records[0]["request"]["runtimeRoot"],
                    "An original host borrowed another runtime location")
            declared["runtimeRoot"] = request["runtimeRoot"]
        require(request == declared, "A host child ran another phase or received an undeclared carrier")
        carried = _wire(request)
        require(all(tokens[name] not in carried for name in (("new",) if ordinal == 0 else ("unrelated", "isolated"))),
                "A host's process input carried a saved fact that its own phase does not declare")
        stdin = record["stdin"] if native else record["requestJson"]
        require(json.loads(stdin) == request
                and hashlib.sha256(stdin.encode()).hexdigest() == record["stdinSha256" if native else "requestSha256"],
                "Host process input differs from its recorded custody digest")
        require(record["exit"] == ({"code": 0, "signal": None} if native else {"code": 0}),
                "A host child did not exit cleanly")
        output = record["output"] if native else record["observation"]
        require(set(output) == {"result", "raw"} and json.loads(record["stdout"]) == output,
                "A host observation differs from the actual child output stream")
        phase, public = output["raw"], output["result"]
        require(phase["pid"] == record["pid"] and phase["ppid"] == raw["coordinatorPid"] and phase["request"] == request,
                "A host's identity or input changed after its process was launched")
        require(public == result["phases"][ordinal], "The public result differs from the hosts' own results")
        (_native_phase if native else _sdk_phase)(case, raw, record, phase, public, ordinal, plan, tokens)
    if native:
        require(raw.get("result") == result, "The coordinator result differs from the returned result")


def validate_capture(case, raw, result, *, native):
    """Bind one engine's raw capture to its public result and to the declared real lifecycle."""
    validate_result(case, result)
    try:
        _capture(case, raw, result, native)
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration) as error:
        raise ValueError(f"The capture lacks a required custody receipt ({type(error).__name__}: {error})") from None
    return True


def validate_pair(case, native_raw, sdk_raw, native_result, sdk_result):
    validate_capture(case, native_raw, native_result, native=True)
    validate_capture(case, sdk_raw, sdk_result, native=False)
    return True


def replay_case(case, directory):
    """Re-read one retained attempt and require both engines' custody to validate again."""
    directory = Path(directory)
    native_raw = json.loads((directory / "evidence/native-raw.json").read_text(encoding="utf-8"))
    sdk_raw = json.loads((directory / "evidence/python-raw.json").read_text(encoding="utf-8"))
    native = json.loads((directory / "stdout.json").read_text(encoding="utf-8"))
    sdk = json.loads((directory / "sdk-output.json").read_text(encoding="utf-8"))
    require(len(native_raw) == 1 and len(sdk_raw) == 1 and native.get("ok") is True, "A retained attempt is incomplete")
    validate_pair(deepcopy(case), native_raw[0], sdk_raw[0], native["result"], sdk)
    return {"validated": True, "nativeSnapshots": 1, "sdkSnapshots": 1}
