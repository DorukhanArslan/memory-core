"""V8-compatible timestamp forms shared by the session reader and promotion store."""
from __future__ import annotations

import json
import math
import re
from threading import local

import quickjs

# ECMAScript's required calendar grammar and V8's common space separator.
_CALENDAR = re.compile(
    r'(?:[+-]\d{6}|\d{4})(?:-\d{2}(?:-\d{2})?)?'
    r'(?:[T ]\d\d:\d\d(?::\d\d(?:[.,]\d+)?)?)?(?:Z|[+-]\d\d:?\d\d)?', re.ASCII | re.I)
# These legacy grammars are deliberately finite. V8 does not specify a general
# interpretation of arbitrary English or locale-dependent date strings.
_SLASH = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{4})(?: +(\d{1,2}):(\d{2})(?::(\d{2}))?(?: +(GMT))?)?', re.ASCII | re.I)
_UTC_STRING = re.compile(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} '
                         r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} '
                         r'\d{2}:\d{2}:\d{2} GMT', re.ASCII | re.I)
_SHORT_NUMBER = re.compile(r'\d{1,2}', re.ASCII)
_NO_NUMBERS = re.compile(r'[a-zA-Z ]*', re.ASCII)
_state = local()


def date_parse_profile(value: str) -> str | None:
    """Supported parser grammar. None means an implementation-defined source input is unverified."""
    if _CALENDAR.fullmatch(value):
        # V8 can delegate this invalid expanded year to a separate legacy parser.
        if value.startswith('-000000') or (' ' in value and (not value[:4].isdecimal() or int(value[:4]) < 1000)):
            return None
        if ' ' in value and (offset := re.search(r'[+-](\d\d):?(\d\d)$', value)) and int(offset[1]) > 23:
            return None
        return 'calendar'
    if slash := _SLASH.fullmatch(value):
        return 'legacy' if int(slash[3]) >= 1000 else None
    if _SHORT_NUMBER.fullmatch(value) or _UTC_STRING.fullmatch(value):
        return 'legacy'
    if _NO_NUMBERS.fullmatch(value):
        return 'invalid'
    return None


def js_date_parse(value: str) -> float:
    """Parse the supported forms with JavaScript Date limits, normalization and local-time rules."""
    profile = date_parse_profile(value)
    if profile is None or profile == 'invalid' or (profile == 'calendar' and ',' in value):
        return math.nan
    if profile == 'calendar':
        value = value.upper().replace(' ', 'T', 1)
    elif slash := _SLASH.fullmatch(value):
        month, day, year, hour, minute, second, gmt = slash.groups()
        value = (f'{year}-{int(month):02d}-{int(day):02d}T{int(hour or 0):02d}:'
                 f'{minute or "00"}:{second or "00"}' + ('Z' if gmt else ''))
    if not hasattr(_state, 'parse'):
        _state.context = quickjs.Context()
        _state.parse = _state.context.eval('wire => Date.parse(JSON.parse(wire))')
    return _state.parse(json.dumps(value, ensure_ascii=True))
