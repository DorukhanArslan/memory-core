"""Whole-operation outcome and publication evidence for the exact apply family.

The strict pair validator binds complete physical/API state and actual live
lease/read/publication receipts. The separate development replay grants no
coverage by itself. Internal origin/event database transactions outside these
declared outer publication relations remain raw, without general DB parity.
"""
from pathlib import Path
import json

from equivalence.get_contract import map_get_fixture_paths
from equivalence.promotion_apply_family import differences, validate_execution_case
from equivalence.promotion_apply_evidence import _tree, _physical, _store_and_events, _outcome
from equivalence.search_contract import _same_json


def require(value, message):
    if not value:
        raise ValueError(message)


def same(actual, expected, message):
    require(_same_json(actual, expected), message)


def document_names(value):
    return list(dict.fromkeys([*value["files"], *(c["path"] for c in value["candidates"]),
                              *(c["path"] for c in value["recall"]["entries"].values()), "MEMORY.md", "DREAMS.md"]))


def validate_native_capture(case, raw, output, *, authority=None, pid=None):
    """Bind whole results and readbacks to authenticated owner/physical receipts."""
    value = validate_execution_case(case)["input"]
    same(raw["input"], value, "The original received a changed whole-operation input")
    require(raw.get("closed") is True and "observationError" not in raw, "Original observation/closure failed")
    if authority is not None:
        same(raw["runtime"], authority, "The raw original runtime lost its exact executable identity")
    if pid is not None:
        require(raw["pid"] == pid, "Original evidence borrowed another process")
    base = Path(raw["fixtureBase"])
    workspace = str(base / "workspace")
    require(base.is_absolute() and raw["workspace"] == workspace, "Original fixture ownership changed")
    same(raw["environment"], {"OPENCLAW_STATE_DIR": str(base / "state"),
         "OPENCLAW_CONFIG_PATH": str(base / "openclaw.json"), "OPENCLAW_HOME": str(base)}, "Original used ambient state")
    same(raw["clock"], {"owner": "node:test", "apis": ["Date"], "nowMs": value["nowMs"],
         "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
         "The original scheduler or non-Date clock was replaced")
    applies = [c for c in raw["calls"] if c["operation"] == "applyShortTermPromotions"]
    require(len(applies) == 1, "Exactly one original apply invocation is required")
    expected_request = {"workspaceDir": workspace, "nowMs": value["nowMs"],
                        "candidates": value["candidates"], **value["options"]}
    expected_after = dict(expected_request)
    if "completion" in value:
        expected_request["consolidation"] = {"subagent": {"complete": "literal host callback"}, "logger": "observed"}
    same(applies[0]["request"], expected_request, "The actual original apply request changed")
    same(applies[0]["requestAfter"], expected_after, "Original request-after lost actual fields")
    outcome = _outcome(applies[0], workspace, value["candidates"])
    decoded = []
    same([s["label"] for s in raw["snapshots"]], ["before", "settlement-before-readback", "after-readback"],
         "Original settlement/readback order changed")
    for snapshot in raw["snapshots"]:
        tree = _tree(snapshot["fsTree"], base)
        rows = _physical(snapshot["physical"], tree, base, raw["databasePath"])
        recall, events = _store_and_events(rows, workspace)
        docs = []
        for name in document_names(value):
            entry = tree.get(str(base / "workspace" / name))
            document = {"path": name, "exists": entry is not None, "kind": entry["kind"] if entry else "missing"}
            if entry and entry["kind"] == "file":
                document.update(bytes=entry["bytes"], text=bytes.fromhex(entry["bytes"]).decode("utf8", "replace"))
            if entry and entry["kind"] == "symlink":
                document["target"] = entry["target"]
            docs.append(document)
        decoded.append({"documents": docs, "recall": recall, "eventRecords": events})
    for label, physical in (("before", decoded[0]), ("after", decoded[2])):
        carriers = [c for c in raw["calls"] if c["operation"] == "readShortTermStore" and c["label"] == label]
        normalizers = [c for c in raw["calls"] if c["operation"] == "normalizeShortTermRecallStore" and c["label"] == label]
        retention = [c for c in raw["calls"] if c["operation"] == "enforceShortTermRecallStoreRetention" and c["label"] == label]
        reads = [c for c in raw["calls"] if c["operation"] == "readStore" and c["label"] == label]
        events = [c for c in raw["calls"] if c["operation"] == "readMemoryHostEventRecords" and c["label"] == label]
        require(len(reads) == len(events) == 1, "A whole original readback was omitted")
        require(len(carriers) == len(normalizers) == len(retention) == 1, "Actual original normalization/retention receipts are required")
        same(carriers[0]["result"], physical["recall"], "Original raw recall read disagrees with actual physical rows")
        same(normalizers[0]["input"], carriers[0]["result"], "The original normalizer received repaired physical input")
        same(retention[0]["inputBefore"], normalizers[0]["result"], "Original retention input lost its genuine normalizer result")
        require(type(retention[0]["returned"]) is int and retention[0]["returned"] >= 0
                and retention[0]["returned"] == len(retention[0]["inputBefore"]["entries"]) - len(retention[0]["result"]["entries"]),
                "The actual original retention return/count was dropped")
        same(reads[0]["result"], retention[0]["result"], "Original recall API disagrees with its real normalized/retained result")
        physical["recall"] = reads[0]["result"]
        same(events[0]["result"], physical["eventRecords"], "Original event API disagrees with actual physical rows")
    # Physical carriers remain raw. The original normalizer may legitimately
    # remove fields (e.g. a session ID on unknown-kind provenance) from its API
    # view without changing the physical carrier. Never reconstruct that policy.
    same(decoded[1]["documents"], decoded[2]["documents"], "Extra readbacks changed documents")
    same(decoded[1]["eventRecords"], decoded[2]["eventRecords"], "Extra readbacks changed persisted events")
    reconstructed = map_get_fixture_paths({"provider": "none", "outcome": outcome,
        "before": decoded[0], "after": decoded[2],
        "completionCalls": [{"request": c["request"], "result": c["result"]} for c in raw["completions"]]}, str(base))
    same(output, reconstructed, "An original result/readback field was dropped, repaired or reassigned")
    same(raw["output"], output, "Original stdout differs from its raw result")
    starts, ends = validate_receipts(raw["ioReceipts"])
    callbacks = [r for r in starts.values() if r["operation"] == "host.complete"]
    require(len(callbacks) == len(raw["completions"]), "Actual original callback call notes were omitted")
    for c, call in zip(raw["completions"], callbacks, strict=True):
        same(call["arguments"], [c["request"]], "Original callback request differs from its live call")
        same(ends[call["sequence"]]["result"], c["result"], "Original callback return differs from its live return")
    return decoded


def replay_case(case, directory: Path):
    validate_execution_case(case)
    evidence = directory / "evidence"
    raw = json.loads((evidence / "native-raw.json").read_text())
    if not isinstance(raw, list) or len(raw) != 1:
        raise ValueError("One genuine original apply observation is required")
    raw = raw[0]
    sdk = json.loads((evidence / "python-raw.json").read_text())
    if isinstance(sdk, list):
        require(len(sdk) == 1, "One actual SDK observation is required")
        sdk = sdk[0]
    stdout = json.loads((directory / "stdout.json").read_text())
    if (raw.get("input") != case["input"] or sdk.get("input") != case["input"]
            or raw.get("closed") is not True or stdout.get("id") != case["id"]
            or stdout.get("ok") is not True or stdout.get("result") != raw.get("output")):
        raise ValueError("Original input, output or settlement observations were changed")
    if differences(map_get_fixture_paths(sdk["unmappedOutput"], sdk["fixtureBase"]), sdk["output"]):
        raise ValueError("SDK public projection changed more than the owned fixture prefix")
    public = stdout["result"]
    if set(public) not in ({"provider", "before", "outcome", "after"},
                           {"provider", "before", "outcome", "after", "completionCalls"}):
        raise ValueError("The complete public envelope is required")
    if "result" in public["outcome"] and set(public["outcome"]["result"]) != {
        "memoryPath", "applied", "appended", "reconciledExisting", "appliedCandidates",
        "rejectedCandidates", "compactedSections", "compactedDates",
    }:
        raise ValueError("An original apply result field was dropped")
    if [snapshot["label"] for snapshot in raw["snapshots"]] != ["before", "settlement-before-readback", "after-readback"]:
        raise ValueError("Settlement must precede additional original readbacks")
    if [snapshot["phase"] for snapshot in sdk["snapshots"]] != ["before-invocation", "actual-settlement-before-extra-readback"]:
        raise ValueError("SDK settlement must precede additional readbacks")
    for snapshot in raw["snapshots"]:
        for database in snapshot["physical"]:
            if database["schemaCount"] != len(database["schema"]):
                raise ValueError("An original physical schema was truncated")
            if any(table["rowCount"] != len(table["rows"]) for table in database["tables"]):
                raise ValueError("Original physical rows were truncated")
    starts, finishes = validate_receipts(raw["ioReceipts"])
    completion = case["input"].get("completion")
    for side in (raw, sdk):
        calls = side["completions"]
        if len(calls) != (1 if completion else 0):
            raise ValueError("The genuine host completion seam was not reached exactly as declared")
        if completion and [m["input"] for m in calls[0]["mutations"]] != completion["mutationsBeforeReturn"]:
            raise ValueError("A declared host mutation did not actually run")
    # Facts, not an inferred acquisition history from absent final lock files.
    observed = [{"call": row["sequence"], "settled": finishes[row["sequence"]]["sequence"],
                 "operation": row["operation"], "arguments": row["arguments"],
                 "result": finishes[row["sequence"]].get("result"),
                 **({"error": finishes[row["sequence"]]["error"]} if "error" in finishes[row["sequence"]] else {})}
                for row in starts.values() if row["operation"] in {"fs.rename", "store[short-term-recall].register",
                    "store[dreaming-memory-backups].register", "store[short-term-locks].compareAndApply"}]
    return {"id": case["id"], "journalCalls": len(starts), "observedPublicationCalls": observed,
            "differences": differences(public, sdk["output"]), "acceptancePointsAwarded": 0}


def validate_receipts(receipts):
    starts, finishes = {}, {}
    for index, row in enumerate(receipts, 1):
        if row["sequence"] != index:
            raise ValueError("The live journal lost its original sequence")
        if row["when"] == "before":
            starts[index] = row
        elif row["when"] == "after":
            call = row["call"]
            if (call not in starts or call in finishes or starts[call]["operation"] != row["operation"]
                    or int(starts[call]["monotonicNs"]) > int(row["monotonicNs"])):
                raise ValueError("A live return/error lost its actual invocation")
            finishes[call] = row
        else:
            raise ValueError("Unknown journal phase")
    if starts.keys() != finishes.keys():
        raise ValueError("An observed owner operation never settled")
    return starts, finishes


def validate_sdk_capture(case, raw, output):
    from types import SimpleNamespace
    from memory_core.consolidation.promotion import PromotionCandidate
    from equivalence.promotion_apply_runtime import _public_result

    value = validate_execution_case(case)["input"]
    same(raw["input"], value, "The SDK received another input")
    same(raw["output"], output, "SDK output differs from its actual raw envelope")
    same(map_get_fixture_paths(raw["unmappedOutput"], raw["fixtureBase"]), output,
         "SDK projection changed more than the exact owned fixture prefix")
    require("richSdkResult" in raw, "The full genuine SDK result is required for these successful literals")
    fields = raw["richSdkResult"]["fields"]
    def candidate(item):
        return PromotionCandidate(**item["fields"])
    run = SimpleNamespace(target=fields["target"], appended=fields["appended"],
        reconciled_existing=fields["reconciled_existing"], compacted_dates=fields["compacted_dates"],
        applied_candidates=[candidate(c) for c in fields["applied_candidates"]],
        rejected_candidates=[SimpleNamespace(candidate=candidate(c["fields"]["candidate"]),
            reason=c["fields"]["reason"], category=c["fields"]["category"]) for c in fields["rejected_candidates"]])
    same(map_get_fixture_paths({"result": _public_result(run, Path(raw["fixtureBase"]) / "workspace")}, raw["fixtureBase"]),
         output["outcome"], "SDK public return lost or repaired a real dataclass field")
    same([s["phase"] for s in raw["snapshots"]], ["before-invocation", "actual-settlement-before-extra-readback"],
         "SDK actual settlement boundary was omitted")
    for label, snapshot in zip(("before", "after"), raw["snapshots"], strict=True):
        tree = {e["path"]: e for e in snapshot["filesystem"]}
        require(len(tree) == len(snapshot["filesystem"]), "An SDK filesystem entry was duplicated")
        require(all("observationError" not in e and "listingError" not in e for e in tree.values()),
                "SDK filesystem observation failed")
        docs = []
        for name in document_names(value):
            entry = tree.get(str(Path(raw["fixtureBase"]) / "workspace" / name))
            doc = {"path": name, "exists": entry is not None, "kind": entry["kind"] if entry else "missing"}
            if entry and entry["kind"] == "file":
                doc.update(bytes=entry["hex"], text=bytes.fromhex(entry["hex"]).decode("utf8", "replace"))
            docs.append(doc)
        same(docs, raw["unmappedOutput"][label]["documents"], "SDK document bytes differ from its physical settlement")
        reads = [r for r in raw["receipts"] if r["operation"] == "readback" and r["phase"] == label]
        require(len(reads) == 1, "Actual SDK canonical readback is missing")
        same(reads[0]["recall"], raw["unmappedOutput"][label]["recall"], "SDK canonical readback was repaired")
        for sql in snapshot["sqlite"]:
            require("observationError" not in sql and sql["schemaCount"] == len(sql["schema"]), "SDK SQL observation failed")
            require({s["name"] for s in sql["schema"] if s["type"] == "table"} == {t["name"] for t in sql["tables"]},
                    "An SDK physical table was dropped")
            require(all(t["rowCount"] == len(t["rows"]) for t in sql["tables"]), "SDK SQL rows were dropped")
    same([r["event"] for r in raw["receipts"] if r["operation"] == "on_event"],
         raw["unmappedOutput"]["after"]["eventRecords"], "SDK callback event fields were dropped")
    completion_calls = []
    callback_invocations = [r for r in raw["receipts"] if r["operation"] == "host.complete" and r["when"] == "before"]
    require(len(callback_invocations) == len(raw["completions"]), "Actual SDK completion invocations were omitted")
    for c, invocation in zip(raw["completions"], callback_invocations, strict=True):
        same(invocation["arguments"], [c["request"]], "SDK callback request differs from its live invocation")
        returns = [r for r in raw["receipts"] if r.get("call") == invocation["sequence"] and r["when"] == "after"]
        require(len(returns) == 1, "Actual SDK callback return was omitted")
        same(returns[0]["result"], c["result"], "SDK callback return differs from its live invocation")
        fields = c["request"]["fields"]
        request = {"agentId": value["options"].get("agentId"), "message": fields["message"],
                   "extraSystemPrompt": fields["system_prompt"], "timeoutMs": fields["timeout_ms"]}
        if fields["model"] is not None:
            request["model"] = fields["model"]
        same(c["publicRequest"], request, "SDK callback projection changed more than declared API key names")
        completion_calls.append({"request": request, "result": {"text": c["result"]}})
    same(output["completionCalls"], completion_calls, "The actual SDK completion request/result was omitted")


def validate_publication_order(case, native, sdk):
    """Validate observed owner order, not hypothetical order from final files."""
    starts, ends = validate_receipts(native["ioReceipts"])
    successful = [r for i, r in starts.items() if "error" not in ends[i]]
    sidecars = [r for r in successful if r["operation"] == "native.openBeneath"
                and len(r["arguments"]) >= 2 and str(r["arguments"][1]).startswith("memory-promotion-")
                and str(r["arguments"][1]).endswith(".lock")]
    acquires, releases = [], []
    for r in successful:
        if r["operation"] == "store[short-term-locks].compareAndApply" and ends[r["sequence"]]["result"].get("status") == "applied":
            mutation = r["arguments"][2]
            if mutation["action"] == "set":
                acquires.append(r)
            elif mutation["action"] == "delete":
                releases.append(r)
    no_live = case["id"] == "promotion-apply-daily-file-quarantine"
    require(len(acquires) == len(releases) == (1 if no_live else 2), "Missing actual initial/commit workspace lease receipts")
    require(len(sidecars) == (0 if no_live else 1), "Promotion sidecar acquisition was not actually observed")
    sdk_locks = [r for r in sdk["receipts"] if r["operation"] == "lock" and r["phase"] == "acquired"]
    require(len(sdk_locks) == (0 if no_live else 1), "SDK sidecar observation is missing")
    if no_live:
        require(not any(r["operation"] == "fs.rename" for r in successful), "The zero-live original published a file")
        require(not any(r["operation"] == "os.replace" for r in sdk["receipts"]), "The zero-live SDK published a file")
        return
    lock = sidecars[0]
    inner, release = acquires[1], releases[1]
    require(ends[acquires[0]["sequence"]]["sequence"] < releases[0]["sequence"] < lock["sequence"] < inner["sequence"],
            "Initial read lease, sidecar and commit lease order changed")
    opened = ends[lock["sequence"]]["result"]
    require(isinstance(opened, dict) and type(opened.get("fd")) is int
            and opened.get("containment") == "kernel-atomic", "The actual native sidecar open receipt was dropped")
    fd = opened["fd"]
    closes = [r for r in successful if r["operation"] == "native.closeOwnedFd" and r["arguments"] == [fd]]
    require(len(closes) == 1, "The actual native sidecar close receipt is missing")
    require(release["sequence"] < closes[0]["sequence"], "Original released the sidecar before its workspace lease")
    rereads = [r for r in successful if r["operation"] == "store[short-term-recall].entriesInKeyRange"
               and inner["sequence"] < r["sequence"] < release["sequence"]]
    require(rereads, "The original never reread authoritative recall under its commit lease")
    publications = [r for r in successful if r["operation"] == "fs.rename" and r["arguments"][1].endswith(("/MEMORY.md", "/DREAMS.md"))]
    for r in publications:
        require(r["arguments"][1] in {str(Path(native["workspace"]) / name) for name in ("MEMORY.md", "DREAMS.md")}
                and Path(r["arguments"][0]).parent == Path(native["workspace"]),
                "Original publication borrowed an unowned document path")
        require(ends[inner["sequence"]]["sequence"] < r["sequence"] < ends[r["sequence"]]["sequence"] < release["sequence"],
                "Original document publication escaped its held workspace lease")
    memory = [r for r in publications if r["arguments"][1].endswith("/MEMORY.md")]
    marked = [r for r in successful if r["operation"] == "store[short-term-recall].register"
              and inner["sequence"] < r["sequence"] < release["sequence"]]
    if memory:
        if native["output"]["before"]["recall"]["entries"]:
            require(marked and ends[memory[-1]["sequence"]]["sequence"] < marked[0]["sequence"],
                    "Original recall marking preceded MEMORY publication")
        else:
            require(not marked and not native["output"]["after"]["recall"]["entries"],
                    "The genuine direct-candidate branch fabricated a stored recall entry")
    dreams = [r for r in publications if r["arguments"][1].endswith("/DREAMS.md")]
    if dreams:
        require(marked and ends[marked[-1]["sequence"]]["sequence"] < dreams[0]["sequence"],
                "Original DREAMS publication preceded recall marking")
    if case["input"].get("completion"):
        complete = [r for r in successful if r["operation"] == "host.complete"]
        require(len(complete) == 1 and ends[complete[0]["sequence"]]["sequence"] < lock["sequence"],
                "The genuine original completion/mutations did not settle before lock acquisition")
    sdk_enter = [r for r in sdk["receipts"] if r["operation"] == "workspace-lock" and r["when"] == "entered"]
    sdk_exit = [r for r in sdk["receipts"] if r["operation"] == "workspace-lock" and r["when"] == "before-exit"]
    require(len(sdk_enter) == len(sdk_exit) == 1, "The SDK commit lease receipt was omitted")
    require(sdk_enter[0]["result"]["fields"]["acquired"] is True,
            "The actual SDK commit lease was not acquired")
    sdk_calls = {r["sequence"]: r for r in sdk["receipts"]
                 if r["operation"] in {"os.replace", "read-recall", "mark-promoted", "host.complete"} and r["when"] == "before"}
    sdk_returns = {r["call"]: r for r in sdk["receipts"] if r.get("call") in sdk_calls and r["when"] == "after"}
    require(sdk_calls.keys() == sdk_returns.keys(), "A genuine SDK owner invocation lost its return/error")
    require(any(r["operation"] == "read-recall" and sdk_enter[0]["sequence"] < r["sequence"] < sdk_exit[0]["sequence"]
                for r in sdk_calls.values()), "The SDK never revalidated authoritative recall under its commit lease")
    replaced = [r for r in sdk_calls.values() if r["operation"] == "os.replace" and "error" not in sdk_returns[r["sequence"]]]
    for r in replaced:
        if r["arguments"][1].endswith(("/MEMORY.md", "/DREAMS.md")):
            require(r["arguments"][1] in {str(Path(sdk["fixtureBase"]) / "workspace" / name) for name in ("MEMORY.md", "DREAMS.md")},
                    "SDK publication borrowed an unowned document path")
    sdk_memory = [r for r in replaced if r["arguments"][1].endswith("/MEMORY.md")]
    sdk_dreams = [r for r in replaced if r["arguments"][1].endswith("/DREAMS.md")]
    sdk_marks = [r for r in sdk_calls.values() if r["operation"] == "mark-promoted"]
    if sdk_memory:
        require(len(sdk_marks) == 1 and sdk_returns[sdk_memory[-1]["sequence"]]["sequence"] < sdk_marks[0]["sequence"],
                "SDK recall marking preceded MEMORY publication")
    if sdk_dreams:
        require(sdk_marks and sdk_returns[sdk_marks[0]["sequence"]]["sequence"] < sdk_dreams[0]["sequence"],
                "SDK DREAMS publication preceded recall marking")
    sdk_preimages = [r for r in replaced if r["arguments"][1].endswith("/consolidation-preimages.json")]
    if sdk_preimages:
        require(sdk_memory and sdk_returns[sdk_preimages[-1]["sequence"]]["sequence"] < sdk_memory[0]["sequence"],
                "SDK preimage publication followed MEMORY publication")
    host_starts = [r for r in sdk["receipts"] if r["operation"] == "host.complete" and r["when"] == "before"]
    host_ends = [r for r in sdk["receipts"] if r["operation"] == "host.complete" and r["when"] == "after"]
    if case["input"].get("completion"):
        require(len(host_starts) == len(host_ends) == 1
                and host_ends[0]["call"] == host_starts[0]["sequence"]
                and host_ends[0]["sequence"] < sdk_locks[0]["sequence"],
                "SDK completion did not settle before the actual sidecar acquisition")
    for r in sdk["receipts"]:
        if r["operation"] == "os.replace" and r["when"] == "before":
            if host_starts and host_starts[0]["sequence"] < r["sequence"] < host_ends[0]["sequence"]:
                require(any(m["operation"] == "write-recall-store" for m in case["input"]["completion"]["mutationsBeforeReturn"])
                        and r["arguments"][1].endswith("/short-term-recall.json"),
                        "An undeclared SDK host publication escaped the commit lease")
                continue
            require(sdk_enter[0]["sequence"] < r["sequence"] < sdk_exit[0]["sequence"],
                    "SDK atomic publication escaped its commit lease")


def validate_pair(case, native, sdk, native_output, sdk_output):
    validate_native_capture(case, native, native_output)
    validate_sdk_capture(case, sdk, sdk_output)
    validate_publication_order(case, native, sdk)
    completion = case["input"].get("completion")
    require(len(native["completions"]) == len(sdk["completions"]) == (1 if completion else 0), "A genuine completion call was omitted")
    if completion:
        n, s = native["completions"][0], sdk["completions"][0]
        same([m["input"] for m in n["mutations"]], completion["mutationsBeforeReturn"], "Original host mutations were changed")
        same([m["input"] for m in s["mutations"]], completion["mutationsBeforeReturn"], "SDK host mutations were changed")
        same(n["result"], {"text": completion["text"]}, "Original completion text was replaced")
        same(s["result"], completion["text"], "SDK completion text was replaced")
        # Requests are compared as public data, not rejected as corrupt evidence
        # merely because the SDK genuinely sends different model-visible bytes.
