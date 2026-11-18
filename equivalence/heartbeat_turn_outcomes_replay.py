"""Reopen the heartbeat producer streams, model callbacks, local recipient and persisted stores."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from equivalence.heartbeat_turn_outcomes import build_cases, wire


def equal(observed, expected, label):
    if wire(observed) != wire(expected):
        raise ValueError(f"Heartbeat evidence differs for {label}")


def read_bytes(path, checksum=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Heartbeat evidence is missing at {path}")
    data = path.read_bytes()
    if checksum is not None:
        equal(sha256(data).hexdigest(), checksum, path.name)
    return data


def run_original(case, node, checkout, runtime, directory):
    from equivalence.heartbeat_turn_outcomes_native import run_native

    observed = run_native(case, node=node, checkout=checkout, runtime=runtime,
                          runtime_root=Path(runtime["runtimeRoot"]), evidence_directory=directory)
    capture = wire([observed["raw"]])
    (directory / "native-raw.json").write_bytes(capture)
    (directory / "public.json").write_bytes(wire(observed["actual"]))
    (directory / "trace.json").write_bytes(wire(observed["releaseTrace"]))
    return {"kind": "official-release-runtime-comparison", "sources": [],
            "results": [{"id": case["id"], "ok": True, "result": observed["actual"]}],
            "releaseSources": observed["releaseSources"], "releaseTrace": observed["releaseTrace"],
            "runtimeDiagnostics": [{"id": case["id"], "rawSnapshots": [observed["raw"]],
                                    "sha256": sha256(capture).hexdigest(), "validationStatus": "verified",
                                    "evidenceDirectory": str(directory)}]}


def _sdk_state(case, raw, public, directory):
    equal(raw["caseSha256"], sha256(wire(case)).hexdigest(), "pinned SDK inputs")
    equal(raw["files"], {"session": "host-session.json", "recipient": "delivered.jsonl",
                         "store": "workspace/.memory-core/automation.json"}, "SDK owned file paths")
    receipts = []
    session = None
    store = None
    queue = []
    serial = 0

    def enqueue(events):
        nonlocal serial
        for event in events:
            serial += 1
            queue.append({"id": str(serial), "text": event["text"], "context_key": event["contextKey"]})

    for step, raw_turn, row in zip(case["input"]["steps"], raw["drives"], public, strict=True):
        label = step["label"]
        result = raw_turn["result"]
        calls = raw_turn["calls"]
        equal(raw_turn["label"], label, "drive identity")
        if session is not None:
            equal(raw_turn["sessionBefore"], session, "session reopened between drives")
        if "scratch" not in step and "tasks" not in step:
            equal(raw_turn["storeBefore"], store, "predecessor file-store state")
        enqueue(step.get("events", []))
        equal(queue, raw_turn["queueBefore"], "complete input queue")
        equal(len(calls), int(result["status"] != "skipped"), "actual model admission")
        message = source = None
        if calls:
            [call] = calls
            message, source = call["turn"]["message"], call["turn"]["internal_turn_source"]
            if not message or not call["context"]["system_prompt"]:
                raise ValueError("Missing admitted model context")
            enqueue(step.get("late", []))
        if result["status"] == "ran":
            equal(result["outcome"]["transcript"][-1], {"role": "assistant", "content": step["reply"]},
                  "actual SDK reply")
            equal(result["consumed_event_ids"], calls[0]["turn"]["selected_event_ids"], "selected queue occurrences")
            if result["disposition"] == "delivered":
                receipts.append(result["outcome"]["decision"]["text"])
        else:
            equal(result["outcome"], None, "skipped or failed completion")
            equal(result["consumed_event_ids"], [], "unsettled event occurrences")
        queue = [e for e in queue if e["id"] not in result["consumed_event_ids"]]
        equal(queue, raw_turn["queueAfter"], "unconsumed events including late arrivals")
        observed_texts = [json.loads(line)["text"] for line in raw_turn["recipientAfter"].splitlines()]
        equal(observed_texts, receipts, "recipient receipts")
        sent = receipts[-1:] if result["disposition"] == "delivered" else []
        observed = {"label": label, "status": result["status"], "reason": result["reason"],
                    "disposition": result["disposition"], "body": message, "internalTurnSource": source,
                    "queueAfter": [{"text": e["text"], "contextKey": e["context_key"]} for e in queue], "sent": sent}
        equal(observed, raw_turn["observation"], "unabridged SDK observation")
        equal(observed, row, "complete public SDK row")
        session = raw_turn["sessionAfter"]
        store = raw_turn["storeAfter"]
        equal(result["session"], session, "persisted session")
        if label == "two-due-one-future":
            due = sorted(job["jobId"] for job in step["tasks"] if job["due"])
            equal([job["job_id"] for job in calls[0]["turn"]["scheduled_tasks"]], due, "due prompt tasks")
            equal(sorted(job["id"] for job in result["outcome"]["jobs_recorded"]), due, "recorded due tasks")
            for job in json.loads(store)["jobs"]:
                equal(job["state"].get("lastRunAtMs"), case["input"]["nowMs"] if job["id"] in due else None,
                      "persisted scheduled run")
        if "scratch" in step:
            equal(json.loads(raw_turn["storeBefore"])["jobs"][0]["state"]["scratch"]["content"], step["scratch"],
                  "stored monitor instructions")
    equal(json.loads(read_bytes(directory / raw["files"]["session"])), session, "final physical session")
    equal(read_bytes(directory / raw["files"]["recipient"]).decode(), raw["drives"][-1]["recipientAfter"],
          "final local recipient file")
    path = directory / raw["files"]["store"]
    equal(read_bytes(path).decode() if path.exists() else None, store, "last physical automation store")


def review_pair(case, original, native, sdk, directory, sdk_hash, implementation):
    if original.get("validationStatus") != "verified":
        raise ValueError("Missing original heartbeat evidence")
    native_dir = Path(original["evidenceDirectory"])
    (directory / "public.json").write_bytes(wire(sdk))
    packet = {"id": case["id"], "nativeDirectory": native_dir.name, "sdkDirectory": directory.name,
              "nativeRawSha256": original["sha256"], "sdkRawSha256": sdk_hash,
              "nativePublicSha256": sha256(wire(native)).hexdigest(), "sdkPublicSha256": sha256(wire(sdk)).hexdigest(),
              "traceSha256": sha256(read_bytes(native_dir / "trace.json")).hexdigest(), "implementation": implementation}
    (directory / "review.json").write_bytes(wire(packet))
    replay(packet, directory.parent)


def replay(packet, root):
    from equivalence.heartbeat_turn_outcomes_native import validate_native

    [case] = [case for case in build_cases() if case["id"] == packet["id"]]
    paths = {}
    for side in ("native", "sdk"):
        folder = packet[side + "Directory"]
        if Path(folder).name != folder or not folder.startswith(side + "-attempt-"):
            raise ValueError("Unexpected heartbeat evidence directory")
        paths[side] = Path(root) / folder
        if paths[side].is_symlink() or not paths[side].is_dir():
            raise ValueError("Missing heartbeat attempt directory")
    native, sdk = (json.loads(read_bytes(paths[side] / "public.json", packet[side + "PublicSha256"]))
                   for side in ("native", "sdk"))
    [original] = json.loads(read_bytes(paths["native"] / "native-raw.json", packet["nativeRawSha256"]))
    [python] = json.loads(read_bytes(paths["sdk"] / "python-raw.json", packet["sdkRawSha256"]))
    trace = json.loads(read_bytes(paths["native"] / "trace.json", packet["traceSha256"]))
    if not trace:
        raise ValueError("Missing heartbeat execution trace")
    validate_native(case, original, native, paths["native"])
    _sdk_state(case, python, sdk, paths["sdk"])
    equal(native, sdk, "both complete public outcomes")
    return len(native)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    args = parser.parse_args()
    packet = json.loads(args.packet.read_bytes())
    print(json.dumps({"case": packet["id"], "matchedSteps": replay(packet, args.evidence_root)}))


if __name__ == "__main__":
    main()
