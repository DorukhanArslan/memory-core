"""Scoped Lab output policy; no credentials are registered or retained globally.

This demo policy protects supplied credentials and verified proof literals. It
does not detect arbitrary PII or unknown credential patterns split over chunks.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from memory_core.redact import redact_secrets
from memory_core.secret_registry import (
    create_secret_value_redactor,
    encode_uri_component,
    json_string_content,
)

REDACTED_IDENTITY_PROOF = "[kimlik bilgisi gizlendi]"
SAFE_DIAGNOSTIC = "[live output unavailable: redaction failed]"


class LivePrivacyPolicy:
    def __init__(
        self, *, proofs: tuple[str, ...] = (), secrets: tuple[str, ...] = (),
        redactor: Callable[[str], str] | None = None,
    ):
        # Only the already-verified workflow utterances supply proof values. This
        # is deliberately not a generic date/customer-number detector.
        proof_values = tuple(dict.fromkeys(
            value for proof in proofs for value in (proof, *re.findall(r"\d[\d./-]*\d|\d", proof))
            if value
        ))
        self.replacements = {value: REDACTED_IDENTITY_PROOF for value in proof_values}
        for secret in secrets:
            if secret:
                for value in (secret, encode_uri_component(secret), json_string_content(secret)):
                    self.replacements[value] = "[redacted]"
        self.literals = tuple(sorted(self.replacements, key=len, reverse=True))
        self._exact = create_secret_value_redactor(self.literals)
        self._redactor = redactor
        self.failed = False

    def text(self, text: str) -> str:
        if self.failed:
            return SAFE_DIAGNOSTIC
        try:
            text = self._exact(text, lambda value, _: self.replacements[value])
            if self._redactor is not None:
                text = self._redactor(text)
                if not isinstance(text, str):
                    self.failed = True
                    return SAFE_DIAGNOSTIC
            result = redact_secrets(text)
            if not isinstance(result, str):
                self.failed = True
                return SAFE_DIAGNOSTIC
            return result
        except Exception:
            self.failed = True
            return SAFE_DIAGNOSTIC

    def payload(self, value: Any) -> Any:
        def walk(item):
            if isinstance(item, str):
                return self.text(item)
            if isinstance(item, dict):
                return {self.text(str(key)): walk(child) for key, child in item.items()}
            if isinstance(item, list | tuple):
                return [walk(child) for child in item]
            return item

        try:
            # Field context matters: e.g. {"apiKey": "..."} must be masked even
            # if its value has no recognizable credential prefix.
            result = redact_secrets(walk(value))
            return {"error": SAFE_DIAGNOSTIC, "redacted": True} if self.failed else result
        except Exception:
            self.failed = True
            return {"error": SAFE_DIAGNOSTIC, "redacted": True}

    def failure_payload(self) -> dict[str, Any]:
        return {"type": "live_turn_failed", "text": "",
                "data": {"error": SAFE_DIAGNOSTIC, "redacted": True}}

    def trace_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        if payload.get("type") in {"text_delta", "sentence"}:
            # A diagnostic record must never persist reconstructable fragments.
            payload["text"] = "[incremental text omitted]"
        if payload.get("type") == "live_turn_failed":
            payload["data"] = {**payload.get("data", {}), "assistant_text": "[partial text omitted]"}
        result = self.payload(payload)
        return self.failure_payload() if self.failed else result


class LiteralStreamFilter:
    """Hold only a suffix that could still become a scoped literal."""

    def __init__(self, policy: LivePrivacyPolicy):
        self.policy = policy
        self.pending = ""

    def feed(self, text: str) -> str:
        value = self.pending + text
        self.pending = ""
        output: list[str] = []
        cursor = 0
        while cursor < len(value):
            literal = next((s for s in self.policy.literals if value.startswith(s, cursor)), None)
            if literal is not None:
                output.append(self.policy.replacements[literal])
                cursor += len(literal)
            elif any(s.startswith(value[cursor:]) for s in self.policy.literals):
                self.pending = value[cursor:]
                break
            else:
                output.append(value[cursor])
                cursor += 1
        return self.policy.text("".join(output))

    def finish(self) -> str:
        # Also mask incomplete prefixes at a normal EOF. A failure/cancellation
        # discards them without manufacturing a terminal success event.
        text = "[redacted]" if self.pending else ""
        self.pending = ""
        return text

    def discard(self) -> None:
        self.pending = ""
