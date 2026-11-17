"""Physically replay diary content, guarded appends and artifact trust on both runtimes."""
import base64
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from equivalence import dream_diary as family
from equivalence.dream_diary_bindings import OWNERS, COMPILED
from equivalence.dream_diary_sdk import SDK_OWNERS, capture, documents
from equivalence.dream_light_evidence import require, same
from equivalence.dream_light_sdk import _owner, event_projection

_EXPECTED = {
    "phase-and-trust": ["published", "published"], "lowercase-and-truncation": ["published", "published"],
    "vanished-source": ["fixture", "skipped"], "missing-quoted-context": ["fixture", "skipped"],
    "older-quoted-entry": ["published"], "publisher-failure": ["fixture", "failed", "fixture", "published"],
    "competing-diary-writers": ["raced"],
}
_STAMPS = {"America/New_York": "January 1, 2026 at 7:00 AM EST", "Asia/Tokyo": "January 1, 2026 at 9:00 PM GMT+9",
           "America/Los_Angeles": "January 2, 2026 at 4:00 AM PST", "UTC": "January 1, 2026 at 12:00 PM UTC"}


def _owned_tree(files):
    for name, fact in files.items():
        path = Path(name)
        require(name == path.as_posix() and not path.is_absolute() and ".." not in path.parts, "Unowned diary file path")
        if fact["kind"] == "file":
            require(hashlib.sha256(fact["text"].encode()).hexdigest() == fact["sha256"], "Corrupt diary file bytes")
        else:
            require(name == "DREAMS.md" and fact["kind"] == "link" and fact["target"] == "owner-copy.md",
                    "Unexpected diary fixture link")


def _database(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        require(db.execute("PRAGMA quick_check").fetchall() == [("ok",)], "Invalid diary SQLite bytes")
        rows = db.execute("SELECT namespace,entry_key,value_json FROM plugin_state_entries "
                          "WHERE plugin_id='memory-core' ORDER BY namespace,entry_key").fetchall()
    return [dict(zip(("namespace", "entry_key", "value_json"), row)) for row in rows]


def _verify_db(capture, blobs, workspace):
    snapshot = capture["dbFiles"]
    require("" in snapshot and set(snapshot) <= {"", "-wal"}, "Missing diary SQLite snapshot")
    with TemporaryDirectory() as directory:
        file = Path(directory) / "database"
        for suffix, info in snapshot.items():
            data = blobs[info["sha256"]]
            require(len(data) == info["size"], "Incomplete SQLite file")
            Path(str(file) + suffix).write_bytes(data)
        rows = _database(file)
    same(rows, capture["database"], "Captured diary state disagrees with its physical SQLite bytes")
    sources, events, leases = [], [], {}
    workspace_key = hashlib.sha256(str(workspace).encode()).hexdigest()
    for row in rows:
        value = json.loads(row["value_json"])
        if row["namespace"] == "short-term-recall":
            require(value["workspaceDir"] == str(workspace) and value["workspaceKey"] == workspace_key
                    and row["entry_key"] == workspace_key + ":" + hashlib.sha256(value["key"].encode()).hexdigest(),
                    "Unbound diary source key")
            sources.append(value["key"])
        elif row["namespace"] == "memory-host.events" and value["kind"] == "event":
            events.append((value["sequence"], value["event"]))
        elif row["namespace"] == "short-term-locks":
            leases[row["entry_key"]] = value
    return sorted(sources), [e for _, e in sorted(events)], leases


def _check_append(op, returned, before, after, expected):
    target = "dreams.md" if "dreams.md" in before and "DREAMS.md" not in before else "DREAMS.md"
    if expected in {"failed", "skipped"}:
        same(before, after, "Rejected diary mutation changed physical evidence")
        if expected == "failed":
            require(returned["message"] == "Refusing to write symlinked DREAMS.md", "Expected an actual publisher failure")
        return
    old = before.get(target, {}).get("text", "")
    now = after[target]["text"]
    entry = f"\n---\n\n*{_STAMPS[op['timezone']]}*\n\n{op['narrative']}\n"
    require(returned["path"] == target and now.count(entry) == old.count(entry) + 1
            and family.END in now and now.endswith("\n"), "Missing dated narrative publication")
    same({k: v for k, v in after.items() if k != target}, {k: v for k, v in before.items() if k != target},
         "Diary append touched an unrelated document")


def _validate(case, public, raw, workspace, native, database_states):
    family.validate_case(case)
    name = case["id"].removeprefix("dream-diary-")
    seed = raw["initial"]["files"] if native else raw["initial"]
    _owned_tree(seed)
    previous = documents(seed)
    same(previous, {p: {"text": t} for p, t in case["input"]["files"].items()}, "Wrong literal diary files")
    same([r["observation"]["outcome"]["status"] for r in raw["rows"]], _EXPECTED[name], "Wrong diary operation outcomes")
    require(len(raw["rows"]) == len(case["input"]["operations"]) == len(public["observations"]), "Incomplete diary operations")
    durable_events = []
    for i, (op, row, observation) in enumerate(zip(case["input"]["operations"], raw["rows"], public["observations"])):
        same(op, row["operation"], "Wrong captured diary operation")
        same(observation, row["observation"], "Changed public diary projection")
        same(observation["operation"], op, "Wrong public diary operation")
        _owned_tree(row["files"])
        docs = documents(row["files"])
        same(observation["documents"], docs, "Public diary differs from the actual file")
        result = observation["outcome"]
        kind = op["op"]
        if native:
            sources, events, leases = database_states[i]
            same(leases, {}, "Original diary write left a durable lease")
        else:
            sources = sorted(json.loads(row["files"]["memory/.dreams/short-term-recall.json"]["text"])["entries"])
            events = row["callbacks"]
        same(observation["sourceKeys"], sources, "Diary claims unavailable source evidence")
        same(sources, [] if name == "vanished-source" else ["leaf"], "Wrong surviving source")
        same(observation["events"], event_projection(events, workspace), "Unbound diary event stream")
        if kind == "phase":
            report = "memory/dreaming/light/2026-01-01.md"
            expected = "# Light Sleep\n\n" + "\n".join(op["lines"]) + "\n"
            same(docs[report], {"text": expected}, "Phase publication lost its source evidence")
            require("\n".join(op["lines"]) in docs[family.NOTE]["text"], "Missing inline phase evidence")
            same(result["paths"], [family.NOTE, report], "Phase publisher returned wrong paths")
            durable_events.append({"type": "memory.dream.completed", "timestamp": datetime.fromtimestamp(
                op["nowMs"] / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "phase": op["phase"], "outcome": "completed", "lineCount": len(op["lines"]), "storageMode": "both",
                "inlinePath": "$WORKSPACE/" + family.NOTE, "reportPath": "$WORKSPACE/" + report})
        elif kind == "append":
            _check_append(op, result, previous, docs, _EXPECTED[name][i])
            if _EXPECTED[name][i] in {"failed", "skipped"}:
                prior = seed if i == 0 else raw["rows"][i-1]["files"]
                for path in docs:
                    same(row["files"][path], prior[path], "A suppressed publication still modified the file")
        elif kind == "race":
            facts = raw["race"]
            same([f["event"] for f in facts], ["first-published", "second-attempted", "contention", "second-published"],
                 "Missing competing diary writers")
            middle = facts[2]
            require(result["pending"] is True and middle["pending"] is True and result["intermediate"] == middle["text"]
                    and op["first"] in middle["text"] and op["second"]["narrative"] not in middle["text"],
                    "Second publication did not wait under the held lease")
            final = docs["DREAMS.md"]["text"]
            require(final.count(op["first"]) == final.count(op["second"]["narrative"]) == 1
                    and final.index(op["first"]) < final.index(op["second"]["narrative"]), "Lost concurrent diary publication")
        expected_trust = [
            {"relativePath": path, "originClass": ("agent" if path == family.NOTE else "untrusted"
             if path == "owner-copy.md" or "link" in doc else "system")} for path, doc in sorted(docs.items())
        ]
        same(observation["trust"], expected_trust, "Diary or phase output acquired incorrect artifact trust")
        same(observation["events"], durable_events, "Missing or duplicated physical phase publication receipt")
        if kind == "append" and result["status"] == "published":
            snippet = " ".join(op["narrative"].split())
            clipped = snippet.encode("utf-16-le")[:720].decode("utf-16-le", errors="ignore").rstrip() + "..."
            require(observation["recent"] and observation["recent"][0] == (clipped if len(snippet.encode("utf-16-le")) > 720 else snippet),
                    "Published evidence missing from bounded diary coverage")
        previous = docs
    current = capture(workspace)
    expected = raw["rows"][-1]["files"]
    if native:
        for item in current.values():
            item.update(mtimeNs=str(item["mtimeNs"]), ino=str(item["ino"]))
    same(current, expected, "Final physical diary workspace changed")


def validate_sdk(case, public, snapshots, directory):
    workspace = Path(directory).resolve() / "sdk-diary"
    require(workspace.resolve() == workspace and isinstance(snapshots, list) and len(snapshots) == 1, "Unowned SDK diary receipt")
    raw = snapshots[0]
    same(raw["case"], case, "Wrong SDK diary case")
    same(raw["owners"], [_owner(fn) for fn in SDK_OWNERS], "SDK diary owner changed")
    require(raw["workspace"] == str(workspace) and raw["complete"] is True, "Incomplete SDK diary receipt")
    events = [json.loads(line) for line in (workspace.parent / "sdk-callbacks.jsonl").read_text().splitlines()]
    same(events, raw["rows"][-1]["callbacks"], "SDK callback receipt changed")
    if raw["race"]:
        facts = raw["race"]
        require(facts[0]["thread"] != facts[1]["thread"] and facts[2]["lease"].get("ownerToken")
                and type(facts[2]["lease"].get("pid")) is int,
                "SDK race lost its distinct writer or physical lease")
    _validate(case, public, raw, workspace, False, [])


def validate_native(case, public, snapshots, directory, loaded):
    require(isinstance(snapshots, list) and len(snapshots) == 1, "Expected one protected native diary receipt")
    raw = snapshots[0]
    workspace = Path(raw["workspace"])
    root = Path(raw["root"])
    require(root.is_absolute() and root.resolve() == root and root.parent == Path(directory).resolve()
            and root.name.startswith("native-diary-") and workspace == root / "workspace" and workspace.resolve() == workspace,
            "Unowned native diary workspace")
    require(raw.get("complete") is True and raw.get("closed") is True and "error" not in raw, "Incomplete native diary write")
    same(raw["input"], case["input"], "Misbound native diary fixture")
    expected = [{"relative": p, "alias": a, "name": n, "sourceSha256": f, "artifactSha256": COMPILED[p][0]}
                for p, a, n, f in OWNERS]
    same(raw["owners"], expected, "Wrong original diary bindings")
    require(all(("node_modules/openclaw", p) in loaded for p in COMPILED), "Native diary did not load original owners")
    calls = raw["calls"]
    appends = [c for c in calls if c["name"] == "appendNarrativeEntry"]
    requested = [op for op in case["input"]["operations"] if op["op"] == "append"]
    if case["input"]["operations"][-1]["op"] == "race":
        r = case["input"]["operations"][-1]
        requested += [{"narrative": r["first"], "nowMs": r["nowMs"], "timezone": "UTC", "keys": [], "recent": []}, r["second"]]
    require(len(requested) == len(appends), "Missing original diary writer invocation")
    for op, call in zip(requested, appends):
        same(call["args"], [{"workspaceDir": str(workspace), "narrative": op["narrative"], "nowMs": op["nowMs"],
                             "timezone": op["timezone"], "sourceEntryKeys": op["keys"], "recentDiaryEntries": op["recent"]}],
             "Guarded source keys or prior quotes omitted from the original publication")
    blobs = {key: gzip.decompress(base64.b64decode(value, validate=True)) for key, value in raw["dbBlobs"].items()}
    require(all(len(data) <= 4 * 1024 * 1024 and hashlib.sha256(data).hexdigest() == key for key, data in blobs.items()),
            "Corrupt original diary database")
    initial_keys, _, _ = _verify_db(raw["initial"], blobs, workspace)
    same(initial_keys, ["leaf"], "Missing original source seed")
    states = [_verify_db(row, blobs, workspace) for row in raw["rows"]]
    database = root / "state/state/openclaw.sqlite"
    same(raw["database"], str(database), "Unowned SQLite path")
    same(_database(database), raw["rows"][-1]["database"], "Final original SQLite journal changed")
    calls = raw["leaseCalls"]
    key = hashlib.sha256(str(workspace).encode()).hexdigest()
    sets = [c for c in calls if c["method"] == "compareAndApply" and c["args"][2]["action"] == "set"
            and c["returned"]["status"] == "applied"]
    deletes = [c for c in calls if c["method"] == "compareAndApply" and c["args"][2]["action"] == "delete"
               and c["returned"]["status"] == "applied"]
    require(sets and len(sets) == len(deletes) and all(c["pid"] == raw["pid"] and c["args"][0] == key for c in calls),
            "Missing original acquisition and cleanup receipts")
    if raw["race"]:
        _, _, leases = _verify_db(raw["race"][2], blobs, workspace)
        require(leases.get(key) in [c["args"][2]["value"] for c in sets] and len(sets) >= 2,
                "Concurrent narrative publication never held the captured lease")
    _validate(case, public, raw, workspace, True, states)
