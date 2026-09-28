"""The memory-core host kit: memory behaviour for one workspace as a few entry points.

A host (a chat app, a channel bot, a voice agent) builds one :class:`HostKit` per workspace
and keeps one :class:`SessionState` per session; the kit returns what to send the model and
takes back what came out. Specification: docs/host_kit.md.
"""

from memory_core.host.kit import MINIMAL_PROMPT_KINDS, HostKit, TurnContext
from memory_core.host.session import SessionState, TurnUsage

__all__ = ["MINIMAL_PROMPT_KINDS", "HostKit", "SessionState", "TurnContext", "TurnUsage"]
