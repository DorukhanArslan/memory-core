"""Check the awaited REM callback, retry, cancellation and failed publication."""

from __future__ import annotations

from copy import deepcopy

from equivalence.dream_light_evidence import require, same


def phase_config(opts):
    return {'light': {'enabled': False}, 'rem': {'enabled': True, 'limit': opts['limit'],
            'lookbackDays': opts['lookbackDays'], 'minPatternStrength': opts['minPatternStrength'],
            'execution': {'model': opts['model']}}}


def validate_callbacks(raw, opts):
    calls = raw['modelCalls']
    replies = opts['provider'] or []
    require(isinstance(calls, list) and len(calls) == len(replies), 'Native provider omitted or added a call')
    for index, (call, reply) in enumerate(zip(calls, replies, strict=True)):
        error = 'error' in reply
        require(set(call) == {'request', 'reply', 'callerStack', 'nowMs', 'error' if error else 'returned'},
                'Native provider invocation is incomplete')
        same(call['reply'], reply, 'Native provider input changed')
        require(type(call['nowMs']) is int and isinstance(call['callerStack'], str) and
                'generateAndAppendDreamNarrative' in call['callerStack'] and
                '/node_modules/openclaw/dist/dreaming-narrative-B8Hp3Mc_.mjs:' in call['callerStack'],
                'Provider delivery is missing its published narrative caller')
        request = call['request']
        model = opts['model'] if index == 0 else None
        require(set(request) == {'agentId', 'message', 'extraSystemPrompt', 'timeoutMs'} | ({'model'} if model else set())
                and opts['agentId'] is not None and request['agentId'] == opts['agentId']
                and request.get('model') == model and type(request['timeoutMs']) is int and request['timeoutMs'] > 0
                and all(isinstance(request[key], str) and request[key] for key in ('message', 'extraSystemPrompt')),
                'Native model request is incomplete')
        if index:
            first = {k: v for k, v in calls[0]['request'].items() if k != 'model'}
            same(request, first, 'Retry on the default model changed other request fields')
        if error:
            observed = call['error']
            require(observed['name'] == 'Error' and observed['message'] == reply['error']
                    and isinstance(observed['stack'], str) and reply['error'] in observed['stack'],
                    'Provider failure was rewritten')
        else:
            same(call['returned'], {'text': reply['text']}, 'Native provider return was rewritten')


def callback_effects(raw, now_ms, now, workspace, take):
    calls = [item for item in raw['modelCalls'] if item['nowMs'] == now_ms]
    for call in calls:
        if 'removeKey' in call['reply']:
            key = call['reply']['removeKey']
            before = deepcopy(take('readStore', [workspace, now]))
            require(key in before['entries'], 'Callback did not observe the actual source to withdraw')
            del before['entries'][key]
            take('writeStore', [workspace, before], undefined=True)
    return [call['request'] for call in calls]


def validate_publication(case, raw, trees, observations):
    first, last = trees[0], trees[-1]
    final = observations[-1]
    name = case['id']
    replies = case['input']['options']['provider'] or []
    logs = [(row['level'], entry) for row in raw['logs'] for entry in row['args'] if isinstance(entry, str)]
    if name == 'dream-rem-source-removed-during-completion':
        key = replies[0]['removeKey']
        require(key not in final['recall']['entries'] and first.get('workspace/DREAMS.md') == last.get('workspace/DREAMS.md')
                and ('info', 'memory-core: narrative publication skipped for rem phase because source memory or diary context changed.') in logs,
                'Original failed to cancel publication after the source was withdrawn')
    if name == 'dream-rem-publication-failure':
        sentinel = 'workspace/DREAMS.md/keep.txt'
        require(last[sentinel] == first[sentinel] and 'workspace/DREAMS.md' not in last
                and final['sweepResults'][-1]['degradedPhases'] == 1
                and any(level == 'warn' and 'Refusing to write non-file DREAMS.md' in msg for level, msg in logs)
                and any(level == 'warn' and 'narrative fallback failed' in msg for level, msg in logs),
                'Original diary publication conflict or fallback failure was lost')
