"""A LangGraph agent with memory from memory-core, over the host kit.

The graph is host code a LangGraph app copies. ``prepare`` asks the kit for the turn's system
prompt and memory tools, ``agent`` calls the host's chat model bound to them, ``tools``
answers every tool call through the kit, and after the final reply ``maintain`` records the
turn and, when the memory flush is due, runs the flush turn on the same model with only the
append-only ``write`` tool. ``/new`` and ``/reset`` save the ending session through the kit
and start the next one in the same thread. The session's memory state lives in the graph
state, so the checkpointer keeps it across turns; one thread is one session key. The adapter
helpers (``memory_core.adapters.langgraph``) convert messages and answer tool calls; they
import no framework. docs/integrations/langgraph.md is the guide, its Findings section what
the kit lacked.

``main`` is a terminal chat against any OpenAI-compatible endpoint (``pip install
"memory-core[langgraph]" langchain-openai``): set ``OPENAI_API_KEY`` and ``OPENAI_MODEL``, and
``OPENAI_BASE_URL`` for an endpoint other than OpenAI's. The workspace is ``my-agent-app/`` in
the working directory, searched FTS-only (no embedder); the checkpointer is in memory, so a
restart starts a new thread state.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import TAG_NOSTREAM
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from memory_core import (
    FeatureFlags,
    FlushOutcome,
    FlushRequest,
    HostKit,
    MemoryConfig,
    ResetTurn,
    SessionState,
    ToolCallRepair,
    TurnState,
)
from memory_core.adapters.langgraph import (
    ToolCallRepairer,
    has_tool_calls,
    repair_tool_calls,
    tool_messages,
    transcript_rows,
    turn_usage,
)
from memory_core.project_name import DIST_NAME

# A turn's model calls with tool calls (host policy, like the Lab's MAX_TOOL_ROUNDS): the next
# call gets no tools, and a reply that still asks for tools fails the turn. LangGraph's default
# recursion_limit (10,007 steps) bounds nothing in practice.
MAX_TOOL_ROUNDS = 6
# The flush turn's tool rounds (host policy, like the Lab's tool loop); a flush turn that
# reaches the bound completes with what it appended.
MAX_FLUSH_TOOL_ROUNDS = 6


class AgentState(TypedDict):
    """The graph state, which the checkpointer stores per thread.

    ``messages`` is the session's visible transcript: never the system prompt, the runtime
    context or the flush turn. The ``memory_*`` values are JSON: the committed
    ``SessionState``, the turn in flight (``TurnState``), the reset turn a bare ``/new``
    leaves for ``prepare`` (``ResetTurn``), and what the last maintenance decided and wrote.
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


def reset_command(message: Any) -> tuple[Literal["new", "reset"], str] | None:
    """``("new" | "reset", rest)`` when a human message starts with ``/new`` or ``/reset``.

    A labelled simplification of upstream's ``resolveSessionResetCommand``
    (src/auto-reply/reply/session-reset-command.ts:249), which also handles mentions,
    envelopes, the soft ``/reset`` mode and configured triggers; the kit takes a parsed command.
    """
    if getattr(message, "type", None) != "human":
        return None
    words = message.text.strip().split(None, 1)
    if not words or words[0].lower() not in ("/new", "/reset"):
        return None
    return ("new" if words[0].lower() == "/new" else "reset"), words[1] if len(words) > 1 else ""


def model_input(turn: TurnState, messages: Sequence[Any], repair: ToolCallRepairer) -> list[Any]:
    """The model's input: the system prompt, then the repaired transcript with the runtime context.

    The transcript goes through ``repair`` (the kit's ``repair_tool_calls``): a call a failed
    turn left without its tool message gets upstream's synthetic error result, and a call
    without an id is dropped from the copy, as upstream repairs the replayed history
    (``sanitizeToolCallInputs``, ``repairToolUseResultPairing``); the stored messages keep
    them. The runtime context goes in as a user message immediately before the turn's active user
    message, where upstream binds its runtime-context carrier
    (src/agents/embedded-agent-runner/run/attempt-llm-boundary.ts:240-268;
    packages/agent-core/src/harness/messages.ts:139-153 sends it as a user message); with no
    active user message it goes last (this example's choice). A bare ``/new`` or ``/reset``
    turn sends its model prompt in place of the transcript row, with upstream's guard
    (``installModelPromptTransform``, attempt-llm-boundary.ts:384-460): only a model prompt
    that is not blank and differs from the row, and only while the active user message's text
    is the row (the example's row is text).
    """
    body = repair_tool_calls(messages, repair)
    index = active_user_index(body)
    reset = turn.reset
    if (
        reset is not None
        and reset.model_prompt.strip()
        and reset.model_prompt != reset.transcript_prompt
        and index is not None
        and _content(body[index]) == reset.transcript_prompt
    ):
        body[index] = {"role": "user", "content": reset.model_prompt}
    if turn.runtime_context:
        runtime = {"role": "user", "content": turn.runtime_context}
        body.insert(index if index is not None else len(body), runtime)
    system = [{"role": "system", "content": turn.system_prompt}] if turn.system_prompt else []
    return system + body


def active_user_index(messages: Sequence[Any]) -> int | None:
    """The turn's active user message: the last one, unless an assistant reply follows it.

    Upstream's ``findActiveUserMessageIndex``
    (src/agents/embedded-agent-runner/run/attempt-history.ts:350-383): an assistant message
    with tool calls is the turn's own scaffolding, one without them ends the turn (``None``).
    Message objects and role dicts read alike.
    """
    for index in range(len(messages) - 1, -1, -1):
        role = _role(messages[index])
        if role == "user":
            return index
        if role == "assistant" and not has_tool_calls(messages[index]):
            return None
    return None


def _role(message: Any) -> str | None:
    if isinstance(message, Mapping):
        return message.get("role")
    return {"human": "user", "ai": "assistant"}.get(getattr(message, "type", None))


def _content(message: Any) -> Any:
    return message.get("content") if isinstance(message, Mapping) else message.content


def tool_rounds(messages: Sequence[Any]) -> int:
    """The current turn's AI messages with tool calls: those after its last human message."""
    rounds = 0
    for message in reversed(messages):
        if message.type == "human":
            break
        rounds += message.type == "ai" and has_tool_calls(message)
    return rounds


def build_graph(
    kit: HostKit,
    model: BaseChatModel,
    *,
    context_window_tokens: int,
    checkpointer: BaseCheckpointSaver | None = None,
    session_key: Callable[[str], str] | None = None,
    new_id: Callable[[], str] | None = None,
    redact: Callable[[str], str] | None = None,
    redactor: Callable[[str], str] | None = None,
) -> CompiledStateGraph:
    """The agent graph for one workspace kit and one chat model.

    ``context_window_tokens`` is the model's window for the flush gate, with no default: the
    kit's 200,000-token default puts a smaller model's flush threshold above its window, so its
    flush would never run. ``checkpointer`` keeps each thread's state (default: an in-process
    ``InMemorySaver``); every run needs ``config={"configurable": {"thread_id": ...}}``.
    ``session_key`` maps the thread id to the session key (default: the thread id itself);
    ``new_id`` makes session ids. ``redact`` maps a failed flush's error text
    before it is stored; ``redactor`` maps each line ``/new`` saves from the ending session.
    """
    key_of = session_key or (lambda thread_id: thread_id)
    make_id = new_id or (lambda: str(uuid.uuid4()))

    def current_session(state: AgentState, config: RunnableConfig) -> tuple[SessionState, bool]:
        data = state.get("memory_session")
        if data is not None:
            return SessionState.from_json(data), False
        thread_id = config["configurable"]["thread_id"]
        return SessionState.new(session_key=key_of(thread_id), session_id=make_id()), True

    def route_input(state: AgentState) -> str:
        return "new_session" if reset_command(state["messages"][-1]) else "prepare"

    def new_session(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        ending, _ = current_session(state, config)
        command, text = reset_command(state["messages"][-1])
        new = kit.on_new_session(
            ending,
            command=command,
            session_id=make_id(),
            transcript=transcript_rows(state["messages"]),
            text=text,
            redactor=redactor,
        )
        # The thread's messages become the new session's transcript: its first row is the
        # reset row of a bare command (the model gets the reset prompt instead) or the text.
        first = new.reset.transcript_prompt if new.reset is not None else text
        return {
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), HumanMessage(first)],
            "memory_session": new.session.to_json(),
            "memory_turn": None,
            "memory_reset": new.reset.to_json() if new.reset is not None else None,
        }

    def prepare(
        state: AgentState, config: RunnableConfig, runtime: Runtime[AgentContext]
    ) -> dict[str, Any]:
        session, created = current_session(state, config)
        context = runtime.context
        reset = state.get("memory_reset")
        turn = TurnState.from_context(
            kit.before_turn(
                session, runtime_context=context.runtime_context if context is not None else None
            ),
            reset=ResetTurn.from_json(reset) if reset is not None else None,
        )
        update: dict[str, Any] = {"memory_turn": turn.to_json(), "memory_reset": None}
        if created:  # a thread's first session keeps its id even if this turn fails
            update["memory_session"] = session.to_json()
        return update

    def agent(state: AgentState) -> dict[str, Any]:
        turn = TurnState.from_json(state["memory_turn"])
        capped = tool_rounds(state["messages"]) >= MAX_TOOL_ROUNDS
        bound = model.bind_tools(list(turn.tools)) if turn.tools and not capped else model
        # Upstream's input repair keeps unanswered calls to the run's tools only
        # (replayAllowedToolNames); a call that has its result stays either way.
        offered = [tool["name"] for tool in turn.tools]

        def repair(rows: Sequence[Mapping[str, Any]]) -> ToolCallRepair:
            return kit.repair_tool_calls(rows, allowed_tool_names=offered)

        reply = bound.invoke(model_input(turn, state["messages"], repair))
        if capped and has_tool_calls(reply):  # not stored: every call in state stays answered
            raise RuntimeError(f"the model asked for tools after {MAX_TOOL_ROUNDS} tool rounds")
        return {"messages": [reply]}

    def tools(state: AgentState) -> dict[str, Any]:
        turn = TurnState.from_json(state["memory_turn"])
        return {"messages": tool_messages(state["messages"][-1], kit.dispatcher(turn.session))}

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
        turn = TurnState.from_json(state["memory_turn"])
        messages = state["messages"]
        record = kit.after_turn(
            turn.session,
            transcript=transcript_rows(messages),
            usage=turn_usage(messages[-1]),
            context_window_tokens=context_window_tokens,
            redact=redact,
        )
        decision = record.flush_decision
        session, failure, wrote = record.session, record.flush_failure, ()
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
                "window": context_window_tokens,
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
    graph.add_node("new_session", new_session)
    graph.add_node("prepare", prepare)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("maintain", maintain)
    graph.add_conditional_edges(START, route_input, ["new_session", "prepare"])
    graph.add_edge("new_session", "prepare")
    graph.add_edge("prepare", "agent")
    graph.add_conditional_edges("agent", after_agent, ["tools", "maintain"])
    graph.add_edge("tools", "agent")
    graph.add_edge("maintain", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())


def context_window(model: BaseChatModel, given: int | None) -> tuple[int, str]:
    """The flush gate's window: ``given``, else the model's LangChain profile.

    The profile (a beta field) knows the window for some model names only; without either the
    host must say, since the kit's 200,000-token default would put a smaller model's flush
    threshold above its window, and the flush would never run.
    """
    if given is not None:
        return given, "--context-window"
    profile = getattr(model, "profile", None)
    window = profile.get("max_input_tokens") if isinstance(profile, Mapping) else None
    if isinstance(window, int) and window > 0:
        return window, "model profile"
    raise SystemExit(
        f"the model profile gives no context window for {getattr(model, 'model_name', model)!r};"
        " pass --context-window TOKENS"
    )


def describe_maintenance(maintenance: Mapping[str, Any]) -> str:
    """One status line for what ``maintain`` decided and wrote."""
    reason = maintenance["flush"]
    gate = f"{maintenance['tokenCount']} of {maintenance['threshold']} tokens"
    if maintenance["failure"] is not None:
        return f"[memory] flush failed ({reason}): {maintenance['failure']['error']}"
    if maintenance["target"] is not None:
        count, target = len(maintenance["wrote"]), maintenance["target"]
        return f"[memory] flush ({reason}, {gate}): {count} entries appended to {target}"
    if reason == "missing_tokens":
        return "[memory] no flush: the provider reported no token usage for the reply"
    return f"[memory] no flush ({reason}, {gate})"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="A LangGraph agent with memory over the host kit.")
    parser.add_argument("--workspace", default="my-agent-app", help="the memory workspace root")
    parser.add_argument("--thread", default="main", help="the LangGraph thread (session key)")
    parser.add_argument(
        "--context-window", type=int, help="the model's context window, when its profile has none"
    )
    args = parser.parse_args(argv)
    missing = [name for name in ("OPENAI_API_KEY", "OPENAI_MODEL") if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"set {' and '.join(missing)} (OPENAI_BASE_URL is optional)")
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise SystemExit(f'pip install "{DIST_NAME}[langgraph]" langchain-openai') from exc
    # stream_usage: a custom base URL turns streamed usage off, and the flush gate needs it.
    model = ChatOpenAI(
        model=os.environ["OPENAI_MODEL"],
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        stream_usage=True,
    )
    window, source = context_window(model, args.context_window)
    root = Path(args.workspace)
    kit = HostKit.open(
        root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    )
    graph = build_graph(kit, model, context_window_tokens=window)
    config: RunnableConfig = {"configurable": {"thread_id": args.thread}}
    print(f"[memory] {root}/, FTS-only search; context window {window} ({source})", file=sys.stderr)
    try:
        while text := input("> "):
            try:
                chat_turn(graph, config, text)
            except Exception as error:  # the thread goes on: the next message starts a new turn
                print(f"[error] {type(error).__name__}: {error}", file=sys.stderr)
    except (EOFError, KeyboardInterrupt):  # Ctrl-D, the end of piped input, Ctrl-C
        print(file=sys.stderr)


def chat_turn(graph: CompiledStateGraph, config: RunnableConfig, text: str) -> None:
    """One terminal turn: the reply to stdout, tool calls and maintenance to stderr."""
    # Drain the stream: the reply comes with the agent update, maintenance after it.
    turn = {"messages": [HumanMessage(text)]}
    for update in graph.stream(turn, config, stream_mode="updates"):
        for node, values in update.items():
            if node == "agent" and not has_tool_calls(values["messages"][-1]):
                print(values["messages"][-1].text)
            elif node == "tools":
                for message in values["messages"]:
                    print(f"[tool] {message['name']}: {message['status']}", file=sys.stderr)
            elif node == "maintain":
                print(describe_maintenance(values["memory_maintenance"]), file=sys.stderr)


if __name__ == "__main__":
    main()
