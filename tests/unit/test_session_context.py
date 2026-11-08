"""Production context projection preserves persisted messages and replay boundaries."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from memory_core.session_context import (
    BRANCH_SUMMARY_PREFIX, BRANCH_SUMMARY_SUFFIX,
    COMPACTION_SUMMARY_PREFIX, COMPACTION_SUMMARY_SUFFIX,
    SessionHistoryMessage, bash_execution_to_text, build_session_context,
    convert_to_llm, create_branch_summary_message, create_compaction_summary_message,
    create_custom_message, is_session_history_prelude, iterate_session_context_messages,
)
from memory_core.tools.common import MemoryToolError


STAMP = '2026-11-09T00:00:00.123Z'
STAMP_MS = 1_794_182_400_123


def _entry(identifier, message, parent=None):
    return {'type': 'message', 'id': identifier, 'parentId': parent,
            'timestamp': STAMP, 'message': message}


def _assistant(text='reply', **extra):
    return {'role': 'assistant', 'content': [{'type': 'text', 'text': text}],
            'provider': 'fixture', 'model': 'fixture-model', 'api': 'fixture-api',
            'timestamp': STAMP_MS, 'stopReason': 'stop',
            'usage': {'input': 3, 'output': 5, 'totalTokens': 8}, **extra}


def test_current_context_keeps_full_messages_and_latest_branch_metadata_without_mutation():
    user = {'role': 'user', 'content': 'Cedar', 'timestamp': STAMP_MS,
            '__openclaw': {'senderIsOwner': True, 'turnTainted': False}}
    assistant = _assistant()
    tool = {'role': 'toolResult', 'toolCallId': 'call', 'toolName': 'lookup',
            'content': [{'type': 'text', 'text': 'result'}], 'isError': False,
            'details': {'source': 'actual'}, 'timestamp': STAMP_MS}
    entries = [
        {'type': 'thinking_level_change', 'id': 'thinking', 'thinkingLevel': 'high'},
        _entry('u', user), _entry('a', assistant, 'u'), _entry('r', tool, 'a'),
        {'type': 'model_change', 'id': 'model', 'provider': 'later', 'modelId': 'selected'},
    ]
    before = deepcopy(entries)
    context = build_session_context(entries)
    assert context == {'messages': [user, assistant, tool], 'thinkingLevel': 'high',
                       'model': {'provider': 'later', 'modelId': 'selected'}}
    assert context['messages'][0] is user
    assert context['messages'][1] is assistant
    assert convert_to_llm(context['messages']) == [user, assistant, tool]
    assert all(message is original for message, original in zip(convert_to_llm(context['messages']),
                                                                (user, assistant, tool)))
    assert entries == before


@pytest.mark.parametrize('header_version', [3, 4])
def test_context_does_not_reinterpret_header_versions_as_messages(header_version):
    message = {'role': 'user', 'content': 'persisted', 'timestamp': STAMP_MS}
    context = build_session_context([
        {'type': 'session', 'version': header_version, 'id': 'session', 'timestamp': STAMP},
        _entry('one', message),
    ])
    assert context == {'messages': [message], 'thinkingLevel': 'off', 'model': None}


def test_reset_retention_keeps_owned_tool_pairs_and_nonpersisted_history_markers():
    user = {'role': 'user', 'content': 'kept', 'timestamp': STAMP_MS, 'excludeFromContext': True}
    checkpoint = {'v': 1, 'type': 'openai-responses-compaction', 'encryptedContent': 'opaque'}
    assistant = _assistant(stopReason='toolUse', content=[
        {'type': 'toolCall', 'id': 'paired', 'name': 'lookup', 'arguments': {'key': 'value'}},
    ], providerReplay=checkpoint)
    result = {'role': 'toolResult', 'toolCallId': 'paired', 'toolName': 'lookup',
              'content': [{'type': 'text', 'text': 'kept result'}], 'timestamp': STAMP_MS}
    current = _assistant('current', providerReplay=checkpoint)
    entries = [
        _entry('kept-user', user), _entry('kept-assistant', assistant, 'kept-user'),
        _entry('paired-result', result, 'kept-assistant'),
        _entry('orphan', {**result, 'toolCallId': 'missing'}),
        {'type': 'custom_message', 'id': 'old-custom', 'customType': 'note', 'content': 'drop',
         'display': True, 'details': {}, 'timestamp': STAMP},
        {'type': 'reset', 'id': 'reset', 'firstKeptEntryId': 'kept-user'},
        _entry('excluded-current', {**user, 'content': 'not in context'}),
        _entry('current', current, 'reset'),
    ]
    before = deepcopy(entries)
    context = build_session_context(entries)
    messages = context['messages']
    assert [message['role'] for message in messages] == ['user', 'assistant', 'toolResult', 'assistant']
    assert messages[0] == user and messages[0] is not user
    assert 'providerReplay' not in messages[1]
    assert messages[2] is result and messages[3] is current
    assert [is_session_history_prelude(message) for message in messages] == [True, True, False, False]
    llm = convert_to_llm(messages)
    assert [is_session_history_prelude(message) for message in llm] == [True, True, False, False]
    assert all(left is right for left, right in zip(llm, messages))
    persisted = json.loads(json.dumps(context))
    assert not any(is_session_history_prelude(message) for message in persisted['messages'])
    assert not is_session_history_prelude({'role': 'user', 'sessionHistoryPrelude': True})
    assert entries == before and assistant['providerReplay'] == checkpoint


def test_compaction_summary_precedes_kept_messages_and_drops_only_retained_checkpoint():
    replay = {'v': 1, 'type': 'anthropic-compaction', 'data': 'checkpoint'}
    kept = _assistant('kept', providerReplay=replay)
    current = _assistant('current', providerReplay=replay)
    entries = [
        _entry('discarded', {'role': 'user', 'content': 'old', 'timestamp': 0}),
        _entry('kept', kept),
        {'type': 'compaction', 'id': 'boundary', 'firstKeptEntryId': 'kept',
         'summary': 'Prior durable facts', 'tokensBefore': 123, 'timestamp': STAMP},
        _entry('current', current, 'boundary'),
    ]
    messages = build_session_context(entries)['messages']
    assert messages[0] == {'role': 'compactionSummary', 'summary': 'Prior durable facts',
                           'tokensBefore': 123, 'timestamp': STAMP_MS}
    assert 'providerReplay' not in messages[1]
    assert messages[2] is current and 'providerReplay' in current
    assert not any(is_session_history_prelude(message) for message in messages)
    assert convert_to_llm(messages)[0] == {
        'role': 'user', 'content': [{'type': 'text', 'text': COMPACTION_SUMMARY_PREFIX +
                                    'Prior durable facts' + COMPACTION_SUMMARY_SUFFIX}],
        'timestamp': STAMP_MS,
    }


def test_custom_and_branch_messages_convert_with_runtime_carrier_and_exact_timestamps():
    entries = [
        {'type': 'custom_message', 'id': 'carrier', 'customType': 'runtime',
         'content': [{'type': 'text', 'text': 'Runtime context'}], 'display': False,
         'details': {'runtimeContextCarrier': True, 'custom': None}, 'timestamp': STAMP},
        {'type': 'branch_summary', 'id': 'branch', 'fromId': 'original',
         'summary': 'Branch facts', 'timestamp': STAMP},
        {'type': 'branch_summary', 'id': 'empty', 'fromId': 'original',
         'summary': '', 'timestamp': 'not parsed for an empty summary'},
    ]
    context = build_session_context(entries)
    assert len(context['messages']) == 2
    assert context['messages'][0]['details'] == {'runtimeContextCarrier': True, 'custom': None}
    assert convert_to_llm(context['messages']) == [
        {'role': 'user', 'content': [{'type': 'text', 'text': 'Runtime context'}],
         'timestamp': STAMP_MS, 'runtimeContextCarrier': True},
        {'role': 'user', 'content': [{'type': 'text', 'text': BRANCH_SUMMARY_PREFIX +
                                    'Branch facts' + BRANCH_SUMMARY_SUFFIX}], 'timestamp': STAMP_MS},
    ]


def test_context_hydration_stops_before_later_payloads_when_consumer_stops():
    navigation = [
        {'type': 'compaction', 'id': 'boundary'},
        {'type': 'message', 'id': 'later'},
    ]
    hydrated = []

    def read(entry):
        hydrated.append(entry['id'])
        if entry['id'] == 'boundary':
            return {'type': 'compaction', 'summary': 'summary', 'tokensBefore': 7, 'timestamp': STAMP}
        raise AssertionError('Later payload should not be read by a bounded consumer')

    iterator = iterate_session_context_messages(navigation, read)
    assert next(iterator)['role'] == 'compactionSummary'
    assert hydrated == ['boundary']
    iterator.close()


@pytest.mark.parametrize('create,args,message', [
    (create_branch_summary_message, ('summary', 'from', 'invalid'), 'branch summary timestamp'),
    (create_compaction_summary_message, ('summary', 5, 'invalid'), 'compaction summary timestamp'),
    (create_custom_message, ('kind', 'content', True, {}, 'invalid'), 'custom message timestamp'),
])
def test_persisted_special_messages_reject_invalid_constructor_timestamps(create, args, message):
    with pytest.raises(MemoryToolError, match=message + ' must be a valid timestamp'):
        create(*args)
    assert create(*args[:-1], '1970-01-01T00:00:00Z')['timestamp'] == 0


def test_llm_conversion_keeps_typed_ordinary_records_and_normalizes_only_compaction_timestamp():
    user = {'role': 'user', 'content': 'full user', 'timestamp': 1, 'extra': {'unchanged': True}}
    unknown = {'role': 'unrecognized', 'content': 'not model input'}
    messages = [
        user, unknown,
        {'role': 'custom', 'content': 'display only', 'excludeFromContext': True, 'timestamp': 9},
        {'role': 'compactionSummary', 'summary': 'corrupt date', 'timestamp': 'invalid'},
        {'role': 'branchSummary', 'summary': 'branch date is already prepared', 'timestamp': 'opaque'},
    ]
    llm = convert_to_llm(messages)
    assert llm[0] is user
    assert len(llm) == 3 and llm[1]['timestamp'] == 0 and llm[2]['timestamp'] == 'opaque'


def test_bash_projection_preserves_status_priority_and_truncation_detail():
    message = {'role': 'bashExecution', 'command': 'echo cedar', 'output': 'cedar',
               'cancelled': True, 'exitCode': 7, 'truncated': True,
               'fullOutputPath': '/owned/output', 'timestamp': 23}
    expected = 'Ran `echo cedar`\n```\ncedar\n```\n\n(command cancelled)\n\n[Output truncated. Full output: /owned/output]'
    assert bash_execution_to_text(message) == expected
    assert convert_to_llm([message]) == [
        {'role': 'user', 'content': [{'type': 'text', 'text': expected}], 'timestamp': 23},
    ]
    assert bash_execution_to_text({'command': 'false', 'output': '', 'exitCode': 2}) == (
        'Ran `false`\n(no output)\n\nCommand exited with code 2'
    )


def test_history_carrier_remains_plain_json_and_current_messages_keep_missing_metadata_absent():
    carried = SessionHistoryMessage({'role': 'user', 'content': 'old', 'timestamp': 1})
    assert json.dumps(carried) == '{"role": "user", "content": "old", "timestamp": 1}'
    assert is_session_history_prelude(carried)
    assert not is_session_history_prelude(dict(carried))
    minimal = {'role': 'assistant', 'content': []}
    assert build_session_context([_entry('minimal', minimal)])['model'] == {}
