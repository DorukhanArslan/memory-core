"""Stable calendar ambiguity and safe-regex terminal inputs, with public controls."""
from __future__ import annotations

from hashlib import sha256
import json

from equivalence.datetime_regex_family import _clock, _regex, wire

POINT = 'engine.datetime-regex.boundaries'
PREFIX = 'engine-datetime-boundary-'
CORPUS = PREFIX + 'stored-calendar'
ZONE = PREFIX + 'zone-admission'
UNSAFE = PREFIX + 'unsafe-pattern'
INVALID = PREFIX + 'invalid-flags'
DIAGNOSTIC = 'engine-datetime-unverified-legacy-grammar'
IDS = (CORPUS, ZONE, UNSAFE, INVALID, DIAGNOSTIC)
UNVERIFIED = ('-000000-01-01', 'January 32 2026')
DEFINITION_SHA256 = 'eed4b7a9ea5384d668d6622815fbc64d2d032fe4b95e10d2c45a6567aaa4ac6c'
STAMPS = (
    '2026-04-02T15:46:00+05:45', '04/02/2026 10:01:00 GMT', '02/04/2026 10:01:00 GMT',
    '15/04/2026 10:01:00 GMT', '2026-02-30T10:01:00Z', '2026-04-02T24:00:00Z',
    '2026-04-02T24:00:00.001Z', '2026-04-02T10:01:00,999Z', '2026-04-02T10:01:00+25:00',
    '0', 'not a date',
)
BASE_MS = 1_600_000_000_000


def _calendar(stamps):
    records = [{'type': 'session', 'id': 'calendar', 'version': 3}]
    for index, stamp in enumerate(stamps, start=1):
        # Distinguish a rejected message timestamp from a valid date or a lost row.
        records.append({'type': 'message', 'id': f'calendar-{index}', 'timestamp': BASE_MS + index,
                        'message': {'role': 'user', 'timestamp': stamp, 'content': f'Calendar entry {index}.'}})
    return {'operation': 'session-projection', 'input': {'reopenDatetimeCorpus': True, 'mtimeMs': BASE_MS,
              'jsonl': ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in records)},
              'driverScope': 'Reopen the same raw timestamped transcript twice through each ordinary session reader. '
                             'A distinct valid record timestamp makes every rejected message timestamp observable.',
              'normalizationPolicy': 'Compare both entire file entries, callbacks, source bytes and public timestamp choices.'}


def _cases():
    corpus = _calendar(STAMPS)
    zone = _clock('boundary-zone-admission', [('2026-11-01T06:30:00.000Z', z) for z in
                  ('America/New_York', 'america/new_york', 'SystemV/AST4', 'right/UTC', '+24:00', '−04:30')])
    text = 'Keep aaa and Ticket:MAPLE.'
    unsafe = _regex('boundary-unsafe-pattern', '(a+)+', 'gu', text)
    invalid = _regex('boundary-invalid-flags', 'Maple', 'gg', text)
    for case in (unsafe, invalid):
        # A valid companion rule must still redact in the same actual request.
        case['input']['patterns'].append('/(Ticket:)([A-Z]+)/g')
        case['driverScope'] = 'Observe the actual compiler refusal and the surviving configured rule across text, structured and stored transcript public policy results.'
    diagnostic = _calendar(UNVERIFIED)
    cases = [corpus, zone, unsafe, invalid, diagnostic]
    for case, ident in zip(cases, IDS, strict=True):
        case.update(id=ident, requirement='engine.datetime-regex', covers=[] if ident == DIAGNOSTIC else [POINT])
    return cases


def build_cases():
    rows = _cases()
    if sha256(wire(rows)).hexdigest() != DEFINITION_SHA256:
        raise ValueError('The date/regex boundary definitions changed')
    return rows


def members(rows):
    return [r for r in rows if (str(r.get('id', '')).startswith(PREFIX) or r.get('id') == DIAGNOSTIC) or POINT in r.get('covers', ())]


def validate_registration(rows):
    actual = members(rows)
    if actual and wire(actual) != wire(build_cases()):
        raise ValueError('The full date/regex boundary family and frozen scope are required')
