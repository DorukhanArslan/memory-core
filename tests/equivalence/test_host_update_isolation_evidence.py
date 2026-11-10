"""Actual SDK update/isolation hosts, retained original captures and adversarial evidence replays.

Every SDK capture below is a real SDK run of a frozen literal, including the real
hard-link refusal and the real unusable publication sidecar. The original captures
are real retained runs of the pinned release found in this checkout's ignored
``.equivalence-results``; their tests are skipped where the checkout has none.
Each attack rewrites a self-consistent copy and names the one guard that must
refuse it, so a guard that is removed or weakened fails its own test.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import equivalence.host_update_isolation_evidence as evidence
from equivalence.host_restart_session import build_cases as restart_cases
from equivalence.host_update_isolation import build_cases
from equivalence.host_update_isolation_evidence import (
    EMPTY_ANSWER, STALE_ERROR, expected_sources, native_refusal_names_source, saved_tokens, validate_capture,
    validate_pair, validate_result,
)
from equivalence.host_update_isolation_sdk import run_host_update_isolation

ROOT = Path(__file__).resolve().parents[2]
RETAINED = ROOT / ".equivalence-results" / "host-update-isolation"
ASCII, UNICODE, REFUSAL, PUBLICATION = range(4)
PRODUCE, UPDATE = 0, 1


@pytest.fixture(scope="module")
def captures(tmp_path_factory):
    root = tmp_path_factory.mktemp("real-update-isolation-hosts")
    rows = []
    for case in build_cases():
        directory = root / case["id"]
        result = run_host_update_isolation(case["input"], evidence_directory=directory)
        raw = json.loads((directory / "python-raw.json").read_text())[0]
        rows.append((case, raw, result))
    return rows


@pytest.fixture(scope="module")
def native_captures():
    """The newest complete retained original capture of each current literal, if this checkout has one."""
    cases, found = build_cases(), {}
    paths = sorted(RETAINED.glob("**/evidence/native-raw.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            raws = json.loads(path.read_text(encoding="utf-8"))
            returned = json.loads((path.parents[1] / "stdout.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raws, list) or len(raws) != 1 or returned.get("ok") is not True:
            continue
        for index, case in enumerate(cases):
            if index not in found and returned.get("id") == case["id"] and raws[0].get("input") == case["input"]:
                found[index] = (case, raws[0], returned["result"])
    if len(found) != len(cases):
        pytest.skip("This checkout retains no original capture of every current literal; "
                    "only a run of the pinned release runtime produces one")
    return [found[index] for index in range(len(cases))]


def _hosts(raw, native):
    """(process record, that host's own observation) for the producer and the updating host."""
    records = raw["children"] if native else raw["phases"]
    return [(record, record["output"] if native else record["observation"]) for record in records]


def _phase(raw, ordinal, native):
    return _hosts(raw, native)[ordinal][1]["raw"]


def _seal(raw, native):
    """Keep a rewritten copy self-consistent: each host's output stream is its rewritten observation."""
    for record, output in _hosts(raw, native):
        record["stdout"] = json.dumps(output, ensure_ascii=False)


def _publish(raw, result, native):
    """Carry a rewritten public result into every copy the hosts and the coordinator retain."""
    for (_, output), phase in zip(_hosts(raw, native), result["phases"]):
        output["result"] = deepcopy(phase)
        if not native:
            output["raw"]["result"] = deepcopy(phase)
    if native:
        raw["result"] = deepcopy(result)


def _request(raw, ordinal, native, mutate):
    """Rewrite one host's process input everywhere it is recorded, with a matching digest."""
    record, output = _hosts(raw, native)[ordinal]
    mutate(record["request"])
    wire = (json.dumps(record["request"]) if native
            else json.dumps(record["request"], ensure_ascii=False, separators=(",", ":")))
    record["stdin" if native else "requestJson"] = wire
    record["stdinSha256" if native else "requestSha256"] = hashlib.sha256(wire.encode()).hexdigest()
    output["raw"]["request"] = deepcopy(record["request"])
    if native:
        output["raw"]["stdin"] = wire


def _read(result, name, ordinal=UPDATE):
    return next(read for read in result["phases"][ordinal]["reads"] if read["session"] == name)


def _turn(raw, ordinal, session):
    return next(turn for turn in _phase(raw, ordinal, False)["turns"] if turn["session"] == session)


def _opened(raw, ordinal, session):
    return next(entry for entry in _phase(raw, ordinal, False)["opens"] if entry["sessionName"] == session)


def _loop(raw, ordinal, label):
    return next(loop for loop in _phase(raw, ordinal, True)["loops"] if loop["label"] == label)


def _session(raw, ordinal, label):
    return next(entry for entry in _phase(raw, ordinal, True)["sessions"] if entry["label"] == label)


def _event(loop, name):
    return next(event for event in loop["toolEvents"] if event["toolName"] == name)


def _request_block(loop, name):
    return next(block for call in loop["modelCalls"] for block in call["response"]["content"]
                if block.get("type") == "toolCall" and block["name"] == name)


def _sdk_call(turn, name):
    return next(call for call in turn["toolCalls"] if call["name"] == name)


def _sdk_arguments(turn, name, mutate):
    call = _sdk_call(turn, name)
    mutate(call["arguments"])
    call["assistant"]["content"][0]["arguments"] = deepcopy(call["arguments"])


def _sdk_payload(turn, name, payload):
    """Rewrite one SDK tool result everywhere the turn shows it to the model or returns it."""
    call = _sdk_call(turn, name)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    shown = [message for message in turn["terminalInput"]["messages"]
             if message.get("role") == "toolResult" and message.get("toolCallId") == call["id"]]
    for message in [call["observed"]["message"], *shown]:
        message["details"], message["content"] = deepcopy(payload), [{"type": "text", "text": text}]
    call["returned"], call["observed"]["payload"] = deepcopy(payload), deepcopy(payload)


def _native_shown(loop, name):
    return [message for call in loop["modelCalls"] for message in call["context"]["messages"]
            if message.get("role") == "toolResult" and message.get("toolName") == name]


def _native_payload(loop, name, payload):
    """Rewrite one original memory tool result everywhere the loop shows it to the model."""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for target in [_event(loop, name)["result"], *_native_shown(loop, name)]:
        target["details"], target["content"] = deepcopy(payload), [{"type": "text", "text": text}]


def _native_reason(loop, name, text, *, failed):
    """Rewrite an original producer tool's result text and outcome everywhere the loop shows it."""
    event = _event(loop, name)
    event["isError"] = failed
    for target in [event["result"], *_native_shown(loop, name)]:
        target["content"] = [{"type": "text", "text": text}]
    for message in _native_shown(loop, name):
        message["isError"] = failed


def _reply(target, text):
    target["content"] = [{"type": "text", "text": text}]


def _fixture(raw, native, base):
    """Move the whole capture to another declared fixture directory, consistently in both hosts' inputs."""
    raw["fixtureBase"] = base
    for ordinal in (PRODUCE, UPDATE):
        _request(raw, ordinal, native, lambda request: request.update(directory=base))


def _memory_row(published):
    return next(row for row in published["sources"] if row["path"] == "MEMORY.md")


def _chunks(owner):
    """The index rows of one original owner in a snapshot."""
    return next(table["rows"] for table in owner["index"] if table["name"] == "memory_index_chunks")


def _main_close(raw, ordinal=UPDATE):
    return next(entry for entry in _phase(raw, ordinal, False)["closeReceipts"] if entry["owner"]["agentId"] == "main")


def _journal(raw, name, ordinal=UPDATE):
    """The main store's journal entries of one kind, with the whole list for reordering."""
    operations = _main_close(raw, ordinal)["before"]["operations"]
    return operations, [entry for entry in operations if entry["name"] == name]


def _move(items, item, before):
    items.remove(item)
    items.insert(items.index(before), item)


# --- SDK capture -----------------------------------------------------------------------------


@pytest.mark.parametrize("index", range(4))
def test_actual_sdk_update_custody(captures, index):
    case, raw, result = captures[index]
    assert validate_capture(case, raw, result, native=False) is True
    assert validate_result(case, result) is True


def test_real_hosts_show_the_declared_outcomes(captures):
    for index in (ASCII, UNICODE):
        case, _, result = captures[index]
        update = case["input"]["phases"][1]["update"]
        assert result["phases"][1]["update"] == {"committed": True, "answer": update["ack"]}
        assert update["new"] in _read(result, "current")["answer"]
        assert update["old"] in _read(result, "supersededBefore", PRODUCE)["answer"]
        assert _read(result, "superseded")["search"]["results"] == []
        assert _read(result, "superseded")["answer"] == EMPTY_ANSWER
    case, raw, result = captures[REFUSAL]
    update = case["input"]["phases"][1]["update"]
    assert result["phases"][1]["update"] == {"committed": False, "answer": update["failureAck"]}
    assert result["phases"][1]["source"] == result["phases"][0]["source"]
    assert update["old"] in _read(result, "current")["answer"] and update["new"] not in json.dumps(result, ensure_ascii=False)
    refused = _turn(raw, UPDATE, "updater")["toolCalls"][0]["observed"]
    assert refused["message"]["isError"] is True and refused["payload"]["status"] == "error"
    case, raw, result = captures[PUBLICATION]
    update = case["input"]["phases"][1]["update"]
    assert [item["failed"] for item in result["phases"][1]["publications"]] == [True, False]
    assert result["phases"][1]["publications"][0]["error"] == STALE_ERROR
    stale = _read(result, "stale")
    assert stale["search"]["stale"] is True and STALE_ERROR in stale["search"]["warning"]
    assert update["old"] in stale["search"]["results"][0]["snippet"] and update["new"] in stale["answer"]
    assert "stale" not in _read(result, "current")["search"]
    committed = _turn(raw, UPDATE, "updater")["toolCalls"][0]["observed"]
    assert committed["message"]["isError"] is False and committed["payload"]["afterWriteError"] == STALE_ERROR


def test_every_host_keeps_the_other_agents_source_and_reads_unchanged(captures):
    for case, _, result in captures:
        first, second = result["phases"]
        assert second["isolatedSource"] == first["isolatedSource"]
        assert [read["session"] for read in first["reads"]] == ["before", "supersededBefore", "isolatedBefore"]
        assert _read(result, "isolated") == first["reads"][2] | {"session": "isolated"}
        own = case["input"]["phases"][0]["save"]["entries"][0]["text"]
        assert own not in json.dumps(first["reads"][2], ensure_ascii=False)


def test_sdk_project_context_is_the_agents_own_source_and_the_only_carrier_of_saved_facts(captures):
    """The real SDK system prompt embeds MEMORY.md. The guard binds it; it is not hidden."""
    case, raw, _ = captures[ASCII]
    tokens = saved_tokens(case)
    before = _turn(raw, PRODUCE, "before")["modelInput"]
    isolated = _turn(raw, PRODUCE, "isolatedBefore")["modelInput"]
    writer = _turn(raw, PRODUCE, "writer")["modelInput"]
    assert tokens["old"] in before["systemPrompt"] and tokens["isolated"] not in before["systemPrompt"]
    assert tokens["isolated"] in isolated["systemPrompt"] and tokens["old"] not in isolated["systemPrompt"]
    assert all(token not in writer["systemPrompt"] for token in tokens.values())
    assert all(token not in json.dumps(before["messages"], ensure_ascii=False) for token in tokens.values())


def _empty(read):
    read["search"]["results"] = []
    read["search"]["debug"].update(hits=0, candidateHits=0)
    read["get"], read["answer"] = None, EMPTY_ANSWER


def _result_attack(name, case, result):
    update = case["input"]["phases"][1]["update"]
    second = result["phases"][1]
    if name == "invented-commit":
        second["update"] = {"committed": True, "answer": update["ack"]}
    elif name == "hidden-refusal-source":
        text = expected_sources(case)["before"].replace(update["old"], update["new"])
        second["source"].update(text=text, hex=text.encode().hex())
    elif name == "dropped-stale-flag":
        for key in ("stale", "warning", "action"):
            del _read(result, "stale")["search"][key]
    elif name == "stale-read-reports-current-index":
        hit = _read(result, "stale")["search"]["results"][0]
        hit["snippet"] = hit["snippet"].replace(update["old"], update["new"])
    elif name == "stale-read-hides-committed-source":
        read = _read(result, "stale")
        read["get"]["text"] = read["get"]["text"].replace(update["new"], update["old"])
        read["answer"] = read["get"]["text"]
    elif name == "missing-stale-read":
        del second["reads"][0]
    elif name == "publication-failure-hidden":
        second["publications"][0].update(failed=False, error=None)
    elif name == "publication-error-rewritten":
        second["publications"][0]["error"] = "an operator supplied this reason"
    elif name == "failed-final-publication":
        second["publications"][-1].update(failed=True, error=STALE_ERROR)
    elif name == "superseded-still-served":
        read = _read(result, "superseded")
        before = deepcopy(result["phases"][0]["reads"][0])
        read.update(search=before["search"], get=before["get"], answer=before["answer"])
    elif name == "superseded-search-never-ran":
        _read(result, "superseded")["search"] = {"results": [], "disabled": True}
    elif name == "superseded-hits-withheld":
        _read(result, "superseded")["search"]["debug"]["withheldHits"] = 1
    elif name == "positive-control-empty":
        _empty(result["phases"][0]["reads"][1])
    elif name == "positive-control-other-entry":
        control = result["phases"][0]["reads"][1]
        unrelated = case["input"]["phases"][0]["save"]["entries"][1]["text"]
        control["search"]["results"][0]["snippet"] = f"- {unrelated}\n"
        control["get"]["text"] = control["answer"] = f"- {unrelated}"
    elif name == "missing-positive-control":
        del result["phases"][0]["reads"][1]
    elif name == "unrelated-fact-lost":
        _empty(_read(result, "unrelated"))
    elif name == "isolated-read-changed":
        read = _read(result, "isolated")
        read["get"]["text"] = "- " + update["new"]
        read["answer"] = read["get"]["text"]
    elif name == "isolated-source-changed":
        second["isolatedSource"] = deepcopy(second["source"])
    elif name == "reordered-reads":
        second["reads"][-2], second["reads"][-1] = second["reads"][-1], second["reads"][-2]
    elif name == "answer-not-from-source":
        _read(result, "current")["answer"] = "- " + update["new"]
    elif name == "extra-publication":
        second["publications"].append(deepcopy(second["publications"][-1]))
    elif name == "stale-warning-after-final":
        _read(result, "current")["search"].update(stale=True, warning="Memory index is stale.")
    elif name == "superseded-text-in-current-answer":
        read = _read(result, "current")
        read["get"]["text"] += "\n- " + update["old"]
        read["answer"] = read["get"]["text"]
    elif name == "producer-read-empty":
        _empty(result["phases"][0]["reads"][0])
    elif name == "producer-source-changed":
        result["phases"][0]["source"]["text"] += "- An undeclared entry.\n"
    else:
        raise AssertionError(name)


RESULT_ATTACKS = [
    (REFUSAL, "invented-commit"), (REFUSAL, "hidden-refusal-source"),
    (PUBLICATION, "dropped-stale-flag"), (PUBLICATION, "stale-read-reports-current-index"),
    (PUBLICATION, "stale-read-hides-committed-source"), (PUBLICATION, "missing-stale-read"),
    (PUBLICATION, "publication-failure-hidden"), (PUBLICATION, "publication-error-rewritten"),
    (ASCII, "failed-final-publication"), (ASCII, "superseded-still-served"), (UNICODE, "superseded-still-served"),
    (ASCII, "superseded-search-never-ran"), (UNICODE, "superseded-hits-withheld"),
    (ASCII, "positive-control-empty"), (UNICODE, "positive-control-empty"),
    (ASCII, "positive-control-other-entry"), (ASCII, "missing-positive-control"),
    (ASCII, "unrelated-fact-lost"), (ASCII, "isolated-read-changed"), (ASCII, "isolated-source-changed"),
    (ASCII, "reordered-reads"), (ASCII, "answer-not-from-source"), (ASCII, "extra-publication"),
    (ASCII, "stale-warning-after-final"), (UNICODE, "superseded-text-in-current-answer"),
    (ASCII, "producer-read-empty"), (ASCII, "producer-source-changed"),
]


@pytest.mark.parametrize(("index", "attack"), RESULT_ATTACKS)
def test_rejects_self_consistent_result_substitutions(captures, index, attack):
    case, original, public = captures[index]
    raw, result = deepcopy(original), deepcopy(public)
    _result_attack(attack, case, result)
    # Keep the copy self-consistent: the hosts' own results and streams carry the same rewrite.
    _publish(raw, result, False)
    _seal(raw, False)
    with pytest.raises(ValueError):
        validate_result(case, result)
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=False)


# Guard messages, as regular-expression fragments.
LITERAL = "does not belong to this exact literal"
PROCESSES = "a coordinator and two distinct sequential host processes"
ORDER = "had not exited before the updating host started"
CARRIER = "ran another phase or received an undeclared carrier"
DIGEST = "differs from its recorded custody digest"
EXIT = "did not exit cleanly"
STREAM = "differs from the actual child output stream"
LAUNCH = "identity or input changed after its process was launched"
OWN_RESULTS = "differs from the hosts' own results"
SESSIONS = "ran other sessions than its declared ones"
FIRST_INPUT = "must hold only its own declared prompt"
LEAK = "saved fact reached a first model input outside the declared prompt"
SEQUENCE = "read tool sequence differs from its public result"
QUERY = "not the declared generic source query"
SEARCH = "public search differs from the dispatched result or the model-visible message"
RANGE = "range did not come from the actual first search hit"
READ = "public source read differs from the dispatched result or the model-visible message"
BACKED = "not the line range of the source that was current when the read ran"
TIMESTAMP = "declared source at its declared physical timestamp"
REPLY = "reply did not come from the actual tool result"
TOOL_FAILED = "real memory tool dispatch failed"
CORPUS = "holds another agent's fact or does not reflect its own current source"
MUTATION = "undeclared filesystem mutation was performed"
LINK_WINDOW = "declared real hard-link refusal window was not observed"
SIDECAR_WINDOW = "declared real publication-sidecar fault window was not observed"
METADATA = "changed source bytes or is not the declared timestamp operation"
RECEIPT = "lacks a required custody receipt"
FIXTURE = "no owned absolute fixture directory"
DETAILS = "differs from the complete tool details"
READ_FAILED = "The source read failed"
UNREPORTED = "source read was dispatched without a public result"

SDK_ACTOR = "not the protected phase actor of this worktree in its declared environment"
SDK_POLICY = "did not resolve the declared memory-only source policy"
SDK_OWNERS = "opened other owners than its declared agents"
SDK_OWNER = "another workspace, index or source policy than declared"
SDK_SHARED = "Two agents shared one SDK owner, store or catalog"
SDK_SESSION = "another identity or did not use its agent's one shared owner"
SDK_OPENED = "opened on other source bytes or another index state"
SDK_TURN = "cancelled, left uncommitted or continued earlier history"
SDK_CONTEXT = "project context is not exactly the agent's own source as the session opened"
SDK_RETURN = "tool return differs from its model-visible result or its recorded request"
SDK_READER = "reader's turn outcome differs from the declared lifecycle"
SDK_SAVE = "not the declared committed curated additions"
SDK_NO_METADATA = "retained no single source-metadata receipt"
SDK_UPDATE = "not one curated replacement with the declared outcome"
SDK_REFUSED = "not the declared hard-link refusal of an uncommitted write"
SDK_REFRESH = "misreported its own index refresh"
SDK_PUBLIC = "public publication outcomes differ from the SDK publication records"
SDK_FORCED = "not the declared forced rebuild of the declared source"
SDK_FAILED = "changed the published index or was not retained by its status"
SDK_PUBLISHED = "did not publish the current source as the next revision"
SDK_SNAPSHOTS = "retained other snapshots than its declared ones"
SDK_SNAPSHOT = "index that is not that agent's current source"
SDK_SETTLED = "left an active turn or blocking producer"
SDK_CLOSERS = "did not close exactly its own owners"
SDK_CLOSED = "did not close after exactly its own sessions"
SDK_STORE = "repaired itself, lost journal entries or still retained a failure at close"
SDK_JOURNAL_PUBLICATIONS = "does not show exactly the recorded forced publications"
SDK_JOURNAL_READS = "does not show exactly the declared reads"
SDK_ATTRIBUTION = "does not place the failed forced publication before the stale read"
SDK_JOURNAL_ORDER = "a failure or a read before the explicit publication"
SDK_RETAINED = "retained result differs from the one it returned"


def _sdk_attack(name, case, raw, result):  # noqa: C901 - one flat catalogue of substitutions
    value, tokens = case["input"], saved_tokens(case)
    produce, update = value["phases"]
    first, second = _phase(raw, PRODUCE, False), _phase(raw, UPDATE, False)
    records = raw["phases"]
    updater = _turn(raw, UPDATE, "updater")
    reader = _turn(raw, PRODUCE, "before")
    # --- the capture and its processes
    if name == "foreign-input":
        raw["input"]["nowMs"] += 1
    elif name == "foreign-kind":
        raw["kind"] = "host-restart-recall"
    elif name == "swapped-phases":
        raw["phases"].reverse()
    elif name == "same-process":
        records[1]["pid"] = second["pid"] = records[0]["pid"]
    elif name == "coordinator-is-a-host":
        raw["coordinatorPid"] = first["ppid"] = second["ppid"] = records[0]["pid"]
    elif name == "times-inverted":
        records[1]["startedAtNs"], records[1]["finishedAtNs"] = records[1]["finishedAtNs"], records[1]["startedAtNs"]
    elif name == "update-started-before-producer-exit":
        records[1]["startedAtNs"] = records[0]["startedAtNs"]
    elif name == "foreign-phase":
        _request(raw, UPDATE, False, lambda request: request["phase"]["update"].update(
            new=request["phase"]["update"]["new"] + " An undeclared fact."))
    elif name == "request-directory-changed":
        _request(raw, UPDATE, False, lambda request: request.update(directory=request["directory"] + "-other"))
    elif name == "request-identity-changed":
        _request(raw, UPDATE, False, lambda request: request["identity"]["updater"].update(sessionId="another-session"))
    elif name == "request-policy-changed":
        _request(raw, UPDATE, False, lambda request: request["policy"].update(sourceMtimeMs=1))
    elif name == "request-clock-changed":
        _request(raw, PRODUCE, False, lambda request: request.update(nowMs=request["nowMs"] + 1))
    elif name == "stdin-digest-corrupted":
        records[1]["requestSha256"] = "0" * 64
    elif name == "stdin-rewritten":
        records[1]["requestJson"] = json.dumps({**records[1]["request"], "inherited": produce["save"]["content"]})
        records[1]["requestSha256"] = hashlib.sha256(records[1]["requestJson"].encode()).hexdigest()
    elif name == "failed-child":
        records[1]["exit"]["code"] = 1
    elif name == "stdout-is-not-the-observation":
        records[0]["stdout"] = json.dumps({"result": {}, "raw": {}})
    elif name == "phase-pid-reassigned":
        second["pid"] += 1
    elif name == "phase-parent-reassigned":
        second["ppid"] += 1
    elif name == "phase-request-differs":
        second["request"]["nowMs"] += 1
    elif name in ("coordinator-environment-key-added", "child-environment-key-added"):
        keys = records[1]["environmentKeys"] if name.startswith("coordinator") else second["environmentKeys"]
        keys.append("OPENAI_API_KEY")
        keys.sort()
    elif name == "foreign-implementation-root":
        second["implementationRoot"] = "/another/worktree"
    elif name == "foreign-actor-module":
        records[0]["argv"][-1] = "equivalence.host_restart_phase_cli"
    elif name == "public-result-differs-from-host-result":
        records[1]["observation"]["result"]["reads"][0]["answer"] += " "
    elif name == "retained-result-differs":
        second["result"]["reads"][0]["answer"] += " "
    # --- sessions and first model inputs
    elif name == "read-session-removed":
        for key in ("turns", "opens", "settlement"):
            del second[key][-1]
    elif name == "session-identity-reassigned":
        _opened(raw, UPDATE, "current")["session"]["sessionId"] = value["identity"]["writer"]["sessionId"]
    elif name == "session-on-foreign-owner":
        _opened(raw, UPDATE, "current")["sessionManagedOwner"]["ownerId"] += 1
    elif name == "session-opened-on-other-bytes":
        _opened(raw, UPDATE, "current")["sourceBefore"] = {"path": "MEMORY.md", "kind": "missing"}
    elif name == "source-seeded-before-save":
        _opened(raw, PRODUCE, "writer")["sourceBefore"] = deepcopy(result["phases"][0]["source"])
    elif name == "stale-session-saw-no-failure":
        del _opened(raw, UPDATE, "stale")["managedStatusAfterOpen"]["lastSyncError"]
    elif name == "current-session-still-saw-failure":
        _opened(raw, UPDATE, "current")["managedStatusAfterOpen"]["lastSyncError"] = STALE_ERROR
    elif name == "session-continued-history":
        reader["outcome"]["appends"][0]["anchor"]["rawSeq"] = 7
    elif name == "read-turn-cancelled":
        reader["outcome"]["cancelled"] = True
    elif name == "update-turn-cancelled":
        updater["outcome"]["cancelled"] = True
    elif name == "update-transcript-uncommitted":
        updater["outcome"]["transcript_committed"] = False
    elif name == "inherited-history":
        reader["modelInput"]["messages"].insert(0, {"role": "assistant", "content": [{"type": "text", "text": "Earlier."}]})
    elif name == "prompt-substituted":
        reader["modelInput"]["messages"][0]["content"] = f"Is {tokens['old']} my drink?"
    elif name == "saved-fact-in-runtime-context":
        reader["modelInput"]["runtimeContext"] = f"The saved drink is {tokens['old']}."
    elif name == "saved-fact-in-tool-descriptor":
        reader["modelInput"]["tools"][0]["description"] = f"Returns {tokens['old']}."
    elif name == "other-agents-fact-in-system-prompt":
        for key in ("modelInput", "terminalInput"):
            reader[key]["systemPrompt"] = f"Another agent drinks {tokens['isolated']}.\n" + reader[key]["systemPrompt"]
    elif name == "foreign-project-context":
        for key in ("modelInput", "terminalInput"):
            reader[key]["systemPrompt"] = reader[key]["systemPrompt"].replace(
                produce["save"]["content"].rstrip("\n"), produce["isolatedSave"]["content"].rstrip("\n"))
    elif name == "terminal-prompt-differs":
        reader["terminalInput"]["systemPrompt"] += "\nA later instruction."
    # --- read dataflow
    elif name == "public-search-rewritten-consistently":
        result["phases"][0]["reads"][0]["search"]["results"][0]["score"] = 0.5
        result["phases"][0]["reads"][0]["search"]["debug"]["hits"] = 9
        _publish(raw, result, False)
    elif name == "search-arguments-changed":
        _sdk_arguments(reader, "memory_search", lambda arguments: arguments.update(maxResults=50))
    elif name == "search-query-carries-the-answer":
        _sdk_arguments(reader, "memory_search", lambda arguments: arguments.update(query=tokens["old"]))
    elif name == "get-range-not-from-hit":
        _sdk_arguments(reader, "memory_get", lambda arguments: arguments.update(lines=40))
    elif name == "tool-return-rewritten":
        _sdk_call(reader, "memory_search")["returned"]["results"][0]["score"] = 0.5
    elif name == "tool-request-rewritten":
        _sdk_call(reader, "memory_search")["assistant"]["content"][0]["arguments"]["query"] = "another query"
    elif name == "model-visible-search-differs":
        shown = next(message for message in reader["terminalInput"]["messages"] if message.get("toolName") == "memory_search")
        shown["details"]["results"][0]["score"] = 0.5
        shown["content"] = [{"type": "text", "text": json.dumps(shown["details"], ensure_ascii=False)}]
    elif name == "model-visible-get-missing":
        reader["terminalInput"]["messages"] = [message for message in reader["terminalInput"]["messages"]
                                               if message.get("toolName") != "memory_get"]
    elif name == "reply-not-the-terminal-message":
        _reply(reader["assistant"], "- " + update["update"]["old"])
    elif name == "get-dispatch-removed":
        del reader["toolCalls"][1]
    elif name == "recall-tool-events-removed":
        reader["toolCalls"] = []
    elif name == "extra-search-dispatch":
        reader["toolCalls"].append(deepcopy(reader["toolCalls"][0]))
    elif name == "memory-tool-error-hidden":
        _sdk_call(reader, "memory_search")["observed"]["message"]["isError"] = True
    elif name in ("get-not-backed-by-source", "hit-timestamp-rewritten"):
        session = "unrelated" if name == "get-not-backed-by-source" else "current"
        read, turn = _read(result, session), _turn(raw, UPDATE, session)
        if name == "get-not-backed-by-source":
            read["get"]["text"] += " (kept)"
            read["answer"] = read["get"]["text"]
            _sdk_payload(turn, "memory_get", read["get"])
            _reply(turn["assistant"], read["answer"])
        else:
            read["search"]["results"][0]["provenance"]["observedAt"] += 1
            _sdk_payload(turn, "memory_search", read["search"])
        _publish(raw, result, False)
    elif name == "stale-turn-failure-hidden":
        _turn(raw, UPDATE, "stale")["outcome"]["failures"] = []
    elif name == "reader-failure-invented":
        _turn(raw, UPDATE, "current")["outcome"]["failures"].append(
            {"phase": "publication", "error_type": "OperationalError", "message": STALE_ERROR, "committed": True})
    elif name == "reader-wrote-memory":
        reader["outcome"]["memory_writes_committed"] = True
    # --- save dispatch and source metadata
    elif name == "save-tool-events-removed":
        _turn(raw, PRODUCE, "writer")["toolCalls"] = []
    elif name == "save-entry-substituted":
        _sdk_arguments(_turn(raw, PRODUCE, "writer"), "add_memory_entry", lambda arguments: arguments.update(text="Another entry."))
    elif name == "save-not-committed":
        _turn(raw, PRODUCE, "isolatedWriter")["outcome"]["memory_writes_committed"] = False
    elif name == "save-failure-hidden":
        _sdk_call(_turn(raw, PRODUCE, "writer"), "add_memory_entry")["observed"]["message"]["isError"] = True
    elif name == "metadata-receipt-removed":
        del _turn(raw, PRODUCE, "writer")["sourceMetadata"]
    elif name == "metadata-changed-bytes":
        after = _turn(raw, PRODUCE, "writer")["sourceMetadata"][0]["after"]["source"]
        after.update(text=after["text"] + "- An undeclared entry.\n", hex=(after["text"] + "- An undeclared entry.\n").encode().hex())
    elif name == "metadata-receipt-duplicated":
        receipts = _turn(raw, PRODUCE, "writer")["sourceMetadata"]
        receipts.append(deepcopy(receipts[0]))
    elif name == "metadata-other-operation":
        _turn(raw, PRODUCE, "writer")["sourceMetadata"][0]["operation"] = "touch"
    elif name == "metadata-on-another-file":
        _turn(raw, PRODUCE, "writer")["sourceMetadata"][0]["path"] += ".other"
    elif name == "metadata-other-call":
        _turn(raw, PRODUCE, "writer")["sourceMetadata"][0]["arguments"]["ns"] = ["1", "1"]
    elif name == "metadata-call-failed":
        _turn(raw, PRODUCE, "writer")["sourceMetadata"][0]["returnedNone"] = False
    elif name == "metadata-on-linked-file":
        receipt = _turn(raw, PRODUCE, "writer")["sourceMetadata"][0]
        receipt["before"]["stat"]["nlink"] = receipt["after"]["stat"]["nlink"] = 2
    elif name == "metadata-instant-not-applied":
        _turn(raw, PRODUCE, "writer")["sourceMetadata"][0]["after"]["stat"]["mtimeNs"] = "1"
    elif name == "metadata-replaced-file":
        _turn(raw, PRODUCE, "writer")["sourceMetadata"][0]["after"]["stat"]["ino"] += 1
    elif name == "update-metadata-missing":
        del updater["sourceMetadata"]
    elif name == "refused-update-set-metadata":
        updater["sourceMetadata"] = deepcopy(_turn(raw, PRODUCE, "writer")["sourceMetadata"])
    # --- update dispatch
    elif name == "swapped-tool":
        updater["toolCalls"][0]["name"] = updater["toolCalls"][0]["assistant"]["content"][0]["name"] = "add_memory_entry"
        updater["toolCalls"][0]["observed"]["message"]["toolName"] = "add_memory_entry"
    elif name == "second-update-call":
        updater["toolCalls"].append(deepcopy(updater["toolCalls"][0]))
    elif name == "update-text-substituted":
        _sdk_arguments(updater, "replace_memory_entry", lambda arguments: arguments.update(new="My drink preference is now water."))
    elif name == "refusal-reported-as-success":
        updater["toolCalls"][0]["observed"]["message"]["isError"] = False
    elif name == "success-reported-as-refusal":
        updater["toolCalls"][0]["observed"]["message"]["isError"] = True
    elif name == "refusal-cause-rewritten":
        payload = {**updater["toolCalls"][0]["observed"]["payload"], "error": "Could not find the exact text in MEMORY.md"}
        _sdk_payload(updater, "replace_memory_entry", payload)
        updater["outcome"]["failures"][0]["message"] = payload["error"]
    elif name == "refusal-without-turn-failure":
        updater["outcome"]["failures"] = []
    elif name == "refusal-recorded-as-committed":
        updater["outcome"]["failures"][0]["committed"] = True
    elif name == "refusal-with-committed-write":
        updater["outcome"]["memory_writes_committed"] = True
    elif name == "committed-update-with-turn-failure":
        updater["outcome"]["failures"].append(
            {"phase": "tool", "error_type": "ToolExecutionFailure", "message": "A hidden failure.", "committed": False})
    elif name in ("after-write-error-dropped", "after-write-error-invented"):
        payload = deepcopy(updater["toolCalls"][0]["observed"]["payload"])
        if name == "after-write-error-dropped":
            del payload["afterWriteError"]
        else:
            payload["afterWriteError"] = STALE_ERROR
        _sdk_payload(updater, "replace_memory_entry", payload)
    elif name == "index-failure-reported-ready":
        updater["outcome"]["index_status"] = "ready"
    elif name == "tool-index-failure-hidden":
        updater["outcome"]["failures"] = []
    # --- publications and the store's own journal
    elif name == "publication-receipts-removed":
        second["publications"] = []
    elif name == "publication-not-forced":
        second["publications"][-1]["request"] = {"force": False}
    elif name == "publication-other-operation":
        first["publications"][0]["operation"] = "ManagedHostSession.synchronize"
    elif name == "publication-other-timestamp":
        next(row for row in second["publications"][-1]["publishedAfter"]["sources"] if row["path"] == "MEMORY.md")["mtime"] += 1
    elif name == "publication-revision-not-advanced":
        second["publications"][-1]["publishedAfter"]["revision"] = second["publications"][-1]["publishedBefore"]["revision"]
    elif name == "published-other-bytes":
        next(row for row in second["publications"][-1]["publishedAfter"]["sources"] if row["path"] == "MEMORY.md")["hash"] = "0" * 64
    elif name == "publication-return-invented":
        second["publications"][-1]["returned"] = 7
    elif name == "final-publication-status-still-failed":
        second["publications"][-1]["statusAfter"]["lastSyncError"] = STALE_ERROR
    elif name == "failed-publication-changed-index":
        second["publications"][0]["publishedAfter"]["revision"] += 1
    elif name == "failed-publication-not-in-status":
        del second["publications"][0]["statusAfter"]["lastSyncError"]
    elif name == "journal-forced-publication-missing":
        operations, whole = _journal(raw, "reindex")
        operations.remove(whole[0])
    elif name == "journal-forced-publication-succeeded":
        whole = _journal(raw, "reindex")[1][0]
        whole["state"] = "completed"
        del whole["error"]
    elif name == "journal-forced-publication-after-stale-read":
        operations, whole = _journal(raw, "reindex")
        _move(operations, whole[0], whole[1])
    elif name == "journal-tool-refresh-did-not-fail":
        scoped = _journal(raw, "reindex-sources")[1][0]
        scoped["state"] = "completed"
        del scoped["error"]
    elif name == "journal-read-missing":
        operations, searches = _journal(raw, "search")
        operations.remove(searches[0])
    elif name == "journal-read-other-query":
        _journal(raw, "search")[1][0]["query"] = "another query"
    elif name == "journal-read-before-publication":
        operations, searches = _journal(raw, "search")
        _move(operations, searches[0], _journal(raw, "reindex")[1][-1])
    elif name == "journal-undeclared-failure":
        scoped = _journal(raw, "reindex-sources")[1][-1]
        scoped.update(state="failed", error={"name": "OperationalError", "message": STALE_ERROR})
    elif name == "journal-hidden-repair":
        _main_close(raw)["before"]["repairs"].append({"id": 1, "reason": "search-bootstrap"})
    elif name == "journal-truncated":
        _main_close(raw)["before"]["operationJournalTruncated"] = True
    elif name == "failure-still-retained-at-close":
        _main_close(raw)["before"]["lastSyncError"] = STALE_ERROR
    elif name == "scoped-failure-still-retained-at-close":
        _main_close(raw)["before"]["memoryScopeSyncFailure"] = {"error": STALE_ERROR, "paths": None}
    # --- declared fault windows
    elif name == "missing-fault-window":
        second["mutations"] = []
    elif name == "undeclared-mutation":
        second["mutations"].append({"operation": "undeclared", "stage": "before-update-tool",
                                    "before": {"kind": "file", "nlink": 1}, "after": {"kind": "file", "nlink": 2}})
    elif name == "producer-host-mutation":
        first["mutations"].append(deepcopy(second["mutations"][0]))
    elif name == "fault-never-linked":
        second["mutations"][0]["after"]["nlink"] = 1
    elif name == "fault-never-removed":
        second["mutations"][1]["after"]["nlink"] = 2
    elif name == "link-on-another-file":
        for entry in second["mutations"]:
            for side in ("before", "after"):
                entry[side]["absolutePath"] += ".other"
    elif name == "linked-other-bytes":
        for entry in second["mutations"]:
            for side in ("before", "after"):
                entry[side]["sha256"] = "0" * 64
    elif name == "sidecar-not-symlink":
        second["mutations"][0]["after"]["kind"] = "missing"
    elif name == "sidecar-left-in-place":
        second["mutations"][1]["after"]["kind"] = "symlink"
    elif name == "sidecar-other-path":
        for entry in second["mutations"]:
            entry["sidecar"] += ".other"
    elif name == "sidecar-target-not-dangling-declared":
        second["mutations"][0]["after"]["target"] = second["mutations"][0]["sidecar"]
    # --- policy, owners, isolation and close
    elif name == "policy-resolution-changed":
        second["policyResolution"]["result"]["sources"].append("sessions")
    elif name == "owner-session-search-enabled":
        second["ownerAcquisitions"][0]["config"]["session_search"] = True
    elif name == "owner-acquisition-removed":
        del first["ownerAcquisitions"][1]
    elif name == "owners-share-one-index":
        first["ownerAcquisitions"][1]["paths"]["index"] = first["ownerAcquisitions"][0]["paths"]["index"]
    elif name == "owners-share-one-store":
        shared = first["ownerAcquisitions"][0]["storeId"]
        first["ownerAcquisitions"][1]["storeId"] = shared
        for entry in [item["sessionManagedOwner"] for item in first["opens"]] + [item["owner"] for item in first["closeReceipts"]]:
            if entry["agentId"] == "other":
                entry["storeId"] = shared
    elif name == "foreign-fact-in-index":
        owner = next(entry for entry in first["snapshots"][-1]["owners"] if entry["agentId"] == "other")
        owner["published"]["chunks"][0]["text"] += f"- {update['update']['old']}\n"
    elif name == "superseded-fact-still-indexed":
        second["snapshots"][-1]["owners"][0]["published"]["chunks"][0]["text"] += f"- {update['update']['old']}\n"
    elif name == "index-behind-source-at-snapshot":
        owner = second["snapshots"][0]["owners"][0]
        next(row for row in owner["published"]["sources"] if row["path"] == "MEMORY.md")["hash"] = "0" * 64
    elif name == "snapshot-other-source":
        first["snapshots"][0]["owners"][0]["source"]["text"] += "- An undeclared entry.\n"
    elif name == "snapshot-removed":
        del second["snapshots"][0]
    elif name == "active-turn-left":
        second["settlement"][0]["activeTurn"] = True
    elif name == "blocking-producer-left":
        second["settlement"][-1]["outstandingBlockingSources"] = 1
    elif name == "close-receipts-removed":
        second["closeReceipts"] = []
    elif name == "owner-not-closed":
        second["closeReceipts"][0]["after"]["closed"] = False
    elif name == "owner-closed-with-active-operation":
        second["closeReceipts"][0]["after"]["activeOperations"] = 1
    elif name == "close-covers-other-sessions":
        second["closeReceipts"][0]["sessions"].append("isolated")
    elif name == "close-returned-a-value":
        second["closeReceipts"][0]["returnedNone"] = False
    elif name == "owner-already-closed-before-close":
        second["closeReceipts"][0]["before"]["closed"] = True
    # --- single conditions of the guards above
    elif name == "relative-fixture-directory":
        _fixture(raw, False, "fixture")
    elif name == "fixture-directory-not-a-path":
        _fixture(raw, False, None)
    elif name == "fixture-directory-with-trailing-separator":
        _fixture(raw, False, raw["fixtureBase"] + "/")
    elif name == "observation-carries-an-extra-field":
        records[1]["observation"]["inherited"] = produce["save"]["content"]
    elif name == "foreign-phase-kind":
        second["kind"] = "host-restart-recall"
    elif name == "phase-label-reassigned":
        second["label"] = "produce"
    elif name == "tool-result-without-details":
        del _sdk_call(reader, "memory_search")["observed"]["message"]["details"]
    elif name == "later-message-in-first-input":
        reader["modelInput"]["messages"].append({"role": "assistant", "content": [{"type": "text", "text": "Earlier."}]})
    elif name == "prompt-from-another-role":
        reader["modelInput"]["messages"][0]["role"] = "system"
    elif name == "undeclared-input-carrier":
        reader["modelInput"]["attachments"] = [tokens["old"]]
    elif name == "project-context-embedded-twice":
        marker = f"## {_opened(raw, PRODUCE, 'before')['paths']['workspace']}/MEMORY.md\n"
        for key in ("modelInput", "terminalInput"):
            reader[key]["systemPrompt"] = marker + "An earlier revision.\n" + reader[key]["systemPrompt"]
    elif name == "model-saw-two-search-results":
        messages = reader["terminalInput"]["messages"]
        messages.append(deepcopy(next(message for message in messages if message.get("toolName") == "memory_search")))
    elif name in ("hit-from-another-file", "hit-from-the-sessions-corpus", "source-read-error-status"):
        session = "unrelated" if name == "source-read-error-status" else "current"
        read, turn = _read(result, session), _turn(raw, UPDATE, session)
        if name == "hit-from-another-file":
            read["search"]["results"][0]["path"] = read["get"]["path"] = "USER.md"
            _sdk_arguments(turn, "memory_get", lambda arguments: arguments.update(path="USER.md"))
        elif name == "hit-from-the-sessions-corpus":
            read["search"]["results"][0]["source"] = "sessions"
        else:
            read["get"]["status"] = "error"
        _sdk_payload(turn, "memory_get", read["get"])
        _sdk_payload(turn, "memory_search", read["search"])
        _publish(raw, result, False)
    elif name == "model-visible-get-differs":
        shown = next(message for message in reader["terminalInput"]["messages"] if message.get("toolName") == "memory_get")
        shown["details"]["text"] += " (kept)"
        shown["content"] = [{"type": "text", "text": json.dumps(shown["details"], ensure_ascii=False)}]
    elif name == "get-result-rewritten-after-dispatch":
        call = _sdk_call(reader, "memory_get")
        payload = {**call["observed"]["payload"], "text": call["observed"]["payload"]["text"] + " (kept)"}
        call["returned"], call["observed"]["payload"] = deepcopy(payload), deepcopy(payload)
        call["observed"]["message"]["details"] = deepcopy(payload)
        call["observed"]["message"]["content"] = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
    elif name == "source-read-dispatched-but-unreported":
        shown = next(message for message in reader["terminalInput"]["messages"] if message.get("toolName") == "memory_get")
        _turn(raw, UPDATE, "superseded")["terminalInput"]["messages"].append(deepcopy(shown))
    elif name == "tool-result-of-another-tool":
        _sdk_call(reader, "memory_search")["observed"]["message"]["toolName"] = "memory_get"
    elif name == "tool-result-of-another-call":
        _sdk_call(reader, "memory_search")["observed"]["message"]["toolCallId"] = "another-call"
    elif name == "session-on-other-agent":
        _opened(raw, UPDATE, "current")["agentId"] = "other"
    elif name == "session-on-other-paths":
        _opened(raw, UPDATE, "current")["paths"]["index"] += ".other"
    elif name == "session-owner-reuse-misreported":
        entry = _opened(raw, UPDATE, "current")
        entry["ownerReused"] = not entry["ownerReused"]
    elif name == "session-key-reassigned":
        _opened(raw, UPDATE, "current")["session"]["sessionKey"] = value["identity"]["writer"]["sessionKey"]
    elif name == "turn-kind-reassigned":
        reader["kind"] = "save"
    elif name == "first-message-not-appended":
        reader["outcome"]["appends"][0]["appended"] = False
    elif name == "session-continued-parent":
        reader["outcome"]["appends"][0]["effectiveParentId"] = "an-earlier-message"
    elif name == "transcript-of-another-session":
        reader["outcome"]["appends"][0]["anchor"]["sessionId"] = value["identity"]["writer"]["sessionId"]
    elif name == "transcript-of-another-agent":
        reader["outcome"]["appends"][0]["anchor"]["agentId"] = "other"
    elif name in ("owner-config-other-workspace", "owner-config-other-index", "owner-config-other-agent",
                  "owner-vector-search-enabled", "owner-other-result-limit", "owner-other-score-floor"):
        config = first["ownerAcquisitions"][0]["config"]
        if name == "owner-config-other-workspace":
            config["workspace_dir"] += "-other"
        elif name == "owner-config-other-index":
            config["store_path"] += ".other"
        elif name == "owner-config-other-agent":
            config["agent_id"] = "other"
        elif name == "owner-vector-search-enabled":
            config["flags"]["vector_search"] = True
        elif name == "owner-other-result-limit":
            config["search_max_results"] = 50
        else:
            config["search_min_score"] = 0.5
    elif name == "save-through-another-tool":
        call = _turn(raw, PRODUCE, "writer")["toolCalls"][0]
        call["name"] = call["assistant"]["content"][0]["name"] = call["observed"]["message"]["toolName"] = "append_daily_note"
    elif name == "save-with-turn-failure":
        _turn(raw, PRODUCE, "writer")["outcome"]["failures"].append(
            {"phase": "tool", "error_type": "ToolExecutionFailure", "message": "A hidden failure.", "committed": False})
    elif name == "save-reply-substituted":
        _reply(_turn(raw, PRODUCE, "writer")["assistant"], "Saved everything.")
    elif name in ("save-tool-error-status", "save-into-another-file"):
        turn = _turn(raw, PRODUCE, "isolatedWriter")
        change = {"status": "error"} if name == "save-tool-error-status" else {"path": "USER.md"}
        _sdk_payload(turn, "add_memory_entry", {**turn["toolCalls"][0]["observed"]["payload"], **change})
    elif name == "update-reply-substituted":
        _reply(updater["assistant"], update["update"]["failureAck"])
    elif name in ("refusal-with-ok-status", "committed-update-with-error-status", "update-into-another-file"):
        change = ({"status": "ok"} if name == "refusal-with-ok-status" else {"status": "error"}
                  if name == "committed-update-with-error-status" else {"path": "USER.md"})
        _sdk_payload(updater, "replace_memory_entry", {**updater["toolCalls"][0]["observed"]["payload"], **change})
    elif name == "published-source-row-missing":
        rows = second["publications"][-1]["publishedAfter"]["sources"]
        rows.remove(_memory_row(second["publications"][-1]["publishedAfter"]))
    elif name == "published-as-sessions-source":
        _memory_row(second["publications"][-1]["publishedAfter"])["source"] = "sessions"
    elif name == "failed-publication-index-already-current":
        current = hashlib.sha256(result["phases"][1]["source"]["text"].encode()).hexdigest()
        for side in ("publishedBefore", "publishedAfter"):
            _memory_row(second["publications"][0][side])["hash"] = current
    elif name == "publication-returned-a-float":
        second["publications"][-1]["returned"] = float(second["publications"][-1]["returned"])
    elif name == "final-publication-unowned-index":
        second["publications"][-1]["statusAfter"]["custom"]["indexIdentity"]["status"] = "missing"
    elif name == "journal-of-another-workspace":
        _main_close(raw)["before"]["workspace"] += "-other"
    elif name == "journal-of-another-index":
        _main_close(raw)["before"]["indexPath"] += ".other"
    elif name == "repair-journal-truncated":
        _main_close(raw)["before"]["repairJournalTruncated"] = True
    elif name == "journal-repair-counted":
        _main_close(raw)["before"]["repairCount"] = 1
    elif name == "journal-extra-forced-publication":
        operations, whole = _journal(raw, "reindex")
        operations.append(deepcopy(whole[-1]))
    elif name == "journal-publication-not-forced":
        _journal(raw, "reindex")[1][-1]["request"] = {"force": False}
    elif name == "journal-forced-publication-other-error":
        _journal(raw, "reindex")[1][0]["error"]["message"] = "database is locked"
    elif name == "journal-read-failed":
        _journal(raw, "search")[1][0].update(state="failed", error={"name": "OperationalError", "message": STALE_ERROR})
    elif name == "journal-extra-failure-after-final":
        _journal(raw, "reindex-sources")[1][-1].update(state="failed", error={"name": "OperationalError", "message": STALE_ERROR})
    elif name == "journal-tool-refresh-other-error":
        _journal(raw, "reindex-sources")[1][0]["error"]["message"] = "database is locked"
    elif name == "link-stages-relabelled":
        second["mutations"][1]["stage"] = "before-update-tool"
    elif name == "link-other-operation":
        second["mutations"][0]["operation"] = "undeclared"
    elif name == "link-on-non-file":
        second["mutations"][0]["after"]["kind"] = "directory"
    elif name == "sidecar-present-before-fault":
        second["mutations"][0]["before"]["kind"] = "file"
    elif name == "sidecar-gone-before-removal":
        second["mutations"][1]["before"]["kind"] = "missing"
    elif name == "sidecar-retargeted-before-removal":
        second["mutations"][1]["before"]["target"] += ".other"
    elif name == "sidecar-other-operation":
        second["mutations"][1]["operation"] = "undeclared"
    elif name == "isolated-owner-never-snapshotted":
        del second["snapshots"][-1]["owners"][1]
    elif name == "third-owner-snapshotted":
        first["snapshots"][0]["owners"].append({**deepcopy(first["snapshots"][0]["owners"][1]), "agentId": "third"})
    elif name == "snapshot-source-row-missing":
        published = first["snapshots"][0]["owners"][0]["published"]
        published["sources"].remove(_memory_row(published))
    elif name == "sessions-chunk-indexed":
        first["snapshots"][0]["owners"][0]["published"]["chunks"][0]["source"] = "sessions"
    elif name == "chunk-from-another-file":
        first["snapshots"][0]["owners"][0]["published"]["chunks"][0]["path"] = "USER.md"
    else:
        raise AssertionError(name)


SDK_CUSTODY_ATTACKS = [
    (ASCII, "foreign-input", LITERAL), (ASCII, "foreign-kind", LITERAL),
    (ASCII, "swapped-phases", PROCESSES), (ASCII, "same-process", PROCESSES), (ASCII, "coordinator-is-a-host", PROCESSES),
    (ASCII, "times-inverted", ORDER), (ASCII, "update-started-before-producer-exit", ORDER),
    (ASCII, "foreign-phase", CARRIER), (ASCII, "request-directory-changed", CARRIER),
    (ASCII, "request-identity-changed", CARRIER), (ASCII, "request-policy-changed", CARRIER),
    (ASCII, "request-clock-changed", CARRIER),
    (ASCII, "stdin-digest-corrupted", DIGEST), (ASCII, "stdin-rewritten", DIGEST), (ASCII, "failed-child", EXIT),
    (ASCII, "stdout-is-not-the-observation", STREAM),
    (ASCII, "phase-pid-reassigned", LAUNCH), (ASCII, "phase-parent-reassigned", LAUNCH),
    (ASCII, "phase-request-differs", LAUNCH),
    (ASCII, "coordinator-environment-key-added", SDK_ACTOR), (ASCII, "child-environment-key-added", SDK_ACTOR),
    (ASCII, "foreign-implementation-root", SDK_ACTOR), (ASCII, "foreign-actor-module", SDK_ACTOR),
    (ASCII, "foreign-phase-kind", SDK_ACTOR), (ASCII, "phase-label-reassigned", SDK_ACTOR),
    (ASCII, "relative-fixture-directory", FIXTURE), (ASCII, "fixture-directory-not-a-path", FIXTURE),
    (ASCII, "fixture-directory-with-trailing-separator", FIXTURE),
    (ASCII, "observation-carries-an-extra-field", STREAM),
    (ASCII, "public-result-differs-from-host-result", OWN_RESULTS), (ASCII, "retained-result-differs", SDK_RETAINED),
    (ASCII, "read-session-removed", SESSIONS), (ASCII, "session-identity-reassigned", SDK_SESSION),
    (ASCII, "session-on-foreign-owner", SDK_SESSION), (ASCII, "session-opened-on-other-bytes", SDK_OPENED),
    (ASCII, "source-seeded-before-save", SDK_OPENED), (PUBLICATION, "stale-session-saw-no-failure", SDK_OPENED),
    (PUBLICATION, "current-session-still-saw-failure", SDK_OPENED),
    (ASCII, "session-continued-history", SDK_TURN), (ASCII, "read-turn-cancelled", SDK_TURN),
    (ASCII, "update-turn-cancelled", SDK_TURN), (PUBLICATION, "update-turn-cancelled", SDK_TURN),
    (REFUSAL, "update-transcript-uncommitted", SDK_TURN),
    (ASCII, "inherited-history", FIRST_INPUT), (ASCII, "prompt-substituted", FIRST_INPUT),
    (ASCII, "saved-fact-in-runtime-context", LEAK), (UNICODE, "saved-fact-in-tool-descriptor", LEAK),
    (ASCII, "other-agents-fact-in-system-prompt", LEAK),
    (ASCII, "foreign-project-context", SDK_CONTEXT), (ASCII, "terminal-prompt-differs", "complete input"),
    (ASCII, "public-search-rewritten-consistently", SEARCH), (ASCII, "search-arguments-changed", QUERY),
    (ASCII, "search-query-carries-the-answer", QUERY), (ASCII, "get-range-not-from-hit", RANGE),
    (ASCII, "tool-return-rewritten", SDK_RETURN), (ASCII, "tool-request-rewritten", SDK_RETURN),
    (ASCII, "model-visible-search-differs", SEARCH), (ASCII, "model-visible-get-missing", READ),
    (ASCII, "reply-not-the-terminal-message", REPLY), (ASCII, "get-dispatch-removed", SEQUENCE),
    (ASCII, "recall-tool-events-removed", SEQUENCE), (ASCII, "extra-search-dispatch", SEQUENCE),
    (ASCII, "memory-tool-error-hidden", TOOL_FAILED),
    (ASCII, "get-not-backed-by-source", BACKED), (UNICODE, "get-not-backed-by-source", BACKED),
    (ASCII, "hit-timestamp-rewritten", TIMESTAMP),
    (PUBLICATION, "stale-turn-failure-hidden", SDK_READER), (ASCII, "reader-failure-invented", SDK_READER),
    (ASCII, "reader-wrote-memory", SDK_READER),
    (ASCII, "save-tool-events-removed", SDK_SAVE), (ASCII, "save-entry-substituted", SDK_SAVE),
    (ASCII, "save-not-committed", SDK_SAVE), (ASCII, "save-failure-hidden", SDK_SAVE),
    (ASCII, "metadata-receipt-removed", SDK_NO_METADATA), (ASCII, "metadata-receipt-duplicated", SDK_NO_METADATA),
    (ASCII, "metadata-changed-bytes", METADATA), (ASCII, "metadata-replaced-file", METADATA),
    (ASCII, "metadata-other-operation", METADATA), (ASCII, "metadata-on-another-file", METADATA),
    (ASCII, "metadata-other-call", METADATA), (ASCII, "metadata-call-failed", METADATA),
    (ASCII, "metadata-on-linked-file", METADATA), (ASCII, "metadata-instant-not-applied", METADATA),
    (ASCII, "update-metadata-missing", SDK_NO_METADATA), (REFUSAL, "refused-update-set-metadata", SDK_REFUSED),
    (ASCII, "swapped-tool", SDK_UPDATE), (ASCII, "second-update-call", SDK_UPDATE),
    (ASCII, "update-text-substituted", SDK_UPDATE),
    (REFUSAL, "refusal-reported-as-success", SDK_UPDATE), (ASCII, "success-reported-as-refusal", SDK_UPDATE),
    (REFUSAL, "refusal-with-committed-write", SDK_UPDATE),
    (REFUSAL, "refusal-cause-rewritten", SDK_REFUSED), (REFUSAL, "refusal-without-turn-failure", SDK_REFUSED),
    (REFUSAL, "refusal-recorded-as-committed", SDK_REFUSED),
    (ASCII, "committed-update-with-turn-failure", SDK_REFRESH),
    (PUBLICATION, "after-write-error-dropped", SDK_REFRESH), (ASCII, "after-write-error-invented", SDK_REFRESH),
    (PUBLICATION, "index-failure-reported-ready", SDK_REFRESH), (PUBLICATION, "tool-index-failure-hidden", SDK_REFRESH),
    (ASCII, "publication-receipts-removed", SDK_PUBLIC), (ASCII, "publication-not-forced", SDK_FORCED),
    (ASCII, "publication-other-operation", SDK_FORCED), (ASCII, "publication-other-timestamp", SDK_FORCED),
    (ASCII, "publication-revision-not-advanced", SDK_PUBLISHED), (ASCII, "published-other-bytes", SDK_PUBLISHED),
    (ASCII, "publication-return-invented", SDK_PUBLISHED),
    (PUBLICATION, "final-publication-status-still-failed", SDK_PUBLISHED),
    (PUBLICATION, "failed-publication-changed-index", SDK_FAILED),
    (PUBLICATION, "failed-publication-not-in-status", SDK_FAILED),
    (PUBLICATION, "journal-forced-publication-missing", SDK_JOURNAL_PUBLICATIONS),
    (PUBLICATION, "journal-forced-publication-succeeded", SDK_JOURNAL_PUBLICATIONS),
    (PUBLICATION, "journal-forced-publication-after-stale-read", SDK_ATTRIBUTION),
    (PUBLICATION, "journal-tool-refresh-did-not-fail", SDK_ATTRIBUTION),
    (ASCII, "journal-read-missing", SDK_JOURNAL_READS), (ASCII, "journal-read-other-query", SDK_JOURNAL_READS),
    (ASCII, "journal-read-before-publication", SDK_JOURNAL_ORDER), (ASCII, "journal-undeclared-failure", SDK_JOURNAL_ORDER),
    (ASCII, "journal-hidden-repair", SDK_STORE), (ASCII, "journal-truncated", SDK_STORE),
    (PUBLICATION, "failure-still-retained-at-close", SDK_STORE),
    (PUBLICATION, "scoped-failure-still-retained-at-close", SDK_STORE),
    (REFUSAL, "missing-fault-window", LINK_WINDOW), (PUBLICATION, "missing-fault-window", SIDECAR_WINDOW),
    (ASCII, "undeclared-mutation", MUTATION), (REFUSAL, "producer-host-mutation", MUTATION),
    (REFUSAL, "fault-never-linked", LINK_WINDOW), (REFUSAL, "fault-never-removed", LINK_WINDOW),
    (REFUSAL, "link-on-another-file", LINK_WINDOW), (REFUSAL, "linked-other-bytes", LINK_WINDOW),
    (PUBLICATION, "sidecar-not-symlink", SIDECAR_WINDOW), (PUBLICATION, "sidecar-left-in-place", SIDECAR_WINDOW),
    (PUBLICATION, "sidecar-other-path", SIDECAR_WINDOW),
    (PUBLICATION, "sidecar-target-not-dangling-declared", SIDECAR_WINDOW),
    (ASCII, "policy-resolution-changed", SDK_POLICY), (ASCII, "owner-session-search-enabled", SDK_OWNER),
    (ASCII, "owner-acquisition-removed", SDK_OWNERS), (ASCII, "owners-share-one-index", SDK_OWNER),
    (ASCII, "owners-share-one-store", SDK_SHARED),
    (ASCII, "foreign-fact-in-index", CORPUS), (ASCII, "superseded-fact-still-indexed", CORPUS),
    (ASCII, "index-behind-source-at-snapshot", SDK_SNAPSHOT), (ASCII, "snapshot-other-source", SDK_SNAPSHOT),
    (ASCII, "snapshot-removed", SDK_SNAPSHOTS),
    (ASCII, "active-turn-left", SDK_SETTLED), (ASCII, "blocking-producer-left", SDK_SETTLED),
    (ASCII, "close-receipts-removed", SDK_CLOSERS), (ASCII, "owner-not-closed", SDK_CLOSED),
    (ASCII, "owner-closed-with-active-operation", SDK_CLOSED), (ASCII, "close-covers-other-sessions", SDK_CLOSED),
    (ASCII, "close-returned-a-value", SDK_CLOSED), (ASCII, "owner-already-closed-before-close", SDK_CLOSED),
    (ASCII, "tool-result-without-details", DETAILS), (ASCII, "later-message-in-first-input", FIRST_INPUT),
    (ASCII, "prompt-from-another-role", FIRST_INPUT), (ASCII, "undeclared-input-carrier", "complete input"),
    (ASCII, "project-context-embedded-twice", SDK_CONTEXT), (ASCII, "model-saw-two-search-results", SEARCH),
    (ASCII, "hit-from-another-file", TIMESTAMP), (ASCII, "hit-from-the-sessions-corpus", TIMESTAMP),
    (ASCII, "source-read-error-status", READ_FAILED), (ASCII, "model-visible-get-differs", READ),
    (ASCII, "get-result-rewritten-after-dispatch", READ), (ASCII, "source-read-dispatched-but-unreported", UNREPORTED),
    (ASCII, "tool-result-of-another-tool", SDK_RETURN), (ASCII, "tool-result-of-another-call", SDK_RETURN),
    (ASCII, "session-on-other-agent", SDK_SESSION), (ASCII, "session-on-other-paths", SDK_SESSION),
    (ASCII, "session-owner-reuse-misreported", SDK_SESSION), (ASCII, "session-key-reassigned", SDK_SESSION),
    (ASCII, "turn-kind-reassigned", SDK_TURN), (ASCII, "first-message-not-appended", SDK_TURN),
    (ASCII, "session-continued-parent", SDK_TURN), (ASCII, "transcript-of-another-session", SDK_TURN),
    (ASCII, "transcript-of-another-agent", SDK_TURN),
    (ASCII, "owner-config-other-workspace", SDK_OWNER), (ASCII, "owner-config-other-index", SDK_OWNER),
    (ASCII, "owner-config-other-agent", SDK_OWNER), (ASCII, "owner-vector-search-enabled", SDK_OWNER),
    (ASCII, "owner-other-result-limit", SDK_OWNER), (ASCII, "owner-other-score-floor", SDK_OWNER),
    (ASCII, "save-through-another-tool", SDK_SAVE), (ASCII, "save-with-turn-failure", SDK_SAVE),
    (ASCII, "save-reply-substituted", SDK_SAVE), (ASCII, "save-tool-error-status", SDK_SAVE),
    (ASCII, "save-into-another-file", SDK_SAVE), (ASCII, "update-reply-substituted", SDK_UPDATE),
    (REFUSAL, "refusal-with-ok-status", SDK_REFUSED), (ASCII, "committed-update-with-error-status", SDK_REFRESH),
    (ASCII, "update-into-another-file", SDK_REFRESH),
    (ASCII, "published-source-row-missing", SDK_FORCED), (ASCII, "published-as-sessions-source", SDK_FORCED),
    (PUBLICATION, "failed-publication-index-already-current", SDK_FAILED),
    (ASCII, "publication-returned-a-float", SDK_PUBLISHED), (ASCII, "final-publication-unowned-index", SDK_PUBLISHED),
    (ASCII, "journal-of-another-workspace", SDK_STORE), (ASCII, "journal-of-another-index", SDK_STORE),
    (ASCII, "repair-journal-truncated", SDK_STORE), (ASCII, "journal-repair-counted", SDK_STORE),
    (ASCII, "journal-extra-forced-publication", SDK_JOURNAL_PUBLICATIONS),
    (ASCII, "journal-publication-not-forced", SDK_JOURNAL_PUBLICATIONS),
    (PUBLICATION, "journal-forced-publication-other-error", SDK_JOURNAL_PUBLICATIONS),
    (ASCII, "journal-read-failed", SDK_JOURNAL_READS),
    (PUBLICATION, "journal-extra-failure-after-final", SDK_ATTRIBUTION),
    (PUBLICATION, "journal-tool-refresh-other-error", SDK_ATTRIBUTION),
    (REFUSAL, "link-stages-relabelled", LINK_WINDOW), (REFUSAL, "link-other-operation", LINK_WINDOW),
    (REFUSAL, "link-on-non-file", LINK_WINDOW),
    (PUBLICATION, "sidecar-present-before-fault", SIDECAR_WINDOW), (PUBLICATION, "sidecar-gone-before-removal", SIDECAR_WINDOW),
    (PUBLICATION, "sidecar-retargeted-before-removal", SIDECAR_WINDOW), (PUBLICATION, "sidecar-other-operation", SIDECAR_WINDOW),
    (ASCII, "isolated-owner-never-snapshotted", SDK_SNAPSHOTS), (ASCII, "third-owner-snapshotted", SDK_SNAPSHOT),
    (ASCII, "snapshot-source-row-missing", SDK_SNAPSHOT), (ASCII, "sessions-chunk-indexed", SDK_SNAPSHOT),
    (ASCII, "chunk-from-another-file", SDK_SNAPSHOT),
]
UNSEALED = {"stdout-is-not-the-observation"}


@pytest.mark.parametrize(("index", "attack", "reason"), SDK_CUSTODY_ATTACKS)
def test_sdk_guard_refuses_each_custody_substitution_for_its_own_reason(captures, index, attack, reason):
    case, original, public = captures[index]
    raw, result = deepcopy(original), deepcopy(public)
    _sdk_attack(attack, case, raw, result)
    if attack not in UNSEALED:
        _seal(raw, False)
    assert validate_result(case, result) is True
    with pytest.raises(ValueError, match=reason):
        validate_capture(case, raw, result, native=False)


def test_sealing_a_real_capture_changes_nothing(captures):
    case, original, public = captures[PUBLICATION]
    raw = deepcopy(original)
    _seal(raw, False)
    _publish(raw, deepcopy(public), False)
    assert validate_capture(case, raw, public, native=False) is True


def test_only_the_interpreters_own_locale_key_may_join_the_declared_child_environment(captures):
    case, original, public = captures[ASCII]
    raw = deepcopy(original)
    keys = _phase(raw, UPDATE, False)["environmentKeys"]
    keys.append("LC_CTYPE")
    keys.sort()
    _seal(raw, False)
    assert validate_capture(case, raw, public, native=False) is True


def test_a_capture_without_its_receipts_is_refused_rather_than_trusted(captures):
    case, original, public = captures[ASCII]
    for key in ("opens", "turns", "publications", "snapshots", "settlement", "closeReceipts", "ownerAcquisitions",
                "policyResolution", "mutations", "environmentKeys", "implementationRoot"):
        raw = deepcopy(original)
        del _phase(raw, UPDATE, False)[key]
        _seal(raw, False)
        with pytest.raises(ValueError, match=RECEIPT):
            validate_capture(case, raw, public, native=False)


def test_one_literals_capture_cannot_validate_another_literal(captures):
    _, raw, result = captures[ASCII]
    with pytest.raises(ValueError):
        validate_capture(captures[UNICODE][0], raw, result, native=False)
    with pytest.raises(ValueError):
        validate_capture(captures[REFUSAL][0], raw, result, native=False)


def test_restart_literal_cannot_borrow_the_update_validator(captures):
    _, raw, result = captures[ASCII]
    with pytest.raises(ValueError, match="independently frozen"):
        validate_capture(restart_cases()[0], raw, result, native=False)


def test_update_literal_cannot_borrow_the_restart_validator(captures):
    from equivalence.host_restart_session_evidence import validate_capture as restart_validator

    case, raw, result = captures[ASCII]
    with pytest.raises((KeyError, TypeError, ValueError)):
        restart_validator(case, raw, result, native=False)


def test_sdk_capture_cannot_pass_as_the_original_capture_or_the_reverse(captures):
    case, raw, result = captures[ASCII]
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=True)


def test_a_host_input_that_carries_a_fact_outside_its_own_phase_is_refused(captures, monkeypatch):
    """A property of the frozen literal. Labelled token substitutions show the guard would notice its loss."""
    case, raw, result = captures[ASCII]
    actual = saved_tokens(case)
    for swapped in ({**actual, "new": actual["old"]}, {**actual, "unrelated": actual["new"]},
                    {**actual, "isolated": actual["old"]}):
        monkeypatch.setattr(evidence, "saved_tokens", lambda _case, tokens=swapped: tokens)
        with pytest.raises(ValueError, match="process input carried a saved fact"):
            validate_capture(case, raw, result, native=False)


def test_generic_readers_cannot_be_declared_with_a_saved_fact_in_their_prompt_or_query():
    tokens = saved_tokens(build_cases()[ASCII])
    for field in ("prompt", "query"):
        instruction = {"prompt": "What drink preference did I ask you to remember?", "query": "drink preference"}
        instruction[field] += " " + tokens["old"]
        item = {"session": "current", "kind": "recall", "instruction": instruction}
        messages = [{"role": "user", "content": instruction["prompt"]}]
        with pytest.raises(ValueError, match="generic reader was given a saved fact"):
            evidence._first_input(item, tokens, messages, {}, native=False)
        # Only the two declared superseded readers may name the old value.
        evidence._first_input({**item, "session": "superseded"}, tokens, messages, {}, native=False)


def test_saved_facts_must_keep_their_declared_distinguishable_form():
    case = deepcopy(build_cases()[ASCII])
    assert saved_tokens(case) == {"old": "aurorakumquat-739 tea", "new": "velvetquince-204 coffee",
                                  "unrelated": "marblefern-551", "isolated": "copperplum-880 juice"}
    case["input"]["phases"][0]["isolatedSave"]["entries"][0]["text"] = case["input"]["phases"][1]["update"]["old"]
    with pytest.raises(ValueError, match="cannot be told apart"):
        saved_tokens(case)
    case["input"]["phases"][1]["update"]["new"] = "A sentence in another form"
    with pytest.raises(ValueError, match="declared sentence form"):
        saved_tokens(case)


def test_sdk_runner_rejects_undeclared_inputs_before_any_host_process():
    case = build_cases()[ASCII]
    for mutate in (lambda value: value.update(kind="host-restart-recall"),
                   lambda value: value.update(source="memory/2026-11-09.md"),
                   lambda value: value["phases"].reverse(),
                   lambda value: value["policy"].update(indexLifecycle="managed"),
                   lambda value: value["phases"][1].update(fault={"operation": "undeclared-fault"}),
                   lambda value: value["phases"][0].pop("supersededRecall"),
                   lambda value: value["phases"][1].update(extra=True)):
        changed = deepcopy(case["input"])
        mutate(changed)
        with pytest.raises(ValueError):
            run_host_update_isolation(changed)


# --- retained original captures ---------------------------------------------------------------

NATIVE_ACTOR = "not the protected phase actor of this coordinator"
NATIVE_CONFIG = "did not share the coordinator's two-workspace configuration"
NATIVE_CLOCK = "differs from the declared Date-only control"
NATIVE_RUNTIME = "borrowed another runtime location"
NATIVE_OWNERS = "Both original owners must resolve their source policy"
NATIVE_POLICY = "original resolver used another source policy or database"
NATIVE_SYNC = "no longer resolves its automatic synchronization as enabled"
NATIVE_SCOPE = "another identity, agent or store than declared"
NATIVE_FRESH = "declared fresh session inherited earlier history"
NATIVE_COMMITS = "did not commit exactly this session's own loop messages"
NATIVE_CALLS = "not this loop's complete ordered calls"
NATIVE_EXECUTION = "no unique real model request or its execution never started"
NATIVE_EXPLAINED = "model calls that its tool results do not explain"
NATIVE_READER = "not given exactly the two original memory tools"
NATIVE_PRODUCER = "not one dispatch of its original coding tool"
NATIVE_SHOWN = "model-visible producer result differs from the dispatched one"
NATIVE_CREATED = "did not create the declared source from an absent file"
NATIVE_EDIT = "edit dispatch differs from the declared update or its outcome"
NATIVE_REFUSED = "not the declared hard-link refusal of this source"
NATIVE_CHANGED = "reported no committed change"
NATIVE_OUTCOMES = "runtime's own tool outcomes differ from the recorded producer results"
NATIVE_NO_METADATA = "not set exactly once after each committed producer write"
NATIVE_PUBLIC = "public publication outcomes differ from the original publication records"
NATIVE_FORCED = "not the declared forced rebuild of that agent's own index"
NATIVE_FAILED = "not raised and retained by the original runtime"
NATIVE_PUBLISHED = "left its index dirty, failed or unowned"
NATIVE_SNAPSHOTS = "retained other snapshots than its declared ones"
NATIVE_SOURCE = "snapshot shows other source bytes than the declared current ones"
NATIVE_INDEXED = "indexed another workspace, database or source"
NATIVE_CLOSED = "resources did not close completely"
NATIVE_NOTIFIED = "notifications do not match the sessions' own commits"
NATIVE_MAINTENANCE = "maintenance beyond acquiring its two managers"
NATIVE_COORDINATOR = "coordinator result differs from the returned result"


def _native_attack(name, case, raw, result):  # noqa: C901 - one flat catalogue of substitutions
    value, tokens = case["input"], saved_tokens(case)
    produce, update = value["phases"]
    first, second = _phase(raw, PRODUCE, True), _phase(raw, UPDATE, True)
    records = raw["children"]
    writer, reader, updater = _loop(raw, PRODUCE, "writer"), _loop(raw, PRODUCE, "before"), _loop(raw, UPDATE, "updater")
    # --- the capture and its processes
    if name == "foreign-input":
        raw["input"]["nowMs"] += 1
    elif name == "swapped-phases":
        raw["children"].reverse()
    elif name == "same-process":
        records[1]["pid"] = second["pid"] = records[0]["pid"]
    elif name == "times-inverted":
        records[0]["startedAtNs"], records[0]["finishedAtNs"] = records[0]["finishedAtNs"], records[0]["startedAtNs"]
    elif name == "update-started-before-producer-exit":
        records[1]["startedAtNs"] = records[0]["startedAtNs"]
    elif name == "request-directory-changed":
        _request(raw, UPDATE, True, lambda request: request.update(directory=request["directory"] + "-other"))
    elif name == "request-identity-changed":
        _request(raw, UPDATE, True, lambda request: request["identity"]["updater"].update(sessionId="another-session"))
    elif name == "request-policy-changed":
        _request(raw, PRODUCE, True, lambda request: request["policy"].update(sourceMtimeMs=1))
    elif name == "request-carries-the-other-phase":
        _request(raw, UPDATE, True, lambda request: request.update(phases=deepcopy(value["phases"])))
    elif name == "runtime-root-borrowed":
        _request(raw, UPDATE, True, lambda request: request.update(runtimeRoot=request["runtimeRoot"] + "-other"))
    elif name == "stdin-digest-corrupted":
        records[0]["stdinSha256"] = "0" * 64
    elif name == "exit-by-signal":
        records[1]["exit"] = {"code": None, "signal": "SIGKILL"}
    elif name == "stdout-is-not-the-observation":
        records[1]["stdout"] = json.dumps({"result": {}, "raw": {}})
    elif name == "phase-pid-reassigned":
        first["pid"] += 1
    elif name == "phase-request-differs":
        first["request"]["nowMs"] += 1
    elif name == "host-parent-reassigned":
        records[1]["ppid"] += 1
    elif name == "foreign-actor":
        records[1]["argv"] = [records[1]["argv"][0].replace("host-update-isolation", "host-restart")]
    elif name == "phase-stdin-differs":
        first["stdin"] += " "
    elif name == "host-config-differs":
        second["config"]["memory"]["search"]["sources"].append("sessions")
    elif name == "workspaces-shared":
        entries = raw["config"]["agents"]["entries"]
        entries["other"]["workspace"] = entries["main"]["workspace"]
        for phase in (first, second):
            phase["config"] = deepcopy(raw["config"])
    elif name == "clock-not-controlled":
        second["clock"]["dateConstructorReplaced"] = False
    elif name == "timers-replaced":
        second["clock"]["setTimeoutUnchanged"] = False
    elif name == "public-result-differs-from-host-result":
        records[1]["output"]["result"]["reads"][0]["answer"] += " "
    elif name == "coordinator-result-differs":
        raw["result"]["phases"][0]["reads"][0]["answer"] += " "
    # --- resolved policy
    elif name == "one-owner-resolved":
        del second["resolvedMemorySearch"][1]
    elif name == "sessions-source-resolved":
        first["resolvedMemorySearch"][0]["config"]["sources"].append("sessions")
    elif name == "session-memory-resolved":
        first["resolvedMemorySearch"][1]["config"]["experimental"]["sessionMemory"] = True
    elif name == "owners-share-one-database":
        second["resolvedMemorySearch"][1]["config"]["store"]["databasePath"] = (
            second["resolvedMemorySearch"][0]["config"]["store"]["databasePath"])
    elif name in ("search-sync-resolved-disabled", "watch-sync-resolved-disabled"):
        key = "onSearch" if name.startswith("search") else "watch"
        first["resolvedMemorySearch"][0]["config"]["sync"][key] = False
    # --- sessions and first model inputs
    elif name == "read-session-removed":
        for key in ("sessions", "loops", "toolFactoryCalls"):
            del second[key][-1]
    elif name == "session-identity-reassigned":
        for entry in (_session(raw, UPDATE, "current"), _loop(raw, UPDATE, "current")):
            entry["scope"]["sessionId"] = value["identity"]["writer"]["sessionId"]
    elif name == "session-on-other-agent":
        for entry in (_session(raw, UPDATE, "isolated"), _loop(raw, UPDATE, "isolated")):
            entry["scope"]["agentId"] = "main"
    elif name == "inherited-messages":
        reader["initialMessages"].append({"role": "assistant", "content": [{"type": "text", "text": "Earlier."}]})
    elif name == "persisted-history":
        _session(raw, PRODUCE, "before")["initialEvents"].append({"type": "message", "id": "earlier"})
    elif name == "session-already-stored":
        entry = _session(raw, UPDATE, "current")
        entry["loadedStore"][entry["scope"]["sessionKey"]] = {"sessionId": entry["scope"]["sessionId"]}
    elif name == "transcript-not-appended":
        _session(raw, PRODUCE, "before")["persistence"][0]["result"]["result"]["appended"] = False
    elif name == "transcript-continued-history":
        _session(raw, PRODUCE, "before")["persistence"][0]["result"]["result"]["anchor"]["rawSeq"] = 7
    elif name == "transcript-bypassed-strict-owner":
        _session(raw, PRODUCE, "before")["persistence"][0]["method"] = "appendSessionTranscriptMessage"
    elif name == "transcript-commits-removed":
        _session(raw, PRODUCE, "before")["persistence"] = []
    elif name == "model-calls-reordered":
        reader["modelCalls"][0]["ordinal"], reader["modelCalls"][1]["ordinal"] = 1, 0
    elif name == "inherited-history":
        reader["modelCalls"][0]["context"]["messages"].insert(
            0, {"role": "assistant", "content": [{"type": "text", "text": "Earlier."}]})
    elif name == "prompt-substituted":
        reader["modelCalls"][0]["context"]["messages"][0]["content"][0]["text"] = f"Is {tokens['old']} my drink?"
    elif name == "saved-fact-in-system-prompt":
        reader["modelCalls"][0]["context"]["systemPrompt"] = f"The saved drink is {tokens['old']}."
    elif name == "saved-fact-in-model-options":
        reader["modelCalls"][0]["options"]["hint"] = tokens["old"]
    elif name == "other-agents-fact-in-tool-descriptor":
        reader["modelCalls"][0]["context"]["tools"][0]["description"] = f"Returns {tokens['isolated']}."
    # --- read dataflow
    elif name == "public-search-rewritten-consistently":
        result["phases"][0]["reads"][0]["search"]["results"][0]["score"] = 0.5
        result["phases"][0]["reads"][0]["search"]["debug"]["hits"] = 9
        _publish(raw, result, True)
    elif name == "search-arguments-changed":
        _request_block(reader, "memory_search")["arguments"]["maxResults"] = 50
    elif name == "search-query-carries-the-answer":
        _request_block(reader, "memory_search")["arguments"]["query"] = tokens["old"]
    elif name == "get-range-not-from-hit":
        _request_block(reader, "memory_get")["arguments"]["lines"] = 40
    elif name == "tool-result-rewritten-after-dispatch":
        event = _event(reader, "memory_search")
        event["result"]["details"]["results"][0]["score"] = 0.5
        event["result"]["content"] = [{"type": "text", "text": json.dumps(event["result"]["details"])}]
    elif name == "tool-text-differs-from-details":
        _event(reader, "memory_search")["result"]["details"]["results"][0]["score"] = 0.5
    elif name == "model-visible-search-differs":
        for shown in _native_shown(reader, "memory_search"):
            shown["details"]["results"][0]["score"] = 0.5
            shown["content"] = [{"type": "text", "text": json.dumps(shown["details"])}]
    elif name == "model-visible-get-missing":
        terminal = reader["modelCalls"][-1]["context"]
        terminal["messages"] = [message for message in terminal["messages"] if message.get("toolName") != "memory_get"]
    elif name == "reply-not-the-terminal-message":
        _reply(reader["messages"][-1], "- " + update["update"]["old"])
    elif name == "recall-tool-events-removed":
        reader["toolEvents"] = []
    elif name == "recall-model-calls-removed":
        reader["modelCalls"] = []
    elif name == "get-dispatch-removed":
        reader["toolEvents"] = reader["toolEvents"][:1]
        del reader["modelCalls"][1]
        for ordinal, call in enumerate(reader["modelCalls"]):
            call["ordinal"] = ordinal
    elif name == "tool-result-without-model-request":
        _event(reader, "memory_get")["toolCallId"] = "another:get"
    elif name == "tool-execution-never-started":
        _event(reader, "memory_search")["executionStarted"] = False
    elif name == "memory-tool-error-hidden":
        _event(reader, "memory_get")["isError"] = True
    elif name == "reader-given-another-tool":
        reader["tools"][0]["name"] = "read"
    elif name == "reader-factory-receipt-missing":
        del first["toolFactoryCalls"][2]["originalToolObjectsPassedToAgentLoop"]
    elif name in ("get-not-backed-by-source", "hit-timestamp-rewritten"):
        session = "unrelated" if name == "get-not-backed-by-source" else "current"
        read, loop = _read(result, session), _loop(raw, UPDATE, session)
        if name == "get-not-backed-by-source":
            read["get"]["text"] += " (kept)"
            read["answer"] = read["get"]["text"]
            _native_payload(loop, "memory_get", read["get"])
            _reply(loop["messages"][-1], read["answer"])
        else:
            read["search"]["results"][0]["provenance"]["observedAt"] += 1
            _native_payload(loop, "memory_search", read["search"])
        _publish(raw, result, True)
    # --- save dispatch and source metadata
    elif name == "save-tool-events-removed":
        writer["toolEvents"] = []
    elif name == "write-never-started":
        _event(writer, "write")["executionStarted"] = False
    elif name == "write-content-substituted":
        _request_block(writer, "write")["arguments"]["content"] += "- An undeclared entry.\n"
    elif name == "write-failure-hidden":
        _native_reason(writer, "write", _event(writer, "write")["result"]["content"][0]["text"], failed=True)
    elif name == "source-existed-before-write":
        _event(_loop(raw, PRODUCE, "isolatedWriter"), "write")["result"]["details"]["created"] = False
        first["sourceMetadataSetup"][1]["trigger"] = deepcopy(_event(_loop(raw, PRODUCE, "isolatedWriter"), "write"))
    elif name == "write-reply-substituted":
        _reply(writer["messages"][-1], "Saved everything.")
    elif name == "write-result-hidden-from-model":
        for shown in _native_shown(writer, "write"):
            shown["content"] = [{"type": "text", "text": "Another result."}]
    elif name == "writer-given-another-tool":
        writer["tools"][0]["name"] = "read"
    elif name == "writer-factory-receipt-missing":
        del first["toolFactoryCalls"][0]["originalToolObjectPassedToAgentLoop"]
    elif name == "write-outcome-missing":
        first["toolOutcomes"] = first["toolOutcomes"][:1]
    elif name == "metadata-receipts-removed":
        first["sourceMetadataSetup"] = []
    elif name == "metadata-changed-bytes":
        first["sourceMetadataSetup"][0]["after"]["sha256"] = "0" * 64
    elif name == "metadata-other-trigger":
        first["sourceMetadataSetup"][0]["trigger"]["toolCallId"] = "another:write"
    elif name == "metadata-other-call":
        first["sourceMetadataSetup"][0]["calls"][0]["arguments"][1:] = [1, 1]
    elif name == "metadata-call-missing":
        first["sourceMetadataSetup"][0]["calls"] = []
    elif name == "metadata-instant-not-applied":
        first["sourceMetadataSetup"][0]["after"]["mtimeMs"] = 1000
    elif name == "metadata-other-operation":
        first["sourceMetadataSetup"][0]["operation"] = "touch"
    elif name == "metadata-other-agent":
        first["sourceMetadataSetup"][0]["agentId"] = "other"
    elif name == "metadata-not-a-file":
        first["sourceMetadataSetup"][0]["after"]["kind"] = "symlink"
    elif name == "metadata-on-linked-file":
        first["sourceMetadataSetup"][0]["after"]["nlink"] = 2
    elif name == "metadata-on-another-file":
        receipt = first["sourceMetadataSetup"][1]
        for side in ("before", "after"):
            receipt[side]["absolutePath"] = first["sourceMetadataSetup"][0]["after"]["absolutePath"]
    elif name == "refused-update-set-metadata":
        second["sourceMetadataSetup"] = deepcopy(first["sourceMetadataSetup"][:1])
    # --- update dispatch
    elif name == "second-update-call":
        updater["toolEvents"].append(deepcopy(updater["toolEvents"][0]))
    elif name == "update-text-substituted":
        _request_block(updater, "edit")["arguments"]["edits"][0]["newText"] = "My drink preference is now water."
    elif name == "edit-never-started":
        event = _event(updater, "edit")
        event["executionStarted"] = False
        _native_reason(updater, "edit", "Could not find the exact text in MEMORY.md", failed=True)
    elif name == "refusal-cause-rewritten":
        _native_reason(updater, "edit", "Could not find the exact text in MEMORY.md", failed=True)
    elif name == "refusal-names-another-file":
        text = _event(updater, "edit")["result"]["content"][0]["text"]
        _native_reason(updater, "edit", text.replace("/workspace/MEMORY.md", "/workspace/USER.md"), failed=True)
    elif name == "refusal-reported-as-success":
        _native_reason(updater, "edit", "Successfully replaced 1 block(s) in MEMORY.md.", failed=False)
    elif name == "success-reported-as-refusal":
        _native_reason(updater, "edit", _event(updater, "edit")["result"]["content"][0]["text"], failed=True)
    elif name == "committed-edit-without-change":
        _event(updater, "edit")["result"]["details"]["changed"] = False
        second["sourceMetadataSetup"][0]["trigger"] = deepcopy(_event(updater, "edit"))
    elif name == "update-reply-substituted":
        _reply(updater["messages"][-1], update["update"]["failureAck"])
    elif name == "edit-outcome-contradicts":
        outcome = second["toolOutcomes"][0]["observation"]
        outcome["resultHash"] = (outcome["resultHash"].removeprefix("error:") if outcome["resultHash"].startswith("error:")
                                 else "error:" + outcome["resultHash"])
    elif name == "edit-outcome-missing":
        second["toolOutcomes"] = []
    # --- publications
    elif name == "publication-receipts-removed":
        second["publications"] = []
    elif name == "publication-not-forced":
        second["publications"][-1]["request"]["force"] = False
    elif name == "publication-other-reason":
        first["publications"][0]["request"]["reason"] = "watch"
    elif name == "publication-other-database":
        first["publications"][1]["statusAfter"]["dbPath"] = first["publications"][0]["statusAfter"]["dbPath"]
    elif name == "publication-indexed-sessions":
        second["publications"][-1]["statusAfter"]["sources"].append("sessions")
    elif name == "final-publication-left-dirty":
        second["publications"][-1]["statusAfter"]["dirty"] = True
    elif name == "final-publication-unowned-index":
        second["publications"][-1]["statusAfter"]["custom"]["indexIdentity"]["status"] = "missing"
    elif name == "final-publication-returned-a-value":
        second["publications"][-1]["returnedUndefined"] = False
    elif name == "failed-publication-raised-by-the-actor":
        second["publications"][0]["error"]["stack"] = "Error: unable to open database file\n    at publish (file:///tmp/actor.mjs:1:1)"
    elif name == "failed-publication-not-in-status":
        del second["publications"][0]["statusAfter"]["lastSyncError"]
    elif name == "failed-publication-left-clean":
        second["publications"][0]["statusAfter"]["dirty"] = False
    elif name == "failure-forgotten-before-final-publication":
        del second["publications"][1]["statusBefore"]["lastSyncError"]
    elif name == "earlier-failure-not-declared":
        second["publications"][-1]["statusBefore"]["lastSyncError"] = STALE_ERROR
    # --- declared fault windows
    elif name == "missing-fault-window":
        second["mutations"] = []
    elif name == "undeclared-mutation":
        second["mutations"].append({"operation": "undeclared", "stage": "before-update-tool", "calls": []})
    elif name == "producer-host-mutation":
        first["mutations"].append(deepcopy(second["mutations"][0]))
    elif name == "fault-never-linked":
        second["mutations"][0]["after"]["nlink"] = 1
    elif name == "link-call-missing":
        second["mutations"][0]["calls"] = []
    elif name == "link-never-removed":
        second["mutations"][1]["calls"] = []
    elif name == "link-on-another-file":
        second["mutations"][0]["calls"][0]["arguments"][0] += ".other"
    elif name == "linked-other-bytes":
        for entry in second["mutations"]:
            for side in ("before", "after"):
                entry[side]["sha256"] = "0" * 64
    elif name == "sidecar-not-symlink":
        second["mutations"][0]["after"]["kind"] = "file"
    elif name == "sidecar-not-restored":
        second["mutations"][1]["after"]["sha256"] = "0" * 64
    elif name == "sidecar-left-in-place":
        second["mutations"][1]["after"]["kind"] = "symlink"
    elif name == "sidecar-other-path":
        for entry in second["mutations"]:
            entry["sidecar"] += ".other"
    elif name == "sidecar-never-linked":
        del second["mutations"][0]["calls"][1]
    # --- isolation, snapshots and close
    elif name == "foreign-fact-in-index":
        owner = next(entry for entry in first["snapshots"][-1]["memory"] if entry["agentId"] == "other")
        _chunks(owner)[0]["text"] += f"- {update['update']['old']}\n"
    elif name == "superseded-fact-still-indexed":
        _chunks(second["snapshots"][-1]["memory"][0])[0]["text"] += f"- {update['update']['old']}\n"
    elif name == "sessions-chunk-indexed":
        _chunks(first["snapshots"][0]["memory"][0])[0]["source"] = "sessions"
    elif name == "snapshot-other-source":
        first["snapshots"][0]["source"]["text"] += "- An undeclared entry.\n"
    elif name == "snapshot-isolated-source-changed":
        second["snapshots"][-1]["isolatedSource"] = deepcopy(second["snapshots"][-1]["source"])
    elif name == "owner-on-another-workspace":
        second["snapshots"][-1]["memory"][1]["status"]["workspaceDir"] = second["snapshots"][-1]["memory"][0]["status"]["workspaceDir"]
    elif name == "snapshot-removed":
        del second["snapshots"][0]
    elif name == "isolated-owner-never-acquired":
        del second["snapshots"][-1]["memory"][1]
    elif name == "close-receipts-removed":
        second["closeReceipts"] = []
    elif name == "close-incomplete":
        second["closeReceipts"][1]["completed"] = False
    elif name == "notifications-miscounted":
        del first["transcriptUpdates"][-1]
    elif name == "undeclared-maintenance":
        second["maintenance"].append({"operation": "sync", "agentId": "main"})
    # --- single conditions of the guards above
    elif name == "relative-fixture-directory":
        _fixture(raw, True, "fixture")
    elif name == "fixture-directory-not-a-path":
        _fixture(raw, True, None)
    elif name == "fixture-directory-with-trailing-separator":
        _fixture(raw, True, raw["fixtureBase"] + "/")
    elif name in ("runtime-root-not-a-path", "runtime-root-relative"):
        for ordinal in (PRODUCE, UPDATE):
            _request(raw, ordinal, True, lambda request: request.update(
                runtimeRoot=None if name == "runtime-root-not-a-path" else "release-runtime"))
    elif name == "observation-carries-an-extra-field":
        records[1]["output"]["inherited"] = produce["save"]["content"]
    elif name == "foreign-phase-kind":
        second["kind"] = "host-restart-phase"
    elif name == "phase-label-reassigned":
        second["label"] = "produce"
    elif name == "phase-other-executable":
        second["executable"] += "-other"
    elif name == "actor-given-arguments":
        records[1]["argv"].append("--inherit")
    elif name == "clock-other-instant":
        second["clock"]["nowMs"] += 1
    elif name == "session-record-removed":
        del second["sessions"][-1]
    elif name == "factory-record-removed":
        del second["toolFactoryCalls"][-1]
    elif name == "search-sources-resolved-sessions":
        first["resolvedMemorySearch"][0]["config"]["searchSources"].append("sessions")
    elif name == "provider-resolved":
        first["resolvedMemorySearch"][0]["config"]["provider"] = "openai"
    elif name == "loop-kind-reassigned":
        reader["kind"] = "save"
    elif name == "transcript-continued-parent":
        _session(raw, PRODUCE, "before")["persistence"][0]["result"]["result"]["effectiveParentId"] = "an-earlier-message"
    elif name == "transcript-append-conflicted":
        _session(raw, PRODUCE, "before")["persistence"][0]["result"]["kind"] = "conflict"
    elif name == "transcript-version-skipped":
        _session(raw, PRODUCE, "before")["persistence"][0]["versionAfter"] += 1
    elif name == "undeclared-context-carrier":
        reader["modelCalls"][0]["context"]["attachments"] = [tokens["old"]]
    elif name == "later-message-in-first-input":
        reader["modelCalls"][0]["context"]["messages"].append(
            {"role": "assistant", "content": [{"type": "text", "text": "Earlier."}]})
    elif name == "prompt-from-another-role":
        reader["modelCalls"][0]["context"]["messages"][0]["role"] = "system"
    elif name == "tool-result-without-details":
        del _event(reader, "memory_search")["result"]["details"]
    elif name == "tool-result-renamed":
        _event(reader, "memory_search")["toolName"] = "memory_get"
    elif name == "tool-event-not-an-end":
        _event(reader, "memory_search")["type"] = "tool_execution_update"
    elif name == "model-saw-two-search-results":
        messages = reader["modelCalls"][-1]["context"]["messages"]
        messages.append(deepcopy(next(message for message in messages if message.get("toolName") == "memory_search")))
    elif name in ("hit-from-another-file", "hit-from-the-sessions-corpus", "source-read-error-status"):
        session = "unrelated" if name == "source-read-error-status" else "current"
        read, loop = _read(result, session), _loop(raw, UPDATE, session)
        if name == "hit-from-another-file":
            read["search"]["results"][0]["path"] = read["get"]["path"] = "USER.md"
            _request_block(loop, "memory_get")["arguments"]["path"] = "USER.md"
        elif name == "hit-from-the-sessions-corpus":
            read["search"]["results"][0]["source"] = "sessions"
        else:
            read["get"]["status"] = "error"
        _native_payload(loop, "memory_get", read["get"])
        _native_payload(loop, "memory_search", read["search"])
        _publish(raw, result, True)
    elif name == "model-visible-get-differs":
        for shown in _native_shown(reader, "memory_get"):
            shown["details"]["text"] += " (kept)"
            shown["content"] = [{"type": "text", "text": json.dumps(shown["details"])}]
    elif name == "get-result-rewritten-after-dispatch":
        event = _event(reader, "memory_get")
        event["result"]["details"]["text"] += " (kept)"
        event["result"]["content"] = [{"type": "text", "text": json.dumps(event["result"]["details"])}]
    elif name == "source-read-dispatched-but-unreported":
        _loop(raw, UPDATE, "superseded")["modelCalls"][-1]["context"]["messages"].append(
            deepcopy(_native_shown(reader, "memory_get")[0]))
    elif name == "factory-supplied-no-such-tool":
        first["toolFactoryCalls"][0]["names"].remove("write")
    elif name == "producer-dispatched-twice":
        again = deepcopy(writer["modelCalls"][0])
        again["response"]["content"][0]["id"] = "writer:write-again"
        writer["modelCalls"].insert(1, again)
        for ordinal, call in enumerate(writer["modelCalls"]):
            call["ordinal"] = ordinal
        writer["toolEvents"].append({**deepcopy(writer["toolEvents"][0]), "toolCallId": "writer:write-again"})
    elif name == "producer-dispatched-another-tool":
        _event(writer, "write")["toolName"] = _request_block(writer, "write")["name"] = "edit"
    elif name == "producer-result-shown-twice":
        messages = writer["modelCalls"][-1]["context"]["messages"]
        messages.append(deepcopy(next(message for message in messages if message.get("toolName") == "write")))
    elif name == "refusal-flag-hidden-from-model":
        for shown in _native_shown(updater, "edit"):
            shown["isError"] = False
    elif name in ("refusal-shortened-for-another-file", "refusal-shortened-under-two-homes",
                  "refusal-half-shortened", "refusal-shortened-with-trailing-text"):
        workspace = raw["fixtureBase"] + "/workspace"
        home, other = workspace.rsplit("/", 3)[0], workspace.rsplit("/", 2)[0]
        root = "~" + workspace[len(home):]
        source = root + "/" + value["source"]
        if name == "refusal-shortened-for-another-file":
            source = root + "/USER.md"
        elif name == "refusal-shortened-under-two-homes":
            source = "~" + workspace[len(other):] + "/" + value["source"]
        elif name == "refusal-half-shortened":
            source = workspace + "/" + value["source"]
        else:
            source += " and another file"
        _native_reason(updater, "edit", f"Hardlinked path is not allowed under sandbox root ({root}): {source}",
                       failed=True)
    elif name == "refusal-other-cause-same-path":
        _native_reason(updater, "edit", f"Could not find the exact text in {value['source']} at "
                       f"{raw['fixtureBase']}/workspace/{value['source']}", failed=True)
    elif name == "publication-other-operation":
        second["publications"][-1]["operation"] = "reindex"
    elif name == "publication-other-workspace":
        second["publications"][-1]["statusAfter"]["workspaceDir"] += "-other"
    elif name == "final-publication-status-still-failed":
        second["publications"][-1]["statusAfter"]["lastSyncError"] = STALE_ERROR
    elif name == "link-stages-relabelled":
        second["mutations"][1]["stage"] = "before-update-tool"
    elif name == "link-other-operation":
        second["mutations"][0]["operation"] = "undeclared"
    elif name == "link-observed-another-file":
        for entry in second["mutations"]:
            for side in ("before", "after"):
                entry[side]["absolutePath"] += ".other"
    elif name == "link-on-non-file":
        second["mutations"][0]["after"]["kind"] = "directory"
    elif name == "sidecar-absent-before-fault":
        second["mutations"][0]["before"]["kind"] = "missing"
    elif name == "sidecar-linked-to-existing-file":
        second["mutations"][0]["after"]["target"] = raw["fixtureBase"] + "/retired-reindex-lock.sqlite"
    elif name == "sidecar-gone-before-restore":
        second["mutations"][1]["before"]["kind"] = "missing"
    elif name == "sidecar-retargeted-before-restore":
        second["mutations"][1]["before"]["target"] += ".other"
    elif name == "sidecar-never-restored":
        del second["mutations"][1]["calls"][1]
    elif name == "sidecar-other-operation":
        second["mutations"][1]["operation"] = "undeclared"
    elif name == "third-owner-snapshotted":
        first["snapshots"][0]["memory"].append({**deepcopy(first["snapshots"][0]["memory"][1]), "agentId": "third"})
    elif name == "owner-on-another-database":
        first["snapshots"][0]["memory"][1]["status"]["dbPath"] = first["snapshots"][0]["memory"][0]["status"]["dbPath"]
    elif name == "owner-indexed-sessions-source":
        first["snapshots"][0]["memory"][0]["status"]["sources"].append("sessions")
    elif name == "chunk-from-another-file":
        _chunks(first["snapshots"][0]["memory"][0])[0]["path"] = "USER.md"
    else:
        raise AssertionError(name)


NATIVE_CUSTODY_ATTACKS = [
    (ASCII, "foreign-input", LITERAL), (ASCII, "swapped-phases", PROCESSES), (ASCII, "same-process", PROCESSES),
    (ASCII, "times-inverted", ORDER), (ASCII, "update-started-before-producer-exit", ORDER),
    (ASCII, "request-directory-changed", CARRIER), (ASCII, "request-identity-changed", CARRIER),
    (ASCII, "request-policy-changed", CARRIER), (ASCII, "request-carries-the-other-phase", CARRIER),
    (ASCII, "runtime-root-borrowed", NATIVE_RUNTIME),
    (ASCII, "stdin-digest-corrupted", DIGEST), (ASCII, "exit-by-signal", EXIT),
    (ASCII, "stdout-is-not-the-observation", STREAM),
    (ASCII, "phase-pid-reassigned", LAUNCH), (ASCII, "phase-request-differs", LAUNCH),
    (ASCII, "host-parent-reassigned", NATIVE_ACTOR), (ASCII, "foreign-actor", NATIVE_ACTOR),
    (ASCII, "phase-stdin-differs", NATIVE_ACTOR),
    (ASCII, "host-config-differs", NATIVE_CONFIG), (ASCII, "workspaces-shared", NATIVE_CONFIG),
    (ASCII, "clock-not-controlled", NATIVE_CLOCK), (ASCII, "timers-replaced", NATIVE_CLOCK),
    (ASCII, "public-result-differs-from-host-result", OWN_RESULTS), (ASCII, "coordinator-result-differs", NATIVE_COORDINATOR),
    (ASCII, "one-owner-resolved", NATIVE_OWNERS), (ASCII, "sessions-source-resolved", NATIVE_POLICY),
    (ASCII, "session-memory-resolved", NATIVE_POLICY), (ASCII, "owners-share-one-database", NATIVE_POLICY),
    (ASCII, "search-sync-resolved-disabled", NATIVE_SYNC), (PUBLICATION, "watch-sync-resolved-disabled", NATIVE_SYNC),
    (ASCII, "read-session-removed", SESSIONS), (ASCII, "session-identity-reassigned", NATIVE_SCOPE),
    (ASCII, "session-on-other-agent", NATIVE_SCOPE),
    (ASCII, "inherited-messages", NATIVE_FRESH), (ASCII, "persisted-history", NATIVE_FRESH),
    (ASCII, "session-already-stored", NATIVE_FRESH),
    (ASCII, "transcript-not-appended", NATIVE_COMMITS), (ASCII, "transcript-continued-history", NATIVE_COMMITS),
    (ASCII, "transcript-bypassed-strict-owner", NATIVE_COMMITS), (ASCII, "transcript-commits-removed", NATIVE_COMMITS),
    (ASCII, "model-calls-reordered", NATIVE_CALLS),
    (ASCII, "inherited-history", FIRST_INPUT), (ASCII, "prompt-substituted", FIRST_INPUT),
    (ASCII, "saved-fact-in-system-prompt", LEAK), (UNICODE, "saved-fact-in-model-options", LEAK),
    (ASCII, "other-agents-fact-in-tool-descriptor", LEAK),
    (ASCII, "public-search-rewritten-consistently", SEARCH), (ASCII, "search-arguments-changed", QUERY),
    (ASCII, "search-query-carries-the-answer", QUERY), (ASCII, "get-range-not-from-hit", RANGE),
    (ASCII, "tool-result-rewritten-after-dispatch", SEARCH), (ASCII, "tool-text-differs-from-details", "complete tool details"),
    (ASCII, "model-visible-search-differs", SEARCH), (ASCII, "model-visible-get-missing", READ),
    (ASCII, "reply-not-the-terminal-message", REPLY),
    (ASCII, "recall-tool-events-removed", NATIVE_EXPLAINED), (ASCII, "recall-model-calls-removed", RECEIPT),
    (ASCII, "get-dispatch-removed", SEQUENCE), (ASCII, "tool-result-without-model-request", NATIVE_EXECUTION),
    (ASCII, "tool-execution-never-started", NATIVE_EXECUTION), (ASCII, "memory-tool-error-hidden", TOOL_FAILED),
    (ASCII, "reader-given-another-tool", NATIVE_READER), (ASCII, "reader-factory-receipt-missing", NATIVE_READER),
    (ASCII, "get-not-backed-by-source", BACKED), (UNICODE, "get-not-backed-by-source", BACKED),
    (ASCII, "hit-timestamp-rewritten", TIMESTAMP),
    (ASCII, "save-tool-events-removed", NATIVE_EXPLAINED), (ASCII, "write-never-started", NATIVE_EXECUTION),
    (ASCII, "write-content-substituted", NATIVE_CREATED), (ASCII, "write-failure-hidden", NATIVE_CREATED),
    (ASCII, "source-existed-before-write", NATIVE_CREATED), (ASCII, "write-reply-substituted", NATIVE_CREATED),
    (ASCII, "write-result-hidden-from-model", NATIVE_SHOWN),
    (ASCII, "writer-given-another-tool", NATIVE_PRODUCER), (ASCII, "writer-factory-receipt-missing", NATIVE_PRODUCER),
    (ASCII, "write-outcome-missing", NATIVE_OUTCOMES),
    (ASCII, "metadata-receipts-removed", NATIVE_NO_METADATA), (ASCII, "metadata-changed-bytes", METADATA),
    (ASCII, "metadata-other-trigger", METADATA), (ASCII, "metadata-other-call", METADATA),
    (ASCII, "metadata-call-missing", METADATA), (ASCII, "metadata-instant-not-applied", METADATA),
    (ASCII, "metadata-other-operation", METADATA), (ASCII, "metadata-other-agent", METADATA),
    (ASCII, "metadata-not-a-file", METADATA), (ASCII, "metadata-on-linked-file", METADATA),
    (ASCII, "metadata-on-another-file", METADATA), (REFUSAL, "refused-update-set-metadata", NATIVE_NO_METADATA),
    (ASCII, "second-update-call", NATIVE_EXPLAINED), (ASCII, "update-text-substituted", NATIVE_EDIT),
    (REFUSAL, "edit-never-started", NATIVE_EXECUTION), (REFUSAL, "refusal-cause-rewritten", NATIVE_REFUSED),
    (REFUSAL, "refusal-names-another-file", NATIVE_REFUSED), (REFUSAL, "refusal-reported-as-success", NATIVE_EDIT),
    (ASCII, "success-reported-as-refusal", NATIVE_EDIT), (ASCII, "committed-edit-without-change", NATIVE_CHANGED),
    (ASCII, "update-reply-substituted", NATIVE_EDIT),
    (ASCII, "edit-outcome-contradicts", NATIVE_OUTCOMES), (REFUSAL, "edit-outcome-contradicts", NATIVE_OUTCOMES),
    (ASCII, "edit-outcome-missing", NATIVE_OUTCOMES),
    (ASCII, "publication-receipts-removed", NATIVE_PUBLIC), (ASCII, "publication-not-forced", NATIVE_FORCED),
    (ASCII, "publication-other-reason", NATIVE_FORCED), (ASCII, "publication-other-database", NATIVE_FORCED),
    (ASCII, "publication-indexed-sessions", NATIVE_FORCED),
    (ASCII, "final-publication-left-dirty", NATIVE_PUBLISHED), (ASCII, "final-publication-unowned-index", NATIVE_PUBLISHED),
    (ASCII, "final-publication-returned-a-value", NATIVE_PUBLISHED),
    (PUBLICATION, "failed-publication-raised-by-the-actor", NATIVE_FAILED),
    (PUBLICATION, "failed-publication-not-in-status", NATIVE_FAILED),
    (PUBLICATION, "failed-publication-left-clean", NATIVE_FAILED),
    (PUBLICATION, "failure-forgotten-before-final-publication", NATIVE_FORCED),
    (ASCII, "earlier-failure-not-declared", NATIVE_FORCED),
    (REFUSAL, "missing-fault-window", LINK_WINDOW), (PUBLICATION, "missing-fault-window", SIDECAR_WINDOW),
    (ASCII, "undeclared-mutation", MUTATION), (REFUSAL, "producer-host-mutation", MUTATION),
    (REFUSAL, "fault-never-linked", LINK_WINDOW), (REFUSAL, "link-call-missing", LINK_WINDOW),
    (REFUSAL, "link-never-removed", LINK_WINDOW), (REFUSAL, "link-on-another-file", LINK_WINDOW),
    (REFUSAL, "linked-other-bytes", LINK_WINDOW),
    (PUBLICATION, "sidecar-not-symlink", SIDECAR_WINDOW), (PUBLICATION, "sidecar-not-restored", SIDECAR_WINDOW),
    (PUBLICATION, "sidecar-left-in-place", SIDECAR_WINDOW), (PUBLICATION, "sidecar-other-path", SIDECAR_WINDOW),
    (PUBLICATION, "sidecar-never-linked", SIDECAR_WINDOW),
    (ASCII, "foreign-fact-in-index", CORPUS), (ASCII, "superseded-fact-still-indexed", CORPUS),
    (ASCII, "sessions-chunk-indexed", NATIVE_INDEXED), (ASCII, "owner-on-another-workspace", NATIVE_INDEXED),
    (ASCII, "snapshot-other-source", NATIVE_SOURCE), (ASCII, "snapshot-isolated-source-changed", NATIVE_SOURCE),
    (ASCII, "snapshot-removed", NATIVE_SNAPSHOTS), (ASCII, "isolated-owner-never-acquired", NATIVE_SNAPSHOTS),
    (ASCII, "close-receipts-removed", NATIVE_CLOSED), (ASCII, "close-incomplete", NATIVE_CLOSED),
    (ASCII, "notifications-miscounted", NATIVE_NOTIFIED), (ASCII, "undeclared-maintenance", NATIVE_MAINTENANCE),
    (ASCII, "relative-fixture-directory", FIXTURE), (ASCII, "fixture-directory-not-a-path", FIXTURE),
    (ASCII, "fixture-directory-with-trailing-separator", FIXTURE),
    (ASCII, "runtime-root-not-a-path", NATIVE_RUNTIME), (ASCII, "runtime-root-relative", NATIVE_RUNTIME),
    (ASCII, "observation-carries-an-extra-field", STREAM),
    (ASCII, "foreign-phase-kind", NATIVE_ACTOR), (ASCII, "phase-label-reassigned", NATIVE_ACTOR),
    (ASCII, "phase-other-executable", NATIVE_ACTOR), (ASCII, "actor-given-arguments", NATIVE_ACTOR),
    (ASCII, "clock-other-instant", NATIVE_CLOCK),
    (ASCII, "session-record-removed", SESSIONS), (ASCII, "factory-record-removed", SESSIONS),
    (ASCII, "search-sources-resolved-sessions", NATIVE_POLICY), (ASCII, "provider-resolved", NATIVE_POLICY),
    (ASCII, "loop-kind-reassigned", NATIVE_SCOPE),
    (ASCII, "transcript-continued-parent", NATIVE_COMMITS), (ASCII, "transcript-append-conflicted", NATIVE_COMMITS),
    (ASCII, "transcript-version-skipped", NATIVE_COMMITS),
    (ASCII, "undeclared-context-carrier", NATIVE_CALLS),
    (ASCII, "later-message-in-first-input", FIRST_INPUT), (ASCII, "prompt-from-another-role", FIRST_INPUT),
    (ASCII, "tool-result-without-details", DETAILS), (ASCII, "tool-result-renamed", NATIVE_EXECUTION),
    (ASCII, "tool-event-not-an-end", NATIVE_EXECUTION), (ASCII, "model-saw-two-search-results", SEARCH),
    (ASCII, "hit-from-another-file", TIMESTAMP), (ASCII, "hit-from-the-sessions-corpus", TIMESTAMP),
    (ASCII, "source-read-error-status", READ_FAILED), (ASCII, "model-visible-get-differs", READ),
    (ASCII, "get-result-rewritten-after-dispatch", READ), (ASCII, "source-read-dispatched-but-unreported", UNREPORTED),
    (ASCII, "factory-supplied-no-such-tool", NATIVE_PRODUCER), (ASCII, "producer-dispatched-twice", NATIVE_PRODUCER),
    (ASCII, "producer-dispatched-another-tool", NATIVE_PRODUCER),
    (ASCII, "producer-result-shown-twice", NATIVE_SHOWN), (REFUSAL, "refusal-flag-hidden-from-model", NATIVE_SHOWN),
    (REFUSAL, "refusal-other-cause-same-path", NATIVE_REFUSED),
    (REFUSAL, "refusal-shortened-for-another-file", NATIVE_REFUSED),
    (REFUSAL, "refusal-shortened-under-two-homes", NATIVE_REFUSED),
    (REFUSAL, "refusal-half-shortened", NATIVE_REFUSED),
    (REFUSAL, "refusal-shortened-with-trailing-text", NATIVE_REFUSED),
    (ASCII, "publication-other-operation", NATIVE_FORCED), (ASCII, "publication-other-workspace", NATIVE_FORCED),
    (ASCII, "final-publication-status-still-failed", NATIVE_PUBLISHED),
    (REFUSAL, "link-stages-relabelled", LINK_WINDOW), (REFUSAL, "link-other-operation", LINK_WINDOW),
    (REFUSAL, "link-observed-another-file", LINK_WINDOW), (REFUSAL, "link-on-non-file", LINK_WINDOW),
    (PUBLICATION, "sidecar-absent-before-fault", SIDECAR_WINDOW),
    (PUBLICATION, "sidecar-linked-to-existing-file", SIDECAR_WINDOW),
    (PUBLICATION, "sidecar-gone-before-restore", SIDECAR_WINDOW),
    (PUBLICATION, "sidecar-retargeted-before-restore", SIDECAR_WINDOW),
    (PUBLICATION, "sidecar-never-restored", SIDECAR_WINDOW), (PUBLICATION, "sidecar-other-operation", SIDECAR_WINDOW),
    (ASCII, "third-owner-snapshotted", NATIVE_INDEXED), (ASCII, "owner-on-another-database", NATIVE_INDEXED),
    (ASCII, "owner-indexed-sessions-source", NATIVE_INDEXED), (ASCII, "chunk-from-another-file", NATIVE_INDEXED),
]


@pytest.mark.parametrize("index", range(4))
def test_retained_original_update_custody(native_captures, index):
    case, raw, result = native_captures[index]
    assert validate_capture(case, raw, result, native=True) is True
    assert validate_result(case, result) is True


def test_retained_original_and_actual_sdk_results_are_equal_and_validate_as_a_pair(native_captures, captures):
    for (case, native_raw, native_result), (_, sdk_raw, sdk_result) in zip(native_captures, captures):
        assert native_result == sdk_result
        assert validate_pair(case, native_raw, sdk_raw, native_result, sdk_result) is True


def test_original_readers_start_from_an_empty_system_prompt_and_only_their_prompt(native_captures):
    case, raw, _ = native_captures[ASCII]
    tokens = saved_tokens(case)
    for ordinal in (PRODUCE, UPDATE):
        for loop in _phase(raw, ordinal, True)["loops"]:
            first = loop["modelCalls"][0]
            assert first["context"]["systemPrompt"] == "" and len(first["context"]["messages"]) == 1
            if loop["kind"] == "recall" and not loop["label"].startswith("superseded"):
                assert all(token not in json.dumps(first, ensure_ascii=False) for token in tokens.values())


@pytest.mark.parametrize(("index", "attack"), RESULT_ATTACKS)
def test_original_guard_rejects_self_consistent_result_substitutions(native_captures, index, attack):
    case, original, public = native_captures[index]
    raw, result = deepcopy(original), deepcopy(public)
    _result_attack(attack, case, result)
    _publish(raw, result, True)
    _seal(raw, True)
    with pytest.raises(ValueError):
        validate_result(case, result)
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=True)


@pytest.mark.parametrize(("index", "attack", "reason"), NATIVE_CUSTODY_ATTACKS)
def test_original_guard_refuses_each_custody_substitution_for_its_own_reason(native_captures, index, attack, reason):
    case, original, public = native_captures[index]
    raw, result = deepcopy(original), deepcopy(public)
    _native_attack(attack, case, raw, result)
    if attack not in UNSEALED:
        _seal(raw, True)
    assert validate_result(case, result) is True
    with pytest.raises(ValueError, match=reason):
        validate_capture(case, raw, result, native=True)


@pytest.mark.parametrize("levels", [1, 3, 6])
def test_original_refusal_shown_relative_to_the_process_home_is_the_same_declared_cause(native_captures, levels):
    """A hosted runner checks the repository out below its home, and the release then prints ``~``."""
    case, original, public = native_captures[REFUSAL]
    raw = deepcopy(original)
    workspace = raw["fixtureBase"] + "/workspace"
    shown = "~" + workspace[len(workspace.rsplit("/", levels)[0]):]
    _native_reason(_loop(raw, UPDATE, "updater"), "edit",
                   f"Hardlinked path is not allowed under sandbox root ({shown}): {shown}/MEMORY.md", failed=True)
    _seal(raw, True)
    assert validate_capture(case, raw, public, native=True) is True


def test_an_original_capture_without_its_receipts_is_refused_rather_than_trusted(native_captures):
    case, original, public = native_captures[ASCII]
    for key in ("sessions", "loops", "toolFactoryCalls", "toolOutcomes", "sourceMetadataSetup", "publications",
                "mutations", "snapshots", "closeReceipts", "resolvedMemorySearch", "transcriptUpdateVersions",
                "maintenance", "clock", "config"):
        raw = deepcopy(original)
        del _phase(raw, UPDATE, True)[key]
        _seal(raw, True)
        with pytest.raises(ValueError, match=RECEIPT):
            validate_capture(case, raw, public, native=True)


def test_original_capture_cannot_pass_as_the_sdk_capture(native_captures):
    case, raw, result = native_captures[ASCII]
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=False)


WORKSPACE = ("/home/runner/work/memory-core/memory-core/.equivalence-results/host-update-isolation/"
             "attempt-labelled/case/evidence/native-host-update-AbCdEf/workspace")
REFUSAL_TEXT = "Hardlinked path is not allowed under sandbox root"


def _shown(home, path=WORKSPACE):
    return "~" + path[len(home):]


@pytest.mark.parametrize("home", [None, "/home/runner", "/home", WORKSPACE.rsplit("/", 1)[0], ""])
def test_refusal_cause_accepts_the_absolute_and_the_home_relative_spelling_of_the_same_paths(home):
    root = WORKSPACE if home is None else _shown(home)
    assert native_refusal_names_source(f"{REFUSAL_TEXT} ({root}): {root}/MEMORY.md", WORKSPACE) is True


@pytest.mark.parametrize("reason", [
    f"{REFUSAL_TEXT} ({WORKSPACE}): {WORKSPACE}/USER.md",
    f"{REFUSAL_TEXT} ({WORKSPACE}-other): {WORKSPACE}-other/MEMORY.md",
    f"{REFUSAL_TEXT} ({_shown('/home/runner')}): {_shown('/home/runner')}/USER.md",
    f"{REFUSAL_TEXT} ({_shown('/home/runner')}): {_shown('/home')}/MEMORY.md",
    f"{REFUSAL_TEXT} ({_shown('/home/runner')}): {WORKSPACE}/MEMORY.md",
    f"{REFUSAL_TEXT} ({WORKSPACE}): {_shown('/home/runner')}/MEMORY.md",
    f"{REFUSAL_TEXT} ({_shown('/home/run')}): {_shown('/home/run')}/MEMORY.md",
    f"{REFUSAL_TEXT} (~/another/workspace): ~/another/workspace/MEMORY.md",
    f"{REFUSAL_TEXT} (~): ~/MEMORY.md",
    f"{REFUSAL_TEXT} (~/): ~//MEMORY.md",
    f"{REFUSAL_TEXT} ({WORKSPACE}): {WORKSPACE}/MEMORY.md and more",
    f"Note: {REFUSAL_TEXT} ({WORKSPACE}): {WORKSPACE}/MEMORY.md",
    f"Could not find the exact text in {WORKSPACE}/MEMORY.md",
    "", None,
])
def test_refusal_cause_rejects_other_files_roots_homes_and_causes(reason):
    assert native_refusal_names_source(reason, WORKSPACE) is False
