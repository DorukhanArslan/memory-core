"""Responses egress projection for the compact-endpoint window check.

``isOpenAIResponsesCompactionOutput`` (packages/ai/src/transports/openai-responses-compaction-window.ts)
requires a saved window to survive provider egress without any rewrite. Egress runs

1. ``sanitizeResponsesImagePayload`` (responses-image-payload-sanitizer.ts): every
   ``input_image`` item with a string ``image_url`` goes through
   :func:`memory_core.inline_image.sanitize_inline_image_data_url`; an image the sanitiser rejects
   (or reduces to the empty string) becomes an ``input_text`` placeholder, and
2. ``applyOpenAIResponsesPayloadPolicy(payload, resolveOpenAIResponsesPayloadPolicy(model))``
   (openai-responses-payload-policy.ts), of which only ``stripInputItemStatuses`` touches
   ``payload.input``: a Responses route that is not a known native OpenAI endpoint loses the
   item-level ``status`` of every input item.

Only that input-relevant part of the policy is ported (endpoint class, native-route test and the
status rule); the store, prompt-cache, server-compaction and reasoning rules never alter
``payload.input`` and are not ported.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from memory_core.bootstrap._js import js_trim
from memory_core.inline_image import sanitize_inline_image_data_url
from memory_core.js_url import url_hostname

OPENAI_RESPONSES_APIS = frozenset(
    {
        "openai-responses",
        "azure-openai-responses",
        "openai-chatgpt-responses",
        "openclaw-openai-responses-transport",
        "openclaw-openai-chatgpt-responses-transport",
        "openclaw-azure-openai-responses-transport",
    }
)
IMAGE_OMITTED_TEXT = "omitted image payload: invalid inline image data"
_AZURE_SUFFIXES = (
    ".openai.azure.com",
    ".cognitiveservices.azure.com",
    ".services.ai.azure.com",
    ".api.cognitive.microsoft.com",
)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_sanitize_value(child) for child in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") == "input_image" and isinstance(value.get("image_url"), str):
        image_url = sanitize_inline_image_data_url(value["image_url"])
        if image_url:
            return {**value, "image_url": image_url}
        return {"type": "input_text", "text": f"[{IMAGE_OMITTED_TEXT}]"}
    return {key: _sanitize_value(child) for key, child in value.items()}


def sanitize_responses_image_payload(params: Mapping[str, Any]) -> Mapping[str, Any]:
    """``sanitizeResponsesImagePayload``: the input is returned unchanged when not an array."""

    if not isinstance(params.get("input"), list):
        return params
    return {**params, "input": _sanitize_value(params["input"])}


def _normalized_lower(value: Any) -> str | None:
    """``normalizeOptionalLowercaseString``: trimmed, lower-cased, ``None`` when blank."""

    if not isinstance(value, str):
        return None
    trimmed = js_trim(value)
    return trimmed.lower() if trimmed else None


def _resolve_url_hostname(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = js_trim(value)
    if not trimmed:
        return None
    host = url_hostname(trimmed)
    if host is None:
        host = url_hostname(f"https://{trimmed}")
    return None if host is None else host.lower()


def resolve_responses_endpoint_class(base_url: Any) -> str:
    """``resolveOpenAIResponsesEndpointClass``."""

    if not isinstance(base_url, str) or not js_trim(base_url):
        return "default"
    host = _resolve_url_hostname(base_url)
    if not host:
        return "custom"
    if host == "api.openai.com":
        return "openai-public"
    if host == "chatgpt.com":
        return "openai"
    if host == "api.x.ai":
        return "xai-native"
    if any(host.endswith(suffix) for suffix in _AZURE_SUFFIXES):
        return "azure-openai"
    return "custom"


def uses_known_native_openai_route(provider: Any, base_url: Any) -> bool:
    """``usesKnownNativeOpenAIRoute`` of the payload capabilities."""

    endpoint_class = resolve_responses_endpoint_class(base_url)
    if endpoint_class == "default":
        return _normalized_lower(provider) == "openai"
    return endpoint_class in ("openai-public", "openai", "azure-openai")


def should_strip_input_status(provider: Any, api: Any, base_url: Any) -> bool:
    """``shouldStripInputStatus``: a Responses route that is not a known native OpenAI route."""

    return _normalized_lower(api) in OPENAI_RESPONSES_APIS and not uses_known_native_openai_route(
        provider, base_url
    )


def project_responses_input(items: list[Any], model: Any | None = None) -> list[Any]:
    """The ``input`` array after the image sanitiser and, with a model, the payload policy.

    ``model`` is anything with ``provider``, ``api`` and ``base_url`` attributes
    (:class:`memory_core.compaction_replay.ReplayModel`); without one only the sanitiser runs, as
    ``isOpenAIResponsesCompactionOutput(value)`` does without a model.
    """

    projected = sanitize_responses_image_payload({"input": items})["input"]
    if model is not None and should_strip_input_status(model.provider, model.api, model.base_url):
        for item in projected:
            if isinstance(item, dict):
                item.pop("status", None)
    return projected
