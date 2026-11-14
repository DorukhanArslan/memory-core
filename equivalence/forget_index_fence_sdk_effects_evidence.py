"""Replay V3 SDK search-effect admission and joins without running an engine.

Both production and fixture source roots are independently selected by callers.
This guard never treats an absent queue as evidence of an absent capability.
"""
from __future__ import annotations

import ast
from concurrent.futures import Future, ThreadPoolExecutor
import hashlib
import inspect
from pathlib import Path
import threading


STOCK_SHA256 = "1b65f5cb9cabd7dfad07bfea7eb0dc05fbf29e846bc5648fe47d5637f0c83d9c"
_TASK_FIELDS = {"kind", "scope", "submitSequence", "executorObjectId", "storeObjectId",
                "contextObjectId", "jobObjectId", "parentCallSequences", "functionCode",
                "futureObjectId", "submitReturnedAtNs"}
_STDLIB = {"ThreadPoolExecutor.submit": ThreadPoolExecutor.submit,
           "Future.result": Future.result, "Condition.wait": threading.Condition.wait}


def _closed_effects_case(case):
    """Admit only the exact frozen V3/V4/V5 inputs sharing effects protocol V3."""
    kind = case.get("input", {}).get("kind") if isinstance(case, dict) else None
    if kind == "forget-index-fence-v3":
        from equivalence.forget_index_fence_v3 import validate_case
        version = 3
    elif kind == "forget-index-fence-v4":
        from equivalence.forget_index_fence_v4 import validate_case
        version = 4
    elif kind == "forget-index-fence-v5":
        from equivalence.forget_index_fence_v5 import validate_case
        version = 5
    else:
        raise ValueError("SDK effects require an exact frozen V3, V4 or V5 case")
    validate_case(case)
    return version


def validate_sdk_effects_v3(case, observation, process, events, returns, *, recorded_root,
                            approved_sdk_root, recorded_adapter_root, approved_adapter_root):
    """Authenticate existing work and return the labelled actual wait receipts."""
    from equivalence.forget_index_fence_evidence import _digest, _ns, _regular, _same, _sdk_code_owner, require

    recorded, approved = Path(recorded_root), Path(approved_sdk_root)
    adapter, trusted_adapter = Path(recorded_adapter_root), Path(approved_adapter_root)
    require(trusted_adapter.is_absolute() and trusted_adapter.resolve(strict=True) == trusted_adapter,
            "SDK effects need an independently selected fixture source root")
    version = _closed_effects_case(case)
    value, pid, actor = case["input"], observation["pid"], observation["actor"]
    require(pid == process["pid"] and actor == process["actor"],
            "SDK effects borrowed another frozen profile or process")
    policy = value["observationPolicy"]["searchEffects"]
    require(policy["protocol"] == "original-search-effects-v3", "SDK effects protocol changed")
    producer_names = {"ManagedSQLiteMemoryStore._run_memory_publication", "_record_search_recalls"}
    calls = [row for row in events.values() if row["event"] == "original-call"]
    watch_proof = {"workers": []}
    if version == 5:
        from equivalence.forget_index_fence_sdk_watch_evidence import validate_sdk_watch_v5
        watch_proof = validate_sdk_watch_v5(case, observation, process, events, returns,
            recorded_root=recorded, approved_sdk_root=approved,
            recorded_adapter_root=adapter, approved_adapter_root=trusted_adapter)

    def ident(value):
        require(isinstance(value, str) and value.isdecimal() and int(value) > 0,
                "SDK effects lost an actual object identity")
        return value

    def stdlib(row, name):
        original = _STDLIB[name]
        code = original.__code__
        source = _regular(Path(inspect.getsourcefile(original)).resolve(strict=True))
        require(row["file"] == str(source) and row["sourceSha256"] == _digest(source)
                and row["qualname"] == code.co_qualname and row["firstLine"] == code.co_firstlineno
                and row["bytecodeSha256"] == hashlib.sha256(code.co_code).hexdigest(),
                "SDK effects used another interpreter's Future, Condition or executor")

    def source(row, filename=None, qualname=None):
        _sdk_code_owner(row, recorded, approved)
        if filename is not None:
            require(row["file"] == str(recorded / filename) and row["qualname"] == qualname,
                    "SDK effects borrowed another production callable")

    def settled(call):
        require(call["sequence"] in returns, "SDK effect original frame has no actual return receipt")
        result = returns[call["sequence"]]
        require(_ns(call["atNs"]) < _ns(result["atNs"]) and call["threadId"] == result["threadId"],
                "SDK effect return changed its original thread or invocation")
        if call["name"] in _STDLIB:
            lookup = result.get("returnLookup")
            require(isinstance(lookup, dict) and lookup["strategy"] == "retained-entry-frame"
                    and lookup["entryCallSequence"] == call["sequence"]
                    and lookup["frameObjectId"] == call["frameObjectId"]
                    and lookup["entryReceiverObjectId"] == call["receiverObjectId"],
                    "SDK standard-library return lost its actual retained entry frame and owner")
            ident(lookup["frameObjectId"])
            _same(lookup["entryCode"], call["code"], "SDK retained standard-library return changed its exact entry code")
            if call["name"] == "ThreadPoolExecutor.submit":
                require(lookup["receiverLocalName"] is None and lookup["receiverLocalPresent"] is False,
                        "SDK executor return fabricated a selected receiver local")
            else:
                require(lookup["receiverLocalName"] == "self" and lookup["receiverLocalPresent"] is True,
                        "SDK Future/Condition return dropped its real receiver local")
                if call["name"] == "Future.result":
                    require(lookup["receiverLocal"] is None,
                            "SDK Future return repaired the self=None local cleared by its original finally block")
                else:
                    require(lookup["receiverLocal"] == {"objectId": call["receiverObjectId"],
                            "module": "threading", "className": "Condition"},
                            "SDK Condition return changed its actual receiver object")
        return result

    def scope(row):
        require(isinstance(row, dict) and set(row) == {"kind", "label", "wallClockNowMs"}
                and row["kind"] == "search", "SDK queued work lost its original search scope")
        key = "search:" + row["label"]
        require(key in observation["publicCalls"], "SDK queued work has no actual original search")
        tick = value["clock"]["sourceWriteClock"]["ticksByCall"][key]
        require(tick["actor"] == actor and tick["wallClockNowMs"] == row["wallClockNowMs"],
                "SDK queued work borrowed another actor epoch")
        return observation["publicCalls"][key]

    def future(row, expected):
        require(isinstance(row, dict) and set(row) == {"module", "className", "objectId", "state", "result", "exception"}
                and row["module"] == "concurrent.futures._base" and row["className"] == "Future"
                and ident(row["objectId"]) == expected
                and row["state"] in {"PENDING", "RUNNING", "FINISHED", "CANCELLED", "CANCELLED_AND_NOTIFIED"},
                "SDK queued work replaced its genuine original Future")

    codes = {row["name"]: row["code"] for row in observation["codeOwners"] if row["name"] in _STDLIB}
    require(set(codes) == set(_STDLIB), "SDK effects omitted a selected original standard-library owner")
    for name, code in codes.items():
        stdlib(code, name)
    for call in calls:
        if call["name"] in _STDLIB:
            stdlib(call["code"], call["name"])

    # Parse signatures and declarations; do not import or evaluate SDK source.
    factory_file = _regular(approved / "memory_core/tools/search_factory.py")
    search_file = _regular(approved / "memory_core/tools/memory_search.py")
    factory_tree = ast.parse(factory_file.read_text())
    search_tree = ast.parse(search_file.read_text())
    definitions = [node for node in factory_tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == "create_memory_search_tool"]
    require(len(definitions) == 1, "SDK effects factory has no unique original declaration")
    factory_definition = definitions[0]
    parameters = [node.arg for node in (*factory_definition.args.posonlyargs,
                  *factory_definition.args.args, *factory_definition.args.kwonlyargs)]
    tool_classes = [node for node in factory_tree.body if isinstance(node, ast.ClassDef) and node.name == "MemorySearchTool"]
    require(len(tool_classes) == 1, "SDK effects tool has no unique original class")
    tool_methods = {node.name for node in tool_classes[0].body if isinstance(node, ast.FunctionDef)}
    recall_definitions = {node.name for node in search_tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    has_recall = "MemorySearchRecallOwner" in recall_definitions and "_record_search_recalls" in recall_definitions
    has_wait = "wait_for_recalls" in tool_methods
    if not has_recall:
        identity = observation["sourceProvenanceBefore"]
        require(identity["sourceFiles"] == 160 and identity["sourceSha256"] == STOCK_SHA256
                and not has_wait and "recall_origins" not in parameters and "on_event" not in parameters,
                "SDK missing recall receipts are not authenticated stock-160 capability absence")
    else:
        require(has_wait and "recall_origins" in parameters and "on_event" in parameters,
                "SDK recall capability declaration is inconsistent with its actual factory")

    searches = {call["label"]: call for call in observation["publicCalls"].values() if call["kind"] == "search"}
    for label, call in searches.items():
        cap = call["searchFactoryCapabilities"]
        source(cap["source"], "memory_core/tools/search_factory.py", "create_memory_search_tool")
        _same(cap["parameters"], parameters, "SDK factory capability signature differs from original source")
        require(type(cap["recallOrigins"]) is bool and cap["recallOrigins"] == ("recall_origins" in parameters)
                and type(cap["onEvent"]) is bool and cap["onEvent"] == ("on_event" in parameters)
                and cap["waitForRecalls"] is has_wait, "SDK effects invented or hid factory capabilities")
        signature = ast.parse("def observed" + cap["signature"] + ":\n pass\n").body[0]
        actual_parameters = [node.arg for node in (*signature.args.posonlyargs, *signature.args.args, *signature.args.kwonlyargs)]
        _same(actual_parameters, parameters, "SDK factory raw signature and parameter carrier disagree")
        ident(cap["toolObjectId"])
        tool_calls = [row for row in calls if row["name"] == "MemorySearchTool.execute" and row["callLabel"] == label]
        require(len(tool_calls) == 1 and tool_calls[0]["receiverObjectId"] == cap["toolObjectId"],
                "SDK effect barrier borrowed another actual public tool")
        if has_recall:
            ident(cap["recallOwnerObjectId"])
            source(cap["waitSource"], "memory_core/tools/search_factory.py", "MemorySearchTool.wait_for_recalls")
        else:
            require(cap["recallOwnerObjectId"] is None and cap["waitSource"] is None,
                    "SDK stock factory fabricated a recall owner or empty recall queue")

    owners = {row["storeObjectId"]: row for row in observation["ownerBindings"]}
    tasks, worker_calls = {}, {}
    for task in observation["queuedSearchTasks"]:
        require(set(task) == _TASK_FIELDS | {"future", "job"}, "SDK effect task carrier was truncated or expanded")
        public = scope(task["scope"])
        store = ident(task["storeObjectId"])
        require(store in owners and public["storeObjectId"] == store, "SDK effect task borrowed another store owner")
        submit = events[task["submitSequence"]]
        require(submit["event"] == "original-call" and submit["name"] == "ThreadPoolExecutor.submit"
                and submit["callLabel"] == public["label"] and submit["callKind"] == "search"
                and submit["selfObjectId"] == ident(task["executorObjectId"]),
                "SDK queued work was not admitted by its actual original executor")
        submit_return = settled(submit)
        fid = ident(task["futureObjectId"])
        require(fid not in tasks and _ns(submit["atNs"]) < _ns(task["submitReturnedAtNs"])
                < _ns(submit_return["atNs"]), "SDK effect admission duplicated a Future or replaced its original return")
        future(submit_return["returned"], fid)
        future(task["future"], fid)
        source(task["functionCode"])
        require(task["kind"] in {"memory-publication", "recall"}, "SDK effect task used an undeclared producer")
        name = "ManagedSQLiteMemoryStore._run_memory_publication" if task["kind"] == "memory-publication" else "_record_search_recalls"
        filename = "memory_core/host/managed_index.py" if task["kind"] == "memory-publication" else "memory_core/tools/memory_search.py"
        source(task["functionCode"], filename, name)
        require(task["functionCode"]["qualname"] == name and submit["arguments"]["fn"]["qualname"] == name,
                "SDK Future submission changed its original producer callable")
        require(task["parentCallSequences"] and len(set(task["parentCallSequences"])) == len(task["parentCallSequences"]),
                "SDK submission lost its original causal parent frames")
        live_parents = [parent["sequence"] for parent in calls
                        if parent["threadId"] == submit["threadId"] and parent["callLabel"] == public["label"]
                        and parent["callKind"] == "search" and _ns(parent["atNs"]) < _ns(submit["atNs"])
                        and (parent["sequence"] not in returns or _ns(submit["atNs"]) < _ns(returns[parent["sequence"]]["atNs"]))]
        _same(task["parentCallSequences"], live_parents, "SDK task omitted actual live causal source frames")
        for sequence in task["parentCallSequences"]:
            parent = events[sequence]
            require(parent["event"] == "original-call" and parent["threadId"] == submit["threadId"]
                    and parent["callLabel"] == public["label"] and parent["callKind"] == "search"
                    and _ns(parent["atNs"]) < _ns(submit["atNs"])
                    and (sequence not in returns or _ns(submit["atNs"]) < _ns(returns[sequence]["atNs"])),
                    "SDK task admission borrowed a parent that was not actually live")
        actual_workers = [row for row in calls if row["code"] == task["functionCode"]
                          and row["callLabel"] == public["label"] and row["receiverObjectId"] == store
                          and row["callKind"] == "search" and _ns(submit["atNs"]) < _ns(row["atNs"])]
        if task["kind"] == "memory-publication":
            require(task["contextObjectId"] is None and ident(task["jobObjectId"])
                    and isinstance(task["job"], dict), "SDK publication task lost its actual job owner")
            job = submit["arguments"]["args"][0]
            require(job["state"] == "queued" and task["job"]["id"] == job["id"],
                    "SDK publication task replaced its admitted original job")
            require(all(task["job"][key] == item for key, item in job.items() if key != "state"),
                    "SDK final publication job changed its actual admitted epoch")
            actual_workers = [row for row in actual_workers if row["arguments"]["job"] == job
                              and row["arguments"]["token"] == submit["arguments"]["args"][1]]
        else:
            require(has_recall and task["jobObjectId"] is None and task["job"] is None,
                    "SDK stock-160 source invented a queued recall producer")
            cid = ident(task["contextObjectId"])
            require(submit["arguments"]["storeObjectId"] == store and submit["arguments"]["contextObjectId"] == cid,
                    "SDK recall admission changed the exact original store or context")
            actual_workers = [row for row in actual_workers if row["contextObjectId"] == cid
                              and row["contextRecallOwnerObjectId"] == searches[public["label"]]["searchFactoryCapabilities"]["recallOwnerObjectId"]]
        require(len(actual_workers) == 1, "SDK task has no unique actual original producer frame")
        worker = actual_workers[0]
        settled(worker)
        require(worker["threadId"] != submit["threadId"], "SDK queued effect was executed inline instead of by its actual worker")
        if task["kind"] == "memory-publication":
            require(task["job"]["threadId"] == worker["threadId"], "SDK publication job changed its real worker thread")
        require(_ns(submit_return["atNs"]) < _ns(events[public["returnSeq"]]["atNs"]),
                "SDK effect Future was admitted after the original public search settled")
        tasks[fid], worker_calls[fid] = task, worker

    submitted = {row["sequence"] for row in calls if row["name"] == "ThreadPoolExecutor.submit"
                 and (version != 5 or row["callKind"] == "search")}
    require(submitted == {task["submitSequence"] for task in tasks.values()},
            "SDK effects omitted or fabricated an actual original submission")
    require(all(row["sequence"] in {worker["sequence"] for worker in worker_calls.values()}
                for row in calls if row["name"] in producer_names and (version != 5 or row["callKind"] == "search")),
            "SDK effects omitted a source-owned queued worker")
    original_tasks = dict(tasks)
    original_workers = dict(worker_calls)
    if version == 5:
        for task in observation["queuedWatchTasks"]:
            fid = task["futureObjectId"]
            matching = [row for row in watch_proof["workers"] if row["code"] == task["functionCode"]
                        and row["receiverObjectId"] == task["storeObjectId"] and row["scope"] == task["scope"]
                        and row["arguments"]["job"]["id"] == task["job"]["id"]]
            require(len(matching) == 1, "SDK search wait borrowed an unauthenticated watcher worker")
            original_tasks[fid], original_workers[fid] = task, matching[0]

    waits = {}
    for wait in observation["searchEffectWaits"]:
        require(set(wait) == {"label", "actor", "pid", "publicReturnSequence", "factoryCapabilities", "enteredAtNs",
                "toolObjectId", "storeObjectId", "conditionObjectId", "tasksAtEntry", "conditionWaits", "recall",
                "publisherBefore", "publisherAfter", "publisherFutures", "returnedAtNs", "tasksAtReturn"},
                "SDK effects barrier lost complete actual custody fields")
        label = wait["label"]
        require(label in searches and label not in waits and wait["actor"] == actor and wait["pid"] == pid
                and "error" not in wait, "SDK effects barrier failed, duplicated or borrowed another actor")
        public = searches[label]
        _same(wait["factoryCapabilities"], public["searchFactoryCapabilities"], "SDK barrier changed actual factory capabilities")
        require(wait["publicReturnSequence"] == public["returnSeq"] and wait["storeObjectId"] == public["storeObjectId"]
                and wait["toolObjectId"] == public["searchFactoryCapabilities"]["toolObjectId"],
                "SDK barrier borrowed another original search, owner or public settlement")
        begin, end = _ns(wait["enteredAtNs"]), _ns(wait["returnedAtNs"])
        require(_ns(events[public["returnSeq"]]["atNs"]) < begin < end, "SDK effects wait replaced public search timing")
        own = {fid: task for fid, task in tasks.items() if task["scope"]["label"] == label}
        require(len(own) <= policy["maxReferencesPerBarrier"], "SDK barrier exceeded its frozen actual-work bound")
        base = [{key: task[key] for key in _TASK_FIELDS} for task in own.values()]
        _same(wait["tasksAtEntry"], base, "SDK barrier drained a fresh, foreign or incomplete task list")
        at_settle = public["effectsAtPublicSettle"]
        require(len(at_settle) == len(own), "SDK public settlement omitted actual queued work")
        for task in at_settle:
            fid = task["futureObjectId"]
            require(fid in own, "SDK public settlement borrowed another queued Future")
            _same({key: task[key] for key in _TASK_FIELDS}, {key: own[fid][key] for key in _TASK_FIELDS},
                  "SDK public settlement repaired original task admission metadata")
            future(task["future"], fid)
        _same(wait["tasksAtReturn"], list(own.values()), "SDK barrier omitted actual final Future/job state")
        recall_ids = [fid for fid, task in own.items() if task["kind"] == "recall"]
        require(wait["recall"]["supported"] is has_wait, "SDK barrier invented recall-wait capability")
        _same(wait["recall"]["futureObjectIds"], recall_ids, "SDK barrier hid queued original recall Futures")
        if has_wait:
            recall = wait["recall"]
            matching = [row for row in calls if row["name"] == "MemorySearchTool.wait_for_recalls"
                        and row["receiverObjectId"] == wait["toolObjectId"]
                        and _ns(recall["enteredAtNs"]) < _ns(row["atNs"])
                        < _ns(settled(row)["atNs"]) < _ns(recall["returnedAtNs"])]
            require(len(matching) == 1, "SDK recall barrier did not call its actual tool-owned wait")
            _same(settled(matching[0])["returned"], recall["returned"], "SDK recall barrier changed its original return")
        else:
            require(wait["recall"] == {"supported": False, "futureObjectIds": []},
                    "SDK legacy capability absence was replaced with an invented wait result")
        after = wait["publisherAfter"]
        def publisher_state(state):
            require(set(state) == {"memoryActive", "syncActivePresent", "syncActive", "fullSyncObjectId", "jobs"}
                    and all(type(state[key]) is bool for key in ("memoryActive", "syncActivePresent", "syncActive"))
                    and isinstance(state["jobs"], list), "SDK publisher wait state was truncated or coerced")
            if state["syncActivePresent"] is False:
                require(state["syncActive"] is False, "SDK publisher wait invented an absent sync-active state")
            for job in state["jobs"]:
                admitted = [task for task in original_tasks.values() if task["kind"] == "memory-publication"
                            and task["storeObjectId"] == wait["storeObjectId"] and task["job"]["id"] == job["id"]]
                require(len(admitted) == 1, "SDK publisher condition state borrowed an unadmitted original job")
                submitted_job = events[admitted[0]["submitSequence"]]["arguments"]["args"][0]
                require(all(job[key] == item for key, item in submitted_job.items() if key != "state"),
                        "SDK publisher condition state changed its admitted original job epoch")
                if "threadId" in job:
                    require(job["threadId"] == original_workers[admitted[0]["futureObjectId"]]["threadId"],
                            "SDK publisher condition state borrowed another worker thread")
        for state in (wait["publisherBefore"], after):
            publisher_state(state)
        for task in own.values():
            if task["kind"] == "memory-publication":
                observed_jobs = [job for job in after["jobs"] if job["id"] == task["job"]["id"]]
                if observed_jobs:
                    require(len(observed_jobs) == 1, "SDK publisher state duplicated one original job")
                    _same(task["job"], observed_jobs[0], "SDK final task job differs from its actual owned condition state")
        require(after["memoryActive"] is False and after["syncActive"] is False and after["fullSyncObjectId"] is None,
                "SDK barrier returned while its actual publisher still owned work")
        ident(wait["conditionObjectId"])
        condition_frames, future_frames = set(), set()
        for condition in wait["conditionWaits"]:
            require(set(condition) == {"enteredAtNs", "returnedAtNs", "returned", "stateBefore", "stateAfter"},
                    "SDK original condition wait receipt was truncated")
            publisher_state(condition["stateBefore"])
            publisher_state(condition["stateAfter"])
            require(condition["stateBefore"]["memoryActive"] or condition["stateBefore"]["syncActive"]
                    or condition["stateBefore"]["fullSyncObjectId"] is not None,
                    "SDK condition wait fabricated an inactive original publisher predicate")
            matches = [row for row in calls if row["name"] == "Condition.wait"
                       and row["receiverObjectId"] == wait["conditionObjectId"] and row["callLabel"] == label
                       and begin < _ns(condition["enteredAtNs"]) < _ns(row["atNs"])
                       < _ns(settled(row)["atNs"]) < _ns(condition["returnedAtNs"]) < end]
            require(len(matches) == 1 and type(condition["returned"]) is bool,
                    "SDK publisher wait lacks a real owned Condition invocation")
            _same(settled(matches[0])["returned"], condition["returned"], "SDK publisher condition wait fabricated a notification")
            require(matches[0]["sequence"] not in condition_frames, "SDK barrier duplicated its actual condition wait")
            condition_frames.add(matches[0]["sequence"])
        publication_ids = [fid for fid, task in own.items() if task["kind"] == "memory-publication"]
        _same([row["futureObjectId"] for row in wait["publisherFutures"]], publication_ids,
              "SDK barrier did not join exactly its admitted publication Futures")
        for joined in wait["publisherFutures"]:
            fid = joined["futureObjectId"]
            matches = [row for row in calls if row["name"] == "Future.result" and row["receiverObjectId"] == fid
                       and row["callLabel"] == label and begin < _ns(joined["enteredAtNs"]) < _ns(row["atNs"])
                       and row["sequence"] in returns
                       and _ns(returns[row["sequence"]]["atNs"]) < _ns(joined["settledAtNs"]) < end]
            require(len(matches) == 1 and "error" not in joined, "SDK effect Future join lacks its actual original return")
            finished = settled(matches[0])
            future_frames.add(matches[0]["sequence"])
            _same(finished["returned"], joined["returned"], "SDK barrier changed its original Future.result value")
            future(own[fid]["future"], fid)
            require(own[fid]["future"]["state"] == "FINISHED" and own[fid]["future"]["exception"] is None
                    and _ns(settled(worker_calls[fid])["atNs"]) < _ns(finished["atNs"]),
                    "SDK barrier manufactured completion before its actual worker returned")
            _same(own[fid]["future"]["result"], joined["returned"], "SDK joined another Future's result")
        for fid in recall_ids:
            matches = [row for row in calls if row["name"] == "Future.result" and row["receiverObjectId"] == fid
                       and row["callLabel"] == label and begin < _ns(row["atNs"])
                       and row["sequence"] in returns and _ns(returns[row["sequence"]]["atNs"]) < end]
            require(len(matches) == 1, "SDK recall wait did not join its actual admitted original Future")
            future_frames.add(matches[0]["sequence"])
            _same(settled(matches[0])["returned"], own[fid]["future"]["result"], "SDK recall wait changed its original Future result")
        for row in calls:
            if not begin < _ns(row["atNs"]) < end or row["callLabel"] != label:
                continue
            if row["name"] == "Condition.wait" and row["receiverObjectId"] == wait["conditionObjectId"]:
                require(row["sequence"] in condition_frames, "SDK barrier omitted an actual owned condition wait")
            if row["name"] == "Future.result" and row["receiverObjectId"] in own:
                require(row["sequence"] in future_frames, "SDK barrier omitted an actual admitted Future.result invocation")
        # Admitted background producers may finish during a barrier. The
        # barrier itself cannot create a new producer or public search.
        worker_threads = [(worker["threadId"], _ns(worker["atNs"]), _ns(settled(worker)["atNs"]))
                          for fid, worker in worker_calls.items() if fid in own]
        if version == 5:
            worker_threads.extend((worker["threadId"], _ns(worker["atNs"]), _ns(settled(worker)["atNs"]))
                                  for worker in watch_proof["workers"])
        for row in calls:
            if begin < _ns(row["atNs"]) < end and row["name"] in {
                    "MemorySearchTool.execute", "execute_memory_search_tool", "_run_memory_search_tool",
                    "ManagedSQLiteMemoryStore.reindex", "ManagedSQLiteMemoryStore.reindex_sources",
                    "SQLiteMemoryStore._reindex_locked", "record_short_term_recalls"}:
                require(any(row["threadId"] == thread and started <= _ns(row["atNs"]) < stopped
                            for thread, started, stopped in worker_threads),
                        "SDK effects wait admitted new retrieval, publication or recall work")
        waits[label] = wait

    require(set(waits) == set(searches), "SDK effects omitted a settled original search barrier")
    commands = [row for row in process["stdinCommands"] if row["operation"] == "await-search-effects"]
    require([row["label"] for row in commands] == list(waits), "SDK effects receipts differ from actual process commands")
    _same(observation["hostEvents"], [row["event"] for row in observation["hostEventReceipts"]],
          "SDK host event buffer differs from its complete original callback receipts")
    for receipt in observation["hostEventReceipts"]:
        require(set(receipt) == {"event", "atNs", "actor", "pid", "callScope"}
                and receipt["pid"] == pid and receipt["actor"] == actor,
                "SDK host effect borrowed another original actor or callback")
        callback_scope = receipt["callScope"]
        require(isinstance(callback_scope, dict)
                and set(callback_scope) == {"label", "kind", "wallClockNowMs"},
                "SDK host effect has no actual original call scope")
        callback_key = callback_scope["kind"] + ":" + callback_scope["label"]
        require(callback_key in observation["publicCalls"], "SDK host effect borrowed an absent original public call")
        tick = value["clock"]["sourceWriteClock"]["ticksByCall"][callback_key]
        require(tick["actor"] == actor and tick["wallClockNowMs"] == callback_scope["wallClockNowMs"],
                "SDK host effect changed its original declared actor epoch")
        event_type = receipt["event"]["type"]
        require(event_type.startswith("memory.recall.") or event_type == "memory.promotion.applied",
                "SDK host effect receipt added an undeclared producer")
        name = "record_short_term_recalls" if event_type.startswith("memory.recall.") else "run_short_term_promotion"
        producers = [row for row in calls if row["name"] == name
                     and row["callLabel"] == callback_scope["label"] and row["callKind"] == callback_scope["kind"]
                     and _ns(row["atNs"]) < _ns(receipt["atNs"])
                     and row["sequence"] in returns and _ns(receipt["atNs"]) < _ns(returns[row["sequence"]]["atNs"])]
        require(len(producers) == 1, "SDK host effect has no unique live original recall/promotion producer")
        producer = producers[0]
        source(producer["code"], "memory_core/consolidation/recall.py" if name == "record_short_term_recalls"
               else "memory_core/consolidation/promotion.py", name)
        sink = producer["arguments"]["on_event"]
        require(sink["callable"] is True and sink["module"] == "equivalence.forget_index_fence_sdk"
                and sink["qualname"] == "_SdkActor._host_event", "SDK host effect lost its actual source-owned callback sink")
        ident(sink["objectId"])
        if callback_scope["kind"] == "search":
            require(any(task["kind"] == "recall" and task["scope"] == callback_scope
                        and worker_calls[fid]["threadId"] == producer["threadId"]
                        and _ns(worker_calls[fid]["atNs"]) < _ns(producer["atNs"])
                        < _ns(settled(worker_calls[fid])["atNs"]) for fid, task in tasks.items()),
                    "SDK asynchronous host recall effect has no original admitted worker")
    # Explicit adapter authority is independently supplied; metadata never
    # selects a program or executable. The enclosing guard verifies its seal.
    adapter_source = _regular(trusted_adapter / "equivalence/forget_index_fence_sdk.py")
    require(adapter_source.relative_to(trusted_adapter).as_posix() == "equivalence/forget_index_fence_sdk.py"
            and adapter.is_absolute(), "SDK effects lost independently approved adapter ownership")
    proof = {"waits": waits, "workers": list(worker_calls.values())}
    if version == 5:
        proof["watchProof"] = watch_proof
    return proof
