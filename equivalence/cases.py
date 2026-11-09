"""Fresh, model-free equivalence inputs and calls to the actual Python engine.

These adapters translate argument names and serialize results. They contain no
copy of an OpenClaw algorithm and no expected-output snapshots. The reference
side imports the pinned upstream TypeScript implementations at execution time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import random
from typing import Any


@dataclass(frozen=True)
class _Result:
    path: str
    score: float
    source: str
    snippet: str
    startLine: int = 1


def _case(identifier: str, requirement: str, operation: str, value: dict) -> dict:
    return {"id": identifier, "requirement": requirement, "operation": operation, "input": value}


def _number(value: float | str) -> float:
    # Standard JSON has no NaN/Infinity. Named inputs exercise the actual
    # implementations' non-finite branches without non-standard JSON literals.
    if isinstance(value, str):
        return {"nan": math.nan, "infinity": math.inf, "-infinity": -math.inf}[value]
    return value


def build_cases(*, include_prospective: bool = False) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for name, text in (
        ("empty", ""),
        ("ascii", 'router vlan "prod"'),
        ("punctuation", "!!! -- ?"),
        ("unicode", "İstanbul Αθήνα café 日本語"),
        ("combining", "cafe\u0301 café"),
        ("numbers", "version_2 ٣ ²"),
        ("emoji", "☕ coffee 😀"),
        ("controls", "alpha\n beta\tzero\u200bwidth"),
    ):
        cases.append(_case(f"fts-{name}", "lexical.fts-query", "fts-query", {"text": text}))

    for name, text in (
        ("empty", ""),
        ("ascii", "Router VLAN_42 router"),
        ("cjk-contiguous", "我喜欢你好"),
        ("cjk-separated", "我喜欢hello你好"),
        ("japanese-korean", "カタカナ 한국어"),
        ("outside-alphabet", "Привет 😀 Καλημέρα"),
        ("unicode-casing", "İSTANBUL Straße ＡＢＣ"),
    ):
        cases.append(_case(
            f"tokens-{name}", "lexical.tokenization", "tokenization", {"text": text},
        ))

    generated = random.Random(20260909)
    alphabet = "AB_z09 \t-\"我你カ한 caféİé\u0301😀"
    for index in range(16):
        text = "".join(generated.choice(alphabet) for _ in range(80))
        for operation, requirement, prefix in (
            ("fts-query", "lexical.fts-query", "fts"),
            ("tokenization", "lexical.tokenization", "tokens"),
        ):
            cases.append(_case(
                f"{prefix}-generated-{index:02d}", requirement, operation, {"text": text},
            ))

    for index, rank in enumerate((-100, -3, -1, 0, 1, 3, "nan", "infinity", "-infinity")):
        cases.append(_case(f"bm25-{index:02d}", "lexical.bm25", "bm25", {"rank": rank}))

    now_ms = 1_767_225_600_000  # 2026-01-01T00:00:00Z, fixed on both sides.
    base_results = [
        {"path": "memory/2025-12-02.md", "score": 0.8, "source": "memory", "snippet": "old"},
        {"path": "memory/2026-01-01.md", "score": 0.7, "source": "memory", "snippet": "today"},
        {"path": "memory/2026-01-15.md", "score": 0.6, "source": "memory", "snippet": "future"},
    ]
    decay_inputs = [
        ("disabled", {"results": base_results, "enabled": False}),
        ("dated", {"results": base_results}),
        ("evergreen", {"results": [
            {"path": "MEMORY.md", "score": 0.8, "source": "memory", "snippet": "root"},
            {"path": "USER.md", "score": 0.7, "source": "memory", "snippet": "user"},
            {"path": "memory/topics/coffee.md", "score": 0.6,
             "source": "memory", "snippet": "topic"},
        ]}),
        ("path-shapes", {"results": [
            {"path": "./memory/2025-12-02.md", "score": 0.5, "source": "memory", "snippet": "dot"},
            {"path": "memory\\2025-12-02.md", "score": 0.5,
             "source": "memory", "snippet": "windows"},
            {"path": "memory/2025-02-30.md", "score": 0.5,
             "source": "memory", "snippet": "invalid"},
        ]}),
        ("session-metadata", {"results": [
            {"path": "session-a", "score": 0.8, "source": "sessions", "snippet": "indexed"},
            {"path": "session-b", "score": 0.7, "source": "sessions", "snippet": "unknown"},
        ], "sessionSourceMtimes": {"session-a": now_ms - 30 * 86_400_000}}),
        ("zero-half-life", {"results": base_results, "halfLifeDays": 0}),
    ]
    rng = random.Random(20260909)
    for index in range(4):
        age = rng.randint(1, 120)
        decay_inputs.append((f"seeded-{index:02d}", {
            "results": [{"path": f"session-{index}", "score": rng.randrange(1, 100) / 100,
                         "source": "sessions", "snippet": "fixed-seed"}],
            "sessionSourceMtimes": {f"session-{index}": now_ms - age * 86_400_000},
            "halfLifeDays": rng.choice([7, 14, 30, 60]),
        }))
    for name, arguments in decay_inputs:
        cases.append(_case(f"decay-{name}", "retrieval.temporal-decay", "temporal-decay", {
            "nowMs": now_ms, "enabled": True, "halfLifeDays": 30, **arguments,
        }))

    items = [
        {"path": "memory/a.md", "score": 1.0, "source": "memory",
         "snippet": "router vlan alpha", "startLine": 1},
        {"path": "memory/b.md", "score": 0.9, "source": "memory",
         "snippet": "router vlan alpha duplicate", "startLine": 1},
        {"path": "memory/c.md", "score": 0.8, "source": "memory",
         "snippet": "calendar preference", "startLine": 1},
    ]
    for name, arguments in (
        ("disabled", {"enabled": False}),
        ("balanced", {"lambda": 0.7}),
        ("diversity", {"lambda": 0}),
        ("relevance", {"lambda": 1}),
        ("negative-lambda", {"lambda": -1}),
        ("large-lambda", {"lambda": 2}),
        ("ties", {"items": [{**item, "score": 1.0} for item in items]}),
        ("empty-token-text", {"items": [
            {**items[0], "snippet": " Привет "},
            {**items[1], "snippet": "привет"},
            {**items[2], "snippet": "Пока"},
        ], "lambda": 0}),
        ("cjk-text", {"items": [
            {**items[0], "snippet": "我喜欢咖啡"},
            {**items[1], "snippet": "我喜欢咖啡茶"},
            {**items[2], "snippet": "明天开会"},
        ], "lambda": 0}),
        ("empty-punctuation-text", {"items": [
            {**items[0], "snippet": ""},
            {**items[1], "snippet": "!!!"},
            {**items[2], "snippet": "???"},
        ], "lambda": 0}),
    ):
        cases.append(_case(f"mmr-{name}", "retrieval.mmr", "mmr", {
            "items": items, "enabled": True, "lambda": 0.7, **arguments,
        }))

    for name, first, second, third in (
        ("bom-punctuation", "\ufeff!!!\ufeff", "!!!", "???"),
        ("nbsp-cyrillic", "\u00a0Привет\u00a0", "привет", "Пока"),
        ("unicode-space-cyrillic", "\u2003\u2028Привет\u2029\u3000", "привет", "Пока"),
        ("emoji", "\t😀\r\n", "😀", "😃"),
        ("all-whitespace", " \t\r\n", "", "!!!"),
        ("nel-distinct", "\u0085Привет\u0085", "привет", "Пока"),
        ("separator-distinct", "\u001cПривет\u001c", "привет", "Пока"),
        ("zero-width-distinct", "\u200bПривет\u200b", "привет", "Пока"),
    ):
        cases.append(_case(f"mmr-normalization-{name}", "retrieval.mmr", "mmr", {
            "items": [{**item, "snippet": text}
                      for item, text in zip(items, (first, second, third), strict=True)],
            "enabled": True, "lambda": 0,
        }))
    duplicate_items = [
        {**items[0], "snippet": " Привет "},
        {**items[1], "snippet": "привет"},
        {**items[2], "snippet": "Пока"},
    ]
    for name, arguments in (
        ("balanced", {"lambda": 0.5}),
        ("equal-scores", {"items": [{**item, "score": 1.0} for item in duplicate_items]}),
        ("disabled", {"enabled": False}),
    ):
        cases.append(_case(f"mmr-normalization-{name}", "retrieval.mmr", "mmr", {
            "items": duplicate_items, "enabled": True, "lambda": 0, **arguments,
        }))

    for case in cases:
        operation, identifier = case["operation"], case["id"]
        if operation in ("fts-query", "tokenization"):
            primary = "query" if operation == "fts-query" else "tokens"
            case["covers"] = [f"{case['requirement']}.{primary}"]
            if "-generated-" in identifier:
                case["covers"].append(f"{case['requirement']}.generated")
        elif operation == "bm25":
            case["covers"] = ["lexical.bm25.ranks", "lexical.bm25.boundaries"]
        elif operation == "temporal-decay":
            case["covers"] = ["retrieval.temporal-decay.time-inputs"]
            if identifier in (
                "decay-dated", "decay-evergreen", "decay-path-shapes", "decay-session-metadata",
            ):
                case["covers"].append("retrieval.temporal-decay.sources")
        elif operation == "mmr":
            case["covers"] = ["retrieval.mmr.order"]
            if (identifier in ("mmr-cjk-text", "mmr-empty-punctuation-text", "mmr-empty-token-text")
                    or identifier.startswith("mmr-normalization-")):
                case["covers"].append("retrieval.mmr.text-boundaries")
    from equivalence.index_identity import build_index_identity_cases
    from equivalence.vector_scoring import build_vector_scoring_cases
    from equivalence.hybrid_scoring import build_hybrid_scoring_cases
    from equivalence.exact_path_priority import build_exact_path_priority_cases
    from equivalence.importance_project import build_importance_project_cases
    from equivalence.search_contract import build_search_contract_cases
    from equivalence.get_contract import build_get_contract_cases
    from equivalence.deadline_contract import build_deadline_contract_cases
    from equivalence.session_contract import build_session_contract_cases
    from equivalence.transcript_boundary_fixtures import build_transcript_boundary_cases
    from equivalence.turn_trust_fixtures import build_turn_trust_cases
    from equivalence.embedding_cache import build_embedding_cache_cases
    from equivalence.incremental_index import build_incremental_index_cases
    from equivalence.index_publication import build_index_publication_cases
    from equivalence.index_lifecycle import build_index_lifecycle_cases
    from equivalence.markdown_chunking import build_markdown_chunking_cases
    from equivalence.bootstrap_budget import build_bootstrap_budget_cases
    from equivalence.flush_contract import build_flush_contract_cases
    from equivalence.flush_target import build_flush_target_cases
    from equivalence.flush_runtime import build_flush_runtime_cases
    from equivalence.flush_execution import build_flush_execution_cases
    from equivalence.session_projection import build_session_projection_cases
    from equivalence.storage_discovery import build_storage_discovery_cases
    from equivalence.storage_paths import build_storage_path_cases

    cases.extend(build_index_identity_cases())
    cases.extend(build_vector_scoring_cases())
    cases.extend(build_hybrid_scoring_cases())
    cases.extend(build_exact_path_priority_cases())
    cases.extend(build_importance_project_cases())
    cases.extend(build_search_contract_cases())
    cases.extend(build_get_contract_cases())
    cases.extend(build_deadline_contract_cases())
    cases.extend(build_session_contract_cases())
    cases.extend(build_transcript_boundary_cases())
    cases.extend(build_turn_trust_cases())
    from equivalence.durable_session_fixtures import build_durable_session_cases

    cases.extend(build_durable_session_cases())
    cases.extend(build_embedding_cache_cases())
    cases.extend(build_incremental_index_cases())
    cases.extend(build_index_publication_cases())
    cases.extend(build_index_lifecycle_cases())
    cases.extend(build_markdown_chunking_cases())
    cases.extend(build_bootstrap_budget_cases())
    cases.extend(build_flush_contract_cases())
    cases.extend(build_flush_target_cases())
    cases.extend(build_flush_runtime_cases())
    cases.extend(build_flush_execution_cases())
    cases.extend(build_session_projection_cases())
    cases.extend(build_storage_discovery_cases())
    cases.extend(build_storage_path_cases())
    if include_prospective:
        from equivalence.flush_contract import build_prospective_flush_contract_cases
        from equivalence.session_projection import build_prospective_session_projection_cases

        registered = {case["id"] for case in cases}
        cases.extend(case for case in (
            *build_prospective_flush_contract_cases(),
            *build_prospective_session_projection_cases(),
        ) if case["id"] not in registered)
    return cases


def run_python(case: dict[str, Any]) -> Any:
    """Execute the installed Python implementation; never manufacture a match."""
    operation, arguments = case["operation"], case["input"]
    if operation == "turn-trust-runtime":
        from equivalence.turn_trust_runtime import run_turn_trust

        return run_turn_trust(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation == "transcript-boundary-runtime":
        from equivalence.transcript_boundaries import run_transcript_boundary

        return run_transcript_boundary(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation == "durable-session-runtime":
        from equivalence.durable_sessions import run_durable_sessions

        return run_durable_sessions(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation in {"session-contract", "session-contract-runtime", "session-contract-helper-runtime"}:
        from equivalence.session_contract import run_session_contract

        return run_session_contract(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation in {"deadline-partial", "deadline-partial-runtime", "deadline-partial-get-runtime"}:
        from equivalence.deadline_contract import run_deadline_contract

        return run_deadline_contract(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation in {"get-contract", "get-contract-runtime", "get-contract-helper-runtime"}:
        from equivalence.get_contract import run_get_contract

        return run_get_contract(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation in {"search-contract", "search-contract-runtime", "search-contract-helper-runtime"}:
        from equivalence.search_contract import run_search_contract

        return run_search_contract(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation in {"importance-project", "importance-project-runtime"}:
        from equivalence.importance_project import run_importance_project

        return run_importance_project(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation in {"exact-path-priority", "exact-path-runtime"}:
        from equivalence.exact_path_priority import run_exact_path_priority

        return run_exact_path_priority(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation == "hybrid-scoring":
        from equivalence.hybrid_scoring import run_hybrid_scoring

        return run_hybrid_scoring(arguments)
    if operation == "vector-scoring":
        from equivalence.vector_scoring import run_vector_scoring

        return run_vector_scoring(arguments)
    if operation == "markdown-chunking":
        from equivalence.markdown_chunking import run_markdown_chunking

        return run_markdown_chunking(arguments)
    if operation == "bootstrap-budget":
        from equivalence.bootstrap_budget import run_bootstrap_budget

        return run_bootstrap_budget(arguments)
    if operation == "flush-contract":
        from equivalence.flush_contract import run_flush_contract

        return run_flush_contract(arguments)
    if operation == "flush-target":
        from equivalence.flush_target import run_flush_target

        return run_flush_target(arguments)
    if operation == "session-projection":
        from equivalence.session_projection import run_session_projection

        return run_session_projection(arguments)
    if operation == "index-publication":
        from equivalence.index_publication import run_index_publication

        return run_index_publication(arguments)
    if operation == "index-lifecycle-runtime":
        from equivalence.index_lifecycle import run_index_lifecycle

        return run_index_lifecycle(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation == "flush-trigger-runtime":
        from equivalence.flush_runtime import run_flush_runtime

        return run_flush_runtime(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation == "flush-execution-runtime":
        from equivalence.flush_execution import run_flush_execution

        return run_flush_execution(arguments, evidence_directory=case.get("_diagnosticDirectory"))
    if operation == "embedding-cache":
        from equivalence.embedding_cache import run_embedding_cache

        return run_embedding_cache(arguments)
    if operation == "incremental-index":
        from equivalence.incremental_index import run_incremental_index

        return run_incremental_index(arguments)
    if operation == "index-identity":
        from equivalence.index_identity import run_index_identity

        return run_index_identity(arguments)
    if operation == "storage-discovery":
        from equivalence.storage_discovery import run_storage_discovery

        return run_storage_discovery(arguments)
    if operation == "storage-read-paths":
        from equivalence.storage_paths import run_storage_paths

        return run_storage_paths(arguments)
    if operation == "fts-query":
        from memory_core.index.fts import build_fts_query

        return build_fts_query(arguments["text"])
    if operation == "bm25":
        from memory_core.index.fts import bm25_rank_to_score

        return bm25_rank_to_score(_number(arguments["rank"]))
    if operation == "tokenization":
        from memory_core.index.mmr import tokenize

        # The return contract is a mathematical set, not Python/JS set iteration order.
        return sorted(tokenize(arguments["text"]))
    if operation == "temporal-decay":
        from memory_core.index.temporal_decay import (
            TemporalDecayConfig,
            apply_temporal_decay_to_hybrid_results,
        )

        results = [_Result(**value) for value in arguments["results"]]
        result = apply_temporal_decay_to_hybrid_results(
            results,
            temporal_decay=TemporalDecayConfig(
                enabled=arguments["enabled"], half_life_days=arguments["halfLifeDays"],
            ),
            now_ms=arguments["nowMs"],
            session_source_mtimes=arguments.get("sessionSourceMtimes"),
        )
        # startLine is not part of this operation's input, so do not add it to the result.
        return [{key: value for key, value in asdict(item).items() if key != "startLine"}
                for item in result]
    if operation == "mmr":
        from memory_core.index.mmr import apply_mmr_to_hybrid_results

        result = apply_mmr_to_hybrid_results(
            [_Result(**value) for value in arguments["items"]],
            enabled=arguments["enabled"], lambda_=arguments["lambda"],
        )
        return [asdict(item) for item in result]
    raise ValueError(f"Unsupported equivalence operation: {operation}")
