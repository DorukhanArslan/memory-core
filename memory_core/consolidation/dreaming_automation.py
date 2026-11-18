"""Manage the dreaming cron declaration and repair historical light/REM jobs."""
from __future__ import annotations

from copy import deepcopy
from functools import cmp_to_key
import json
import os
import time
from uuid import uuid4

from memory_core.automation import AutomationJob, FileAutomationStore, _persisted_job, compute_job_next_run_at_ms
from memory_core.bootstrap._js import js_trim, locale_compare
from memory_core.consolidation._util import js_to_fixed
from memory_core.consolidation.policy import resolve_deep_dreaming_policy

KEY = "memory-core:memory-dreaming-promotion"
NAME = "Memory Dreaming Promotion"
TAG = "[managed-by=memory-core.short-term-promotion]"
EVENT = "__openclaw_memory_core_short_term_promotion_dream__"
PHASES = (
    ("Memory Light Dreaming", "[managed-by=memory-core.dreaming.light]", "__openclaw_memory_core_light_sleep__"),
    ("Memory REM Dreaming", "[managed-by=memory-core.dreaming.rem]", "__openclaw_memory_core_rem_sleep__"),
)


def _text(value):
    return js_trim(value) if isinstance(value, str) else ""


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _invalid_reason(row):
    try:
        parsed = AutomationJob.from_json(row)
    except (ValueError, TypeError) as error:
        return str(error)
    if _persisted_job(parsed, normalize=False) is None:
        return "invalid persisted job"
    return None


def _classify(row):
    if row.get("declarationKey") == KEY:
        return "declared"
    if row.get("declarationKey") is not None:
        return None
    name, description = _text(row.get("name")), _text(row.get("description"))
    payload = _mapping(row.get("payload"))
    kind = _text(payload.get("kind")).lower()
    token = _text(payload.get({"systemevent": "text", "agentturn": "message"}.get(kind)))
    phase = None
    for phase_name, tag, event in PHASES:
        if tag in description:
            if token not in (event, EVENT):
                return "ambiguous"
            phase = "phase"
        if name == phase_name and kind == "systemevent" and token == event:
            phase = "phase"
    if TAG in description:
        return "legacy" if token == EVENT else phase or "ambiguous"
    return "legacy" if name == NAME and token == EVENT else phase


def _desired(config, policy):
    nested = _mapping(_mapping(_mapping(config.get("plugins")).get("entries")).get("memory-core"))
    settings = _mapping(_mapping(nested.get("config") or config).get("dreaming"))
    schedule = {"kind": "cron", "expr": _text(settings.get("frequency")) or "0 3 * * *"}
    timezone = _text(settings.get("timezone")) or _text(_mapping(_mapping(config.get("agents")).get("defaults")).get("userTimezone"))
    if timezone:
        schedule["tz"] = timezone
    description = (f"{TAG} Promote weighted short-term recalls into MEMORY.md (limit={policy.limit}, "
                   f"minScore={js_to_fixed(policy.min_score, 3)}, minRecallCount={policy.min_recall_count}, "
                   f"minUniqueQueries={policy.min_unique_queries}, recencyHalfLifeDays={policy.recency_half_life_days}, "
                   f"maxAgeDays={policy.max_age_days if policy.max_age_days is not None else 'none'}).")
    return {"declarationKey": KEY, "name": NAME, "description": description, "enabled": True,
            "schedule": schedule, "sessionTarget": "isolated", "wakeMode": "now",
            "payload": {"kind": "agentTurn", "message": EVENT, "lightContext": True}, "delivery": {"mode": "none"}}


def _assign_next(job, stamp):
    value = compute_job_next_run_at_ms(AutomationJob.from_json(job), stamp)
    if value is None:
        raise ValueError("Dreaming cron schedule has no valid next run")
    job["state"]["nextRunAtMs"] = value


def _patch(row, desired, stamp):
    before = deepcopy(row)
    for field in ("name", "description", "sessionTarget", "wakeMode"):
        current = _text(row.get(field))
        if (current.lower() if field in ("sessionTarget", "wakeMode") else current) != desired[field]:
            row[field] = desired[field]
    schedule = _mapping(row.get("schedule"))
    updated_schedule = any(_text(schedule.get(k)) != _text(desired["schedule"].get(k)) for k in ("kind", "expr", "tz"))
    enabling = row.get("enabled") is not True
    row["enabled"] = True
    if updated_schedule:
        row["schedule"] = desired["schedule"]
    payload = _mapping(row.get("payload"))
    if _text(payload.get("message")) != EVENT or payload.get("lightContext") is not True:
        row["payload"] = {**payload, **desired["payload"]}
    if _text(_mapping(row.get("delivery")).get("mode")).lower() != "none":
        row["delivery"] = {**_mapping(row.get("delivery")), "mode": "none"}
    if row == before:
        return False
    if updated_schedule or enabling:
        row.setdefault("state", {})["scheduleActivatedAtMs"] = stamp
        _assign_next(row, stamp)
    row["updatedAtMs"] = stamp
    return True


def _order(row, field, fallback):
    return row.get(field) if type(row.get(field)) in (int, float) else fallback


def reconcile_dreaming_jobs(store: FileAutomationStore, config: dict, *, now_ms=None, scheduler_enabled=True):
    """Converge the active managed job under the store lock, preserving operator jobs."""
    stamp = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    policy = resolve_deep_dreaming_policy(config)
    logs = []
    def log(level, message):
        logs.append({"level": level, "message": message})
    if policy.enabled and not scheduler_enabled:
        return logs
    with store._locked() as data:
        rows = data["jobs"]
        compare_ids = cmp_to_key(locale_compare)
        ordered = sorted((row for row in rows if _invalid_reason(row) is None), key=lambda row: (
            _order(_mapping(row.get("state")), "nextRunAtMs", float("inf")), compare_ids(str(row.get("id", "")))))
        categories = [(row, _classify(row)) for row in ordered]
        managed = [row for row, kind in categories if kind == "declared"]
        ambiguous = [row["id"] for row, kind in categories if kind == "ambiguous"]
        if ambiguous:
            log("warn", f"memory-core: cron jobs {', '.join(ambiguous)} retain historical dreaming tags with authored payloads; rows left unchanged. Review their ownership manually.")
        legacy = any(kind in ("legacy", "phase") for _, kind in categories)
        if not policy.enabled:
            remove = {r["id"] for r in managed}
            if remove:
                data["jobs"] = [r for r in rows if not isinstance(r, dict) or not isinstance(r.get("id"), str) or r["id"] not in remove]
                store._save(data)
                log("info", f"memory-core: removed {len(remove)} managed dreaming cron job(s).")
            if not legacy:
                return logs
        if legacy or any(_mapping(r.get("payload")).get("kind") != "agentTurn" for r in managed):
            log("warn", "memory-core: historical dreaming cron jobs require repair; run repair_dreaming_jobs(). Runtime reconciliation left legacy jobs unchanged.")
            return logs
        desired = _desired(config, policy)
        if not managed:
            job = {**desired, "id": str(uuid4()), "createdAtMs": stamp, "updatedAtMs": stamp, "state": {},
                   "payload": {**desired["payload"], "toolsAllow": ["*"]},
                   "scheduledToolPolicy": {"version": 1, "mode": "trusted"}}
            _assign_next(job, stamp)
            rows.append(job)
            log("info", "memory-core: created managed dreaming cron job.")
        else:
            primary, *duplicates = managed
            removing = {row["id"] for row in duplicates}
            if removing:
                data["jobs"] = [r for r in rows if not isinstance(r, dict) or not isinstance(r.get("id"), str) or r["id"] not in removing]
            if _patch(primary, desired, stamp):
                log("info", "memory-core: updated managed dreaming cron job.")
            elif removing:
                log("info", "memory-core: pruned duplicate managed dreaming cron jobs.")
            else:
                return logs
        store._save(data)
    return logs


def _repair_plan(rows, store_path, enabled):
    candidates, warnings = [], []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            warnings.append(f"Could not inspect job row {index} in {store_path}: invalid definition; row retained.")
            continue
        kind = _classify(row)
        if kind == "ambiguous":
            warnings.append(f"Dreaming cron job {row['id']} in {store_path} retains a historical dreaming tag with an authored payload; review its ownership manually. Row retained.")
        elif kind:
            reason = _invalid_reason(row)
            if reason:
                warnings.append(f"Dreaming cron job {row.get('id')} in {store_path} needs cron repair ({reason}); row retained.")
            else:
                candidates.append((row, kind))
    if not enabled or not candidates:
        return {row["id"]: None for row, _ in candidates}, warnings
    priority = {"declared": 0, "legacy": 1, "phase": 2}
    by_id = cmp_to_key(locale_compare)
    primary, kind = min(candidates, key=lambda item: (priority[item[1]], _order(item[0], "createdAtMs", 2**53-1),
                                                     by_id(item[0]["id"])))
    fixed = deepcopy(primary)
    fixed.update(declarationKey=KEY, sessionTarget="isolated")
    payload = _mapping(fixed.get("payload"))
    if payload.get("kind") != "agentTurn" or kind == "phase":
        payload = {k: v for k, v in payload.items() if k != "text"}
        payload.update(kind="agentTurn", message=EVENT)
    fixed["payload"] = {**payload, "lightContext": True}
    fixed["delivery"] = {**_mapping(fixed.get("delivery")), "mode": "none"}
    if kind == "phase":
        for phase_name, tag, _ in PHASES:
            if fixed["name"] == phase_name:
                fixed["name"] = NAME
            if isinstance(fixed.get("description"), str):
                fixed["description"] = fixed["description"].replace(tag, TAG, 1)
    changes = {row["id"]: None for row, _ in candidates if row["id"] != primary["id"]}
    if fixed != primary:
        changes[fixed["id"]] = fixed
    return changes, warnings


def repair_dreaming_jobs(store: FileAutomationStore, config: dict, *, preview=False):
    """Keep the pre-repair file and replace all affected rows under one exclusive lock."""
    enabled = resolve_deep_dreaming_policy(config).enabled
    if preview:
        changes, warnings = _repair_plan(store._load()["jobs"], store.path, enabled)
        messages = ([f"Repair {len(changes)} historical dreaming cron row(s) after a verified JSON backup."] if changes else []) + warnings
        return {"preview": messages} if messages else None
    with store._locked() as data:
        changes, warnings = _repair_plan(data["jobs"], store.path, enabled)
        result = {"changes": [], "warnings": warnings, "warningDisposition": "recoverable"}
        if not changes:
            return result
        source = store.path.read_bytes()
        if json.loads(source) != data:
            raise ValueError("Automation store changed before Doctor backup")
        backup = store.path.with_name(f"{store.path.name}.doctor-cron-{uuid4()}.bak")
        with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
            output.write(source)
            output.flush()
            os.fsync(output.fileno())
        if backup.read_bytes() != source or store.path.read_bytes() != source:
            raise ValueError("Could not verify the automation store backup")
        retained = []
        for row in data["jobs"]:
            if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] in changes:
                replacement = changes[row["id"]]
                if replacement is not None:
                    retained.append(replacement)
            else:
                retained.append(row)
        data["jobs"] = retained
        store._save(data)
        summary = (f"Repaired {len(changes)} historical dreaming cron row(s); survivor IDs, order, and runtime state preserved."
                   if enabled else f"Retired {len(changes)} managed dreaming cron row(s) because dreaming is disabled.")
        result["changes"] = [f"{summary} JSON backup: {backup}."]
        return result
