"""Replay managed hook returns, durable SQL, SDK files and narrative settlement."""

from __future__ import annotations

import base64
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from equivalence.dream_deep import RECALL, SIGNALS, TOKEN, canonical, validate_case
from equivalence.dream_deep_bindings import HOOK, MODULES, OWNERS, REGISTRATIONS, required_modules
from equivalence.dream_light_evidence import _decode_blobs, _physical, _tree, require, same
from equivalence.dream_light_sdk_evidence import _files, _stores


def _sql(tree, relative, table, query):
    if relative not in tree:
        return []
    with TemporaryDirectory() as directory:
        dbfile = Path(directory, "observed.sqlite")
        dbfile.write_bytes(tree[relative])
        if relative + "-wal" in tree:
            Path(str(dbfile) + "-wal").write_bytes(tree[relative + "-wal"])
        with closing(sqlite3.connect(dbfile.as_uri() + "?mode=ro", uri=True)) as connection:
            require(connection.execute("PRAGMA quick_check").fetchall() == [("ok",)], "Deep SQLite snapshot is inconsistent")
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            return connection.execute(query).fetchall() if exists else []


def _origins(tree, native):
    name = "state/agents/main/agent/openclaw-agent.sqlite" if native else "agents/main/origins.sqlite"
    rows = _sql(tree, name, "memory_entry_origins",
                "SELECT entry_key, agent_id, session_id, session_key, origin_class, observed_at "
                "FROM memory_entry_origins ORDER BY observed_at, entry_key")
    return [dict(zip(("entryKey", "agentId", "sessionId", "sessionKey", "originClass", "observedAt"), row, strict=True))
            for row in rows]


def _backups(tree, workspace):
    rows = _sql(tree, "state/state/openclaw.sqlite", "plugin_state_entries",
                "SELECT entry_key,value_json FROM plugin_state_entries WHERE plugin_id='memory-core' "
                "AND namespace='dreaming-memory-backups' ORDER BY entry_key")
    key = hashlib.sha256(workspace.encode()).hexdigest()
    records = []
    for row_key, body in rows:
        row = json.loads(body)
        require(row["workspaceKey"] == key and row["workspaceDir"] == workspace and row["version"] == 1
                and row_key == key + ":" + hashlib.sha256(row["key"].encode()).hexdigest(), "Foreign preimage")
        records.append({"key": row["key"], "value": row["value"]})
    return records


def _documents(tree):
    return {k.removeprefix("workspace/"): data.decode() for k, data in tree.items()
            if k.startswith("workspace/") and k.endswith(".md")}


def _events(events, workspace):
    return [{k: ("$WORKSPACE/" + v[len(workspace) + 1:] if k in ("memoryPath", "inlinePath", "reportPath")
                 and isinstance(v, str) and v.startswith(workspace + "/") else v) for k, v in item.items()}
            for item in events]


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _setup(case, public, snapshots, native):
    validate_case(case)
    require(isinstance(snapshots, list) and len(snapshots) == 1, "One complete deep capture required")
    raw = snapshots[0]
    require(raw.get("completed") is True and "error" not in raw, "Managed deep capture did not complete")
    value = case["input"]
    same(raw["input"], value, "Managed deep fixture input changed")
    require(len(raw["snapshots"]) == len(value["turns"]) + 1
            and len(raw["atReturnSnapshots"]) == len(raw["turnReceipts"]) == len(value["turns"]),
            "Incomplete managed turn, return or settlement boundary")
    if native:
        blobs = _decode_blobs(raw)
        tree_fn = _tree
    else:
        blobs = {sha: base64.b64decode(content, validate=True) for sha, content in raw["blobs"].items()}
        require(all(sha == hashlib.sha256(x).hexdigest() for sha, x in blobs.items()), "Changed SDK captured bytes")
        tree_fn = _files
    trees = [tree_fn(t, blobs) for t in raw["snapshots"]]
    at_return = [tree_fn(t, blobs) for t in raw["atReturnSnapshots"]]
    same({p.removeprefix("workspace/"): b.decode() for p, b in trees[0].items() if p.startswith("workspace/")},
         value["files"], "Deep seed files changed")
    same(_origins(trees[0], native), value["originSeeds"], "Deep origin seed SQL rows changed")
    providers = raw["provider"]
    replies = value["provider"] or []
    require(len(providers) == len(replies), "Managed deep provider calls are missing or duplicated")
    for index, (receipt, reply) in enumerate(zip(providers, replies, strict=True)):
        same(receipt["reply"], reply, "Deep provider reply changed")
        same(receipt["returned"], reply, "Deep provider did not return the literal reply")
        req = receipt["request"]
        require(set(req) == {"agentId", "message", "extraSystemPrompt", "timeoutMs"} and req["agentId"] == "main"
                and type(req["timeoutMs"]) is int and req["timeoutMs"] > 0
                and all(type(req[k]) is str and req[k] for k in ("message", "extraSystemPrompt")),
                "Deep provider call lost its actual request")
        if native:
            owner = "short-term-promotion-MX1vHJuE.mjs" if index == 0 else "dreaming-narrative-B8Hp3Mc_.mjs"
            name = "consolidateMemory" if index == 0 else "generateAndAppendDreamNarrative"
            require(name in receipt["callerStack"] and "/node_modules/openclaw/dist/" + owner + ":" in receipt["callerStack"],
                    "Deep callback bypassed the original consolidation or diary owner")
        else:
            stack = receipt["caller"]
            require(all(type(f) is list and len(f) == 2 for f in stack)
                    and any(Path(path).as_posix().endswith("/memory_core/consolidation/" +
                            ("llm_consolidation.py" if index == 0 else "dream_narrative.py")) for path, _ in stack),
                    "Deep callback bypassed the SDK consolidation or diary owner")
    same(raw["observations"], public["observations"], "Returned deep observations differ from raw")
    return raw, trees, at_return


def _turn_extras(raw, ordinal, workspace, events, native):
    control = raw["turnReceipts"][ordinal]
    prev = raw["turnReceipts"][ordinal - 1] if ordinal else {"providerCalls": 0, "logCount": 0, "eventCount": 0}
    require(set(control) == set(prev) == {"providerCalls", "logCount", "eventCount"} and
            all(type(control[k]) is int and control[k] >= prev[k] for k in control)
            and control["providerCalls"] <= len(raw["provider"]) and control["logCount"] <= len(raw["logs"])
            and control["eventCount"] == len(events), "Deep hook receipts lost their turn boundary")
    if ordinal + 1 == len(raw["turnReceipts"]):
        require(control["providerCalls"] == len(raw["provider"]) and control["logCount"] == len(raw["logs"]),
                "Deep hook lost final callback or log output")
    for receipt in raw["provider"][prev["providerCalls"]:control["providerCalls"]]:
        same(receipt["nowMs"], raw["input"]["turns"][ordinal]["nowMs"], "Deep callbacks escaped the triggering turn")
    texts = [l["args"][0] if native else l["text"] for l in raw["logs"][:control["logCount"]]]
    return {"events": _events(events, workspace),
            "modelCalls": [c["request"] for c in raw["provider"][:control["providerCalls"]]],
            "summaries": [t for t in texts if isinstance(t, str) and t.startswith("memory-core: dreaming promotion complete")]}


def _boundaries(case, observations, trees):
    name = case["id"]
    final = observations[-1]
    if name.endswith("cron-pending-narrative"):
        diary = final["documents"]["DREAMS.md"]
        text = case["input"]["provider"][-1]["text"]
        require(text not in (final["diaryAtReturn"] or "") and text in diary and
                any("narrativesPending=1" in msg for msg in final["summaries"]), "Detached diary timing was lost")
    if name.endswith("report-publication-failure"):
        require(trees[0]["workspace/DREAMS.md/keep.txt"] == trees[-1]["workspace/DREAMS.md/keep.txt"]
                and "workspace/DREAMS.md" not in trees[-1] and "workspace/MEMORY.md" in trees[-1]
                and any(e["type"] == "memory.dream.completed" and e.get("phase") == "deep" and e["outcome"] == "failed"
                        and "Refusing to write non-file DREAMS.md" in e["error"] for e in final["events"]),
                "The actual publication conflict or prior promotion was lost")


def validate_deep_native(case, public, snapshots, evidence_directory, loaded):
    raw, trees, at_return = _setup(case, public, snapshots, True)
    root = Path(raw["root"])
    ws = str(root / "workspace")
    require(root.is_absolute() and root.parent == Path(evidence_directory) and root.name.startswith("native-deep-")
            and raw["workspace"] == ws and raw["kind"] == "official-managed-deep-dreaming"
            and raw["clockRestored"] is True and raw["storeClosed"] is True, "Wrong managed hook identity")
    value = case["input"]
    require(raw["inputSha256"] == hashlib.sha256(canonical(value)).hexdigest(), "Managed hook input hash changed")
    for name in required_modules(case):
        item = loaded.get(("node_modules/openclaw", name))
        require(isinstance(item, dict) and item["sha256"] == MODULES[name][0], "Missing managed runtime owner " + name)
    wanted = set(OWNERS)
    if not value["originSeeds"]:
        wanted.remove("recordMemoryEntryOrigins")
    if SIGNALS not in value["files"]:
        wanted.remove("writePhaseSignalStore")
    require({o["name"] for o in raw["owners"]} == wanted and len(raw["owners"]) == len(wanted), "Deep owner was lost")
    for owner in raw["owners"]:
        rel, alias, sha = OWNERS[owner["name"]]
        same(owner, {"relative": rel, "alias": alias, "name": owner["name"], "sourceSha256": sha,
                     "artifactSha256": MODULES[rel][0]}, "Deep original function identity changed")
    same(raw["registrations"], REGISTRATIONS, "Deep plugin registrations changed")
    same(raw["invokedHookSha256"], HOOK, "A different before_agent_reply hook was invoked")
    opts = value["options"]
    deep = {"enabled": opts["enabled"], **{k: opts[k] for k in ("limit", "minScore", "minRecallCount", "minUniqueQueries")}}
    dream = {"enabled": opts["enabled"], "timezone": opts["timezone"], "storage": {"mode": opts["storageMode"]},
             "phases": {"deep": deep, "light": {"enabled": opts["light"]}, "rem": {"enabled": opts["rem"]}}}
    cfg = {"agents": {"defaults": {"workspace": ws, "userTimezone": "UTC"}, "list": [{"id": "main", "workspace": ws}]},
           "plugins": {"entries": {"memory-core": {"enabled": True, "config": {"dreaming": dream}}}},
           "logging": {"level": "silent", "consoleLevel": "silent", "file": str(root / "openclaw.log")}}
    env = {"OPENCLAW_STATE_DIR": str(root / "state"), "OPENCLAW_HOME": str(root),
           "OPENCLAW_CONFIG_PATH": str(root / "openclaw.json")}
    same(raw["cfg"], cfg, "Wrong original deep config")
    same(json.loads(trees[0]["openclaw.json"]), cfg, "Native deep config differs on disk")
    same(raw["env"], env, "Deep state escaped the owned workspace")
    require(raw["factoryCalls"] and all(c["env"] == env and c["options"].get("namespace") for c in raw["factoryCalls"]),
            "Missing native deep keyed state")
    calls = deque(raw["calls"])

    def take(name, args):
        require(calls and calls[0]["name"] == name, "Missing original call " + name)
        receipt = calls.popleft()
        same(receipt["args"], args, "Wrong original input for " + name)
        require(set(receipt) == {"name", "args", "returned"}, "Original call did not return")
        result = receipt["returned"]
        if result == {"kind": "undefined"}:
            return None
        require(set(result) == {"kind", "value"} and result["kind"] == "value", "Incomplete native return")
        return result["value"]

    for name, file in (("writeStore", RECALL), ("writePhaseSignalStore", SIGNALS)):
        if file in value["files"]:
            same(take(name, [ws, json.loads(value["files"][file])]), None, "Store seed failed")
    if value["originSeeds"]:
        same(take("recordMemoryEntryOrigins", [{"agentId": "main", "origins": value["originSeeds"]}]),
             _origins(trees[0], True), "Origin publisher did not seed the observed SQL rows")
    observations = []
    for i, (turn, tree, prior) in enumerate(zip(value["turns"], trees[1:], at_return, strict=True)):
        if turn["queued"]:
            same(take("enqueueSystemEvent", [TOKEN, {"sessionKey": "agent:main:main", "agentId": "main",
                                                     "contextKey": "cron:observatory"}]), True, "Managed event was not queued")
        args = [{"cleanedBody": turn["cleanedBody"]}, {"trigger": turn["trigger"], "agentId": turn["agentId"],
                "sessionKey": turn["sessionKey"], "workspaceDir": ws}]
        returned = take("before_agent_reply", args)
        now = _iso(turn["nowMs"])
        stores, persisted_events = _physical(tree, ws, now)
        for kind in ("recall", "phase"):
            same(take("readShortTermStore", [ws, kind, now]), stores[kind], "Original SQL carrier changed")
        recall = take("readStore", [ws, now])
        signals = take("readPhaseSignalStore", [ws, now])
        events = take("readMemoryHostEventRecords", [{"workspaceDir": ws, "env": env}])
        same(events, persisted_events, "Original deep events differ from their SQLite journal")
        backups = take("readMemoryCoreWorkspaceEntries", [{"workspaceDir": ws, "namespace": "dreaming-memory-backups"}])
        same(backups, _backups(tree, ws), "Original recoverable preimages differ from SQLite")
        origins = take("listMemoryEntryOrigins", [{"agentId": "main"}])
        same(origins, _origins(tree, True), "Deep original origin ledger differs from SQL")
        observations.append({"turn": turn, "returned": returned, "documents": _documents(tree), "recall": recall,
            "signals": signals, "diaryAtReturn": _documents(prior).get("DREAMS.md"),
            "preimages": [e["value"] for e in backups], "origins": origins, **_turn_extras(raw, i, ws, events, True)})
    require(not calls, "Unexpected original managed deep operations")
    same(public, {"observations": observations}, "Public hook output contradicts native owners and durable state")
    _boundaries(case, observations, trees)


def validate_deep_sdk(case, public, snapshots, directory):
    from equivalence.dream_light_sdk import snapshot_files
    from memory_core.consolidation.dreaming_repair import repair_dreaming_recall
    from memory_core.consolidation.managed_dreaming import _run_deep, run_managed_dreaming_turn

    raw, trees, at_return = _setup(case, public, snapshots, False)
    directory = Path(directory).absolute()
    root = directory / "sdk-fixture"
    ws = str(root / "workspace")
    require(directory.resolve(strict=True) == directory and root.resolve(strict=True) == root and raw["root"] == str(root)
            and raw["kind"] == "sdk-managed-dreaming", "Foreign SDK deep workspace")
    disk_capture = directory / "python-raw.json"
    require(disk_capture.is_file() and not disk_capture.is_symlink(), "Missing original SDK capture")
    same(json.loads(disk_capture.read_bytes()), snapshots, "SDK capture differs from its retained packet")
    wanted = []
    for fn in (run_managed_dreaming_turn, _run_deep, repair_dreaming_recall):
        path = Path(inspect.getsourcefile(fn)).resolve(strict=True)
        wanted.append({"name": fn.__qualname__, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    same(raw["owners"], wanted, "SDK managed hook owner drifted")
    current_blobs = {}
    current = snapshot_files(root, current_blobs)
    same(current, raw["snapshots"][-1], "Retained SDK workspace differs from its final file snapshot")
    observations = []
    for i, (turn, tree, prior, call) in enumerate(zip(case["input"]["turns"], trees[1:], at_return, raw["calls"], strict=True)):
        same(call["turn"], turn, "SDK hook input changed")
        require(set(call) == {"turn", "returned", "diaryAtReturn", "queuedJobs"}
                and type(call["queuedJobs"]) is int and 0 <= call["queuedJobs"] <= 1, "SDK hook receipt is incomplete")
        diary = _documents(prior).get("DREAMS.md")
        same(call["diaryAtReturn"], diary, "SDK return-time diary differs from its physical bytes")
        if call["queuedJobs"]:
            require(turn["trigger"] == "cron" and case["input"]["provider"], "Unexpected detached SDK work")
        elif case["id"].endswith("cron-pending-narrative"):
            raise ValueError("Managed SDK cron completed its narrative inline")
        recall, signals = _stores(tree, turn["nowMs"])
        backup_file = tree.get("workspace/memory/.dreams/consolidation-preimages.json")
        backups = json.loads(backup_file)["entries"] if backup_file else []
        events = raw["events"][:raw["turnReceipts"][i]["eventCount"]]
        observations.append({"turn": turn, "returned": call["returned"], "documents": _documents(tree),
            "diaryAtReturn": diary, "recall": recall, "signals": signals, "origins": _origins(tree, False),
            "preimages": backups, **_turn_extras(raw, i, ws, events, False)})
    require(raw["turnReceipts"][-1]["eventCount"] == len(raw["events"]), "Deep SDK hook dropped events")
    same(public, {"observations": observations}, "Managed SDK output differs from its durable evidence")
    _boundaries(case, observations, trees)
