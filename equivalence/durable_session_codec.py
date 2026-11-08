"""Exact append/read-anchor identity codec, with original evidence retained."""
from __future__ import annotations

from copy import deepcopy
import re


def map_durable_session_identities(phases: list[dict], store_paths: list[str]) -> list[dict]:
    if not isinstance(phases, list) or len(phases) != len(store_paths):
        raise ValueError("Missing durable producer paths")
    generations: dict[str, str] = {}
    results = deepcopy(phases)
    for phase, store_path in zip(results, store_paths, strict=True):
        anchors = [entry.get("result", {}).get("anchor") for entry in phase["appendResults"]]
        anchors.append(phase.get("activeAnchor"))
        for anchor in filter(None, anchors):
            generation = anchor.get("generation")
            if (not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{32}", generation)
                    or not isinstance(anchor.get("agentId"), str) or anchor.get("storePath") != store_path):
                raise ValueError("An opaque anchor has no recognized producer identity")
            if generation not in generations:
                generations[generation] = f"$GENERATION/{len(generations) + 1}"
            anchor["generation"] = generations[generation]
            anchor["storePath"] = f"$SESSION_STORE/{anchor['agentId']}"
    return results
