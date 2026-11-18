"""Run the deterministic narrative provider at the real SDK callback boundary."""
from copy import deepcopy
import traceback

from memory_core.consolidation._util import write_json_atomic
from memory_core.consolidation.rem_phase import RemDreamingOptions
from memory_core.consolidation.store import memory_workspace_lock, read_canonical_recall_store, recall_store_path


def rem_options(opts, workspace, now, calls, receipts):
    def complete(request):
        index = len(calls)
        calls.append(deepcopy(request))
        reply = opts["provider"][index]
        receipt = {"request": deepcopy(request), "reply": deepcopy(reply), "nowMs": now,
                   "caller": [(f.filename, f.name) for f in traceback.extract_stack()[-6:]]}
        receipts.append(receipt)
        if key := reply.get("removeKey"):
            with memory_workspace_lock(workspace, now_ms=now):
                path = recall_store_path(workspace)
                current = read_canonical_recall_store(path, now)
                del current["entries"][key]
                write_json_atomic(path, current)
        if "error" in reply:
            receipt["error"] = {"name": "RuntimeError", "message": reply["error"]}
            raise RuntimeError(reply["error"])
        receipt["returned"] = {"text": reply["text"]}
        return dict(receipt["returned"])

    return {"agent_id": opts["agentId"],
            "rem_options": RemDreamingOptions(enabled=opts["enabled"], min_pattern_strength=opts["minPatternStrength"],
                storage_mode=opts["storageMode"], model=opts["model"],
                complete=complete if opts["provider"] is not None else None)}
