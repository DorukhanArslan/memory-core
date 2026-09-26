"""Private helpers shared by the consolidation modules.

Scalar coercion, timestamps, hashing and atomic JSON writes used by the
short-term recall store, promotion and dreaming ports
(``extensions/memory-core/src/short-term-promotion.ts`` at OpenClaw pin
4c42815348). Not part of the public API.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DAY_MS = 24 * 60 * 60 * 1000


def normalize_snippet(raw: str) -> str:
    """Collapse whitespace runs and trim (upstream ``normalizeSnippet``)."""
    return " ".join(raw.strip().split())


def hash_query(value: str) -> str:
    """First 12 hex chars of SHA-1 (upstream ``hashQuery``)."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def append_distinct(values: list[str], value: str, limit: int) -> list[str]:
    next_values = [item for item in values if item]
    if value and value not in next_values:
        next_values.append(value)
    return next_values[-limit:]


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def to_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def clamp_score(value: float) -> float:
    """Clamp to [0, 1]; non-finite values become 0 (upstream ``clampScore``)."""
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def iso_ms(now_ms: int) -> str:
    """UTC ISO-8601 with milliseconds and ``Z`` (JS ``Date.prototype.toISOString``)."""
    dt = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ms(value: str, fallback: int) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return fallback


def parse_day_ms(value: str) -> int | None:
    try:
        return int(datetime.fromisoformat(f"{value}T00:00:00+00:00").timestamp() * 1000)
    except ValueError:
        return None


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` as indented JSON via a same-directory temp file and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def exception_message(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


def unified_diff(before: str, after: str, target: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{target}",
            tofile=f"b/{target}",
        )
    )
