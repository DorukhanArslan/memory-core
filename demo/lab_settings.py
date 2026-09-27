"""Lab settings (process memory only; nothing is written to ``.env``) and provider checks.

Keys are never accepted here and never returned: they travel request-scoped in
``openai.apiKey`` / ``embedding.apiKey`` or come from the environment, and the
settings only say where a key would come from (``keySource``).
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from demo.chat_engine import DEFAULT_OPENAI_MODEL_SOURCE
from demo.lab_runtime import (
    CONTEXT_INJECTION_MODES,
    LAB_FLAGS,
    LAB_TIMEZONE,
    LAYOUTS,
    WARNING_MODES,
    LabError,
    LabRuntime,
    optional_text,
    redact_secrets,
    safe_exception_message,
)
from memory_core.bootstrap import DEFAULT_BOOTSTRAP_MAX_CHARS, DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS
from memory_core.heartbeat import resolve_heartbeat_interval_ms
from memory_core.memory_flush import (
    DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR,
    DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
    build_memory_flush_plan,
    resolve_memory_flush_threshold,
)


def settings_payload(lab: LabRuntime) -> dict[str, Any]:
    settings = lab.settings
    chat = lab.resolve_chat({})
    embedding = lab.resolve_embedding({})
    window = settings.effective_context_window_tokens
    return {
        "chat": {
            "baseUrl": chat.base_url,
            "model": chat.model,
            "keySource": "env" if chat.has_key else "none",
            "keyEnv": "MEMORY_CORE_DEMO_OPENAI_API_KEY",
            "defaultModel": dict(DEFAULT_OPENAI_MODEL_SOURCE),
            "lastCheck": lab.provider_status.get("chat"),
        },
        "embedding": {
            "baseUrl": embedding.base_url,
            "model": embedding.model if embedding.available else None,
            "keySource": embedding.key_source if embedding.key_source in {"env", "none"} else "env",
            "keyEnv": "MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY",
            "mode": embedding.mode,
            "reason": embedding.reason,
            "lastCheck": lab.provider_status.get("embedding"),
        },
        "layout": settings.layout,
        "budgets": {
            "maxChars": settings.max_chars,
            "totalMaxChars": settings.total_max_chars,
            "warningMode": settings.warning_mode,
            "defaults": {
                "maxChars": DEFAULT_BOOTSTRAP_MAX_CHARS,
                "totalMaxChars": DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
                "warningMode": "always",
            },
        },
        "contextInjection": settings.context_injection,
        "flush": _flush_settings(settings.context_window_tokens, window),
        "heartbeat": {
            "every": settings.heartbeat_every,
            "everyMs": resolve_heartbeat_interval_ms(settings.heartbeat_every),
            "ackMaxChars": settings.heartbeat_ack_max_chars,
            "lightContext": settings.heartbeat_light_context,
        },
        "flags": {
            name: {"on": settings.flags.get(name, spec[0]), "label": spec[1], "extension": spec[2]}
            for name, spec in LAB_FLAGS.items()
        },
        "timezone": LAB_TIMEZONE,
        "workspace": {"root": str(lab.root)},
        "liveWorkspace": {"root": str(lab.live_root)},
    }


def _flush_settings(configured_window: int | None, window: int) -> dict[str, Any]:
    """v2026.9.6 flush thresholds for the window (flush-plan.ts, agent-runner-memory.ts:1254-1260).

    The reserve floor and the soft threshold derive from the window; the flush plan has no
    reserve or prompt settings any more, so the window is the Lab's only flush input.
    """
    plan = build_memory_flush_plan(workspace_dir=None, context_window_tokens=window)
    return {
        "mode": "threshold",
        "contextWindowTokens": configured_window,
        "effectiveContextWindowTokens": window,
        "reserveTokensFloor": plan.reserve_tokens_floor,
        "softThresholdTokens": plan.soft_threshold_tokens,
        "threshold": resolve_memory_flush_threshold(
            context_window_tokens=window,
            reserve_tokens_floor=plan.reserve_tokens_floor,
            soft_threshold_tokens=plan.soft_threshold_tokens,
        ),
        "defaults": {
            "reserveTokensFloor": DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR,
            "softThresholdTokens": DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
        },
    }


def _contains_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key == "apiKey" or _contains_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item) for item in value)
    return False


def _url_or_none(value: Any, name: str) -> str | None:
    text = optional_text(value)
    if text is None:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LabError(400, f"{name} must be an http(s) URL", code="invalid_setting")
    return text.rstrip("/")


def _positive_int_or_none(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LabError(400, f"{name} must be a positive integer or null", code="invalid_setting")
    return value


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise LabError(400, f"{key} must be an object", code="invalid_setting")
    return value


def update_settings(lab: LabRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    if _contains_key(payload):
        raise LabError(
            400,
            "settings never store keys; send them per request (openai.apiKey / embedding.apiKey) "
            "or set them in the environment",
            code="key_not_accepted",
        )
    settings = lab.settings
    changed: list[str] = []
    chat = _section(payload, "chat")
    if "baseUrl" in chat:
        settings.chat_base_url = _url_or_none(chat["baseUrl"], "chat.baseUrl")
        changed.append("chat.baseUrl")
    if "model" in chat:
        settings.chat_model = optional_text(chat["model"])
        changed.append("chat.model")
    embedding = _section(payload, "embedding")
    if "baseUrl" in embedding:
        settings.embedding_base_url = _url_or_none(embedding["baseUrl"], "embedding.baseUrl")
        changed.append("embedding.baseUrl")
    if "model" in embedding:
        settings.embedding_model = optional_text(embedding["model"])
        changed.append("embedding.model")
    if "layout" in payload:
        if payload["layout"] not in LAYOUTS:
            raise LabError(400, "layout must be 'memory-core' or 'upstream'", code="invalid_setting")
        settings.layout = payload["layout"]
        changed.append("layout")
    budgets = _section(payload, "budgets")
    if "maxChars" in budgets:
        settings.max_chars = _positive_int_or_none(budgets["maxChars"], "budgets.maxChars") or DEFAULT_BOOTSTRAP_MAX_CHARS
        changed.append("budgets.maxChars")
    if "totalMaxChars" in budgets:
        settings.total_max_chars = (
            _positive_int_or_none(budgets["totalMaxChars"], "budgets.totalMaxChars") or DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS
        )
        changed.append("budgets.totalMaxChars")
    if "warningMode" in budgets:
        if budgets["warningMode"] not in WARNING_MODES:
            raise LabError(400, "budgets.warningMode must be off, once or always", code="invalid_setting")
        settings.warning_mode = budgets["warningMode"]
        changed.append("budgets.warningMode")
    if "contextInjection" in payload:
        if payload["contextInjection"] not in CONTEXT_INJECTION_MODES:
            raise LabError(400, "contextInjection must be always, continuation-skip or never", code="invalid_setting")
        settings.context_injection = payload["contextInjection"]
        changed.append("contextInjection")
    flush = _section(payload, "flush")
    if "mode" in flush and flush["mode"] != "threshold":
        raise LabError(
            400,
            "flush.mode is 'threshold' (upstream trigger, D1); the per-turn demo flush was removed",
            code="invalid_setting",
        )
    if "contextWindowTokens" in flush:
        settings.context_window_tokens = _positive_int_or_none(flush["contextWindowTokens"], "flush.contextWindowTokens")
        changed.append("flush.contextWindowTokens")
    heartbeat = _section(payload, "heartbeat")
    if "every" in heartbeat:
        every = heartbeat["every"]
        if not isinstance(every, str) or (every.strip() and resolve_heartbeat_interval_ms(every) is None):
            raise LabError(400, "heartbeat.every must be a duration like 30m (empty disables)", code="invalid_setting")
        settings.heartbeat_every = every.strip()
        changed.append("heartbeat.every")
    if "ackMaxChars" in heartbeat:
        value = heartbeat["ackMaxChars"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LabError(400, "heartbeat.ackMaxChars must be a non-negative integer", code="invalid_setting")
        settings.heartbeat_ack_max_chars = value
        changed.append("heartbeat.ackMaxChars")
    if "lightContext" in heartbeat:
        if not isinstance(heartbeat["lightContext"], bool):
            raise LabError(400, "heartbeat.lightContext must be a boolean", code="invalid_setting")
        settings.heartbeat_light_context = heartbeat["lightContext"]
        changed.append("heartbeat.lightContext")
    flags = _section(payload, "flags")
    for name, value in flags.items():
        if name not in LAB_FLAGS:
            raise LabError(400, f"unknown flag {name}", code="invalid_setting")
        on = value.get("on") if isinstance(value, dict) else value
        if not isinstance(on, bool):
            raise LabError(400, f"flag {name} must be a boolean", code="invalid_setting")
        settings.flags[name] = on
        changed.append(f"flags.{name}")
    unknown = set(payload) - {"chat", "embedding", "layout", "budgets", "contextInjection", "flush", "heartbeat", "flags"}
    if unknown:
        raise LabError(400, f"unknown settings: {', '.join(sorted(unknown))}", code="invalid_setting")
    if changed:
        lab.bus.emit("settings.changed", summary=f"ayar değişti: {', '.join(changed)}", data={"changed": changed})
    return settings_payload(lab)


def provider_check(lab: LabRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    """One short completion or one embedding call; errors are redacted."""
    from demo.lab_api import resolve_chat_engine

    secrets = lab.secret_values(payload)
    target = "embedding" if "embedding" in payload and "openai" not in payload else "chat"
    started = time.perf_counter()
    result: dict[str, Any]
    try:
        if target == "chat":
            engine = resolve_chat_engine(lab, payload)
            if getattr(engine, "provider", "") == "scripted":
                raise LabError(400, "the scripted engine has nothing to check", code="invalid_engine")
            info = engine.check()
            result = {"ok": True, "model": info.get("model")}
        else:
            resolution = lab.resolve_embedding(payload)
            if not resolution.available:
                result = {"ok": False, "mode": "fts-only", "reason": resolution.reason, "model": None}
            else:
                provider = lab.embedding_provider(resolution)
                provider.embed_query("ping")
                result = {"ok": True, "model": resolution.model, "mode": "hybrid"}
    except LabError:
        raise
    except Exception as exc:
        result = {"ok": False, "error": safe_exception_message(exc, secrets), "redacted": True}
    result["target"] = target
    result["latencyMs"] = int((time.perf_counter() - started) * 1000)
    lab.provider_status[target] = {"ok": result["ok"], "ts": lab.now_ms(), "error": result.get("error")}
    lab.bus.emit(
        "provider.check",
        summary=f"bağlantı sınaması ({target}): {'ok' if result['ok'] else 'hata'}",
        data={"target": target, "ok": result["ok"], "latencyMs": result["latencyMs"],
              "error": redact_secrets(result.get("error") or "", secrets) or None},
    )
    return result
