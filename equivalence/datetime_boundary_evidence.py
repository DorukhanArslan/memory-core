"""Classify actual parser decisions. Missing receipts can never stand for equal refusals."""
from __future__ import annotations

from hashlib import sha256
import json

from equivalence.datetime_boundary_cases import CORPUS, DIAGNOSTIC, INVALID, POINT as POINT, STAMPS, UNSAFE, ZONE, build_cases, members
from equivalence.datetime_regex_evidence import same
from equivalence.datetime_regex_family import CLOCK_OWNERS, wire

CORPUS_OWNERS = ['packages/memory-host-sdk/src/host/session-files.ts', 'packages/memory-host-sdk/src/host/session-reset-recall.ts']


# Raw results from the first full five-case comparison; both numeric wire encodings are retained.
PUBLIC_DIGESTS = {'engine-datetime-boundary-stored-calendar': {'openclaw': 'b7743cf023195e643edf1cc6b18ba427b5f36459de725c289beebc37da05eef4',
                                              'python': 'df47e4d2760a9c837210df318d5f56fe200139ce7ddc29326cabc6dae069f11a'},
 'engine-datetime-boundary-zone-admission': {'openclaw': '0f52241662599d9179ad54d7f7cd1a06afd8aa51620b11563c0c6ea68384d035',
                                             'python': '0f52241662599d9179ad54d7f7cd1a06afd8aa51620b11563c0c6ea68384d035'},
 'engine-datetime-boundary-unsafe-pattern': {'openclaw': '1e59cf66857d53b5ca66e4e20c5a03eb6e0c1abab1150eb9a8aaaaf50a6236f7',
                                             'python': '1e59cf66857d53b5ca66e4e20c5a03eb6e0c1abab1150eb9a8aaaaf50a6236f7'},
 'engine-datetime-boundary-invalid-flags': {'openclaw': '275facec42180075d0bf76cc8bb9b2741f6b8f57f4fe4a26e243ace329138905',
                                            'python': '275facec42180075d0bf76cc8bb9b2741f6b8f57f4fe4a26e243ace329138905'},
 'engine-datetime-unverified-legacy-grammar': {'openclaw': '2894a4e3507c76c6ae0262b13b5627903bcb966471bcd7df529f0a1c81afdb49',
                                               'python': '6e70c4b4022bb834969d2d37855927adbeab4cd06c4503907cf57a8156941fe7'}}
DIAGNOSTIC_CELLS = [{'probe': '-000000-01-01',
  'openclaw': {'status': 'accepted', 'value': 978307200000},
  'python': {'status': 'rejected', 'value': 1600000000001},
  'comparison': 'mismatched',
  'sdkGrammar': None},
 {'probe': 'January 32 2026',
  'openclaw': {'status': 'rejected', 'value': 1600000000002},
  'python': {'status': 'rejected', 'value': 1600000000002},
  'comparison': 'uncovered',
  'sdkGrammar': None}]

def _decision(value, fallback):
    return {'status': 'rejected' if value == fallback else 'accepted', 'value': value}


def _classify(probe, native, sdk, *, supported=True):
    return {'probe': probe, 'openclaw': native, 'python': sdk,
            'comparison': ('mismatched' if native != sdk else 'matched' if supported else 'uncovered')}


def _corpus(case, output):
    first, reopened = output['reads']
    same(first, reopened)
    raw = case['input']['jsonl']
    records = [json.loads(line) for line in raw.splitlines()][1:]
    same(first['sourceSha256'], sha256(raw.encode()).hexdigest())
    entry, events = first['entry'], first['observed']
    same(entry['lineMap'], list(range(2, len(records) + 2)))
    same(entry['content'].splitlines(), ['User: ' + r['message']['content'] for r in records])
    same([e['message'] for e in events], [r['message'] for r in records])
    times = [e['at'] for e in events]
    same(entry['messageTimestampsMs'], times)
    same([p['observedAt'] for p in entry['lineProvenance']], times)
    return [_decision(t, r['timestamp']) for t, r in zip(times, records, strict=True)]


def _zones(case, output):
    same([r['iso'] for r in output['instants']], [r['iso'] for r in case['input']['instants']])
    result = []
    for entry, request in zip(output['instants'], case['input']['instants'], strict=True):
        clock = entry['resolved']
        if not entry['refreshed'].endswith(clock['timeLine']):
            raise ValueError('Configured zone did not reach the current-time refresh owner')
        result.append({'status': 'accepted' if clock['userTimezone'] == request['zone'] else 'rejected',
                       'zone': clock['userTimezone'], 'timeLine': clock['timeLine']})
    return result


def observe(case, report, native, sdk):
    cid = case['id']
    if cid in (CORPUS, DIAGNOSTIC, ZONE):
        owners = CORPUS_OWNERS if cid != ZONE else CLOCK_OWNERS
        same(report['datetimeSourceImports'][cid], owners)
        if not set(owners) <= {r['path'] for r in report['sources']}:
            raise ValueError('A public parser owner is missing')
        getter = _zones if cid == ZONE else _corpus
        original, python = getter(case, native), getter(case, sdk)
        if cid == ZONE:
            probes = [r['zone'] for r in case['input']['instants']]
            return [_classify(p, n, s) for p, n, s in zip(probes, original, python, strict=True)]
        from memory_core._js_date import date_parse_profile
        probes = [json.loads(line)['message']['timestamp'] for line in case['input']['jsonl'].splitlines()[1:]]
        results = []
        for probe, n, s in zip(probes, original, python, strict=True):
            profile = date_parse_profile(probe)
            results.append({**_classify(probe, n, s, supported=profile is not None), 'sdkGrammar': profile})
        return results
    [policy] = [r['sourceExecution'] for r in report['sourcePolicyDiagnostics'] if r['id'] == cid]
    [frame] = policy['observations']
    same(policy['requestCase'], case)
    same(frame['input'], case['input'])
    same(frame['output'], native)
    [call] = [c for c in frame['calls'] if c['name'] == 'compileConfigRegex']
    same(call['result'], native['result']['directCompiler'])
    [packet] = [r for r in report['runtimeDiagnostics'] if r['id'] == cid and r['side'] == 'python']
    [snapshot] = packet['rawSnapshots']
    [child] = snapshot['children']
    same(child['request'], {'operation': case['operation'], 'input': case['input']})
    same(child['raw']['output'], sdk)
    same(json.loads(child['stdout']), {'result': sdk, 'raw': child['raw']})
    same(child['exit'], {'code': 0, 'signal': None})
    same([child['raw']['pid'], child['raw']['ppid']], [child['pid'], snapshot['coordinatorPid']])
    if child['pid'] == snapshot['coordinatorPid']:
        raise ValueError('The policy worker requires a separate process')
    compilers = [public['result']['directCompiler'] for public in (native, sdk)]
    for compiler in compilers:
        same([compiler['pattern'], compiler['flags']], [case['input']['directRegex']['source'], case['input']['directRegex']['flags']])
    same(compilers[0]['reason'], 'unsafe-nested-repetition' if cid == UNSAFE else 'invalid-regex')
    same(compilers[0]['accepted'], False)
    if native['result']['explicitSensitiveText'] == case['input']['text']:
        raise ValueError('The independent ordinary companion redaction rule did not execute')
    return [_classify(case['input']['directRegex'], *compilers)]


def family_complete(rows):
    definitions = build_cases()
    actual = members(rows)
    if len(actual) != len(definitions):
        return False
    from equivalence.harness import _same_json
    for case, row in zip(definitions, actual, strict=True):
        if wire({key: row.get(key) for key in case}) != wire(case):
            return False
        public = row.get('publicValueSha256')
        if 'openclaw' in row and 'python' in row:
            public = {k: sha256(wire(row[k])).hexdigest() for k in ('openclaw', 'python')}
        if public != PUBLIC_DIGESTS[case['id']]:
            return False
        classified = row.get('datetimeBoundaryEvidence', [])
        if case['id'] == DIAGNOSTIC:
            if not (row.get('status') == 'mismatched' and row['covers'] == []
                    and _same_json(classified, DIAGNOSTIC_CELLS)):
                return False
            continue
        count = {CORPUS: len(STAMPS), ZONE: len(case['input'].get('instants', [])), UNSAFE: 1, INVALID: 1}[case['id']]
        if not (row.get('status') == 'matched'
                and len(classified) == count and all(c['comparison'] == 'matched' and
                _same_json(c['openclaw'], c['python']) for c in classified)):
            return False
    return True
