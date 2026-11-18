"""Forked and summarized durable conversations measured through the normal model request."""
from hashlib import sha256

from equivalence.automation_job_state import wire
from equivalence.compaction_assembly_inputs import inputs

POINT = "compaction.context-assembly.outcomes"
PREFIX = "compaction-active-history-"
SUMMARY = "The prior route ended at the old mill."
INACTIVE = "Abandoned station branch marker."
RECENT = "The published result has already been read."


def build_cases():
    result = []
    for name, compact, repeats, budget in (("fork", False, 2, 32000),
            ("summary", True, 2, 32000), ("bounded-result", True, 9000, 12000)):
        value = inputs()["retained"]
        value.update(historyLimit=32, activeHistory={"compact": compact, "summary": SUMMARY,
            "inactive": INACTIVE, "recent": RECENT, "repeat": '"\\', "repeatCount": repeats,
            "contextTokenBudget": budget})
        del value["file"]["text"]
        result.append({"id": PREFIX + name, "operation": "compaction-assembly-restart-runtime",
            "requirement": "compaction.context-assembly", "covers": [POINT], "input": value,
            "driverScope": "Cold-reopen a forked conversation in both hosts and compare the entire Responses input, "
                           "the actual memory_get result and physical events before and after reopening.",
            "normalizationPolicy": "Preserve all provider items and text, including truncation markers and the durable "
                                   "checkpoint. Compare branch facts apart from independently assigned entry IDs."})
    if sha256(wire(result)).hexdigest() != "159594ec7b84268e61c192bb17eb7cf4d9d289aca3be8376ab327831ee3664fa":
        raise ValueError("The registered active branch, summary or provider budget changed")
    return result


def source_text(value):
    if "activeHistory" not in value:
        return value["file"]["text"]
    options = value["activeHistory"]
    return "START " + options["repeat"] * options["repeatCount"] + " END legacy file bytes.\n"


def active_case(row):
    return row["id"].startswith(PREFIX) or POINT in row.get("covers", ()) or "activeHistory" in row.get("input", {})


def validate_registration(rows):
    actual = [r for r in rows if active_case(r)]
    if actual and wire(actual) != wire(build_cases()):
        raise ValueError("The three active-branch controls must be measured together")


def family_complete(rows):
    selected = [r for r in rows if active_case(r)]
    expected = build_cases()
    return len(selected) == len(expected) and all(
        r.get("status") == "matched" and r.get("runtimeEvidenceValidated") is True
        and all(wire(r.get(k)) == wire(v) for k, v in c.items()) for r, c in zip(selected, expected, strict=True))


def branch_facts(events, value, *, reopened=False):
    """Walk only the physical parents of the current leaf, independent of either context implementation."""
    nodes = {e["id"]: e for e in events if e.get("type") != "session" and isinstance(e.get("id"), str)}
    path, visited = [], set()
    current = next(e for e in reversed(events) if e.get("id") in nodes)
    while current:
        if current["id"] in visited:
            raise ValueError("Cyclic retained conversation")
        visited.add(current["id"])
        path.append(current)
        parent = current.get("parentId")
        if parent is not None and parent not in nodes:
            raise ValueError("Unresolved physical branch parent")
        current = nodes.get(parent)
    hidden = [e for e in nodes.values() if e.get("message", {}).get("content") == value["inactive"]]
    if len(hidden) != 1 or hidden[0]["id"] in visited:
        raise ValueError("The abandoned branch must remain on disk outside the selected path")
    summaries = [e for e in path if e["type"] == "compaction"]
    if len(summaries) != int(value["compact"]):
        raise ValueError("The active compaction control changed")
    if summaries:
        summary, = summaries
        kept = nodes.get(summary["firstKeptEntryId"], {})
        if kept.get("message", {}).get("content") != "Recent turn" or summary["summary"] != value["summary"]:
            raise ValueError("Incorrect physical compaction boundary")
    recent_rows = [e for e in events if e.get("message", {}).get("content") == value["recent"]]
    if len(recent_rows) != 1:
        raise ValueError("Lost the original external turn on disk")
    merged = reopened and not value["compact"]
    if (recent_rows[0]["id"] in visited) == merged:
        raise ValueError("Reopening did not select the expected physical user branch")
    if merged:
        texts = []
        for event in path:
            message = event.get("message", {})
            if message.get("role") != "user":
                continue
            content = message["content"]
            texts.extend([content] if isinstance(content, str) else [part.get("text") for part in content])
        if not any(isinstance(text, str) and value["recent"] + "\n\n" in text for text in texts):
            raise ValueError("An unanswered user was detached without being merged into the submitted prompt")
    return {"inactiveStored": True, "inactiveVisible": False, "summary": summaries[0]["summary"] if summaries else None,
            "firstKept": "Recent turn" if summaries else None, "recent": value["recent"], "queuedUserMerged": merged}


def verify_public(case, public):
    value, options = case["input"], case["input"]["activeHistory"]
    facts = public["retainedBefore"]
    if facts != public["retainedAfter"] or facts["result"]["details"] != public["tool"]:
        raise ValueError("Reopening changed a durable tool result or checkpoint")
    visible = public["input"]
    users = [p["text"] for item in visible if item.get("role") == "user" for p in item["content"]]
    if (any(options["inactive"] in text for text in users) or not any(options["recent"] in text for text in users)
            or not users[-1].endswith(value["prompt"]) or any(text.endswith("Recent turn") for text in users) != options["compact"]
            or any(text.endswith("Old fixture fact") for text in users)
            or any(options["summary"] in text for text in users) != options["compact"]):
        raise ValueError("The provider received the wrong active branch or summary")
    if not options["compact"]:
        wanted = ("[Queued user message from a previous active turn; preserved as context only. "
                  "Continue with the active prompt below.]\n" + options["recent"] + "\n\n" + value["prompt"])
        if not users[-1].endswith(wanted) or len(users) != 1:
            raise ValueError("The original pending user and current prompt must be sent as one turn")
    if [item for item in visible if item.get("type") == "compaction"] != ([] if options["compact"] else [value["checkpointItem"]]):
        raise ValueError("The provider replayed a pre-summary checkpoint or lost an active one")
    call, = [item for item in visible if item.get("type") == "function_call"]
    output, = [item for item in visible if item.get("type") == "function_call_output"]
    if output["call_id"] != call["call_id"] or call["name"] != "memory_get":
        raise ValueError("The bound tool output lost its call")
    text = facts["result"]["content"][0]["text"]
    if options["repeatCount"] > 2:
        if not (public["tool"].get("truncated") is True and len(text) > 16000 and len(output["output"]) == 6000
                and output["output"].endswith("more characters truncated; rerun with narrower args if needed]")):
            raise ValueError("The long physical tool result did not reach the bounded provider input")
    elif output["output"] != text or public["tool"]["text"] != source_text(value).rstrip("\n"):
        raise ValueError("The short tool result was changed")
