"""Offline scripted-model example with real memory writes and immediate recall.

Run: python examples/host_session_lifecycle.py [--workspace /path/to/demo]
No network requests, model calls, prepopulated memory or fabricated search hits.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import tempfile

from memory_core import (
    HostModelResult, HostSessionRunner, SessionState, TurnUsage,
)
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.session_catalog import MemorySessionCatalog


def assistant_call(turn, name, arguments, call_id):
    turn.record_message({"role": "assistant", "content": [
        {"type": "toolCall", "id": call_id, "name": name, "arguments": arguments}],
        "provider": "scripted-offline-example", "model": "literal-callback"})


async def demonstrate(workspace: Path) -> dict:
    config = MemoryConfig(workspace, flags=FeatureFlags(vector_search=False))
    catalog = MemorySessionCatalog(config.resolved_store_path().with_name("sessions.sqlite"))
    runner = HostSessionRunner.open(workspace, config=config, catalog=catalog,
        session=SessionState.new(session_key="agent:main:dm:example", session_id="example-conversation"))

    async def scripted_save(turn):
        # This small scripted callback reads the actual admitted user text.
        text = turn.messages[-1]["content"]
        note = text.removeprefix("Remember that ").rstrip(".") + "."
        arguments = {"text": note}
        assistant_call(turn, "append_daily_note", arguments, "save-note")
        await turn.dispatch_async("save-note", "append_daily_note", arguments)
        turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "Saved the note."}]})
        return HostModelResult(TurnUsage(20, 3))

    hits = []
    async def scripted_recall(turn):
        arguments = {"query": "calibration token", "corpus": "memory", "minScore": 0}
        assistant_call(turn, "memory_search", arguments, "find-note")
        actual = await turn.dispatch_async("find-note", "memory_search", arguments)
        hits.extend(actual["results"])
        text = "\n".join(hit["snippet"] for hit in actual["results"]) or "No saved note was found."
        turn.record_message({"role": "assistant", "content": [{"type": "text", "text": text}]})
        return HostModelResult(TurnUsage(20, 3))

    saved = await runner.run_turn("Remember that my calibration token is ZEPHYR-482.", execute=scripted_save)
    recalled = await runner.run_turn("Find my saved calibration token.", execute=scripted_recall)
    if not saved.ready or not recalled.ready or not hits:
        raise RuntimeError(f"The actual lifecycle failed: {saved.failures!r}; {recalled.failures!r}")
    reopened = MemorySessionCatalog(catalog.path).read_continuation("example-conversation",
        session_key="agent:main:dm:example")
    return {"model": "scripted offline callback", "workspace": str(workspace),
        "firstTurn": {"ready": saved.ready, "memoryCommitted": saved.memory_writes_committed,
                      "index": saved.index_status},
        "immediateFollowup": {"ready": recalled.ready, "actualHits": hits},
        "reopenedTranscriptEvents": len(reopened["events"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, help="Keep the demo's actual state at this path.")
    args = parser.parse_args()
    if args.workspace is not None:
        result = asyncio.run(demonstrate(args.workspace.resolve()))
    else:
        with tempfile.TemporaryDirectory(prefix="host-session-example-") as root:
            result = asyncio.run(demonstrate(Path(root)))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
