from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

DAY_MS = 24 * 60 * 60 * 1000
DATED_MEMORY_PATH_RE = re.compile(r"(?:^|/)memory/(\d{4})-(\d{2})-(\d{2})\.md$")


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
    return math.exp(-lambda_ * clamped_age)


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
    match = DATED_MEMORY_PATH_RE.search(normalized)
    if match is None:
        return None

    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None


def _is_evergreen_memory_path(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/").removeprefix("./")
    if normalized == "MEMORY.md":
        return True
    if not normalized.startswith("memory/"):
        return False
    return DATED_MEMORY_PATH_RE.search(normalized) is None


def _extract_timestamp(
    *,
    file_path: str,
    source: str | None,
    workspace_dir: str | None,
) -> datetime | None:
    from_path = _parse_memory_date_from_path(file_path)
    if from_path is not None:
        return from_path

    if source == "memory" and _is_evergreen_memory_path(file_path):
        return None

    if workspace_dir is None:
        return None

    path = Path(file_path)
    absolute_path = path if path.is_absolute() else Path(workspace_dir) / path
    try:
        return datetime.fromtimestamp(absolute_path.stat().st_mtime, tz=UTC)
    except OSError:
        return None


def _age_in_days_from_timestamp(timestamp: datetime, now_ms: int) -> float:
    age_ms = max(0.0, now_ms - timestamp.timestamp() * 1000)
    return age_ms / DAY_MS


def apply_temporal_decay_to_hybrid_results(
    results: list[T],
    *,
    temporal_decay: TemporalDecayConfig | None = None,
    workspace_dir: str | None = None,
    now_ms: int | None = None,
) -> list[T]:
    config = temporal_decay or TemporalDecayConfig()
    if not config.enabled:
        return list(results)

    effective_now_ms = (
        now_ms if now_ms is not None else int(datetime.now(tz=UTC).timestamp() * 1000)
    )
    timestamp_cache: dict[tuple[str | None, str], datetime | None] = {}
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
        decayed.append(entry.__class__(**{**entry.__dict__, "score": decayed_score}))

    return decayed
