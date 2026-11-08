"""Build persisted session context and its model-facing message sequence.

The window selector and checkpoint owner are shared with replay. History-prelude
state lives on a typed carrier, outside dictionary keys, like the native
non-enumerable sessionHistoryPrelude symbol; JSON persistence omits that state.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
import math
from typing import Any

from memory_core.bootstrap._js import js_truthy
from memory_core.compaction_replay import _js_number_to_string, strip_compaction_replay_checkpoint
from memory_core.session_context_window import iterate_session_context_entries
from memory_core.session_entry import js_date_parse
from memory_core.tools.common import MemoryToolError


COMPACTION_SUMMARY_PREFIX = (
    'The conversation history before this point was compacted into the following summary:\n\n<summary>\n'
)
COMPACTION_SUMMARY_SUFFIX = '\n</summary>'
BRANCH_SUMMARY_PREFIX = (
    'The following is a summary of a branch that this conversation came back from:\n\n<summary>\n'
)
BRANCH_SUMMARY_SUFFIX = '</summary>'
_MISSING = object()


class SessionHistoryMessage(dict[str, Any]):
    """A reset-retained message with non-persisted history-prelude identity."""

    __slots__ = ()


def is_session_history_prelude(message: object) -> bool:
    """Read actual context-carrier state without trusting an authored JSON field."""
    return isinstance(message, SessionHistoryMessage)


def _fields(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not _MISSING}


def _timestamp_ms(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    parsed = js_date_parse(value)
    return int(parsed) if math.isfinite(parsed) else None


def _require_timestamp_ms(value: object, label: str) -> int:
    parsed = _timestamp_ms(value)
    if parsed is None:
        raise MemoryToolError(f'{label} must be a valid timestamp')
    return parsed


def create_branch_summary_message(summary: str, from_id: str, timestamp: str) -> dict[str, Any]:
    return _fields(role='branchSummary', summary=summary, fromId=from_id,
                   timestamp=_require_timestamp_ms(timestamp, 'branch summary timestamp'))


def create_compaction_summary_message(
    summary: str, tokens_before: int | float, timestamp: str,
) -> dict[str, Any]:
    return _fields(role='compactionSummary', summary=summary, tokensBefore=tokens_before,
                   timestamp=_require_timestamp_ms(timestamp, 'compaction summary timestamp'))


def create_custom_message(
    custom_type: str, content: Any, display: bool, details: Any, timestamp: str,
) -> dict[str, Any]:
    return _fields(role='custom', customType=custom_type, content=content, display=display,
                   details=details, timestamp=_require_timestamp_ms(timestamp, 'custom message timestamp'))


def project_session_entry_message(entry: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Project one persisted entry; display-only messages stay outside context."""
    kind = entry.get('type')
    if kind == 'message':
        message = entry['message']
        return None if message.get('excludeFromContext') is True else message
    if kind == 'custom_message':
        return create_custom_message(
            entry.get('customType', _MISSING), entry.get('content', _MISSING),
            entry.get('display', _MISSING), entry.get('details', _MISSING),
            entry.get('timestamp', _MISSING),
        )
    if kind == 'branch_summary':
        return create_branch_summary_message(entry.get('summary', _MISSING),
                                             entry.get('fromId', _MISSING),
                                             entry.get('timestamp', _MISSING))
    if kind == 'compaction':
        return create_compaction_summary_message(entry.get('summary', _MISSING),
                                                 entry.get('tokensBefore', _MISSING),
                                                 entry.get('timestamp', _MISSING))
    return None


def iterate_session_context_messages(
    path_entries: Sequence[Mapping[str, Any]],
    read_entry: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> Iterator[Mapping[str, Any]]:
    """Hydrate only selected entries, retaining reset and compaction semantics."""
    for entry, context in iterate_session_context_entries(path_entries):
        if entry.get('type') == 'reset':
            continue
        hydrated = read_entry(entry) if read_entry is not None else entry
        if hydrated.get('type') == 'branch_summary' and not js_truthy(hydrated.get('summary')):
            continue
        message = (hydrated['message']
                   if context == 'reset-retained' and hydrated.get('type') == 'message'
                   else project_session_entry_message(hydrated))
        if message is None:
            continue
        if context != 'current' and message.get('role') == 'assistant':
            message = strip_compaction_replay_checkpoint(message)
        if context == 'reset-retained' and message.get('role') in ('user', 'assistant'):
            message = SessionHistoryMessage(message)
        yield message


def build_session_context(path_entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build selected messages and the latest thinking/model state of the branch."""
    thinking_level: object = 'off'
    model = None
    for entry in path_entries:
        kind = entry.get('type')
        if kind == 'thinking_level_change':
            thinking_level = entry.get('thinkingLevel', _MISSING)
        elif kind == 'model_change':
            model = _fields(provider=entry.get('provider', _MISSING),
                            modelId=entry.get('modelId', _MISSING))
        elif kind == 'message' and entry['message'].get('role') == 'assistant':
            model = _fields(provider=entry['message'].get('provider', _MISSING),
                            modelId=entry['message'].get('model', _MISSING))
    return _fields(messages=list(iterate_session_context_messages(path_entries)),
                   thinkingLevel=thinking_level, model=model)


def _text(value: Any) -> str:
    if value is _MISSING:
        return 'undefined'
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            return 'NaN' if math.isnan(value) else '-Infinity' if value < 0 else 'Infinity'
        return _js_number_to_string(value)
    if isinstance(value, list):
        return ','.join('' if item is None else _text(item) for item in value)
    return '[object Object]'


def bash_execution_to_text(message: Mapping[str, Any]) -> str:
    text = f"Ran `{_text(message.get('command', _MISSING))}`\n"
    output = message.get('output')
    text += f'```\n{_text(output)}\n```' if js_truthy(output) else '(no output)'
    if js_truthy(message.get('cancelled')):
        text += '\n\n(command cancelled)'
    else:
        code = message.get('exitCode')
        if code is not None and (isinstance(code, bool) or code != 0):
            text += f'\n\nCommand exited with code {_text(code)}'
    if js_truthy(message.get('truncated')) and js_truthy(message.get('fullOutputPath')):
        text += f"\n\n[Output truncated. Full output: {_text(message['fullOutputPath'])}]"
    return text


def is_runtime_context_carrier(message: Mapping[str, Any]) -> bool:
    details = message.get('details')
    return message.get('role') == 'custom' and isinstance(details, Mapping) and details.get('runtimeContextCarrier') is True


def convert_to_llm(messages: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Convert harness messages, preserving ordinary messages and hidden markers."""
    converted = []
    for index in range(len(messages)):
        if index >= len(messages):
            continue
        message = messages[index]
        role = message.get('role')
        if role in ('user', 'assistant', 'toolResult'):
            converted.append(message)
            continue
        if role in ('bashExecution', 'custom') and js_truthy(message.get('excludeFromContext')):
            continue
        if role == 'bashExecution':
            content = [{'type': 'text', 'text': bash_execution_to_text(message)}]
        elif role == 'custom':
            value = message.get('content', _MISSING)
            content = [{'type': 'text', 'text': value}] if isinstance(value, str) else value
        elif role == 'branchSummary':
            content = [{'type': 'text', 'text': BRANCH_SUMMARY_PREFIX + _text(message.get('summary', _MISSING)) + BRANCH_SUMMARY_SUFFIX}]
        elif role == 'compactionSummary':
            content = [{'type': 'text', 'text': COMPACTION_SUMMARY_PREFIX + _text(message.get('summary', _MISSING)) + COMPACTION_SUMMARY_SUFFIX}]
        else:
            continue
        timestamp = message.get('timestamp', _MISSING)
        if role == 'compactionSummary' and not (
            isinstance(timestamp, int | float) and not isinstance(timestamp, bool)
        ):
            timestamp = _timestamp_ms(timestamp)
            if timestamp is None:
                timestamp = 0
        converted.append(_fields(
            role='user', content=content, timestamp=timestamp,
            **({'runtimeContextCarrier': True} if is_runtime_context_carrier(message) else {}),
        ))
    return converted


__all__ = [
    'SessionHistoryMessage', 'is_session_history_prelude',
    'COMPACTION_SUMMARY_PREFIX', 'COMPACTION_SUMMARY_SUFFIX',
    'BRANCH_SUMMARY_PREFIX', 'BRANCH_SUMMARY_SUFFIX',
    'create_branch_summary_message', 'create_compaction_summary_message', 'create_custom_message',
    'project_session_entry_message', 'iterate_session_context_messages', 'build_session_context',
    'bash_execution_to_text', 'is_runtime_context_carrier', 'convert_to_llm',
]
