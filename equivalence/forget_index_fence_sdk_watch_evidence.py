"""Independent V5 SDK watcher delivery and original publication custody.

Only explicitly frozen inputs and independently selected SDK/adapter sources
are authorities. Readiness, delivered versions and terminal index work are
separate facts; empty queues are never delivery evidence.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import hashlib
import inspect
from pathlib import Path


_WATCH_SCOPE = {"kind", "label", "origin", "watcherObjectId", "storeObjectId", "detectorGeneration"}


def _closed_watch_case(case):
    if isinstance(case, dict) and case.get("operation") == "forget-index-fence-v6-runtime":
        from equivalence.forget_index_fence_v6 import validate_case
    else:
        from equivalence.forget_index_fence_v5 import validate_case
    return validate_case(case)


def validate_sdk_watch_v5(case, observation, process, events, returns, *, recorded_root,
                          approved_sdk_root, recorded_adapter_root, approved_adapter_root):
    """Return actual readiness/effect receipts, worker frames and captured targets."""
    from equivalence.forget_index_fence_evidence import _digest, _ns, _regular, _same, _sdk_code_owner, require

    _closed_watch_case(case)
    value = case["input"]
    require(value["observationPolicy"]["watchEffects"]["protocol"] == "original-watch-effects-v5",
            "SDK watcher controls used another frozen protocol")
    recorded, approved = Path(recorded_root), Path(approved_sdk_root)
    adapter, trusted_adapter = Path(recorded_adapter_root), Path(approved_adapter_root)
    require(adapter.is_absolute() and trusted_adapter.is_absolute(), "SDK watcher source roots were not independently selected")
    _regular(trusted_adapter / "equivalence/forget_index_fence_sdk.py")
    pid, actor = observation["pid"], observation["actor"]
    require(pid == process["pid"] and actor == process["actor"] and not observation.get("observerFailures"),
            "SDK watcher observation failed or borrowed another original process")
    calls = [row for row in events.values() if row["event"] == "original-call"]
    owners = {row["storeObjectId"]: row for row in observation["ownerBindings"]}

    def ident(item):
        require(isinstance(item, str) and item.isdecimal() and int(item) > 0, "SDK watcher lost an actual object identity")
        return item

    def source(code, filename, qualname):
        _sdk_code_owner(code, recorded, approved)
        require(code["file"] == str(recorded / filename) and code["qualname"] == qualname,
                "SDK watcher receipt substituted another original callable")

    def original(call):
        require(call["sequence"] in returns, "SDK watcher original invocation has no actual return")
        result = returns[call["sequence"]]
        require(call["threadId"] == result["threadId"] and _ns(call["atNs"]) < _ns(result["atNs"]),
                "SDK watcher original return lost its live frame or thread")
        return result

    def members(name, receiver=None, *, begin=None, end=None):
        return [row for row in calls if row["name"] == name
                and (receiver is None or row["receiverObjectId"] == receiver or row.get("selfObjectId") == receiver)
                and (begin is None or begin < _ns(row["atNs"]))
                and (end is None or row["sequence"] in returns and _ns(returns[row["sequence"]]["atNs"]) < end)]

    def span(row, prefix):
        require(row["pid"] == pid and row["actor"] == actor, "SDK watch control borrowed another actor")
        entered, returned = events[row["enterSeq"]], events[row["returnSeq"]]
        require(entered["event"] == prefix + "-control-enter" and returned["event"] == prefix + "-control-return"
                and entered["label"] == returned["label"] == row["label"]
                and entered["threadId"] == returned["threadId"]
                and entered["sequence"] < returned["sequence"], "SDK watch control lost its actual command lifetime")
        return _ns(entered["atNs"]), _ns(returned["atNs"])

    def watch_scope(scope):
        require(isinstance(scope, dict) and set(scope) == _WATCH_SCOPE and scope["kind"] == "watch"
                and scope["origin"] == "original-memory-watcher", "SDK watcher work was relabelled as a public call or clock")
        wid, sid = ident(scope["watcherObjectId"]), ident(scope["storeObjectId"])
        generation = scope["detectorGeneration"]
        require(type(generation) is int and generation >= 0 and sid in owners
                and scope["label"] == f"watch:{wid}:{generation}" and wid in watchers and watchers[wid] == sid,
                "SDK watcher work changed its genuine detector generation or owning store")
        return wid, sid, generation

    def version(target):
        require(isinstance(target, dict) and set(target) == {"path", "exists", "version"}
                and type(target["exists"]) is bool, "SDK watcher retained version was truncated or coerced")
        path = Path(target["path"])
        workspace = Path(process["request"]["directory"]) / "workspace"
        require(path.is_absolute() and path.is_relative_to(workspace) and path.resolve() == path,
                "SDK watcher retained target escaped its owned physical workspace")
        if target["exists"]:
            row = target["version"]
            require(isinstance(row, dict) and set(row) == {"device", "inode", "size", "mtimeNs", "ctimeNs"}
                    and type(row["size"]) is int and row["size"] >= 0,
                    "SDK watcher discarded complete physical source version")
            for key in ("device", "inode", "mtimeNs", "ctimeNs"):
                require(type(row[key]) is str and str(int(row[key])) == row[key],
                        "SDK watcher source version changed its original decimal-string carrier")
        else:
            require(target["version"] is None, "SDK watcher absence acquired invented file metadata")
        return path

    # Actual property returns bind a detector to its original managed store.
    watchers = {}
    for call in members("ManagedSQLiteMemoryStore.memory_watcher"):
        source(call["code"], "memory_core/host/managed_index.py", "ManagedSQLiteMemoryStore.memory_watcher")
        returned = original(call)
        if returned["returned"] is None:
            continue
        wid = returned.get("returnedOwnerObjectId", returned["returned"].get("objectId"))
        sid = call["receiverObjectId"]
        require(sid in owners, "SDK detector was read from an unknown managed owner")
        ident(wid)
        require(wid not in watchers or watchers[wid] == sid, "SDK detector changed its actual owner")
        watchers[wid] = sid

    readiness = {}
    for row in observation["watchReadyWaits"]:
        begin, end = span(row, "watch-ready")
        require(row["label"] not in readiness and "error" not in row, "SDK watch readiness failed or duplicated")
        sid, wid = row["ownerObjectId"], row["watcherObjectId"]
        if row["outcome"]["status"] == "absent":
            if sid is None:
                require(not owners and wid is None and row["status"] is None and row["resources"] is None,
                        "SDK watcher absence hid an already acquired owner")
            elif row["ownerClosed"] is True:
                require(sid in owners and members("ManagedSQLiteMemoryStore.close", sid, end=begin),
                        "SDK watcher absence has no actual original owner close")
            else:
                absent = [call for call in members("ManagedSQLiteMemoryStore.memory_watcher", sid, begin=begin, end=end)
                          if original(call)["returned"] is None]
                require(len(absent) == 1, "SDK watcher absence was inferred from an empty queue or missing receipt")
        else:
            require(row["outcome"] == {"status": "ready"} and row["ownerClosed"] is False
                    and wid in watchers and watchers[wid] == sid, "SDK readiness has no original detector/owner association")
            status, snapshot, resources = row["status"], row["snapshot"], row["resources"]
            for name in ("status", "snapshot"):
                candidates = members("MemoryFileWatcher." + name, wid, begin=begin, end=end)
                require(len(candidates) == 1, "SDK readiness has no unique original status/snapshot read")
                _same(original(candidates[0])["returned"], row[name], "SDK readiness changed an original detector return")
            for role, qualname, filename in (("memoryWatcherProperty", "ManagedSQLiteMemoryStore.memory_watcher", "memory_core/host/managed_index.py"),
                    ("start", "MemoryFileWatcher.start", "memory_core/host/memory_watcher.py"),
                    ("status", "MemoryFileWatcher.status", "memory_core/host/memory_watcher.py"),
                    ("snapshot", "MemoryFileWatcher.snapshot", "memory_core/host/memory_watcher.py")):
                binding = row["sourceRoles"][role]
                require(binding["registered"] is True and binding["qualname"] == qualname
                        and binding["module"] == filename.removesuffix(".py").replace("/", "."),
                        "SDK readiness lost an original source role")
                source(binding["code"], filename, qualname)
            starts = members("MemoryFileWatcher.start", wid, end=end)
            require(starts and all(original(call)["returned"] is None for call in starts),
                    "SDK readiness has no genuine original detector startup")
            require(status["started"] is True and status["closed"] is False and status["alive"] is True
                    and snapshot["started"] is True and snapshot["closed"] is False and snapshot["alive"] is True
                    and resources["threadAlive"] is True and resources["threadId"] == status["threadId"],
                    "SDK readiness replaced actual live detector resources with flags")
            ident(resources["threadObjectId"])
            require(type(resources["threadId"]) is int and isinstance(resources["shutdownPipe"], list)
                    and len(resources["shutdownPipe"]) == 2, "SDK watcher lost its original thread or shutdown pipe")
            if status["backend"] == "inotify":
                bid = ident(resources["backendObjectId"])
                require(type(resources["fd"]) is int and resources["fd"] >= 0 and resources["paths"],
                        "SDK inotify readiness has no installed native subscription")
                backend_starts = members("_Inotify.__init__", bid, end=end)
                reconciliations = members("_Inotify.reconcile", bid, end=end)
                require(backend_starts and reconciliations, "SDK inotify resources lack actual source-owned installation")
                for call in (*backend_starts, *reconciliations):
                    source(call["code"], "memory_core/host/memory_watcher.py", call["name"])
                paths = {item["path"]: item["watchDescriptor"] for item in resources["paths"]}
                require(len(paths) == len(resources["paths"]) and {item["path"]: item["watchDescriptor"] for item in resources["descriptors"]} == paths,
                        "SDK inotify subscription identities were dropped or reassigned")
                require(all(type(item["watchDescriptor"]) is int and item["watchDescriptor"] >= 0
                            and isinstance(item["identity"], list) and len(item["identity"]) == 2
                            and all(type(part) is int and part >= 0 for part in item["identity"])
                            for item in resources["paths"]), "SDK native subscription descriptor/directory identity was coerced")
            else:
                require(status["backend"] == "stat" and resources["backendObjectId"] is None and resources["fd"] is None,
                        "SDK detector invented a different event backend")
        readiness[row["label"]] = row

    all_tasks = observation["queuedOriginalTasks"]
    _same(observation["queuedSearchTasks"], [task for task in all_tasks if task["scope"]["kind"] == "search"],
          "SDK search work was lost or relabelled as a watcher")
    _same(observation["queuedWatchTasks"], [task for task in all_tasks if task["scope"]["kind"] == "watch"],
          "SDK watcher work was hidden in another queue")
    require(all(task["scope"]["kind"] in {"search", "watch"} for task in all_tasks), "SDK original task queue added an unknown scope")
    tasks, workers, scopes = {}, {}, {}
    stdlib = {"ThreadPoolExecutor.submit": ThreadPoolExecutor.submit, "Future.result": Future.result}
    for task in all_tasks:
        fid = ident(task["futureObjectId"])
        require(fid not in tasks, "SDK watcher queue duplicated an actual submitted Future")
        submit = events[task["submitSequence"]]
        require(submit["name"] == "ThreadPoolExecutor.submit" and submit["event"] == "original-call"
                and submit["selfObjectId"] == task["executorObjectId"], "SDK watch publication has no actual admission")
        code = stdlib["ThreadPoolExecutor.submit"].__code__
        require(submit["code"]["file"] == inspect.getsourcefile(ThreadPoolExecutor.submit)
                and submit["code"]["sourceSha256"] == _digest(_regular(Path(inspect.getsourcefile(ThreadPoolExecutor.submit))))
                and submit["code"]["bytecodeSha256"] == hashlib.sha256(code.co_code).hexdigest(),
                "SDK watch publication changed the genuine executor source")
        returned = original(submit)
        require(returned["returned"]["objectId"] == fid and returned["returned"]["className"] == "Future"
                and task["future"]["objectId"] == fid and task["future"]["className"] == "Future",
                "SDK watch publication replaced its original submitted Future")
        tasks[fid] = task
        if task["scope"]["kind"] != "watch":
            continue
        wid, sid, generation = watch_scope(task["scope"])
        require(task["kind"] == "memory-publication" and task["storeObjectId"] == sid
                and submit["callKind"] == "watch" and submit["scope"] == task["scope"],
                "SDK watch publication borrowed a search or manufactured a public tick")
        source(task["functionCode"], "memory_core/host/managed_index.py", "ManagedSQLiteMemoryStore._run_memory_publication")
        job, token = submit["arguments"]["args"]
        require(job["reason"] == "watch" and job["state"] == "queued", "SDK watcher changed its admitted original job")
        matching = [call for call in calls if call["code"] == task["functionCode"]
                    and call["receiverObjectId"] == sid and call["scope"] == task["scope"]
                    and call["arguments"]["job"] == job and call["arguments"]["token"] == token
                    and _ns(submit["atNs"]) < _ns(call["atNs"])]
        require(len(matching) == 1, "SDK watcher task has no actual source-owned worker")
        worker = matching[0]
        original(worker)
        require(task["job"]["threadId"] == worker["threadId"] and worker["threadId"] != submit["threadId"],
                "SDK watch publication substituted another worker thread")
        live = [call["sequence"] for call in calls if call["threadId"] == submit["threadId"]
                and _ns(call["atNs"]) < _ns(submit["atNs"])
                and (call["sequence"] not in returns or _ns(submit["atNs"]) < _ns(returns[call["sequence"]]["atNs"]))]
        _same(task["parentCallSequences"], live, "SDK watch worker dropped actual causal parent frames")
        for sequence in live:
            parent_scope = events[sequence]["scope"]
            parent_wid, parent_sid, _ = watch_scope(parent_scope)
            require(parent_wid == wid and parent_sid == sid,
                    "SDK watch admission borrowed a control call or foreign watcher ancestry")
        require(any(events[sequence]["name"] == "ManagedSQLiteMemoryStore._queue_memory_watch_publication" for sequence in live),
                "SDK watch worker was manufactured by a lifecycle join")
        workers[fid], scopes[worker["sequence"]] = worker, task["scope"]
    require({task["submitSequence"] for task in all_tasks} == {call["sequence"] for call in calls if call["name"] == "ThreadPoolExecutor.submit"},
            "SDK watch/search queue partition omitted actual original admissions")

    targets = []
    for public in observation["publicCalls"].values():
        capture = public.get("watchTargetCapture")
        if "returnSeq" not in public:
            require(capture is None, "SDK terminated caller acquired an invented completion capture")
            continue
        require(isinstance(capture, dict) and capture["pid"] == pid and capture["actor"] == actor
                and capture["callKey"] == public["kind"] + ":" + public["label"]
                and capture["storeObjectId"] == public["storeObjectId"]
                and _ns(capture["capturedAtNs"]) < _ns(capture["completedAtNs"])
                < _ns(events[public["returnSeq"]]["atNs"]), "SDK watcher target was recaptured after original completion")
        captured_versions = []
        expected = [row for row in observation["sourceClockReceipts"] if row.get("committed") and row["callKey"] == capture["callKey"]]
        expected.extend(row for row in observation["sourceClockOriginalIO"] if row.get("syscall") == "unlink"
                        and row.get("scope", {}).get("kind") == public["kind"] and row["scope"]["label"] == public["label"]
                        and row.get("arguments") and str(row["arguments"][0]).endswith((".md", ".txt")))
        expected.sort(key=lambda row: _ns(row["atNs"]))
        _same([row["receipt"] for row in capture["mutations"]], expected,
              "SDK watch targets omitted successful original source mutations")
        wid = capture["watcherObjectId"]
        for mutation in capture["mutations"]:
            receipt = mutation["receipt"]
            require(mutation["receiptSequence"] == receipt["sequence"], "SDK watch target borrowed another source receipt")
            path = receipt["absolutePath"] if mutation["receiptKind"] == "source-write-clock" else receipt["arguments"][0]
            invocations = [call for call in members("MemoryFileWatcher.capture_versions", wid,
                           begin=_ns(capture["capturedAtNs"]), end=_ns(capture["completedAtNs"]))
                           if call["arguments"]["paths"] == [path]] if wid is not None else []
            if wid is None:
                require(mutation["capture"] is None and mutation["applicabilityError"] is None,
                        "SDK absent detector manufactured a source version")
                continue
            require(wid in watchers and len(invocations) == 1, "SDK retained version lacks its original capture API")
            call = invocations[0]
            source(call["code"], "memory_core/host/memory_watcher.py", "MemoryFileWatcher.capture_versions")
            if mutation["applicabilityError"] is not None:
                require(mutation["capture"] is None and any(row["event"] == "original-exception"
                        and row["name"] == "MemoryFileWatcher.capture_versions"
                        and _ns(call["atNs"]) < _ns(row["atNs"]) < _ns(original(call)["atNs"])
                        and row["error"]["message"] == mutation["applicabilityError"]["message"] for row in events.values()),
                        "SDK watch eligibility was guessed instead of an original rejection")
                continue
            _same(original(call)["returned"], mutation["capture"], "SDK retained source version changed its actual API return")
            require(len(mutation["capture"]) == 1, "SDK source mutation did not retain its complete target version")
            target = mutation["capture"][0]
            version(target)
            require(target["path"] == path, "SDK source capture changed the actual mutated path")
            if mutation["receiptKind"] == "source-write-clock":
                info = receipt["committedState"]["stat"]
                _same(target, {"path": path, "exists": True, "version": {"device": info["st_dev"],
                      "inode": info["st_ino"], "size": int(info["st_size"]), "mtimeNs": info["st_mtime_ns"],
                      "ctimeNs": info["st_ctime_ns"]}}, "SDK retained target changed its original published inode/version")
            else:
                require(mutation["receiptKind"] == "source-delete" and receipt["returned"] is None,
                        "SDK deletion target has no real successful original unlink")
                _same(target, {"path": path, "exists": False, "version": None}, "SDK deletion capture recreated an original source")
            captured_versions.extend(mutation["capture"])
        _same(capture["versions"], captured_versions, "SDK retained target list was truncated or superseded")
        targets.append(capture)

    waits = {}
    for row in observation["watchEffectWaits"]:
        begin, end = span(row, "watch-effects")
        require(row["label"] not in waits and "error" not in row, "SDK watch effects failed or duplicated")
        retained = [target for public in row["sourceCalls"] for target in public.get("watchTargetCapture", {}).get("versions", [])]
        _same(row["versions"], retained, "SDK watch join recaptured or replaced its retained source versions")
        outcome, sid, wid = row["outcome"]["status"], row["ownerObjectId"], row["watcherObjectId"]
        if outcome == "interrupted-before-source-publication":
            interrupted = row["interruptedSourceCalls"]
            require(interrupted and not retained and not row["versions"],
                    "SDK interrupted source call was turned into positive version delivery")
            for stopped in interrupted:
                require(stopped["kind"] == "original-interrupted-source-call"
                        and stopped["callKey"] == stopped["call"]["kind"] + ":" + stopped["call"]["label"]
                        and "apiEntry" in stopped["call"] and "returnSeq" not in stopped["call"]
                        and "watchTargetCapture" not in stopped["call"]
                        and stopped["reap"]["exit"] == {"code": -9},
                        "SDK interrupted source call fabricated completion or actual process death")
                cutoff = stopped["sourceIOCutoff"]
                require(not any(part.get("committed") for part in cutoff["sourceClockReceipts"])
                        and not any(part.get("event") == "original-source-io-return"
                                    and part.get("syscall") in {"write", "pwrite", "replace", "unlink"}
                                    for part in cutoff["originalIO"]),
                        "SDK interrupted source call omitted an actual source publication")
            waits[row["label"]] = row
            continue
        if outcome == "no-applicable-targets":
            require(not retained and sid in owners and wid in watchers, "SDK empty watch target list masqueraded as delivery")
            waits[row["label"]] = row
            continue
        if outcome == "absent":
            require(sid is None and not owners or row["ownerClosed"] is True
                    and members("ManagedSQLiteMemoryStore.close", sid, end=begin),
                    "SDK watch join inferred detector absence without actual owner lifecycle")
            waits[row["label"]] = row
            continue
        require(outcome == "fulfilled" and retained and wid in watchers and watchers[wid] == sid,
                "SDK watch join has no retained target and original detector")
        api = row["api"]
        require(api["registered"] is True and api["receiverObjectId"] == sid
                and api["module"] == "memory_core.host.managed_index"
                and api["qualname"] == "ManagedSQLiteMemoryStore.wait_for_memory_watches",
                "SDK watch publication join lost its actual managed owner")
        source(api["code"], "memory_core/host/managed_index.py", "ManagedSQLiteMemoryStore.wait_for_memory_watches")
        joins = members("ManagedSQLiteMemoryStore.wait_for_memory_watches", sid, begin=begin, end=end)
        require(len(joins) == 1, "SDK watch effects did not call its real managed lifecycle API")
        join = joins[0]
        _same(join["arguments"]["versions"], retained, "SDK managed watcher wait received a refreshed source version")
        result = row["returned"]
        _same(original(join)["returned"], result, "SDK watch effects changed its original terminal API result")
        delivery_calls = members("MemoryFileWatcher.wait_for_versions", wid, begin=_ns(join["atNs"]), end=_ns(original(join)["atNs"]))
        require(len(delivery_calls) == 1, "SDK watch effects did not join its original delivery journal")
        _same(original(delivery_calls[0])["returned"], result["delivery"], "SDK watch delivery result differs from the real detector API")
        _same(result["delivery"]["targets"], retained, "SDK delivery API silently selected only newer targets")
        require(len(result["delivery"]["deliveries"]) == len(retained), "SDK watch delivery dropped an applicable committed version")
        for target, fact in zip(retained, result["delivery"]["deliveries"], strict=True):
            path = version(target)
            _same({key: fact[key] for key in ("path", "exists", "version")}, target,
                  "SDK delivery journal changed the original retained source version")
            generation = fact["generation"]
            require(type(generation) is int and generation > 0
                    and generation <= result["delivery"]["settledGeneration"]
                    and fact["backend"] in {"inotify", "stat"}, "SDK watcher manufactured delivery from its initial inventory")
            accepted = [call for call in members("MemoryFileWatcher._deliver", wid, end=end)
                        if original(call)["returned"] == generation]
            require(len(accepted) == 1, "SDK delivered source version has no genuine accepted reconciliation")
            accepted = accepted[0]
            require(_ns(accepted["atNs"]) < _ns(fact["observedAtNs"]) < _ns(original(accepted)["atNs"]),
                    "SDK delivery journal lost its actual reconciliation observation lifetime")
            previous, current = accepted["arguments"]["previous"], accepted["arguments"]["current"]
            root = Path(owners[sid]["config"]["workspace_dir"])
            key = "file:" + path.relative_to(root).as_posix()
            require(previous is not None and previous.get(key) != current.get(key),
                    "SDK initial baseline or unchanged inventory masqueraded as a delivered event")
            physical = None if not target["exists"] else [int(fact["version"]["device"]), int(fact["version"]["inode"]),
                        fact["version"]["size"], int(fact["version"]["mtimeNs"]), int(fact["version"]["ctimeNs"])]
            _same(current.get(key), physical, "SDK delivery journal disagrees with its accepted physical reconciliation snapshot")
            if not target["exists"]:
                require(previous.get(key) is not None and fact["previousVersion"] is not None,
                        "SDK watcher invented deletion delivery for an initially absent source")
            callback = [call for call in members("MemoryFileWatcher._dirty", wid, end=end)
                        if call["arguments"]["generation"] == generation]
            require(callback and _ns(original(accepted)["atNs"]) < _ns(callback[0]["atNs"]),
                    "SDK delivered generation never reached its original dirty callback")
            changed = [call for call in members("ManagedSQLiteMemoryStore._memory_watch_changed", sid, end=end)
                       if call["threadId"] == accepted["threadId"] and call.get("scope", {}).get("kind") == "watch"
                       and call["scope"]["watcherObjectId"] == wid
                       and call["scope"]["detectorGeneration"] >= generation]
            require(changed, "SDK delivered source version never settled through its original managed callback")
            source(changed[0]["code"], "memory_core/host/managed_index.py", "ManagedSQLiteMemoryStore._memory_watch_changed")
            require(any(call["name"] == "MemoryFileWatcher.settling_generation"
                        and call["receiverObjectId"] == wid and call["sequence"] in returns
                        and _ns(changed[0]["atNs"]) < _ns(call["atNs"])
                        < _ns(original(changed[0])["atNs"])
                        and original(call)["returned"] == changed[0]["scope"]["detectorGeneration"]
                        for call in calls), "SDK watch callback scope guessed its detector settling generation")
            source(accepted["code"], "memory_core/host/memory_watcher.py", "MemoryFileWatcher._deliver")
            detector_thread = accepted["threadId"]
            if fact["backend"] == "inotify":
                reads = [call for call in members("_Inotify.read", end=_ns(accepted["atNs"]))
                         if call["threadId"] == detector_thread and call["callLabel"] == accepted["callLabel"]]
                require(reads, "SDK inotify delivery has no genuine OS event read before reconciliation")
                source(reads[-1]["code"], "memory_core/host/memory_watcher.py", "_Inotify.read")
                os_paths, overflow = original(reads[-1])["returned"]
                require(type(overflow) is bool, "SDK inotify delivery changed its original overflow flag")
                if not overflow:
                    require(isinstance(os_paths, dict) and os_paths.get("mappingEntries"),
                            "SDK inotify delivery substituted an empty queue for an actual event")
                    candidates = [call for call in members("MemoryFileWatcher._candidate", wid,
                                  begin=_ns(original(reads[-1])["atNs"]), end=_ns(accepted["atNs"]))
                                  if call["threadId"] == detector_thread and original(call)["returned"] is True]
                    require(any([call["arguments"]["path"], call["arguments"]["directory"]] in os_paths["mappingEntries"]
                                for call in candidates), "SDK watch reconciliation has no admitted original inotify path")
            else:
                inventories = [call for call in members("_inventory", end=_ns(accepted["atNs"]))
                               if call["threadId"] == detector_thread and call["callLabel"] == accepted["callLabel"]]
                require(inventories, "SDK stat-fallback delivery has no original filesystem inventory")
                source(inventories[-1]["code"], "memory_core/host/memory_watcher.py", "_inventory")
                _same(original(inventories[-1])["returned"][0], current,
                      "SDK stat delivery replaced its original accepted filesystem snapshot")
        fid = ident(result["futureObjectId"])
        require(fid in tasks, "SDK watch lifecycle result invented a publication Future")
        task = tasks[fid]
        matching_workers = [call for call in calls if call["code"] == task["functionCode"]
                            and call["receiverObjectId"] == sid and call["callLabel"] == task["scope"]["label"]
                            and call["arguments"].get("job", {}).get("id") == result["job"]["id"]]
        require(len(matching_workers) == 1, "SDK watch lifecycle result has no genuine terminal publication worker")
        worker = matching_workers[0]
        original(worker)
        joins_future = [call for call in members("Future.result", fid, begin=_ns(join["atNs"]), end=_ns(original(join)["atNs"]))]
        require(len(joins_future) == 1, "SDK watch lifecycle did not join the actual retained publisher Future")
        _same(original(joins_future[0])["returned"], result["futureReturned"], "SDK watch wait changed its real Future result")
        require(_ns(original(worker)["atNs"]) < _ns(original(joins_future[0])["atNs"])
                and result["job"]["state"] == result["status"] and result["status"] in {"completed", "failed"},
                "SDK callback settlement was substituted for real terminal index work")
        source(worker["code"], "memory_core/host/managed_index.py", "ManagedSQLiteMemoryStore._run_memory_publication")
        nested = [call for call in calls if call["threadId"] == worker["threadId"]
                  and call["receiverObjectId"] == sid and call["name"] in {
                      "ManagedSQLiteMemoryStore.reindex", "ManagedSQLiteMemoryStore.reindex_sources"}
                  and _ns(worker["atNs"]) < _ns(call["atNs"]) < _ns(original(worker)["atNs"])]
        if result["status"] == "completed":
            require(result["job"]["publishedWatchGeneration"] >= result["watchGeneration"],
                    "SDK watcher accepted a job which did not cover its original generation")
            require(any(original(call)["returned"] == result["job"].get("returned") for call in nested),
                    "SDK completed watcher job lacks its original index producer result")
            table_writes = [call for call in calls if call["name"] == "write_prepared_index"
                            and call["threadId"] == worker["threadId"]
                            and _ns(worker["atNs"]) < _ns(call["atNs"]) < _ns(original(worker)["atNs"])]
            for written in table_writes:
                require(any(sql["statement"].strip().upper() == "COMMIT"
                            and sql["connectionId"] == written["receiverObjectId"]
                            and _ns(original(written)["atNs"]) < _ns(sql["atNs"]) < _ns(original(worker)["atNs"])
                            for sql in observation["sqlStatements"]),
                        "SDK watch table publication lacks its genuine owned transaction COMMIT")
        else:
            require(result["job"]["watchGeneration"] >= result["watchGeneration"] and result["job"].get("error"),
                    "SDK watcher failure was hidden behind an unqualified queue settlement")
            error = result["job"]["error"]
            require(any(event["event"] == "original-exception" and event["threadId"] == worker["threadId"]
                        and event["error"]["name"] == error["name"] and event["error"]["message"] == error["message"]
                        and _ns(worker["atNs"]) < _ns(event["atNs"]) < _ns(original(worker)["atNs"])
                        for event in events.values()), "SDK watcher job error has no actual original producer exception")
        waits[row["label"]] = row
    require(not set(readiness) & set(waits), "SDK watcher readiness/effect labels were aliased")
    return {"waits": {**readiness, **waits}, "workers": list(workers.values()), "targets": targets, "workerScopes": scopes}
