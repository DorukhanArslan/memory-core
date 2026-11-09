"""Actual SDK ranking calls and complete own-store observations."""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile


_OPTIONS = {"limit": "limit", "minScore": "min_score", "minRecallCount": "min_recall_count",
            "minUniqueQueries": "min_unique_queries", "maxAgeDays": "max_age_days",
            "includePromoted": "include_promoted", "recencyHalfLifeDays": "recency_half_life_days",
            "weights": "weights"}


def _files(root):
    return [{"path": path.relative_to(root).as_posix(), "hex": path.read_bytes().hex(),
             "stat": {"size": path.stat().st_size, "mode": path.stat().st_mode,
                      "mtimeNs": path.stat().st_mtime_ns, "inode": path.stat().st_ino}}
            for path in sorted(root.rglob("*")) if path.is_file()]


def run_promotion_ranking(arguments, *, evidence_directory=None):
    import memory_core
    from memory_core.config import MemoryConfig
    from memory_core.consolidation._util import write_json_atomic
    from memory_core.consolidation.promotion import (
        evaluate_short_term_promotion_candidates, rank_short_term_promotion_candidates,
    )
    from memory_core.consolidation.store import (
        phase_signal_store_path,
        read_canonical_phase_signal_store as read_phase_signal_store,
        read_canonical_recall_store as read_recall_store,
        recall_store_path, write_recall_store,
    )

    owner = Path(__file__).resolve().parents[1]
    if not Path(memory_core.__file__).resolve().is_relative_to(owner):
        raise RuntimeError("Ranking imported an SDK outside its owning worktree")
    value = deepcopy(arguments)
    if value["kind"] != "promotion-ranking":
        raise ValueError("An explicit promotion ranking profile is required")
    for query in value["queries"]:
        if set(query["options"]) - _OPTIONS.keys():
            raise ValueError("A ranking option is outside the declared public interface")
        if not {"limit", "minScore", "minRecallCount", "minUniqueQueries"} <= query["options"].keys():
            raise ValueError("The common ranking profile supplies explicit score and count options")
    with tempfile.TemporaryDirectory(prefix="sdk-promotion-ranking-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        workspace.mkdir()
        config = MemoryConfig(workspace_dir=workspace)
        raw = {"input": deepcopy(value), "pid": os.getpid(), "fixtureBase": str(root),
               "implementationRoot": str(owner), "calls": [], "snapshots": []}
        store = deepcopy(value["store"])
        write_recall_store(recall_store_path(workspace), store)
        raw["calls"].append({"operation": "write_recall_store", "arguments": deepcopy(value["store"]),
                             "postCallArguments": deepcopy(store), "result": None})
        write_json_atomic(phase_signal_store_path(workspace), deepcopy(value["phase"]))
        raw["calls"].append({"operation": "seed_phase_file", "arguments": deepcopy(value["phase"]), "result": None})

        def observe():
            return {"recall": read_recall_store(recall_store_path(workspace), value["nowMs"]),
                    "phase": read_phase_signal_store(phase_signal_store_path(workspace), value["nowMs"])}

        output = {"before": observe(), "queries": []}
        raw["snapshots"].append({"phase": "before", "logical": deepcopy(output["before"]), "files": _files(root)})
        for query in value["queries"]:
            options = {_OPTIONS[key]: item for key, item in query["options"].items()}
            candidates = rank_short_term_promotion_candidates(config=config, now_ms=value["nowMs"], **options)
            evaluations = evaluate_short_term_promotion_candidates(
                config=config, now_ms=value["nowMs"], **{key: item for key, item in options.items() if key != "limit"})
            actual = [candidate.to_json() for candidate in candidates]
            raw["calls"].append({"operation": "rank_short_term_promotion_candidates", "label": query["label"],
                "options": deepcopy(query["options"]), "result": deepcopy(actual),
                "candidateDataclasses": [asdict(item) for item in candidates],
                "evaluationDataclasses": [asdict(item) for item in evaluations]})
            output["queries"].append({"label": query["label"], "candidates": actual})
        output["after"] = observe()
        raw["snapshots"].append({"phase": "after", "logical": deepcopy(output["after"]), "files": _files(root)})
        raw["output"] = deepcopy(output)
        if evidence_directory is not None:
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "python-raw.json").write_text(
                json.dumps([raw], ensure_ascii=True, allow_nan=False, indent=2) + "\n", encoding="utf-8")
        return output
