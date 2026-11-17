"""Verify SDK light-dreaming outcomes against physical files and the frozen operations."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath

from equivalence import dream_rem, dream_rem_sdk_evidence
from equivalence.dream_light import NOW, RECALL, SIGNALS, TODAY, validate_case
from equivalence.dream_light_evidence import require, same
from equivalence.dream_light_sdk import event_projection, snapshot_files
from memory_core.consolidation._util import iso_ms, js_to_fixed
from memory_core.consolidation.store_normalization import (
    normalize_short_term_phase_signal_store, normalize_short_term_recall_store,
)

_OWNER_MODULES = {
    "run_dreaming_sweep": "dreaming", "prepare_light_phase": "light_phase",
    "publish_daily_dreaming_phase_block": "light_phase", "ingest_daily_memory_signals": "daily_ingestion",
    "ingest_session_transcript_signals": "session_ingestion", "read_canonical_recall_store": "store",
    "read_canonical_phase_signal_store": "store",
}

# The contributing keys are visible in the literal seeds. Missing/blocked entries and
# stale sources must never appear, even if both runtime adapters were to skip the sweep.
_GROUPS = {
    "group-and-order": [[["cedar", "archive"], ["wave"]]],
    "diary-priority": [[["wave"]]],
    "freshness": [[["wave"]], []],
    "missing-and-tainted": [[["cedar"], ["wave"]], None, []],
    "empty-inline": [[]],
    "disabled-limit": [[]],
}


def _files(tree, blobs):
    result = {}
    for name, info in tree.items():
        path = PurePosixPath(name)
        require(name and not path.is_absolute() and ".." not in path.parts and name == str(path),
                "Unexpected SDK snapshot path")
        data = blobs[info["sha256"]]
        require(type(info["size"]) is int and len(data) == info["size"] and type(info["mtimeNs"]) is int,
                "SDK snapshot size or timestamp mismatch")
        result[name] = data
    return result


def _stores(files, now):
    def decoded(name):
        content = files.get("workspace/" + name)
        return None if content is None else json.loads(content)
    return (normalize_short_term_recall_store(decoded(RECALL), now),
            normalize_short_term_phase_signal_store(decoded(SIGNALS), now))


def _expected_groups(name, ordinal, recall, case):
    if name != "daily-ingestion":
        return _GROUPS[name][ordinal]
    # Derive membership and order from the daily note rather than embedding observed claim IDs.
    bullets = [line[2:] for line in case["input"]["files"][TODAY].splitlines() if line.startswith("- ")]
    require(len(bullets) == 2, "Daily ingestion needs two literal source lines")
    groups = []
    for text in bullets:
        keys = [key for key, entry in recall["entries"].items()
                if entry["path"] == TODAY and entry["snippet"].endswith(text) and entry["dailyCount"] == 1]
        require(len(keys) == 1, "Missing or duplicated daily source")
        groups.append(keys)
    return groups


def _verify_sweep(case, ordinal, row, workspace, before, after, now, added_events, recall, signals):
    name = case["id"].removeprefix("dream-light-")
    options = case["input"]["options"]
    expected_groups = _expected_groups(name, ordinal, recall, case)
    returned = row["return"]
    same(returned["$type"], "memory_core.consolidation.dreaming.DreamingSweepResult", "Wrong SDK sweep return")
    fields = returned["fields"]
    entries = fields["light_entries"]
    same(fields["phase"], "light", "Incorrect SDK phase")
    same([entry["sourceEntryKeys"] for entry in entries], expected_groups, "Unexpected staged source groups")
    same([entry["key"] for entry in entries], [group[0] for group in expected_groups], "Wrong group leaders")
    same(fields["phase_signals_recorded"], len(entries), "Incorrect SDK signal count")
    enabled = options["enabled"] and options["limit"] > 0
    same(fields["skip_reason"], None if enabled else "disabled", "Incorrect SDK skip reason")
    same(fields["candidates"], [], "Light sweep produced scored promotion candidates")
    if not enabled:
        same(added_events, [], "Disabled SDK light sweep emitted an event")
        same(fields["files_changed"], [], "Disabled SDK light sweep wrote a report")
        require(before == {key: data for key, data in after.items() if key.startswith("workspace/")},
                "Disabled light sweep changed workspace files")
        return
    timestamp = iso_ms(now)
    day = timestamp[:10]
    mode = options["storageMode"]
    daily = fields["daily_ingestion"]["fields"]
    expected_daily_count = 0 if ordinal or name == "empty-inline" else (2 if name == "daily-ingestion" else 1)
    same(sum(len(batch["fields"]["results"]) for batch in daily["batches"]), expected_daily_count,
         "Daily ingestion did not observe the frozen source lines")
    expected_events = []
    for batch in daily["batches"]:
        batch = batch["fields"]
        results = [{key: result[key] for key in ("path", "startLine", "endLine", "score")}
                   for result in batch["results"]]
        expected_events.append({"type": "memory.recall.recorded", "timestamp": timestamp,
                                "query": "__dreaming_daily__:" + batch["day"], "resultCount": len(results),
                                "results": results})
    require(not fields["session_ingestion"]["fields"]["batches"], "Unexpected SDK session corpus")
    event = {"type": "memory.dream.completed", "timestamp": timestamp, "phase": "light",
             "outcome": "completed", "lineCount": max(1, 5 * len(entries)), "storageMode": mode}
    changes = []
    lines = []
    previous_signals = _stores(before, now)[1]
    expected_signals = deepcopy(previous_signals)
    for entry in entries:
        group = [recall["entries"][key] for key in entry["sourceEntryKeys"]]
        leader = group[0]
        for key in ("snippet", "path", "startLine", "endLine", "dailyCount", "groundedCount"):
            same(entry[key], leader[key], "Reported group leader lost its physical source identity")
        for key in ("recallCount", "totalScore", "maxScore"):
            same(entry[key], max(item[key] for item in group), "Wrong merged group evidence")
        count = sum(entry[field] for field in ("recallCount", "dailyCount", "groundedCount"))
        average = max(0, min(1, entry["totalScore"] / count)) if count else 0
        lines.extend([f"- Candidate: {entry['snippet']}", f"  - confidence: {js_to_fixed(average, 2)}",
                      f"  - evidence: {entry['path']}:{entry['startLine']}-{entry['endLine']}",
                      f"  - recalls: {entry['recallCount']}", "  - status: staged"])
        key = entry["key"]
        signal = expected_signals["entries"].setdefault(key, {"key": key, "lightHits": 0, "remHits": 0})
        signal.update(lightHits=min(9999, signal["lightHits"] + 1), lastLightAt=timestamp)
        expected_signals["updatedAt"] = timestamp
    same(signals, expected_signals, "Physical phase signals disagree with the selected group leaders")
    body = "\n".join(lines) if lines else "- No notable updates."
    inline = f"memory/{day}.md"
    report = f"memory/dreaming/light/{day}.md"
    if mode in {"inline", "both"} and (entries or "workspace/" + inline in before):
        changes.append(inline)
        event["inlinePath"] = str(workspace / inline)
        original = before.get("workspace/" + inline, b"").decode().rstrip()
        block = "## Light Sleep\n<!-- openclaw:dreaming:light:start -->\n" + body + "\n<!-- openclaw:dreaming:light:end -->\n"
        require(after["workspace/" + inline] == ((original + "\n\n" if original else "") + block).encode(),
                "Physical inline report disagrees with staged groups")
    if mode in {"separate", "both"} and entries:
        changes.append(report)
        event["reportPath"] = str(workspace / report)
        require(after["workspace/" + report] == ("# Light Sleep\n\n" + body + "\n").encode(),
                "Physical separate report disagrees with staged groups")
    if entries:
        changes.append(SIGNALS)
    unchanged_documents = {
        key: data for key, data in before.items()
        if key.endswith(".md") and key.removeprefix("workspace/") not in changes
    }
    require(unchanged_documents == {
        key: data for key, data in after.items()
        if key.endswith(".md") and key.removeprefix("workspace/") not in changes
    }, "SDK light sweep modified an unrelated or previously published note")
    same(fields["files_changed"], changes, "Returned SDK publication paths disagree with physical files")
    same(added_events, [*expected_events, event], "SDK ingestion and publication events disagree with the sweep")


def validate_sdk(case, public, snapshots, directory):
    rem = case.get("operation") == dream_rem.OPERATION
    (dream_rem.validate_case if rem else validate_case)(case)
    directory = Path(directory).absolute()
    root = directory / "sdk-fixture"
    workspace = root / "workspace"
    require(directory == directory.resolve() and root.is_dir() and root == root.resolve()
            and workspace.is_dir() and workspace == workspace.resolve(), "Unowned SDK workspace")
    require(isinstance(snapshots, list) and len(snapshots) == 1, "Expected one SDK light capture")
    raw = snapshots[0]
    require(raw.get("complete") is True and "error" not in raw and raw["kind"] == ("dream-rem-sdk" if rem else "dream-light-sdk"),
            "Incomplete SDK light capture")
    same(raw["workspace"], str(workspace), "Misbound SDK fixture")
    same(raw["input"], case["input"], "SDK used a different fixture")
    same(raw["output"], public, "SDK public result differs from captured output")
    expected_owners = []
    owner_root = Path(__file__).resolve().parents[1] / "memory_core/consolidation"
    owner_modules = list(_OWNER_MODULES.items())
    if rem:
        owner_modules[1:2] = [("prepare_rem_phase", "rem_phase"), ("run_rem_narrative", "dream_narrative")]
    for name, module in owner_modules:
        path = owner_root / (module + ".py")
        expected_owners.append({"name": name, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    same(raw["owners"], expected_owners, "SDK production source identity changed")
    blobs = {key: base64.b64decode(value, validate=True) for key, value in raw["blobs"].items()}
    require(all(hashlib.sha256(value).hexdigest() == key for key, value in blobs.items()), "Corrupt SDK content blob")
    literal = snapshot_files(root, {})
    same(raw["snapshots"][-1], literal, "Final SDK snapshot differs from the live fixture")
    trees = [_files(tree, blobs) for tree in raw["snapshots"]]
    require(set(blobs) == {info["sha256"] for tree in raw["snapshots"] for info in tree.values()},
            "Unexpected or missing SDK content blobs")
    seed = {"workspace/" + path: content.encode() for path, content in case["input"]["files"].items()}
    require(trees[0] == seed and all(info["mtimeNs"] == NOW * 1_000_000 for info in raw["snapshots"][0].values()),
            "Initial SDK workspace differs from the literal seed")
    operations = case["input"]["operations"]
    require(len(trees) == len(operations) + 1 and len(raw["operations"]) == len(public["observations"]) == len(operations),
            "Incomplete SDK operation evidence")
    previous_events = []
    phase_results = []
    now = NOW
    for index, (op, row, observation) in enumerate(zip(operations, raw["operations"], public["observations"])):
        same(row["operation"], op, "Unexpected SDK operation")
        before, after = trees[index:index + 2]
        now = op.get("nowMs", now)
        recall, signals = _stores(after, now)
        events = row["events"]
        same(events[:len(previous_events)], previous_events, "SDK cumulative event history changed")
        added = events[len(previous_events):]
        if op["op"] == "remove":
            require(not added and "return" not in row, "Removing a source ran a sweep")
            require(after == {key: data for key, data in before.items() if key != "workspace/" + op["path"]},
                    "Removal changed other files")
        elif rem:
            phase_results.append(dream_rem_sdk_evidence.verify_sweep(
                case, index, row, workspace, before, after, now, added, recall, signals, _stores))
        else:
            _verify_sweep(case, index, row, workspace, before, after, now, added, recall, signals)
        documents = {key.removeprefix("workspace/"): data.decode() for key, data in after.items()
                     if key.startswith("workspace/") and key.endswith(".md")}
        physical = {"operation": op, "documents": documents, "recall": recall, "signals": signals,
                    "events": event_projection(events, workspace)}
        if rem:
            calls = dream_rem_sdk_evidence.verify_callbacks(case, raw["modelCalls"], now)
            physical.update(sweepResults=deepcopy(phase_results), modelCalls=calls)
        same(row["observation"], physical, "SDK readback disagrees with physical files or callbacks")
        same(observation, physical, "Public SDK observation disagrees with physical files or callbacks")
        previous_events = events
    same(raw["events"], previous_events, "Incomplete final SDK event stream")
