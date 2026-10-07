"""Shared harness of the redaction-policy oracle tests: scenarios run by the real TypeScript and by
the Python port, step by step.

A scenario is ``{registry, fileConfig, config, fullContext, steps}`` (see the ``redactPolicies``
operation of ``scripts/openclaw_oracle_runner.ts``). :func:`run_python` executes one with
:mod:`memory_core.redact` and :mod:`memory_core.secret_registry` in the same shape the oracle
returns, so a test compares ``run_python(scenario)`` with the oracle's entry for it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from demo.openclaw_oracle import OpenClawOracle
from memory_core import redact, secret_registry
from memory_core.redact_user_patterns import compile_redact_pattern


def _cust_exec(text: str):
    for found in re.finditer(r"CUST-([0-9]+)", text):
        yield redact.RedactMatch(
            found.group(0),
            (found.group(1),),
            found.start(),
            "<cust>" if len(found.group(1)) > 3 else None,
        )


def _whole_exec(text: str):
    for found in re.finditer(r"ZZ[0-9]{3,}", text):
        yield redact.RedactMatch(found.group(0), (), found.start())


_MATCHERS: dict[str, Any] = {
    "cust": redact.RedactMatcher("cust", _cust_exec),
    "whole": redact.RedactMatcher("whole", _whole_exec),
    "aws": redact.AWS_SECRET_ACCESS_KEY_MATCHER,
}


def _map_patterns(patterns):
    if not isinstance(patterns, list):
        return patterns
    return [_MATCHERS[entry["matcher"]] if isinstance(entry, dict) else entry for entry in patterns]


def _cfg(cfg: dict | None):
    patterns = ((cfg or {}).get("logging") or {}).get("redactPatterns")
    return redact.LoggingConfig(tuple(patterns)) if patterns is not None else None


def _units(text: str) -> int:
    return len(redact.to_units(text))


def run_python(scenario: dict) -> dict:
    secret_registry.reset_secret_redaction_registry()
    base = secret_registry.get_secret_redaction_registry_revision()
    register_error = None
    for value in scenario.get("registry", []):
        try:
            secret_registry.register_secret_value_for_redaction(value)
        except ValueError:
            register_error = "URIError"
    file_config = scenario.get("fileConfig")
    redact.configure_logging_redaction(
        redact.LoggingConfig(tuple(file_config.get("redactPatterns") or ())) if file_config else None
    )
    config = scenario.get("config")
    logging_config = redact.LoggingConfig(tuple(config["redactPatterns"])) if config else None
    if scenario.get("fullContext"):
        logging_config = redact.mark_full_context_tool_payload_redaction(
            logging_config if logging_config is not None else redact.LoggingConfig()
        )
    snapshots: list[Any] = []
    steps = []
    try:
        for step in scenario.get("steps", []):
            fn = step["fn"]
            if fn == "sensitiveText":
                out: Any = redact.redact_sensitive_text(
                    step["text"], mode=step.get("mode", "tools"), patterns=_map_patterns(step.get("patterns"))
                )
            elif fn == "sensitiveTextConfig":
                out = redact.redact_sensitive_text(step["text"], config="host")
            elif fn == "toolPayload":
                out = redact.redact_tool_payload_text(step["text"], logging_config=logging_config)
            elif fn == "toolPayloadHost":
                out = redact.redact_tool_payload_text(step["text"])
            elif fn == "modelVisibleText":
                out = redact.redact_model_visible_tool_payload_text(step["text"], logging_config=logging_config)
            elif fn == "field":
                out = redact.redact_sensitive_field_value(step["key"], step["value"], logging_config=logging_config)
            elif fn == "modelVisibleField":
                out = redact.redact_model_visible_field_value(
                    step["key"], step["value"], logging_config=logging_config
                )
            elif fn == "secrets":
                out = redact.redact_secrets(step["value"])
            elif fn == "modelVisibleSecrets":
                out = redact.redact_model_visible_secrets(step["value"])
            elif fn == "transcriptText":
                out = redact.redact_transcript_text(
                    step["text"],
                    logging_config=_cfg(step.get("cfg")),
                    model_visible_tool_result=bool(step.get("modelVisible")),
                )
            elif fn == "transcriptField":
                out = redact.redact_transcript_structured_field_value(
                    step["key"],
                    step["value"],
                    logging_config=_cfg(step.get("cfg")),
                    model_visible_tool_result=bool(step.get("modelVisible")),
                )
            elif fn == "register":
                try:
                    secret_registry.register_secret_value_for_redaction(step["value"])
                except ValueError:
                    steps.append({"error": "URIError"})
                    continue
                out = None
            elif fn == "registryState":
                snapshot = secret_registry.capture_secret_redaction_registry_snapshot()
                out = {
                    "revision": secret_registry.get_secret_redaction_registry_revision() - base,
                    "has": secret_registry.has_registered_secret_values_for_redaction(),
                    "values": list(snapshot.values),
                    "registered": [
                        secret_registry.is_secret_value_registered_for_redaction(v) for v in step.get("probe", [])
                    ],
                }
            elif fn == "snapshot":
                snapshots.append(redact.capture_sensitive_text_redaction_snapshot())
                out = None
            elif fn == "snapshotRedact":
                out = redact.create_sensitive_text_redactor(snapshots[step["index"]])(step["text"])
            elif fn == "registered":
                out = secret_registry.redact_registered_secret_values(
                    step["text"], lambda value, index: f"<{_units(value)}@{index}>"
                )
            elif fn == "compile":
                compiled = compile_redact_pattern(step["pattern"])
                out = (
                    None
                    if compiled is None
                    else {"source": compiled.pattern, "flags": compiled.flags, "reason": compiled.reason}
                )
            else:
                raise AssertionError(fn)
            steps.append({"value": out})
    finally:
        redact.configure_logging_redaction(None)
        secret_registry.reset_secret_redaction_registry()
    return {"steps": steps, "registerError": register_error}


def oracle_run(scenarios: list[dict]) -> list[dict]:
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    result = oracle.run({"operation": "redactPolicies", "scenarios": scenarios})
    assert result["ok"] is True, result
    scenarios_out = result["result"]["scenarios"]
    assert len(scenarios_out) == len(scenarios)
    return scenarios_out


def compare(scenario: dict, want: dict) -> list[tuple[int, Any, Any, Any]]:
    """Mismatching steps as ``(index, step, oracle value, python value)``."""
    got = run_python(scenario)
    bad: list[tuple[int, Any, Any, Any]] = []
    if got["registerError"] != want["registerError"]:
        bad.append((-1, "registerError", want["registerError"], got["registerError"]))
    for index, (step, expected, actual) in enumerate(zip(scenario["steps"], want["steps"], got["steps"], strict=True)):
        if expected != actual:
            bad.append((index, step, expected, actual))
    return bad
