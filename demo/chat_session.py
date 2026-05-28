from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from demo.chat_engine import ChatMessage


@dataclass
class ChatTurn:
    id: int
    user_message: str
    recall_query: str
    recall_results: list[dict[str, Any]]
    memory_context: list[str]
    assistant_response: str
    transcript_messages: list[ChatMessage] = field(default_factory=list)
    flush: dict[str, Any] | None = None
    promotion: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "userMessage": self.user_message,
            "recallQuery": self.recall_query,
            "recallResults": self.recall_results,
            "memoryContext": self.memory_context,
            "assistantResponse": self.assistant_response,
            "transcriptMessages": [
                {"role": message.role, "content": message.content}
                for message in self.transcript_messages
            ],
            "flush": self.flush,
            "promotion": self.promotion,
        }


@dataclass
class ChatSessionState:
    turns: list[ChatTurn] = field(default_factory=list)
    selected_turn_id: int | None = None

    def add_turn(
        self,
        *,
        user_message: str,
        recall_query: str,
        recall_results: list[dict[str, Any]],
        assistant_response: str,
        memory_context: list[str],
        transcript_messages: list[ChatMessage] | None = None,
        flush: dict[str, Any] | None = None,
        promotion: dict[str, Any] | None = None,
    ) -> ChatTurn:
        turn = ChatTurn(
            id=len(self.turns) + 1,
            user_message=user_message,
            recall_query=recall_query,
            recall_results=recall_results,
            memory_context=memory_context,
            assistant_response=assistant_response,
            transcript_messages=transcript_messages or [],
            flush=flush,
            promotion=promotion,
        )
        self.turns.append(turn)
        self.selected_turn_id = turn.id
        return turn

    def latest(self) -> ChatTurn | None:
        return self.turns[-1] if self.turns else None

    def transcript_messages(self) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        for turn in self.turns:
            messages.append(ChatMessage(role="user", content=turn.user_message))
            messages.append(ChatMessage(role="assistant", content=turn.assistant_response))
        return messages

    def reset(self) -> None:
        self.turns.clear()
        self.selected_turn_id = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "turns": [turn.as_dict() for turn in self.turns],
            "selectedTurnId": self.selected_turn_id,
        }
