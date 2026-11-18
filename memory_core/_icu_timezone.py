"""ICU's named time zones, including aliases and zones missing from system TZif data."""
from __future__ import annotations

import ctypes
from datetime import datetime, timedelta, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memory_core._icu import _I32, _STATUS, _U16, _UTF16, _check, _function, _icu, _text_units

_EPOCH = datetime(1970, 1, 1)
_PTR = ctypes.c_void_p


@lru_cache(maxsize=1)
def _zones():
    icu = _icu()
    start = _function(icu.i18n_library, 'ucal_openTimeZones', _PTR, _STATUS)
    step = _function(icu.common_library, 'uenum_next', ctypes.c_char_p, _PTR, _STATUS, _STATUS)
    close = _function(icu.common_library, 'uenum_close', None, _PTR)
    status, length = _I32(), _I32()
    pointer = start(ctypes.byref(status))
    _check(status)
    names = {}
    try:
        while (raw := step(pointer, ctypes.byref(length), ctypes.byref(status))) is not None:
            name = raw.decode('ascii')
            names[name.upper()] = name
        _check(status)
    finally:
        close(pointer)
    return names


@lru_cache(maxsize=512)
def named_time_zone(name: str) -> tzinfo | None:
    if not name.isascii():
        return None
    actual = _zones().get(name.upper())
    if actual is None:
        return None
    status, system = _I32(), ctypes.c_int8()
    _, source, length = _text_units(actual)
    target = (ctypes.c_uint16 * 256)()
    canonical = _function(_icu().i18n_library, 'ucal_getCanonicalTimeZoneID', _I32,
                          _U16, _I32, _U16, _I32, ctypes.POINTER(ctypes.c_int8), _STATUS)
    size = canonical(source, length, target, len(target), ctypes.byref(system), ctypes.byref(status))
    _check(status)
    zone = ctypes.string_at(target, size * 2).decode(_UTF16)
    if not system.value or zone == 'Etc/Unknown':
        return None
    for key in (actual, zone):
        try:
            return ZoneInfo(key)
        except ZoneInfoNotFoundError:
            pass
    return _ICUTimeZone(zone)


class _ICUTimeZone(tzinfo):
    """PEP 495 conversion for ICU zones with no installed TZif equivalent."""
    def __init__(self, key: str):
        self.key = key
        _, self._name, self._length = _text_units(key)
        library = _icu().i18n_library
        self._open = _function(library, 'ucal_open', _PTR, _U16, _I32, ctypes.c_char_p, _I32, _STATUS)
        self._close = _function(library, 'ucal_close', None, _PTR)
        self._set = _function(library, 'ucal_setMillis', None, _PTR, ctypes.c_double, _STATUS)
        self._get = _function(library, 'ucal_get', _I32, _PTR, _I32, _STATUS)
        self._local = _function(library, 'ucal_getTimeZoneOffsetFromLocal', None, _PTR, _I32, _I32, _STATUS, _STATUS, _STATUS)

    def _offsets(self, at: datetime, utc: bool):
        status = _I32()
        calendar = self._open(self._name, self._length, b'en', 1, ctypes.byref(status))
        _check(status)
        try:
            delta = at.replace(tzinfo=None) - _EPOCH
            self._set(calendar, delta // timedelta(milliseconds=1), ctypes.byref(status))
            if utc:
                # UCAL_ZONE_OFFSET, UCAL_DST_OFFSET in milliseconds.
                raw = self._get(calendar, 15, ctypes.byref(status))
                dst = self._get(calendar, 16, ctypes.byref(status))
            else:
                # Both gaps and overlaps choose the former side at fold=0.
                option = 0x0C if at.fold else 0x04
                base, daylight = _I32(), _I32()
                self._local(calendar, option, option, ctypes.byref(base), ctypes.byref(daylight), ctypes.byref(status))
                raw, dst = base.value, daylight.value
            _check(status)
            return timedelta(milliseconds=raw + dst), timedelta(milliseconds=dst)
        finally:
            self._close(calendar)

    def fromutc(self, dt):
        if dt.tzinfo is not self:
            raise ValueError('fromutc requires its own time zone')
        offset, _ = self._offsets(dt, utc=True)
        local = dt + offset
        return local if self.utcoffset(local) == offset else local.replace(fold=1)

    def utcoffset(self, dt):
        return self._offsets(dt, utc=False)[0] if dt is not None else None

    def dst(self, dt):
        return self._offsets(dt, utc=False)[1] if dt is not None else None

    def tzname(self, dt):
        return self.key
