"""Managed dreaming definitions, operator-owned rows and historical repairs."""
NOW = 1767225600000
KEY = "memory-core:memory-dreaming-promotion"
TAG = "[managed-by=memory-core.short-term-promotion]"
LIGHT_TAG = "[managed-by=memory-core.dreaming.light]"
REM_TAG = "[managed-by=memory-core.dreaming.rem]"
TOKEN = "__openclaw_memory_core_short_term_promotion_dream__"


def dreaming_input():
    def row(identifier, name, description, text, *, key=None, stamp=NOW - 3000):
        definition = {"id": identifier, "name": name, "description": description, "enabled": True,
                      "agentId": "main", "sessionTarget": "main", "wakeMode": "next-heartbeat",
                      "payload": {"kind": "systemEvent", "text": text},
                      "schedule": {"kind": "cron", "expr": "15 2 * * *", "tz": "UTC"},
                      "state": {"lastRunAtMs": NOW - 86_400_000, "nextRunAtMs": NOW + 8100000,
                                "lastRunStatus": "ok"}, "createdAtMs": stamp, "updatedAtMs": stamp}
        if key is not None:
            definition["declarationKey"] = key
        return definition

    light = row("original-light", "Memory Light Dreaming", LIGHT_TAG, "__openclaw_memory_core_light_sleep__")
    rem = row("original-rem", "Memory REM Dreaming", REM_TAG, "__openclaw_memory_core_rem_sleep__")
    ambiguous = row("operator", "Nightly reading", LIGHT_TAG, "My operator-authored prompt.")
    legacy = row("previous-deep", "Memory Dreaming Promotion", TAG, TOKEN)
    own = row("owned", "My renamed promotion", TAG, TOKEN, key=KEY)
    own.update(sessionTarget="isolated", delivery={"mode": "none"},
               payload={"kind": "agentTurn", "message": TOKEN, "lightContext": True, "timeoutSeconds": 55})
    unchanged = row("elsewhere", "A different automation", "Operator-owned schedule", "Read my private note.")

    def phase(operation, dreaming=None):
        return {"operation": operation, "dreaming": dreaming or {}}

    return {"kind": "dreaming", "nowMs": NOW, "scenarios": [
        {"name": "lifecycle", "jobs": [unchanged], "phases": [phase("reconcile"), phase("reconcile"),
            phase("reconcile", {"frequency": "17 4 * * *", "timezone": "Europe/Istanbul"}),
            phase("reconcile", {"enabled": False})]},
        {"name": "managed-edits", "jobs": [own, {**own, "id": "duplicate", "createdAtMs": NOW - 1000}, unchanged],
         "phases": [phase("reconcile"), phase("reconcile")]},
        {"name": "historical", "jobs": [rem, legacy, light, ambiguous, unchanged], "phases": [
            phase("reconcile"), phase("doctor-preview"), phase("doctor-repair"), phase("doctor-preview"),
            phase("reconcile")]},
        {"name": "retire", "jobs": [light, ambiguous, unchanged],
         "phases": [phase("doctor-preview", {"enabled": False}), phase("doctor-repair", {"enabled": False})]},
    ]}
