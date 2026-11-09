"""Real SDK caller for the independent eight-input development capability."""
from copy import deepcopy
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
from unittest.mock import patch

from equivalence.get_contract import map_get_fixture_paths
from equivalence.promotion_apply_family import validate_case
from equivalence.promotion_apply_runtime import (
    _OPTIONS, _documents, _error_record, _filesystem_snapshot, _json_value,
    _public_result, _safe_path, _source_owners, _sqlite_snapshot,
)


def run_family_sdk(case, evidence_directory: Path):
    value = validate_case(case)["input"]
    from memory_core.config import MemoryConfig
    from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
    from memory_core.consolidation.llm_consolidation import DeepConsolidation, LlmConsolidationOptions
    from memory_core.consolidation.origins import MemoryEntryOriginLedger
    from memory_core.consolidation.promotion import PromotionCandidate, run_short_term_promotion
    from memory_core.consolidation.store import read_canonical_recall_store, recall_store_path, write_recall_store
    from memory_core.flags import FeatureFlags
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.consolidation import promotion

    evidence_directory.mkdir(parents=True, exist_ok=True)
    root = evidence_directory / "sdk-promotion-apply-fixture"
    root.mkdir()
    workspace = root / "workspace"
    workspace.mkdir()
    raw = {"input": deepcopy(value), "fixtureBase": str(root), "receipts": [], "snapshots": [], "completions": []}
    events = []

    def receipt(operation, **facts):
        raw["receipts"].append({"sequence": len(raw["receipts"]) + 1, "operation": operation, **_json_value(facts)})

    def observe_call(operation, original):
        def call(*args, **kwargs):
            receipt(operation, when="before", arguments=args, keywords=kwargs)
            try:
                returned = original(*args, **kwargs)
            except BaseException as error:
                receipt(operation, when="after", error=error)
                raise
            receipt(operation, when="after", result=returned)
            return returned
        return call

    @contextmanager
    def observe_workspace_lock(*args, **kwargs):
        receipt("workspace-lock", when="before", arguments=args, keywords=kwargs)
        with original_workspace_lock(*args, **kwargs) as locked:
            receipt("workspace-lock", when="entered", result=locked)
            try:
                yield locked
            finally:
                receipt("workspace-lock", when="before-exit")
        receipt("workspace-lock", when="released")

    def snapshot(phase):
        tree = _filesystem_snapshot(root)
        raw["snapshots"].append({"phase": phase, "filesystem": tree, "sqlite": [
            _sqlite_snapshot(Path(item["path"])) for item in tree
            if item.get("hex", "").startswith(b"SQLite format 3\x00".hex())]})

    names = list(dict.fromkeys([*value["files"], *(c["path"] for c in value["candidates"]),
                               *(c["path"] for c in value["recall"]["entries"].values()), "MEMORY.md", "DREAMS.md"]))

    def observe(phase):
        documents, rich = _documents(workspace, names)
        recall = read_canonical_recall_store(recall_store_path(workspace), value["nowMs"])
        receipt("readback", phase=phase, documents=rich, recall=recall)
        return {"documents": documents, "recall": recall, "eventRecords": deepcopy(events)}

    try:
        for name in value["directories"]:
            _safe_path(workspace, name).mkdir(parents=True, exist_ok=True)
        for name, content in value["files"].items():
            target = _safe_path(workspace, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf8", newline="")
        write_recall_store(recall_store_path(workspace), deepcopy(value["recall"]))
        provenance = MemoryArtifactProvenanceStore(root / "provenance.sqlite")
        mapping = {"relativePath": "relative_path", "contentBefore": "content_before", "contentAfter": "content_after",
                   "originClass": "origin_class", "observedAt": "observed_at"}
        for entry in value.get("artifactProvenanceWrites", []):
            rollback = provenance.record_write(workspace_dir=workspace, **{mapping[k]: v for k, v in entry.items()})
            receipt("record_write", request=entry, returnedType=type(rollback).__name__)
        config = MemoryConfig(workspace_dir=workspace, store_path=root / "index.sqlite", flags=FeatureFlags(vector_search=False))
        store = SQLiteMemoryStore(config, None)
        options = {**_OPTIONS, "agentId": "agent_id", "workspaceAgentIds": "workspace_agent_ids"}
        kwargs = {options[key]: item for key, item in value["options"].items()}
        if "completion" in value:
            def complete(request):
                entry = {"request": _json_value(request), "mutations": []}
                raw["completions"].append(entry)
                for mutation in value["completion"]["mutationsBeforeReturn"]:
                    if mutation["operation"] == "write-recall-store":
                        result = write_recall_store(recall_store_path(workspace), deepcopy(mutation["value"]))
                    else:
                        target = _safe_path(workspace, mutation["path"])
                        mode = "a" if mutation["operation"] == "append-file" else "w"
                        with target.open(mode, encoding="utf8", newline="") as stream:
                            result = stream.write(mutation["text"])
                    entry["mutations"].append({"input": mutation, "result": _json_value(result)})
                entry["result"] = value["completion"]["text"]
                return entry["result"]
            kwargs["consolidation"] = DeepConsolidation(model=complete, options=LlmConsolidationOptions(enabled=True))
        kwargs["origins"] = MemoryEntryOriginLedger(lambda agent: root / "agents" / agent / "memory.sqlite")
        before = observe("before")
        snapshot("before-invocation")

        def on_event(event):
            events.append(deepcopy(event))
            receipt("on_event", event=event)

        original_workspace_lock = promotion.acquire_short_term_promotion_lock
        try:
            with ExitStack() as observers:
                observers.enter_context(patch.object(promotion, "acquire_short_term_promotion_lock", observe_workspace_lock))
                for target, name, label in [(os, "replace", "os.replace"),
                                            (promotion, "read_recall_store", "read-recall"),
                                            (promotion, "_mark_promoted", "mark-promoted")]:
                    observers.enter_context(patch.object(target, name, observe_call(label, getattr(target, name))))
                run = run_short_term_promotion(config=config, store=store, now_ms=value["nowMs"],
                    candidates=[PromotionCandidate.from_json(c) for c in value["candidates"]],
                    artifact_provenance=provenance, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                    state_dir=root / "state", on_event=on_event,
                    lock_observer=lambda phase, path: receipt("lock", phase=phase, path=path), **kwargs)
        except BaseException as error:
            outcome = {"error": _error_record(error)}
        else:
            outcome = {"result": _public_result(run, workspace)}
            raw["richSdkResult"] = _json_value(run)
        snapshot("actual-settlement-before-extra-readback")
        output = {"provider": "none", "outcome": outcome, "before": before, "after": observe("after")}
        raw["indexReadbacks"] = {"published": _json_value(store.read_published_index()), "chunks": store.count_chunks()}
        raw["unmappedOutput"] = output
        raw["output"] = map_get_fixture_paths(output, str(root))
        return raw["output"]
    finally:
        raw["sourceOwners"] = _source_owners()
        (evidence_directory / "python-raw.json").write_text(json.dumps(raw, ensure_ascii=True, indent=2) + "\n")
