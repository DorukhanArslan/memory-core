"""Quickstart: an agent host loop with memory from memory-core, for any framework.

A terminal chat over the host kit. Each turn the kit builds the system prompt and offers the
memory tools, answers the model's tool calls, and after the reply decides the memory flush: a
second model run that appends durable facts to ``memory/YYYY-MM-DD.md``. The kit never calls a
model; replace ``call_my_llm`` with yours. The workspace is ``my-agent-app/`` in the working
directory. The README's Integrations section links to this file.
"""

import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from memory_core import FeatureFlags, HostKit, MemoryConfig, SessionState, TurnUsage


def call_my_llm(
    messages: Sequence[dict[str, str]],
    tools: Sequence[dict[str, Any]],
    run_tool: Callable[[str, Any], dict[str, Any]],
) -> tuple[str, TurnUsage]:
    """Your model call and its tool loop.

    Send ``messages`` and offer ``tools`` (``{"name", "description", "parameters"}`` specs, to
    wrap in your provider's format). Answer each tool call with ``run_tool(name, arguments)``,
    the arguments as JSON text or a dict, and send the payload back until the model replies.
    Return the reply text and the last call's token usage as the provider reports it.
    """
    raise NotImplementedError("replace call_my_llm with your model call")


def main() -> None:
    root = Path("my-agent-app")
    # FTS-only search; pass embedding_provider= instead of config= for hybrid search.
    kit = HostKit.open(
        root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    )
    state = SessionState.new(session_key="agent:main:main", session_id=str(uuid.uuid4()))
    history: list[dict[str, str]] = []
    while text := input("> "):
        turn = kit.before_turn(state)
        history.append({"role": "user", "content": text})
        reply, usage = call_my_llm(
            [{"role": "system", "content": turn.system_prompt}, *history],
            turn.tools,
            kit.dispatcher(turn.session),
        )
        print(reply)  # deliver the reply; the memory flush runs after it
        history.append({"role": "assistant", "content": reply})
        record = kit.after_turn(turn.session, transcript=history, usage=usage)
        state = record.session
        if record.flush is not None:  # the flush run's own reply is never shown
            call_my_llm(record.flush.messages, record.flush.tools, record.flush.dispatch)
            state = record.flush.complete(state).session


if __name__ == "__main__":
    main()
