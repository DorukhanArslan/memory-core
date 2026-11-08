from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from memory_core.index._js_exp import exp as _js_exp
from memory_core.memory_paths import parse_dated_memory_path

T = TypeVar("T")

DAY_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class TemporalDecayConfig:
    enabled: bool = False
    half_life_days: float = 30.0


def _to_decay_lambda(half_life_days: float) -> float:
    if not math.isfinite(half_life_days) or half_life_days <= 0:
        return 0.0
    return math.log(2) / half_life_days


def calculate_temporal_decay_multiplier(*, age_in_days: float, half_life_days: float) -> float:
    lambda_ = _to_decay_lambda(half_life_days)
    clamped_age = max(0.0, age_in_days)
    if lambda_ <= 0 or not math.isfinite(clamped_age):
        return 1.0
    return _js_exp(-lambda_ * clamped_age)


def apply_temporal_decay_to_score(
    *,
    score: float,
    age_in_days: float,
    half_life_days: float,
) -> float:
    return score * calculate_temporal_decay_multiplier(
        age_in_days=age_in_days,
        half_life_days=half_life_days,
    )


def _parse_memory_date_from_path(file_path: str) -> datetime | None:
    normalized = file_path.replace("\\", "/").removeprefix("./")
    parts = parse_dated_memory_path(normalized)
    if parts is None:
        return None

    year, month, day = parts
    try:
        return datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None


def _is_evergreen_memory_path(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/").removeprefix("./")
    if normalized in ("MEMORY.md", "USER.md"):
        return True
    if not normalized.startswith("memory/"):
        return False
    return parse_dated_memory_path(normalized) is None


def _time_clip(timestamp_ms: float | None) -> int | None:
    """The millisecond instant retained by JavaScript's numeric Date constructor."""
    if timestamp_ms is None or not math.isfinite(timestamp_ms) or abs(timestamp_ms) > 8.64e15:
        return None
    return math.trunc(timestamp_ms)


def _extract_timestamp(
    *,
    file_path: str,
    source: str | None,
    workspace_dir: str | None,
    session_source_mtimes: Mapping[str, float | None] | None = None,
    memory_source_mtimes: Mapping[str, float | None] | None = None,
) -> int | None:
    if source == "sessions":
        # Session paths are logical identities, not workspace files: ranking uses the indexed
        # source activity (a host-supplied mtime in ms), never a same-named file.
        mtime = (session_source_mtimes or {}).get(file_path)
        return _time_clip(mtime)
    from_path = _parse_memory_date_from_path(file_path)
    if from_path is not None:
        return int(from_path.timestamp() * 1000)

    if source == "memory" and _is_evergreen_memory_path(file_path):
        return None

    if source == "memory" and memory_source_mtimes is not None:
        # An explicit indexed map, even empty, is authoritative for remote
        # files. Never replace missing host metadata with a local file mtime.
        mtime = memory_source_mtimes.get(file_path)
        return _time_clip(mtime)

    if workspace_dir is None:
        return None

    path = Path(file_path)
    absolute_path = path if path.is_absolute() else Path(workspace_dir) / path
    try:
        return _time_clip(absolute_path.stat().st_mtime * 1000)
    except OSError:
        return None


def _age_in_days_from_timestamp(timestamp: int, now_ms: int) -> float:
    age_ms = max(0.0, now_ms - timestamp)
    return age_ms / DAY_MS


def apply_temporal_decay_to_hybrid_results(
    results: list[T],
    *,
    temporal_decay: TemporalDecayConfig | None = None,
    workspace_dir: str | None = None,
    now_ms: int | None = None,
    session_source_mtimes: Mapping[str, float | None] | None = None,
    memory_source_mtimes: Mapping[str, float | None] | None = None,
) -> list[T]:
    config = temporal_decay or TemporalDecayConfig()
    if not config.enabled:
        return list(results)

    effective_now_ms = (
        now_ms if now_ms is not None else int(datetime.now(tz=UTC).timestamp() * 1000)
    )
    timestamp_cache: dict[tuple[str | None, str], int | None] = {}
    decayed: list[T] = []

    for entry in results:
        source = getattr(entry, "source", None)
        path = getattr(entry, "path")
        cache_key = (source, path)
        if cache_key not in timestamp_cache:
            timestamp_cache[cache_key] = _extract_timestamp(
                file_path=path,
                source=source,
                workspace_dir=workspace_dir,
                session_source_mtimes=session_source_mtimes,
                memory_source_mtimes=memory_source_mtimes,
            )

        timestamp = timestamp_cache[cache_key]
        if timestamp is None:
            decayed.append(entry)
            continue

        decayed_score = apply_temporal_decay_to_score(
            score=getattr(entry, "score"),
            age_in_days=_age_in_days_from_timestamp(timestamp, effective_now_ms),
            half_life_days=config.half_life_days,
        )
        if dataclasses.is_dataclass(entry) and not getattr(entry, "__dataclass_params__").frozen:
            entry.score = decayed_score  # type: ignore[attr-defined]
            decayed.append(entry)
        else:
            decayed.append(dataclasses.replace(entry, score=decayed_score))  # type: ignore[type-var]

    return decayed
