"""Re-open each writer's journal, native worker traces, leases and final workspace."""
import hashlib
from pathlib import Path

from equivalence.harness import _same_json


def require(value, message):
    if not value:
        raise ValueError(message)


def replay_locks(data, cases, args, runtime):
    from equivalence.workspace_lock_cases import build_cases, validate_registration
    from equivalence.workspace_lock_evidence import observe_drive, source_bindings
    from equivalence.workspace_lock_native import finish_actor
    from equivalence.strict_report_reader import _object, _constant, _finite
    import json

    validate_registration(cases)
    require(cases == build_cases() and cases, "Workspace locks require the complete ordered drives")
    require(source_bindings(args.reference) == data["workspaceLockBindings"], "Workspace lock source changed")
    root = args.report.resolve().parent / "workspace-locks"
    require(root.resolve(strict=True) == root, "Invalid retained writer directory")
    indexed = {(r["package"], r["path"]): r["sha256"] for r in data["followupReleaseSources"]}
    seen = set()
    replays = []
    for case in cases:
        cid = case["id"]
        rows = data["followupRows"][cid]
        reported = rows["case"]
        result = {"id": cid, "children": [], "physicalStateRebuilt": True}
        outputs = {}
        traces = []
        for side, retained_side, basename, prefix in (("native", "native", "native-raw.json", "native-attempt-"),
                                                      ("python", "sdk", "python-raw.json", "sdk-attempt-")):
            record = rows[side]
            path = Path(record["rawPath"])
            require(record["id"] == cid and record["side"] == side and record["validationStatus"] == "verified"
                    and path.name == basename and path.parent.name.startswith(prefix) and path.parent.parent == root
                    and path.resolve(strict=True) == path and path.is_file() and path.stat().st_nlink == 1
                    and path not in seen, "Incorrect retained workspace-lock capture")
            seen.add(path)
            raw_bytes = path.read_bytes()
            sha = hashlib.sha256(raw_bytes).hexdigest()
            packet = json.loads(raw_bytes, object_pairs_hook=_object, parse_constant=_constant)
            _finite(packet)
            require(sha == record["sha256"] and _same_json(packet, record["rawSnapshots"]) and len(packet) == 1,
                    "Workspace-lock capture digest or payload differs from the report")
            raw = packet[0]
            actors = path.parent / "actors"
            require(raw["side"] == retained_side and raw["root"] == str(actors)
                    and actors.resolve(strict=True) == actors
                    and not any(p.is_symlink() for p in actors.rglob("*")), "Foreign workspace-lock actors")
            outputs[side] = observe_drive(case, raw, replay_disk=True)
            require(_same_json(outputs[side], reported["openclaw" if side == "native" else "python"]),
                    "Retained journals and final leases differ from the reported output")
            for role in ("holder", "waiter"):
                actor = raw["receipts"][role]
                code = -9 if role == "holder" and case["input"]["holder"] == "kill" else 0
                require(type(actor["returncode"]) is int and actor["returncode"] == code, "Wrong writer exit status")
                streams = {name: (actors / role / (name + ".log")).read_bytes() for name in ("stdout", "stderr")}
                child = {"side": side, "role": role, "pid": actor["pid"], "returncode": code,
                         "receipts": len(actor["receipts"]),
                         **{name + "Sha256": hashlib.sha256(b).hexdigest() for name, b in streams.items()}}
                if side == "native":
                    actual = finish_actor(actors, role, case, args.node, runtime, actor["pid"], code)
                    # The per-actor SQL view was taken at the instant this actor exited.
                    # The final view is reconstructed above after both owners exited.
                    require(_same_json({k: v for k, v in actor.items() if k != "physical"},
                                       {k: v for k, v in actual.items() if k != "physical"}),
                            "Original process, worker, marker or CAS evidence changed")
                    require(actual["physical"]["rows"] == [] and
                            actor["physical"]["database"] == actual["physical"]["database"],
                            "Writer final SQL state or captured database identity changed")
                    observed_sql = [event["physical"]["rows"] for writer in raw["receipts"].values()
                                    for event in writer["receipts"] if "physical" in event]
                    historical = actor["physical"]["rows"]
                    require(all(any(row in view for view in observed_sql) for row in historical)
                            and len({row["entry_key"] for row in historical}) == len(historical),
                            "The writer exit snapshot contains an unobserved SQLite lease")
                    trace = actual["trace"]
                    require(all(indexed.get((item["package"], item["path"])) == item["sha256"]
                                for item in trace["loaded"]), "Writer imports missing from the full report")
                    traces.append(trace["bootstraps"])
                    child["authenticatedThreads"] = len(trace["bootstraps"])
                else:
                    observed_bytes = {event["bytes"] for writer in raw["receipts"].values()
                                      for event in writer["receipts"] if isinstance(event.get("bytes"), str)}
                    for relative, content in actor["files"].items():
                        path_parts = Path(relative).parts
                        require(len(path_parts) >= 3 and path_parts[0] == "workspaces" and path_parts[1] in {"A", "B"},
                                "The SDK writer observed a foreign workspace")
                        tail = "/".join(path_parts[2:])
                        if tail == "journal.txt":
                            require(any(step["journals"][path_parts[1]] == content for step in raw["observations"]),
                                    "The SDK writer exit journal differs from every publication")
                        elif tail == "memory/.dreams/short-term-promotion.lock":
                            require(content in observed_bytes, "The SDK writer exit lease was never observed")
                        else:
                            require(tail == "memory/.dreams/short-term-promotion.lock.guard" and content == "",
                                    "Unrecognized file in the SDK writer exit snapshot")
                    require(_same_json(actor["streams"], {k + ".log": v.decode() for k, v in streams.items()}),
                            "SDK writer streams disagree with their captured bytes")
                result["children"].append(child)
            label = "native" if side == "native" else "sdk"
            result.update({label + "RawSha256": sha, label + "RawFileBytes": len(raw_bytes)})
            require(hashlib.sha256(path.read_bytes()).hexdigest() == sha, "Writer files changed during replay")
        require(_same_json(rows["trace"], {"id": cid, "kind": "two-protected-workspace-writers", "provider": "none",
                                          "networkFetchDenied": True, "actors": traces}),
                "Reported workspace-lock trace differs from the actual actors")
        result["publicMatch"] = _same_json(outputs["native"], outputs["python"])
        require(reported["workspaceLockEvidenceValidated"] is True
                and (reported["status"] == "matched") is result["publicMatch"], "Workspace lock status changed")
        replays.append(result)
    return replays
