"""Check REM phase receipts against physical files and the sealed callback boundary."""
from copy import deepcopy
from pathlib import Path

from equivalence.dream_light_evidence import require, same
from equivalence.dream_rem import SIGNALS
from memory_core.consolidation._util import iso_ms


# Sources and publication expectations follow from the literal records, not the SDK readback.
_EXPECTED = {
    "staged-then-consumed": [(("fern",), ("fern", "mist"), "skipped"),
                             (("fern", "dew"), (), "skipped")],
    "themes-evidence-diary": [(("fern", "dew"), (), "completed")],
    "lost-and-blocked": [(("fern",), (), "skipped"), None, ((), (), "skipped")],
    "no-truth-empty-reply": [((), (), "degraded")],
    "model-retry": [(("dew",), (), "completed")],
    "source-removed-during-completion": [(("fern", "dew"), (), "skipped")],
    "publication-failure": [(("fern",), (), "degraded")],
    "no-owner": [((), (), "completed")],
}


def verify_sweep(case, index, row, workspace, before, after, now, added, recall, signals, stores):
    name = case["id"].removeprefix("dream-rem-")
    leaders, considered, status = _EXPECTED[name][index]
    timestamp = iso_ms(now)
    day = timestamp[:10]
    returned = row["return"]
    same(returned["$type"], "memory_core.consolidation.dreaming.DreamingSweepResult", "Wrong SDK sweep return")
    fields = returned["fields"]
    same((fields["phase"], fields["narrative_status"], fields["phase_signals_recorded"]),
         ("rem", status, len(leaders)), "REM phase publication returned the wrong outcome")
    require(not fields["daily_ingestion"]["fields"]["batches"], "Daily ingestion fed the REM report back as a memory")
    same(len(added), 1, "REM sweep emitted an unexpected number of events")
    event = added[0]
    same((event["type"], event["phase"], event["outcome"], event["timestamp"], event["storageMode"]),
         ("memory.dream.completed", "rem", "completed", timestamp, case["input"]["options"]["storageMode"]),
         "Incorrect REM phase event")
    original, expected = stores(before, now)
    for key in considered:
        expected["entries"][key]["lastRemConsideredAt"] = timestamp
    for key in leaders:
        signal = expected["entries"].setdefault(key, {"key": key, "lightHits": 0, "remHits": 0})
        signal.update(lastRemAt=timestamp, remHits=signal["remHits"] + 1)
    if leaders or considered:
        expected["updatedAt"] = timestamp
    same(signals, expected, "Persisted REM hits or stage consumption changed")
    expected_recall = deepcopy(original)
    if name == "source-removed-during-completion":
        del expected_recall["entries"]["dew"]
    same(recall, expected_recall, "The host provider's source mutation differs from physical recall")
    files = []
    report = f"memory/dreaming/rem/{day}.md"
    inline = f"memory/{day}.md"
    if name == "lost-and-blocked" and index == 2:
        require("reportPath" not in event and before["workspace/" + report] == after["workspace/" + report],
                "An empty REM sweep overwrote its earlier report")
    else:
        require(event["reportPath"] == str(workspace / report), "REM event reported a different destination")
        body = after["workspace/" + report].decode()
        title, sections = body.split("\n\n", 1)
        require(title == "# REM Sleep" and sections.startswith("### Reflections\n"), "Physical REM report is incomplete")
        texts = sections.rstrip("\n").split("\n")
        require(len(texts) == event["lineCount"], "REM event line count differs from physical report")
        truths = texts[texts.index("### Possible Lasting Truths") + 1:]
        if leaders:
            require(len(truths) == len(leaders), "REM report has an unexpected number of lasting truths")
            for text, key in zip(truths, leaders, strict=True):
                entry = original["entries"][key]
                require(text.startswith("- " + entry["snippet"] + " [confidence=") and
                        text.endswith(f" evidence={entry['path']}:{entry['startLine']}-{entry['endLine']}]"),
                        "Published truth lost the physical source range or selected the wrong memory")
        else:
            same(truths, ["- No strong candidate truths surfaced."], "Weak sources surfaced as lasting truths")
        if name == "staged-then-consumed":
            files.append(inline)
            same(event["inlinePath"], str(workspace / inline), "Incorrect inline REM event")
            same(after["workspace/" + inline].decode(), "## REM Sleep\n<!-- openclaw:dreaming:rem:start -->\n" +
                 sections + "<!-- openclaw:dreaming:rem:end -->\n", "Inline report differs from separate report")
        files.append(report)
    if leaders or considered:
        files.append(SIGNALS)
    diary = after.get("workspace/DREAMS.md")
    if status == "completed" or name == "no-truth-empty-reply":
        files.append("DREAMS.md")
        provider = case["input"]["options"]["provider"]
        expected_text = (provider[-1]["text"].strip() if name in ("model-retry", "themes-evidence-diary")
                         else "A memory trace surfaced, but details were unavailable in this run.")
        require(diary is not None and expected_text.encode() in diary, "Expected diary publication is absent")
    else:
        require(diary == before.get("workspace/DREAMS.md"), "Canceled or failed completion changed the diary")
    same(fields["files_changed"], files, "SDK reported different physical publication destinations")
    return {"degradedPhases": int(status == "degraded"), "pendingNarratives": 0}


def verify_callbacks(case, receipts, now):
    opts = case["input"]["options"]
    planned = opts["provider"] or []
    require(len(receipts) == len(planned), "Missing or unplanned REM callback")
    calls = []
    path = Path(__file__).resolve().parents[1] / "memory_core/consolidation/dream_narrative.py"
    for i, (receipt, reply) in enumerate(zip(receipts, planned, strict=True)):
        same(receipt["reply"], reply, "Fixture model reply changed")
        same(receipt["nowMs"], now, "Fixture model ran in a different sweep")
        require([str(path), "run_rem_narrative"] in receipt["caller"], "Completion did not originate in the SDK")
        request = receipt["request"]
        fields = {"agentId", "message", "extraSystemPrompt", "timeoutMs"}
        if i == 0 and opts["model"]:
            fields.add("model")
            same(request["model"], opts["model"], "Configured model was dropped")
        require(set(request) == fields and request["agentId"] == opts["agentId"] and
                request["timeoutMs"] == 60_000 and request["extraSystemPrompt"] and request["message"],
                "Wrong REM completion request")
        if "error" in reply:
            same(receipt["error"], {"name": "RuntimeError", "message": reply["error"]}, "Model failure was hidden")
        else:
            same(receipt["returned"], {"text": reply["text"]}, "Model return was changed")
        calls.append(request)
    return calls
