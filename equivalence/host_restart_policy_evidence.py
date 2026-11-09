"""Separate zero-credit policy/metadata custody guard; no result normalization."""
import json
from pathlib import Path

from equivalence.host_restart_evidence import _validate_capture, _text, require
from equivalence.promotion_apply_family import differences


def _validate_policy_capture(case, raw, result, *, native, publication=False, managed=False, session_managed=False):
    _validate_capture(case, raw, result, native=native, policy=True, publication=publication, managed=managed,
                      session_managed=session_managed)
    value, policy = case["input"], case["input"]["policy"]
    sources = ["memory", "sessions"] if policy["rememberAcrossConversations"] else ["memory"]
    resolved = {"sources": sources, "searchSources": ["memory"], "sessionMemory": policy["rememberAcrossConversations"]}
    phases = raw["children"] if native else raw["phases"]
    timelines = []
    for ordinal, record in enumerate(phases):
        phase = record["output" if native else "observation"]["raw"]
        require(record["request"]["policy"] == policy, "The host changed its explicit source policy")
        if native:
            require(len(phase["resolvedMemorySearch"]) == 2
                    and {owner["agentId"] for owner in phase["resolvedMemorySearch"]} == {value["identity"]["agentId"], value["identity"]["isolatedAgentId"]},
                    "Both original host owners must resolve their explicit policy")
            for owner in phase["resolvedMemorySearch"]:
                config = owner["config"]
                require(config["sources"] == sources and config["searchSources"] == ["memory"]
                        and config["experimental"]["sessionMemory"] == resolved["sessionMemory"],
                        "The actual original resolver used a different source policy")
            for snapshot in phase["snapshots"]:
                rows = []
                for manager in snapshot["memory"]:
                    require(manager["status"]["sources"] == sources, "A Native manager indexed undeclared sources")
                    chunks = next(table["rows"] for table in manager["sql"]["tables"] if table["name"] == "memory_index_chunks")
                    require(all(chunk["source"] in sources for chunk in chunks), "The Native index contains undeclared source chunks")
                    rows.append({"agentId": manager["agentId"], "chunks": [{key: chunk[key] for key in ("path", "source", "text")} for chunk in chunks]})
                timelines.append({"phase": record["label"], "snapshot": snapshot["label"], "owners": rows})
        else:
            require(phase["policyResolution"] == {"input": policy, "result": resolved}, "The SDK did not use its actual source resolver")
            require(all(owner["config"]["session_search"] is resolved["sessionMemory"] for owner in phase["opens"]), "SDK session admission differs from the resolved policy")
            for snapshot in phase["snapshots"]:
                chunks = snapshot["published"]["chunks"]
                require(all(chunk["source"] in sources for chunk in chunks), "The SDK index contains undeclared source chunks")
                timelines.append({"phase": record["label"], "session": snapshot["session"],
                    "revision": snapshot["published"]["revision"], "chunks": [{key: chunk[key] for key in ("path", "source", "text")} for chunk in chunks]})
        if ordinal == 1:
            require(not phase.get("sourceMetadataSetup") if native else all("sourceMetadata" not in turn for turn in phase["turns"]),
                    "The restarted host performed hidden source metadata repair")
            continue
        content = value["phases"][0]["write"]["content"]
        if native:
            first = phase["snapshots"][0]
            manager = next(owner for owner in first["memory"] if owner["agentId"] == value["identity"]["agentId"])
            chunks = next(table["rows"] for table in manager["sql"]["tables"] if table["name"] == "memory_index_chunks")
            require(len(phase["sourceMetadataSetup"]) == 1, "The genuine producer must retain exactly one metadata syscall")
            metadata = phase["sourceMetadataSetup"][0]
            before, after = metadata["before"], metadata["after"]
            require(metadata["trigger"] == phase["loops"][0]["toolEvents"][0], "Metadata control ran before the real writer result")
            require(before["kind"] == after["kind"] == "file" and before["hex"] == after["hex"] == content.encode().hex()
                    and after["mtimeMs"] == policy["sourceMtimeMs"] and metadata["contentUnchanged"], "The Native metadata syscall changed source bytes or failed to set its mtime")
            require(metadata["calls"] == [{"operation": "utimesSync", "arguments": [after["absolutePath"], policy["sourceMtimeMs"] / 1000, policy["sourceMtimeMs"] / 1000], "returnedUndefined": True}], "Missing actual Native metadata syscall receipt")
            require(_text(phase["loops"][0]["messages"][-1]) == value["phases"][0]["saveAck"], "Producer acknowledgement differs from its own literal response")
        else:
            writer = phase["turns"][0]
            chunks = phase["snapshots"][0]["published"]["chunks"]
            metadata = writer["sourceMetadata"]
            before, after = metadata["before"], metadata["after"]
            require(before["source"] == after["source"] and after["source"]["hex"] == content.encode().hex(), "The SDK metadata syscall changed actual source bytes")
            require(all(before["stat"][key] == after["stat"][key] for key in ("dev", "ino", "mode", "nlink", "size")), "The SDK replaced its produced source during metadata control")
            instant = str(policy["sourceMtimeMs"] * 1_000_000)
            require(after["stat"]["mtimeNs"] == instant and metadata["arguments"] == {"ns": [instant, instant]}
                    and metadata["returnedNone"], "Missing actual SDK metadata syscall receipt")
            require(metadata["publishedBefore"] == metadata["publishedAfterMetadataChange"], "Filesystem metadata setup secretly rewrote the index or provenance ledger")
            require(_text(writer["assistant"]) == value["phases"][0]["saveAck"], "The SDK writer acknowledgement differs from its literal input")
        sessions = [chunk for chunk in chunks if chunk["source"] == "sessions"]
        if policy["rememberAcrossConversations"]:
            expected = "User: " + value["phases"][0]["savePrompt"] + "\nAssistant: " + value["phases"][0]["saveAck"]
            require(len(sessions) == 1 and sessions[0]["path"] == "sessions/" + value["identity"]["agentId"] + "/" + value["identity"]["writer"]["sessionId"] + ".jsonl"
                    and sessions[0]["text"] == expected, "The actual writer session projection was omitted or changed")
        else:
            require(sessions == [], "The memory-only producer indexed undeclared sessions")
    return {"structuralCustodyPassed": True, "policyResolutionPassed": True,
            "metadataSyscallCustodyPassed": True, "observedCorpusTimeline": timelines,
            "acceptancePointsAwarded": 0}


def validate_capture(case, raw, result, *, native):
    return _validate_policy_capture(case, raw, result, native=native)


def replay_case(case, directory):
    directory = Path(directory)
    native = json.loads((directory / "evidence/native-raw.json").read_text())[0]
    sdk = json.loads((directory / "evidence/python-raw.json").read_text())[0]
    original = json.loads((directory / "stdout.json").read_text())["result"]
    implementation = json.loads((directory / "sdk-output.json").read_text())
    return {"native": validate_capture(case, native, original, native=True),
            "sdk": validate_capture(case, sdk, implementation, native=False),
            "structuralCustodyPassed": True, "differences": differences(original, implementation),
            "acceptancePointsAwarded": 0}
