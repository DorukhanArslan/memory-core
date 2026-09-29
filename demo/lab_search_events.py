"""Lab events for memory_search outcomes (the playground and the model's tool calls)."""

from __future__ import annotations

from typing import Any

from demo.lab_runtime import LabRuntime, redact_secrets


def emit_search_outcome(
    lab: LabRuntime,
    result: dict[str, Any],
    *,
    secrets,
    data: dict[str, Any],
    ms: int | None = None,
    turn_id: int | None = None,
    label: str | None = None,
) -> None:
    """One Lab event per memory_search outcome (v2026.9.6 per-corpus results): the whole call
    ``unavailable``; ``search.partial`` for keyword-only memory hits left by the deadline;
    ``search.corpus_unavailable`` when another corpus answered but one failed; else
    ``search.completed``. The event carries ``corpora``, ``timedOut`` and ``stale``."""
    label = label or str(data.get("mode") or "")
    hits = len(result.get("results") or [])
    corpora = result.get("corpora") or []
    failed = [item for item in corpora if item.get("outcome") in ("unavailable", "partial")]
    extra = {
        key: result[key]
        for key in ("corpora", "timedOut", "stale", "partial")
        if key in result
    }
    error = redact_secrets(str(result.get("error")), secrets)
    kwargs = {"turn_id": turn_id} if turn_id is not None else {}
    if result.get("unavailable"):
        lab.bus.emit(
            "search.unavailable",
            summary=f"memory_search kullanılamıyor: {error}",
            data={**data, "error": error, "warning": result.get("warning"),
                  "action": result.get("action"), **extra},
            **kwargs,
        )
    elif result.get("partial"):
        lab.bus.emit(
            "search.partial",
            summary=f"memory_search ({label}): süre doldu, {hits} anahtar kelime sonucu",
            data={**data, "hits": hits, "ms": ms, "warning": result.get("warning"), **extra},
            **kwargs,
        )
    elif failed:
        names = ", ".join(f"{item.get('corpus')} {item.get('outcome')}" for item in failed)
        lab.bus.emit(
            "search.corpus_unavailable",
            summary=f"memory_search ({label}): {hits} sonuç · {names}: {error}",
            data={**data, "hits": hits, "ms": ms, "warning": result.get("warning"),
                  "action": result.get("action"), **extra},
            **kwargs,
        )
    else:
        suffix = f" · {ms} ms" if ms is not None else ""
        lab.bus.emit(
            "search.completed",
            summary=f"memory_search ({label}): {hits} sonuç{suffix}",
            data={**data, "hits": hits, "ms": ms, **extra},
            **kwargs,
        )
