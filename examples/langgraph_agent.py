"""A LangGraph agent with memory from memory-core, over the host kit.

The graph is host code a LangGraph app copies. ``prepare`` asks the kit for the turn's system
prompt and memory tools, ``agent`` calls the host's chat model bound to them, ``tools``
answers every tool call through the kit, and after the final reply ``maintain`` records the
turn and, when the memory flush is due, runs the flush turn on the same model with only the
append-only ``write`` tool. The session's memory state lives in the graph state, so the
checkpointer keeps it across turns; one thread is one session. The adapter helpers
(``memory_core.adapters.langgraph``) convert messages and answer tool calls; they import no
framework. docs/integrations/langgraph.md is the guide, its Findings section what the kit
lacked.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, NotRequired, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import TAG_NOSTREAM
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from memory_core import FlushOutcome, FlushRequest, HostKit, SessionState
from memory_core.adapters.langgraph import (
    PendingTurn,
    has_tool_calls,
    tool_messages,
    transcript_rows,
    turn_usage,
)
from memory_core.host import DEFAULT_CONTEXT_WINDOW_TOKENS
from memory_core.memory_flush import MemoryFlushFailureOutcome

# The flush turn's tool rounds (host policy, like the Lab's tool loop); a flush turn that
# reaches the bound completes with what it appended.
MAX_FLUSH_TOOL_ROUNDS = 6


class AgentState(TypedDict):
    """The graph state, which the checkpointer stores per thread.

    ``messages`` is the session's visible transcript: never the system prompt, the runtime
    context or the flush turn. The ``memory_*`` values are JSON: the committed
    ``SessionState``, the turn in flight (``PendingTurn``), the reset prompt a bare ``/new``
    leaves for ``prepare``, and what the last maintenance decided and wrote.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    memory_session: NotRequired[dict[str, Any] | None]
    memory_turn: NotRequired[dict[str, Any] | None]
    memory_reset: NotRequired[dict[str, Any] | None]
    memory_maintenance: NotRequired[dict[str, Any] | None]


@dataclass
class AgentContext:
    """The run context: ``graph.invoke(..., context=AgentContext(...))``, optional."""

    # The host's per-turn text (channel, sender, time); the kit wraps it in the runtime
    # context markers.
    runtime_context: str | None = None


def model_input(turn: PendingTurn, messages: Sequence[Any]) -> list[Any]:
    """The model's input: the system prompt, then the transcript with the runtime context.

    The runtime context goes in as a user message immediately before the turn's user message,
    where upstream keeps its runtime-context carrier (src/agents/internal-runtime-context.ts:378;
    packages/agent-core/src/harness/messages.ts:139-153 sends it as a user message). A bare
    ``/new`` or ``/reset`` turn sends its model prompt in place of the transcript row.
    """
    body = [
        {"role": "user", "content": turn.model_prompt}
        if turn.model_prompt_message_id is not None
        and getattr(message, "id", None) == turn.model_prompt_message_id
        else message
        for message in messages
    ]
    if turn.runtime_context:
        users = [index for index, message in enumerate(messages) if message.type == "human"]
        runtime = {"role": "user", "content": turn.runtime_context}
        body.insert(users[-1] if users else len(body), runtime)
    system = [{"role": "system", "content": turn.system_prompt}] if turn.system_prompt else []
    return system + body


def build_graph(
    kit: HostKit,
    model: BaseChatModel,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    context_window_tokens: int | None = None,
    session_key: Callable[[str], str] | None = None,
    new_id: Callable[[], str] | None = None,
    redact: Callable[[str], str] | None = None,
) -> CompiledStateGraph:
    """The agent graph for one workspace kit and one chat model.

    ``checkpointer`` keeps each thread's state (default: an in-process ``InMemorySaver``);
    every run needs ``config={"configurable": {"thread_id": ...}}``. ``context_window_tokens``
    is the model's window for the flush gate (the kit's default when ``None``).
    ``session_key`` maps the thread id to the session key (default: the thread id itself);
    ``new_id`` makes session ids. ``redact`` maps a failed flush's error text before it is
    stored.
    """
    key_of = session_key or (lambda thread_id: thread_id)
    make_id = new_id or (lambda: str(uuid.uuid4()))
    window = (
        context_window_tokens
        if context_window_tokens is not None
        else DEFAULT_CONTEXT_WINDOW_TOKENS
    )

    def current_session(state: AgentState, config: RunnableConfig) -> tuple[SessionState, bool]:
        data = state.get("memory_session")
        if data is not None:
            return SessionState.from_json(data), False
        thread_id = config["configurable"]["thread_id"]
        return SessionState.new(session_key=key_of(thread_id), session_id=make_id()), True

    def prepare(
        state: AgentState, config: RunnableConfig, runtime: Runtime[AgentContext]
    ) -> dict[str, Any]:
        session, created = current_session(state, config)
        context = runtime.context
        turn = kit.before_turn(
            session, runtime_context=context.runtime_context if context is not None else None
        )
        reset = state.get("memory_reset")
        pending = PendingTurn.from_context(
            turn,
            model_prompt=reset["modelPrompt"] if reset else None,
            model_prompt_message_id=reset["messageId"] if reset else None,
        )
        update: dict[str, Any] = {"memory_turn": pending.to_json(), "memory_reset": None}
        if created:  # a thread's first session keeps its id even if this turn fails
            update["memory_session"] = session.to_json()
        return update

    def agent(state: AgentState) -> dict[str, Any]:
        turn = PendingTurn.from_json(state["memory_turn"])
        bound = model.bind_tools(list(turn.tools)) if turn.tools else model
        return {"messages": [bound.invoke(model_input(turn, state["messages"]))]}

    def tools(state: AgentState) -> dict[str, Any]:
        turn = PendingTurn.from_json(state["memory_turn"])
        dispatch = functools.partial(kit.dispatch, session=turn.session)
        return {"messages": tool_messages(state["messages"][-1], dispatch)}

    def after_agent(state: AgentState) -> str:
        return "tools" if has_tool_calls(state["messages"][-1]) else "maintain"

    def run_flush(request: FlushRequest, session: SessionState) -> FlushOutcome:
        # Same model, only the flush's write tool, kept out of a "messages" stream; the flush
        # reply is never delivered and never enters the transcript.
        flush_model = model.bind_tools(list(request.tools)).with_config(tags=[TAG_NOSTREAM])
        messages: list[Any] = list(request.messages)
        try:
            for _ in range(MAX_FLUSH_TOOL_ROUNDS):
                reply = flush_model.invoke(messages)
                if not has_tool_calls(reply):
                    break
                messages += [reply, *tool_messages(reply, request.dispatch)]
        except Exception as error:  # the reply is already in state; a failed flush is a strike
            return request.complete(session, error=error, redact=redact)
        return request.complete(session)

    def maintain(state: AgentState) -> dict[str, Any]:
        turn = PendingTurn.from_json(state["memory_turn"])
        messages = state["messages"]
        record = kit.after_turn(
            turn.session,
            transcript=transcript_rows(messages),
            usage=turn_usage(messages[-1]),
            context_window_tokens=window,
        )
        decision = record.flush_decision
        session, failure, wrote = record.session, record.flush_failure, ()
        if failure is not None and redact is not None:  # after_turn takes no redact
            failure = MemoryFlushFailureOutcome(
                entry=failure.entry,
                failure_count=failure.failure_count,
                exhausted=failure.exhausted,
                error=redact(failure.error),
            )
        if record.flush is not None:
            outcome = run_flush(record.flush, session)
            session, failure, wrote = outcome.session, outcome.failure, outcome.entries
        return {
            "memory_session": session.to_json(),
            "memory_turn": None,
            "memory_maintenance": {
                "flush": decision.reason,
                "tokenCount": decision.total_tokens,
                "threshold": decision.threshold,
                "window": window,
                "target": record.flush_plan.relative_path if decision.should_flush else None,
                "wrote": list(wrote),
                "failure": None
                if failure is None
                else {
                    "error": failure.error,
                    "failureCount": failure.failure_count,
                    "exhausted": failure.exhausted,
                },
            },
        }

    graph = StateGraph(AgentState, context_schema=AgentContext)
    graph.add_node("prepare", prepare)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("maintain", maintain)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "agent")
    graph.add_conditional_edges("agent", after_agent, ["tools", "maintain"])
    graph.add_edge("tools", "agent")
    graph.add_edge("maintain", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
