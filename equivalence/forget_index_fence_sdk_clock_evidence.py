"""Independent replay of actual SDK V2 filesystem and datetime clock receipts.

No actor, producer, source writer or temporal ranking algorithm is executed.
The caller authenticates the enclosing process and its original event stream.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
import inspect
import math
import os
from pathlib import Path
import stat


ROLES = {
    "io": ("memory_core/atomic_publication.py", "_io"),
    "write-all": ("memory_core/atomic_publication.py", "_write_all"),
    "atomic": ("memory_core/atomic_publication.py", "_commit"),
    "append": ("memory_core/atomic_publication.py", "append_memory_content"),
    "in-place": ("memory_core/atomic_publication.py", "_write_existing_in_place"),
    "dreams": ("memory_core/consolidation/artifacts.py", "write_dreams_file_atomic"),
    "source-read": ("memory_core/index/sqlite_store.py", "read_index_source"),
}
_STAT = {"st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_uid", "st_gid",
         "st_atime_ns", "st_mtime_ns", "st_ctime_ns"}


def validate_sdk_clock_v2(case, observation, process, events, returns, *, recorded_root,
                          approved_sdk_root, fixture_root, recorded_adapter_root=None, approved_adapter_root=None,
                          source_read_workers=()):
    """Return independently authenticated commits/reads for cross-process replay."""
    # Import only here: the main guard invokes this helper during SDK replay.
    from equivalence.forget_index_fence_evidence import (
        ROOT, _digest, _ns, _regular, _same, _sdk_code_owner, require,
    )

    value = case["input"]
    recorded, approved = Path(recorded_root), Path(approved_sdk_root)
    fixture = Path(fixture_root)
    workspace = fixture / "workspace"
    pid, actor = observation["pid"], observation["actor"]
    require(pid == process["pid"] and actor == process["actor"], "SDK clock borrowed another actor")
    require(not observation["sourceClockFailures"] and not observation["datetimeClockFailures"],
            "SDK clock fixture failed; its original outcomes cannot receive credit")
    declarations = observation["clockBindings"]
    writes = declarations["sourceWrites"]
    _same(writes["declaration"], value["clock"]["sourceWriteClock"], "SDK filesystem clock input changed")
    require(writes["syscallsReplaced"] is False and writes["extraFsync"] is False,
            "SDK filesystem clock replaced an original syscall or added durability")
    owners = {}
    for row in writes["owners"]:
        role = row["role"]
        require(role in ROLES and role not in owners, "SDK clock source roles were omitted or duplicated")
        filename, qualname = ROLES[role]
        _sdk_code_owner(row["code"], recorded, approved)
        require(row["code"]["file"] == str(recorded / filename) and row["code"]["qualname"] == qualname,
                "SDK clock substituted another original source owner")
        owners[role] = row["code"]
    require(set(owners) == set(ROLES), "SDK clock omitted an original writer/read owner")

    originals = [row for row in events.values() if row["event"] == "original-call"]

    def code(row, role):
        _sdk_code_owner(row, recorded, approved)
        _same(row, owners[role], "SDK clock source frame differs from its actual original owner")

    def scope(row):
        require(isinstance(row, dict) and set(row) == {"label", "kind", "wallClockNowMs"},
                "SDK source clock lost its exact public-call scope")
        key = row["kind"] + ":" + row["label"]
        tick = value["clock"]["sourceWriteClock"]["ticksByCall"].get(key)
        require(tick is not None and tick["actor"] == actor
                and tick["wallClockNowMs"] == row["wallClockNowMs"], "SDK source clock borrowed another literal tick")
        require(key in observation["publicCalls"], "SDK clock has no actual declared public invocation")
        call = observation["publicCalls"][key]
        require("apiEntry" in call, "SDK clock scope lacks the original public entry")
        return key, tick, call

    def bracket(row, *, role, result=None, check_result=False):
        at = _ns(row["atNs"])
        stack = row.get("sourceStack", [])
        require(isinstance(stack, list) and stack, "SDK source clock lacks its original source frame stack")
        for parent in stack:
            require(parent["sourceRole"] in owners, "SDK clock added an undeclared source role")
            code(parent["code"], parent["sourceRole"])
            require(any(call["code"] == parent["code"] and _ns(call["atNs"]) < at
                        and (call["sequence"] not in returns or at < _ns(returns[call["sequence"]]["atNs"]))
                        for call in originals), "SDK clock stack borrowed a source frame that was not live")
        require(stack[0]["sourceRole"] == role, "SDK clock was detached from its immediate original frame")
        candidates = [call for call in originals if call["code"] == owners[role]
                      and _ns(call["atNs"]) < at
                      and (call["sequence"] not in returns or at < _ns(returns[call["sequence"]]["atNs"]))]
        if "scope" in row:
            key, _, public = scope(row["scope"])
            candidates = [call for call in candidates if call["callLabel"] == row["scope"]["label"]
                          and call["callKind"] == row["scope"]["kind"]]
            require(_ns(public["apiEntry"]["atNs"]) <= at, "SDK clock preceded its actual public entry")
            if "returnSeq" in public:
                require(at < _ns(events[public["returnSeq"]]["atNs"]), "SDK clock followed its public settlement")
        require(len(candidates) == 1, "SDK clock lacks a unique live original source invocation")
        selected = candidates[0]
        if check_result:
            require(selected["sequence"] in returns, "SDK clock invented an original source return")
            require(not any(event["event"] == "original-exception" and event.get("name") == selected["name"]
                            and event["callLabel"] == selected["callLabel"]
                            and _ns(selected["atNs"]) < _ns(event["atNs"])
                            < _ns(returns[selected["sequence"]]["atNs"]) for event in events.values()),
                    "SDK clock relabelled an original raised invocation as a successful return")
            _same(returns[selected["sequence"]]["returned"], result, "SDK clock altered an original syscall return")
        return selected

    def owned(path, *, source=False):
        path = Path(path)
        require(path.is_absolute() and path.is_relative_to(workspace) and path.resolve() == path,
                "SDK source clock path escaped or aliased its owned workspace")
        if source:
            require(path.suffix.lower() in {".md", ".txt"}, "SDK clock timestamped an unrelated private file")
        return path

    def stats(row):
        require(isinstance(row, dict) and _STAT <= set(row), "SDK clock stripped complete filesystem statistics")
        require(all(type(row[key]) is str and str(int(row[key])) == row[key] for key in _STAT),
                "SDK clock changed the original integer-string filesystem stat carrier")
        parsed = {key: int(row[key]) for key in _STAT}
        require(stat.S_ISREG(parsed["st_mode"]) and parsed["st_nlink"] == 1 and parsed["st_size"] >= 0,
                "SDK clock did not own one regular inode")
        return parsed

    def inspection(row):
        require(set(row) == {"stat", "statAfterRead", "bytes", "sha256", "identity", "size", "inspectionRead"},
                "SDK clock dropped a complete physical inspection")
        payload = bytes.fromhex(row["bytes"])
        require(payload.hex() == row["bytes"] and hashlib.sha256(payload).hexdigest() == row["sha256"]
                and type(row["size"]) is int and row["size"] == len(payload), "SDK clock source bytes were replaced")
        first, last = stats(row["stat"]), stats(row["statAfterRead"])
        _same(first, last, "SDK clock observation changed its inspected source inode")
        require(first["st_size"] == len(payload) and row["identity"] == {
            "device": first["st_dev"], "inode": first["st_ino"]}, "SDK clock source identity was detached from stat")
        read = row["inspectionRead"]
        require(type(read["descriptor"]) is int and read["descriptor"] >= 0
                and read["flags"] == os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME,
                "SDK clock verification changed source atime or followed another inode")
        _same(stats(read["openedStat"]), first, "SDK clock verifier opened another physical inode")
        require(isinstance(read["readReturns"], list) and read["readReturns"] and read["readReturns"][-1] == ""
                and all(part != "" for part in read["readReturns"][:-1])
                and b"".join(bytes.fromhex(part) for part in read["readReturns"]) == payload,
                "SDK clock source inspection omitted actual read returns")
        return first, payload

    collections = (observation["sourceClockReceipts"], observation["sourceClockOriginalIO"], observation["sourceClockReads"])
    combined = sorted((row for rows in collections for row in rows), key=lambda row: row["sequence"])
    for number, row in enumerate(combined, 1):
        require(type(row["sequence"]) is int and row["sequence"] == number and row["pid"] == pid
                and row["actor"] == actor, "SDK clock receipts were omitted, duplicated or reassigned")
        require(_ns(process["startedAtNs"]) < _ns(row["atNs"]) < _ns(process["reapedAtNs"]),
                "SDK source clock escaped its actual process lifetime")
    require(all(_ns(a["atNs"]) <= _ns(b["atNs"]) for a, b in zip(combined, combined[1:])),
            "SDK source-clock chronology was reversed")
    io_by_sequence = {row["sequence"]: row for row in observation["sourceClockOriginalIO"]}
    io_frames = {}
    for row in observation["sourceClockOriginalIO"]:
        kind = row["event"]
        if kind == "original-source-io-return":
            call = bracket(row, role="io", result=row["returned"], check_result=True)
            arguments = call["arguments"]
            require(arguments["function"]["module"] in {"posix", "os"}
                    and arguments["function"]["qualname"] == row["syscall"], "SDK source IO borrowed another OS primitive")
            actual = arguments["args"]
            for index, item in enumerate(row["arguments"]):
                # The original observer retains an ignored memoryview object;
                # the source-clock recorder separately retains its actual bytes.
                if isinstance(item, dict) and set(item) == {"bytesHex", "bytes"}:
                    data = bytes.fromhex(item["bytesHex"])
                    require(len(data) == item["bytes"], "SDK source write lost its actual buffer bytes")
                    require(isinstance(actual[index], dict) and actual[index].get("className") == "memoryview"
                            or actual[index] == item, "SDK source IO replaced another argument with invented bytes")
                else:
                    _same(actual[index], item, "SDK source IO arguments differ from the original invocation")
            require(len(actual) == len(row["arguments"]), "SDK source IO arguments were truncated")
            io_frames[row["sequence"]] = call
        elif kind == "original-full-write-return":
            call = bracket(row, role="write-all", result=row["returned"], check_result=True)
            require(call["arguments"]["descriptor"] == row["descriptor"], "SDK full-write borrowed another original descriptor")
            io_frames[row["sequence"]] = call
        elif kind == "original-dreams-textio-settlement":
            bracket(row, role="dreams")
            require(row["settlement"] in {"returned", "raised"} and row["method"] in {"write", "__exit__"},
                    "SDK DREAMS writer fabricated a C return value")
        elif kind == "original-source-io-exception":
            call = bracket(row, role="io")
            require(any(event["event"] == "original-exception" and event.get("name") == "_io"
                        and event["callLabel"] == row["scope"]["label"]
                        and _ns(call["atNs"]) < _ns(event["atNs"])
                        and event["error"]["message"] == row["error"]["message"] for event in events.values()),
                    "SDK clock invented an original source-IO exception")
        else:
            raise ValueError("SDK clock accepted an undeclared original IO receipt")

    commits, claimed_commits, versions = [], set(), {}
    for row in observation["sourceClockReceipts"]:
        require(row["event"] == "source-write-clock-v2" and row["protocol"] == "owned-source-write-clock-v2",
                "SDK source-clock receipt used another protocol")
        key = row["callKey"]
        tick = value["clock"]["sourceWriteClock"]["ticksByCall"].get(key)
        _same(row["tick"], tick, "SDK source-clock timestamp was derived from an observed result")
        require(tick is not None and tick["actor"] == actor, "SDK source-clock tick belongs to another actor")
        source = owned(row["absolutePath"], source=True)
        require(row["ownedRoot"] == str(workspace) and row["path"] == source.relative_to(workspace).as_posix(),
                "SDK source-clock destination changed its original owned path")
        stage = owned(row["stagePath"])
        before, payload = inspection(row["before"])
        after, after_bytes = inspection(row["after"])
        require(payload == after_bytes and all(before[k] == after[k] for k in
                ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_uid", "st_gid")),
                "SDK clock changed source bytes or inode ownership")
        _same(stats(row["statImmediatelyAfterUtime"]), after, "SDK utime result lost its actual immediate stat")
        require(after["st_mtime_ns"] == tick["mtimeMs"] * 1_000_000
                and after["st_atime_ns"] == tick["atimeMs"] * 1_000_000,
                "SDK source clock did not apply both declared actual timestamps")
        utime_at, utime_end = _ns(row["utimeEnterAtNs"]), _ns(row["utimeReturnAtNs"])
        require(_ns(row["atNs"]) <= utime_at < utime_end and row["utimeReturn"] is None,
                "SDK source clock lacks the actual successful OS utime return")
        _same(row["utimeArguments"]["ns"], [tick["atimeMs"] * 1_000_000, tick["mtimeMs"] * 1_000_000],
              "SDK source clock changed its actual OS timestamp arguments")
        mode = row["mode"]
        require(mode in {"atomic-staged", "in-place-owned-fd", "atomic-closed-stage"}, "SDK source clock mode is unsupported")
        frame = bracket(row, role="dreams" if mode == "atomic-closed-stage" else "io")
        require(frame["callKind"] + ":" + frame["callLabel"] == key,
                "SDK source-clock tick borrowed another live public call")
        if mode == "atomic-closed-stage":
            require(row["descriptor"] is None and row["utimeArguments"]["target"] == str(stage)
                    and row["originalFsyncPresent"] is False and row["originalFsync"] is None
                    and row["originalOpen"] is None and row["originalFullWrite"] is None
                    and row["originalWrites"] == [], "SDK DREAMS clock invented an original fsync or descriptor writer")
            require(frame["arguments"]["path"] == str(source)
                    and frame["arguments"]["content"].encode("utf8") == payload,
                    "SDK DREAMS stage differs from its original full content argument")
            require(row["originalTextIO"] and all(part in observation["sourceClockOriginalIO"] for part in row["originalTextIO"])
                    and any(part["method"] == "write" and part["settlement"] == "returned" for part in row["originalTextIO"]),
                    "SDK DREAMS stage has no original successful text writer")
        else:
            fd = row["descriptor"]
            require(type(fd) is int and fd >= 0 and row["utimeArguments"]["target"] == fd,
                    "SDK source clock timestamped another original descriptor")
            for part in (row["originalOpen"], *row["originalWrites"], row["originalFullWrite"], row["originalFsync"]):
                require(part is not None and part["sequence"] in io_by_sequence, "SDK source clock omitted an actual writer receipt")
                _same(part, io_by_sequence[part["sequence"]], "SDK source clock fabricated an original writer receipt")
                require(_ns(part["atNs"]) < utime_at, "SDK clock preceded its original complete writer")
                actual = io_frames[part["sequence"]]
                require(actual["callKind"] + ":" + actual["callLabel"] == key,
                        "SDK source clock borrowed writer receipts from another public call")
            opened = row["originalOpen"]
            require(opened["syscall"] == "open" and opened["returned"] == fd and opened["arguments"][0] == str(stage),
                    "SDK source clock lost its genuine staged/open inode association")
            require(row["originalFsyncPresent"] is True and row["originalFsync"]["syscall"] == "fsync"
                    and row["originalFsync"]["arguments"] == [fd] and row["originalFsync"]["returned"] is None,
                    "SDK source clock fabricated original writer durability")
            require(row["originalWrites"] and all(part["syscall"] in {"write", "pwrite"} and part["arguments"][0] == fd
                    and type(part["returned"]) is int and part["returned"] > 0 for part in row["originalWrites"]),
                    "SDK source clock lost actual source write counts or descriptor")
            require(_ns(opened["atNs"]) < min(_ns(part["atNs"]) for part in row["originalWrites"])
                    and max(_ns(part["atNs"]) for part in row["originalWrites"]) < _ns(row["originalFullWrite"]["atNs"])
                    < _ns(row["originalFsync"]["atNs"]),
                    "SDK source clock reordered original open, full write, or actual fsync")
            full = io_frames[row["originalFullWrite"]["sequence"]]
            require(full["arguments"]["descriptor"] == fd, "SDK complete write borrowed another fd")
            full_payload = full["arguments"]["content"]
            chunks = []
            for part in row["originalWrites"]:
                buffer = part["arguments"][1]
                require(isinstance(buffer, dict) and set(buffer) == {"bytesHex", "bytes"},
                        "SDK original source write discarded its actual buffer bytes")
                raw_buffer = bytes.fromhex(buffer["bytesHex"])
                require(part["returned"] <= len(raw_buffer) == buffer["bytes"],
                        "SDK original source write count exceeded its original buffer")
                chunks.append(raw_buffer[:part["returned"]])
            require(b"".join(chunks).hex() == full_payload["bytesHex"],
                    "SDK original complete write differs from its actual successful syscall buffers")
            if mode == "atomic-staged":
                require(row["originalArguments"] == [str(stage), str(source)] and stage != source
                        and frame["arguments"]["function"]["qualname"] == "replace",
                        "SDK atomic source clock lost its genuine original rename")
                require(full_payload["bytesHex"] == payload.hex() and full_payload["bytes"] == len(payload),
                        "SDK atomic stage differs from its original complete write argument")
            else:
                require(stage == source and frame["arguments"]["function"]["qualname"] == "close",
                        "SDK in-place source clock does not precede original descriptor close")
        commit = row.get("originalCommit")
        require(commit is not None, "SDK source-clock control lost its actual original commit settlement")
        if row["committed"] is not True:
            require(commit["witness"] in {"original-os-replace-raised", "original-os-replace-c-exception"},
                    "SDK failed source rename lacks an original exception receipt")
            continue
        committed, final_bytes = inspection(row["committedState"])
        require(final_bytes == payload and all(committed[k] == after[k] for k in
                ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_uid", "st_gid", "st_mtime_ns")),
                "SDK original publication lost the actual clocked inode or bytes")
        commit_at = _ns(commit["atNs"])
        require(utime_end < commit_at and commit["returned"] is None,
                "SDK clock was applied after original publication or replaced its return")
        if mode != "atomic-closed-stage":
            require(commit["witness"] == ("original-os-replace-return" if mode == "atomic-staged"
                    else "original-owned-fd-close-return"), "SDK source-clock commit witness was relabelled")
            candidates = [part for part in observation["sourceClockOriginalIO"]
                          if part["event"] == "original-source-io-return"
                          and part["sequence"] in io_frames
                          and io_frames[part["sequence"]]["sequence"] == frame["sequence"]]
            require(len(candidates) == 1, "SDK committed source has no unique actual original syscall return")
            part = candidates[0]
            require(part["syscall"] == ("replace" if mode == "atomic-staged" else "close"),
                    "SDK source commit relabelled an unrelated original syscall")
            require(_ns(part["atNs"]) <= commit_at < _ns(returns[frame["sequence"]]["atNs"]),
                    "SDK source commit escaped its original returning syscall frame")
            _same(part["returned"], commit["returned"], "SDK source commit changed its original return")
            claimed_commits.add(part["sequence"])
        else:
            require(commit["witness"] == "original-dreams-atomic-writer-return"
                    and frame["sequence"] in returns and commit_at < _ns(returns[frame["sequence"]]["atNs"]),
                    "SDK DREAMS commit lost its original writer return")
        identity = key, str(source)
        sha = hashlib.sha256(payload).hexdigest()
        require(identity not in versions or versions[identity] == sha,
                "SDK source clock hid two distinct committed versions under one input tick")
        versions[identity] = sha
        commits.append({"path": str(source), "sha256": sha, "bytes": payload.hex(),
                        "mtimeNs": committed["st_mtime_ns"], "atNs": commit["atNs"], "callKey": key, "pid": pid})

    for row in observation["sourceClockOriginalIO"]:
        if row["event"] != "original-source-io-return":
            continue
        if row["syscall"] == "replace" and Path(row["arguments"][1]).suffix.lower() in {".md", ".txt"}:
            require(row["sequence"] in claimed_commits, "SDK source publication omitted its original clock receipt")
        if row["syscall"] == "close":
            roles = {part["sourceRole"] for part in row["sourceStack"]}
            if roles & {"append", "in-place"}:
                require(row["sequence"] in claimed_commits, "SDK in-place source completion omitted its clock receipt")

    # The separate source-clock channel cannot erase successful original IO
    # already present in the independently authenticated stock source stream.
    represented = {call["sequence"] for call in io_frames.values()}
    writer_codes = [owners[role] for role in ("atomic", "append", "in-place", "dreams")]
    syscalls = {"open", "write", "pwrite", "fsync", "ftruncate", "close", "replace", "utime"}
    for call in originals:
        if call["code"] != owners["io"] or call["sequence"] not in returns:
            continue
        args = call["arguments"]
        syscall = args["function"]["qualname"]
        positional = args["args"]
        raised = any(event["event"] == "original-exception" and event.get("name") == "_io"
                     and event["callLabel"] == call["callLabel"]
                     and _ns(call["atNs"]) < _ns(event["atNs"])
                     < _ns(returns[call["sequence"]]["atNs"]) for event in events.values())
        if syscall in syscalls and not raised:
            parents = [parent for parent in originals if parent["code"] in writer_codes
                       and parent["callLabel"] == call["callLabel"] and parent["callKind"] == call["callKind"]
                       and _ns(parent["atNs"]) < _ns(call["atNs"])
                       and (parent["sequence"] not in returns or _ns(call["atNs"]) < _ns(returns[parent["sequence"]]["atNs"]))]
            if any(isinstance(parent["arguments"].get("path"), str)
                   and Path(parent["arguments"]["path"]).is_relative_to(workspace)
                   and Path(parent["arguments"]["path"]).suffix.lower() in {".md", ".txt"} for parent in parents):
                require(call["sequence"] in represented,
                        "SDK source-clock channel omitted an actual selected original source-IO return")
        if syscall == "replace" and len(positional) == 2:
            target = Path(positional[1])
            if target.is_relative_to(workspace) and target.suffix.lower() in {".md", ".txt"}:
                require(call["sequence"] in represented,
                        "SDK source-clock channel omitted a successful original source publication")
        elif syscall == "close" and positional:
            fd = positional[0]
            previous = [opened for opened in originals if opened["code"] == owners["io"]
                        and opened["arguments"]["function"]["qualname"] == "open"
                        and opened["sequence"] in returns and returns[opened["sequence"]]["returned"] == fd
                        and _ns(returns[opened["sequence"]]["atNs"]) < _ns(call["atNs"])]
            if previous:
                opened = max(previous, key=lambda item: _ns(item["atNs"]))["arguments"]["args"]
                target = Path(opened[0])
                if (opened[1] & os.O_ACCMODE != os.O_RDONLY and target.is_relative_to(workspace)
                        and target.suffix.lower() in {".md", ".txt"}):
                    require(call["sequence"] in represented,
                            "SDK source-clock channel omitted an original writable-source completion")

    reads, read_frames = [], set()
    for row in observation["sourceClockReads"]:
        require(row["event"] == "original-index-source-read-return", "SDK source read receipt used another event")
        code(row["sourceCode"], "source-read")
        call, key = None, None
        if row["scope"] is not None:
            key, _, public = scope(row["scope"])
            candidates = [call for call in originals if call["code"] == owners["source-read"]
                          and call["callLabel"] == row["scope"]["label"] and call["sequence"] in returns
                          and _ns(call["atNs"]) < _ns(row["atNs"]) < _ns(returns[call["sequence"]]["atNs"])]
            require(len(candidates) == 1, "SDK source read lacks a unique original invocation")
            call = candidates[0]
            require(call["sequence"] not in read_frames, "SDK source read duplicated an original invocation")
            read_frames.add(call["sequence"])
            _same(returns[call["sequence"]]["returned"], row["returned"], "SDK source read altered its original complete return")
            _same(call["arguments"]["file"], row["arguments"]["file"], "SDK source read borrowed another original file")
            if value["kind"] in {"forget-index-fence-v3", "forget-index-fence-v4"} and "returnSeq" in public and _ns(row["atNs"]) >= _ns(events[public["returnSeq"]]["atNs"]):
                workers = [worker for worker in source_read_workers if worker["callLabel"] == call["callLabel"]
                           and worker["callKind"] == call["callKind"] == "search"
                           and worker["threadId"] == call["threadId"] and worker["sequence"] in returns
                           and _ns(worker["atNs"]) < _ns(call["atNs"])
                           < _ns(returns[call["sequence"]]["atNs"]) < _ns(returns[worker["sequence"]]["atNs"])]
                require(len(workers) == 1, "A late SDK source read lost its authenticated original queued-worker frame")
        source = owned(row["arguments"]["file"]["abs_path"], source=True)
        returned = row["returned"]
        require(returned["source"] == "memory" and returned["path"] == source.relative_to(workspace).as_posix(),
                "SDK source read relabelled its actual file")
        raw = row["arguments"]["raw"]
        payload = bytes.fromhex(raw["bytesHex"])
        require(raw["bytes"] == len(payload) == returned["size"], "SDK source read lost its original byte count")
        _same(row["arguments"]["text"], returned["text"], "SDK source read changed original decoded content")
        mtime = returned["mtime"]
        require(type(mtime) in (int, float) and math.isfinite(mtime) and int(mtime) == mtime,
                "SDK V2 original source read lacks an exact integral millisecond filesystem clock")
        if call is None:
            # The existing managed publisher can read on an unlabelled worker.
            # Its actual return profiler retains the original function/locals,
            # but supplies no public API entry, clock tick, or thread lineage.
            # Do not invent those missing facts or extend write clock scopes.
            initial = value["initialFiles"].get(source.relative_to(workspace).as_posix())
            initial_bytes = initial.encode("utf8").hex() if isinstance(initial, str) else None
            known_initial = initial_bytes == payload.hex() and mtime == value["clock"]["initialSourceMtimeMs"]
            known_commit = any(item["path"] == str(source) and item["bytes"] == payload.hex()
                               and item["mtimeNs"] == int(mtime) * 1_000_000 and _ns(item["atNs"]) < _ns(row["atNs"])
                               for item in commits)
            require(known_initial or known_commit,
                    "An unscoped original SDK read borrowed bytes/mtime outside its verified initial or committed source")
            require(payload.decode("utf8", "replace") == returned["text"]
                    and hashlib.sha256(returned["text"].encode("utf8")).hexdigest() == returned["hash"]
                    and row["arguments"]["file"]["source"] == "memory"
                    and row["arguments"]["info"][6] == len(payload),
                    "An unscoped SDK read lost its actual original local file bytes/stat/text/return relation")
        reads.append({"path": str(source), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": payload.hex(),
                      "mtimeNs": int(mtime) * 1_000_000, "mtimeMs": mtime, "enteredAtNs": call["atNs"] if call else None,
                      "finishedAtNs": returns[call["sequence"]]["atNs"] if call else row["atNs"], "atNs": row["atNs"],
                      "callKey": key, "pid": pid})
    for call in originals:
        if call["code"] == owners["source-read"] and call["sequence"] in returns:
            returned = returns[call["sequence"]]["returned"]
            if (isinstance(returned, dict) and returned.get("source") == "memory"
                    and Path(returned["path"]).suffix.lower() in {".md", ".txt"}):
                require(call["sequence"] in read_frames,
                        "SDK clock channel omitted an actual completed original source read")

    _validate_datetime(value, observation, originals, returns, recorded, approved, approved_adapter_root or ROOT,
                       recorded_adapter=recorded_adapter_root,
                       scope=scope, require=require, same=_same, code_owner=_sdk_code_owner,
                       digest=_digest, regular=_regular, ns=_ns)
    return {"commits": commits, "reads": reads}


def _validate_datetime(value, observation, originals, returns, recorded, approved, root, *,
                       scope, require, same, code_owner, digest, regular, ns, recorded_adapter=None):
    binding = observation["clockBindings"]["datetime"]
    same(binding["declaration"], value["clock"]["sdkDatetimeClock"], "SDK datetime clock declaration changed")
    require(binding["module"] == "memory_core.index.temporal_decay" and binding["binding"] == "datetime"
            and binding["bindingIsExactProxy"] is True
            and binding["originalClassObjectId"] != binding["proxyObjectId"], "SDK clock replaced another datetime namespace")
    source = binding["sourceCode"]
    code_owner(source, recorded, approved)
    require(source["file"] == str(recorded / "memory_core/index/temporal_decay.py")
            and source["qualname"] == "apply_temporal_decay_to_hybrid_results", "SDK datetime clock lost its original temporal owner")
    original = binding["originalClass"]
    require(original["module"] == "datetime" and original["name"] == "datetime", "SDK clock fabricated its original datetime class")
    expected = [("datetime", "datetime", inspect.getsourcefile(datetime)),
                ("datetime", "date", inspect.getsourcefile(date)), ("builtins", "object", None)]
    require(len(original["mro"]) == len(expected), "SDK original datetime MRO changed")
    for row, (module, name, filename) in zip(original["mro"], expected, strict=True):
        require(row["module"] == module and row["name"] == name, "SDK clock original datetime ancestry changed")
        require(row["sourceFile"] == filename and row["sourceSha256"] == (digest(regular(filename)) if filename else None),
                "SDK clock original datetime source is not the independently selected standard library")
    proxy = binding["proxyClass"]
    require(proxy["module"] == "equivalence.forget_index_fence_sdk_clock" and proxy["name"] == "DatetimeClockProxy"
            and len(proxy["mro"]) == 2, "SDK datetime clock used another fixture proxy")
    cls = proxy["mro"][0]
    require(cls["module"] == proxy["module"] and cls["name"] == proxy["name"]
            and cls["sourceFile"] == str(Path(recorded_adapter or recorded) / "equivalence/forget_index_fence_sdk_clock.py")
            and cls["sourceSha256"] == digest(regular(root / "equivalence/forget_index_fence_sdk_clock.py")),
            "SDK datetime proxy differs from its independently selected fixture source")
    temporal = [call for call in originals if call["code"] == source]
    assigned = set()
    for row in observation["datetimeClockCalls"]:
        code_owner(row["sourceCode"], recorded, approved)
        same(row["sourceCode"], source, "SDK datetime receipt borrowed another temporal source")
        key, tick, _ = scope(row["scope"])
        require(row["pid"] == observation["pid"] and row["actor"] == observation["actor"]
                and row["wallClockNowMs"] == tick["wallClockNowMs"]
                and row["timezone"] == "datetime.timezone.utc"
                and row["returnedClass"] == {"module": "datetime", "name": "datetime"}
                and row["returnedISO"] == datetime.fromtimestamp(row["wallClockNowMs"] / 1000, UTC).isoformat(),
                "SDK datetime fallback lost its genuine declared UTC wall instant or original type")
        matches = [call for call in temporal if call["callLabel"] == key.split(":", 1)[1]
                   and call["sequence"] in returns and ns(call["atNs"]) < ns(row["atNs"])
                   < ns(returns[call["sequence"]]["atNs"])]
        require(len(matches) == 1 and matches[0]["sequence"] not in assigned
                and matches[0]["arguments"]["now_ms"] is None,
                "SDK datetime fallback was fabricated, duplicated or used despite explicit now_ms")
        assigned.add(matches[0]["sequence"])
    for call in temporal:
        config = call["arguments"].get("temporal_decay")
        if (call["sequence"] in returns and call["arguments"].get("now_ms") is None
                and isinstance(config, dict) and config.get("enabled") is True):
            require(call["sequence"] in assigned, "SDK omitted the actual enabled temporal datetime fallback")
