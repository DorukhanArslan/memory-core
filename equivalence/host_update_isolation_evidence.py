"""Custody checks for the closed host update/isolation family.

These guards admit a capture only when its public result was produced by the
declared literal through real tool dispatches, real source bytes and the
declared real fault. They never repair, reorder or drop an observed field.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from equivalence.host_update_isolation import validate_case

EMPTY_ANSWER = "No source-backed memory found."
HARD_LINK = "source-hard-link-during-update"
SIDECAR = "index-publication-sidecar-symlink"
STALE_ERROR = "unable to open database file"


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


def _children(case, raw, native):
    require(isinstance(raw, dict) and raw.get("kind") == "host-update-isolation" and raw.get("input") == case["input"],
            "The capture does not belong to this exact literal")
    children = raw["children"] if native else raw["phases"]
    require([child["label"] for child in children] == ["produce", "update"] and len({child["pid"] for child in children}) == 2,
            "The capture requires two distinct sequential host processes")
    for child, phase in zip(children, case["input"]["phases"]):
        require(child["request"]["phase"] == phase and child["exit"]["code"] == 0, "A host child ran another phase or failed")
    return children


def validate_capture(case, raw, result, *, native):
    """Bind one engine's raw capture to its public result and to the declared real lifecycle."""
    validate_result(case, result)
    expected = expected_sources(case)
    fault = expected["fault"]
    children = _children(case, raw, native)
    observations = [child["output"] if native else child["observation"] for child in children]
    require([item["result"] for item in observations] == result["phases"], "The public result differs from the hosts' own results")
    if native:
        require(raw.get("result") == result, "The coordinator result differs from the returned result")
    update_raw = observations[1]["raw"]
    mutations = update_raw["mutations"]
    if fault == HARD_LINK:
        require([item["stage"] for item in mutations] == ["before-update-tool", "after-update-tool"]
                and mutations[0]["before"]["nlink"] == 1 and mutations[0]["after"]["nlink"] == 2
                and mutations[1]["before"]["nlink"] == 2 and mutations[1]["after"]["nlink"] == 1,
                "The declared real hard-link refusal window was not observed")
    elif fault == SIDECAR:
        require([item["stage"] for item in mutations] == ["before-update", "after-stale-read"]
                and mutations[0]["after"]["kind"] == "symlink" and mutations[1]["before"]["kind"] == "symlink"
                and mutations[1]["after"]["kind"] == ("file" if native else "missing"),
                "The declared real publication-sidecar fault window was not observed")
    else:
        require(mutations == [], "An undeclared filesystem mutation was performed")
    if native:
        for child_raw in (item["raw"] for item in observations):
            for call in child_raw["toolFactoryCalls"]:
                require(call.get("originalToolObjectPassedToAgentLoop") is True
                        or call.get("originalToolObjectsPassedToAgentLoop") is True, "A tool was not the genuine factory object")
            require(child_raw["clock"]["dateConstructorReplaced"] is True and child_raw["clock"]["setTimeoutUnchanged"] is True,
                    "The host clock control differs from the declared Date-only control")
        edits = [event for loop in update_raw["loops"] if loop["kind"] == "update" for event in loop["toolEvents"]]
        require(len(edits) == 1 and edits[0]["toolName"] == "edit" and edits[0]["isError"] is (fault == HARD_LINK),
                "The genuine edit result differs from the declared outcome")
    else:
        turns = [turn for turn in update_raw["turns"] if turn["kind"] == "update"]
        require(len(turns) == 1 and [call["name"] for call in turns[0]["toolCalls"]] == ["replace_memory_entry"],
                "The update was not one genuine curated replacement")
        observed = turns[0]["toolCalls"][0]["observed"]
        require(observed["message"].get("isError") is (True if fault == HARD_LINK else False),
                "The genuine replacement result differs from the declared outcome")
        payload = observed["payload"]
        require(("afterWriteError" in payload) is (fault == SIDECAR), "The write tool misreported its index publication")
        if fault == SIDECAR:
            require(payload["afterWriteError"] == STALE_ERROR and turns[0]["outcome"]["index_status"] == "failed",
                    "The committed write did not report its real failed index publication")
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
