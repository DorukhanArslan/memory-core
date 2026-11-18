"""Drive the fixed provider script through the public host and retain its durable observations."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from equivalence.compaction_assembly_inputs import inputs as assembly_inputs
from equivalence.compaction_assembly_sdk import drive as seed_assembly, read_events
from equivalence.provider_overflow_cases import build_cases, wire
from memory_core.compaction_replay import ReplayModel
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import HostSessionRunner, ProviderTurnExecutor, RuntimePromptInput, SessionState
from memory_core.overflow_recovery import CONTINUATION_PROMPT
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.transcript_tree import select_visible_transcript_events


def _text(message):
    content = message["content"]
    return (
        content
        if isinstance(content, str)
        else "".join(b["text"] for b in content if b.get("type") == "text")
    )


def _assistant(model, value, index, clock):
    if "read" in value:
        blocks = [
            {
                "type": "toolCall",
                "id": f"call_orchard_{index}_{n}",
                "name": "memory_get",
                "arguments": {"path": "MEMORY.md", "from": 1, "lines": 1},
            }
            for n in range(value["read"])
        ]
        stop = "toolUse"
    elif "error" in value:
        blocks, stop = [], "error"
    else:
        blocks, stop = [{"type": "text", "text": value["text"]}], "stop"
    return {
        "role": "assistant",
        "api": model.api,
        "provider": model.provider,
        "model": model.id,
        "content": blocks,
        "stopReason": stop,
        "timestamp": clock,
        "usage": {"input": 2, "output": 1, "totalTokens": 3, "cacheRead": 0, "cacheWrite": 0},
        **({"errorMessage": value["error"]} if "error" in value else {}),
    }


def _observation(case, raw, folder):
    files = ("catalog.sqlite", "callback-receipts.jsonl", "before.json", "outcome.json")
    for name in files:
        path = folder / name
        if path.resolve(strict=True) != folder.resolve() / name or not path.is_file():
            raise ValueError("SDK retained file escapes the producer")
    before = json.loads((folder / "before.json").read_bytes())
    outcome = json.loads((folder / "outcome.json").read_bytes())
    receipts = [json.loads(line) for line in (folder / "callback-receipts.jsonl").read_bytes().splitlines()]
    call_receipts = [digest for kind, digest in receipts if kind == "call"]
    observation_receipts = [digest for kind, digest in receipts if kind == "event"]
    if (
        before != raw["before"]
        or any(raw.get(key) != value for key, value in outcome.items())
        or len(receipts) != len(call_receipts) + len(observation_receipts)
        or call_receipts != [sha256(wire(call)).hexdigest() for call in raw["calls"]]
        or observation_receipts != [sha256(wire(event)).hexdigest() for event in raw["observed"]]
    ):
        raise ValueError("SDK runtime receipt differs from the original producer file")
    events = read_events(folder / "catalog.sqlite", raw["sessionId"])
    if events != raw["after"] or sha256(wire(case)).hexdigest() != raw["caseSha256"]:
        raise ValueError("Physical SDK transcript or frozen provider inputs changed")
    pre = {e.get("id") for e in raw["before"]}
    user = case["input"]["prompt"] * case["input"]["promptRepeat"]
    added = [e for e in events if e.get("id") not in pre]
    admissions = [
        e
        for e in added
        if e.get("message", {}).get("role") == "user" and _text(e["message"]).strip() == user.strip()
    ]
    checkpoints = [e for e in added if e.get("type") == "compaction"]
    if any(not e.get("summary") or not e.get("firstKeptEntryId") for e in checkpoints):
        raise ValueError("SDK committed a compaction without its summary or retained cut")
    if [c["reply"] for c in raw["calls"]] != case["input"]["sequence"]:
        raise ValueError("SDK provider and summary callbacks did not consume the original reply sequence")
    dispatches = []
    for call in raw["calls"]:
        if call["kind"] == "provider":
            last = _text(call["request"]["messages"][-1])
            value = call["assistant"]
            if value["stopReason"] == "toolUse":
                observed = {"read": len(value["content"])}
            elif value["stopReason"] == "error":
                observed = {"error": value["errorMessage"]}
            else:
                observed = {"text": _text(value)}
        else:
            if not call["request"]["messages"]:
                raise ValueError("SDK summarizer received no conversation")
            last, observed = "", {"text": call["summary"]}
        if observed != call["reply"]:
            raise ValueError("SDK callback receipt does not contain its actual response")
        dispatches.append(
            {
                "kind": call["kind"],
                "continuation": CONTINUATION_PROMPT if last.endswith(CONTINUATION_PROMPT) else None,
                "reply": observed,
            }
        )
    receipts = raw["tools"]
    if any(
        t["sourceExecuted"] is not True or t["sourceSettled"] is not True or "result" not in t
        for t in receipts
    ):
        raise ValueError("SDK tool admission lacks a successful tool completion")
    tools = [{"id": t["toolCallId"], "name": t["name"], "arguments": t["arguments"]} for t in receipts]
    ids = {t["id"] for t in tools}
    results = [
        {"id": m["toolCallId"], "textSha256": sha256(_text(m).encode()).hexdigest()}
        for event in select_visible_transcript_events(events)
        if (m := event.get("message", {})).get("role") == "toolResult" and m["toolCallId"] in ids
    ]
    if len(results) != len(ids) or {r["id"] for r in results} != ids:
        raise ValueError("Final active transcript lost or duplicated a completed tool result")
    observed = raw["observed"]
    if "checkpoint" in case["input"] and not case["input"].get("outerRecovery"):
        state = outcome["preflightResult"]
        if (
            outcome["scope"] != "attempt-preflight"
            or not state["skipped"]
            or state["source"] != "precheck"
            or not state["error"]
            or state["recovery"]["route"] != "compact_only"
        ):
            raise ValueError("SDK attempt did not return the checkpoint rejection")
        terminal = {"kind": "precheck", "text": None}
    else:
        if outcome["scope"] != "host-turn" or outcome["failures"]:
            raise ValueError("SDK host producer did not finish its normal turn")
        [terminal] = [value for kind, value in observed if kind == "terminal"]
    if terminal["kind"] == "precheck":
        if raw["payloads"] or not any(e.get("message", {}).get("providerReplay") for e in events):
            raise ValueError("Actual preflight must retain its eligible checkpoint")
    elif raw["payloads"] != [
        {"text": terminal["text"], **({"isError": True} if terminal["kind"] != "completed" else {})}
    ]:
        raise ValueError("SDK terminal payload and state disagree")
    return {
        "preflight": [v for k, v in observed if k == "preflight"],
        "midturn": [v for k, v in observed if k == "midturn"],
        "dispatches": dispatches,
        "tools": tools,
        "compactionAttempts": sum(k == "compaction-attempt" for k, v in observed),
        "compactionsCommitted": len(checkpoints),
        "durableUserAdmissions": len(admissions),
        "durableToolResults": results,
        "terminal": terminal,
    }


async def _drive(case, folder):
    v = case["input"]
    clock = v["clock"]
    workspace = folder / "workspace"
    db = folder / "catalog.sqlite"
    if "checkpoint" in v:
        original = assembly_inputs()[v["checkpoint"]]
        original["model"]["contextWindow"] = v["contextWindow"]
        original.update(seedMs=clock - 60000, attemptMs=clock, prompt=v["prompt"] * v["promptRepeat"])
        await seed_assembly({"input": original}, folder, "seed")
        session = SessionState.new(session_key=original["sessionKey"], session_id=original["sessionId"])
        facts = original["model"]
        model = ReplayModel(facts["provider"], facts["api"], facts["id"], facts["baseUrl"])
    else:
        session = SessionState.new(session_key="agent:main:main", session_id="orchard-session")
        model = ReplayModel(v["provider"], "openai-completions", v["model"])
        workspace.mkdir()
        (workspace / "MEMORY.md").write_text("pear trees " + "water " * v["fileRepeat"] + "\n")
    catalog = MemorySessionCatalog(db, clock_ms=lambda: clock)
    if "checkpoint" not in v:
        catalog.upsert_session(session.session_key, {"sessionId": session.session_id, "updatedAt": clock})

        def stamp(ms):
            return (
                datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )

        entries = [
            {
                "type": "session",
                "id": session.session_id,
                "version": 3,
                "timestamp": stamp(clock),
                "cwd": str(workspace),
            }
        ]
        for i, h in enumerate(v["history"]):
            txt = h["text"] * h.get("repeat", 1)
            ms = clock + i
            message = (
                {"role": "user", "content": txt, "timestamp": ms}
                if h["role"] == "user"
                else _assistant(model, {"text": txt}, i, ms)
            )
            entries.append(
                {
                    "type": "message",
                    "id": "seed-" + str(i),
                    "parentId": "seed-" + str(i - 1) if i else None,
                    "timestamp": stamp(ms),
                    "message": message,
                }
            )
        catalog.replace_events(session.session_id, entries, session_key=session.session_key)
    config = MemoryConfig(
        workspace_dir=workspace, store_path=folder / "index.sqlite", flags=FeatureFlags(vector_search=False)
    )
    runner = HostSessionRunner.open(
        workspace,
        catalog=catalog,
        session=session,
        config=config,
        seed_bootstrap=False,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        now_ms=lambda: clock,
        timezone="UTC",
        time_format="24",
    )
    before = read_events(db, session.session_id)
    (folder / "before.json").write_bytes(wire(before))
    journal = folder / "callback-receipts.jsonl"
    journal.touch(exist_ok=False)
    calls = []
    observed = []

    def record(kind, receipt, collection):
        collection.append(receipt)
        with journal.open("ab") as output:
            output.write(wire([kind, sha256(wire(receipt)).hexdigest()]) + b"\n")

    def observe(kind, value):
        record("event", [kind, value], observed)

    async def provider(request):
        i = len(calls)
        reply = v["sequence"][i]
        assistant = _assistant(model, reply, i, clock)
        record(
            "call", {"kind": "provider", "request": request, "reply": reply, "assistant": assistant}, calls
        )
        return assistant

    async def summarize(request):
        reply = v["sequence"][len(calls)]
        s = reply["text"]
        record("call", {"kind": "summary", "request": asdict(request), "reply": reply, "summary": s}, calls)
        return s

    options = v["compaction"]
    executor = ProviderTurnExecutor(
        model,
        v["contextWindow"],
        provider,
        summarize,
        keep_recent_tokens=options["keepRecentTokens"],
        reserve_tokens=options.get("reserveTokens", 16384),
        mid_turn_precheck=options.get("midTurnPrecheck", {}).get("enabled", False),
        observe=observe,
    )
    prompt = v["prompt"] * v["promptRepeat"]
    context_options = RuntimePromptInput(offered_tool_names=["memory_get"])
    if "checkpoint" in v and not v.get("outerRecovery"):
        current = catalog.read_continuation(session.session_id, session_key=session.session_key)
        context = runner.kit.before_turn(session)
        model_prompt = runner._prepare_model_prompt(prompt, context_options, context, case["id"])
        state = executor.preflight(
            session,
            history=current["context"]["messages"],
            prompt=prompt,
            system_prompt=model_prompt.system_prompt,
            now_ms=clock,
        )
        returned = {
            "source": state.prompt_error_source,
            "error": str(state.prompt_error),
            "skipped": state.skip_prompt_submission,
            "recovery": state.preflight_recovery.to_dict() if state.preflight_recovery else None,
        }
        result = {
            "scope": "attempt-preflight",
            "preflightResult": returned,
            "tools": [],
            "payloads": [],
            "failures": [],
        }
    else:
        outcome = await runner.run_turn(
            prompt, execute=executor, request_id=case["id"], prompt_context=context_options
        )
        result = {
            "scope": "host-turn",
            "tools": list(outcome.tools),
            "payloads": list(outcome.payloads),
            "failures": [asdict(f) for f in outcome.failures],
        }
    raw = {
        "caseSha256": sha256(wire(case)).hexdigest(),
        "sessionId": session.session_id,
        "before": before,
        "after": read_events(db, session.session_id),
        "observed": observed,
        "calls": calls,
        **result,
    }
    (folder / "outcome.json").write_bytes(wire(result))
    (folder / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=True, allow_nan=False) + "\n")
    return _observation(case, raw, folder)


def run_sdk(case, directory):
    if wire(case) not in {wire(c) for c in build_cases()}:
        raise ValueError("Unrecognized provider overflow scenario")
    return asyncio.run(_drive(case, Path(directory)))


def read_sdk(case, raw, directory):
    return _observation(case, raw, Path(directory))
