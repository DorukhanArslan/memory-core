"""The pinned ICU data behind OpenClaw's default English ordering and word breaks."""

from __future__ import annotations

import ctypes
import sys
import weakref
from ctypes.util import find_library
from functools import lru_cache
from importlib.metadata import distribution

from icu4py import icu_version_info

# ICU C APIs take counted arrays of UTF-16 units. Keeping the count separate
# preserves embedded NULs and lone surrogate halves exactly as in JavaScript.
_U16 = ctypes.POINTER(ctypes.c_uint16)
_I32 = ctypes.c_int32
_STATUS = ctypes.POINTER(_I32)
_UTF16 = "utf-16-le" if sys.byteorder == "little" else "utf-16-be"


def _library(unix_name: str, windows_name: str):
    package = distribution("icu4py")
    for path in package.files or ():
        name = path.name.lower()
        if name.startswith("lib" + unix_name) or (name.startswith(windows_name) and name.endswith(".dll")):
            return ctypes.CDLL(str(package.locate_file(path)))
    # A source installation links the system ICU used to build icu4py.
    library = find_library(unix_name) or find_library(windows_name)
    if not library:
        raise ImportError(f"Could not locate {unix_name} from the installed ICU runtime")
    return ctypes.CDLL(library)


def _function(library, name, result, *parameters):
    function = getattr(library, f"{name}_{icu_version_info[0]}")
    function.argtypes = parameters
    function.restype = result
    return function


def _check(status: _I32):
    # Negative ICU codes are success with additional information (e.g. a
    # requested locale using its parent locale's equivalent collation).
    if status.value > 0:
        raise RuntimeError(f"ICU operation failed with UErrorCode {status.value}")


class _ICU:
    def __init__(self):
        if icu_version_info[:2] != (78, 3):
            raise ImportError("The pinned OpenClaw Unicode profile requires ICU 78.3")
        i18n = _library("icui18n", "icuin")
        common = _library("icuuc", "icuuc")
        self.data_library = _library("icudata", "icudt")
        version = (ctypes.c_uint8 * 4)()
        _function(common, "u_getVersion", None, ctypes.POINTER(ctypes.c_uint8))(version)
        self.runtime_version = tuple(version)
        _function(common, "u_getUnicodeVersion", None, ctypes.POINTER(ctypes.c_uint8))(version)
        self.unicode_version = tuple(version)
        if self.runtime_version[:2] != (78, 3) or self.unicode_version[:2] != (17, 0):
            raise ImportError("The active ICU libraries do not match the pinned Unicode data")
        self.i18n_library = i18n
        self.common_library = common
        ptr = ctypes.c_void_p
        open_collator = _function(i18n, "ucol_open", ptr, ctypes.c_char_p, _STATUS)
        close_collator = _function(i18n, "ucol_close", None, ptr)
        self.sort_key = _function(i18n, "ucol_getSortKey", _I32, ptr, _U16, _I32, ptr, _I32)
        self.open_breaker = _function(common, "ubrk_open", ptr, _I32, ctypes.c_char_p, _U16, _I32, _STATUS)
        self.next_break = _function(common, "ubrk_next", _I32, ptr)
        self.rule_status = _function(common, "ubrk_getRuleStatus", _I32, ptr)
        self.close_breaker = _function(common, "ubrk_close", None, ptr)
        self.lower = _function(common, "u_strToLower", _I32, _U16, _I32, _U16, _I32, ctypes.c_char_p, _STATUS)
        self.category = _function(common, "u_charType", ctypes.c_int8, _I32)
        self.script = _function(common, "uscript_getScript", _I32, _I32, _STATUS)
        self.script_name = _function(common, "uscript_getShortName", ctypes.c_char_p, _I32)
        nfkc = _function(common, "unorm2_getNFKCInstance", ptr, _STATUS)
        self.normalize = _function(common, "unorm2_normalize", _I32, ptr, _U16, _I32, _U16, _I32, _STATUS)
        status = _I32()
        self.nfkc = nfkc(ctypes.byref(status))
        _check(status)
        # Immutable after initialization. ICU const operations may share it
        # between threads; each mutable break iterator below is per call.
        self.collator = open_collator(b"en_US", ctypes.byref(status))
        _check(status)
        if not self.collator:
            raise RuntimeError("ICU returned no English collator")
        weakref.finalize(self, close_collator, self.collator)


@lru_cache(maxsize=1)
def _icu() -> _ICU:
    return _ICU()


def _text_units(text: str):
    encoded = text.encode(_UTF16, "surrogatepass")
    length = len(encoded) // 2
    return encoded, (ctypes.c_uint16 * length).from_buffer_copy(encoded), length


@lru_cache(maxsize=2048)
def character_category(char: str) -> int:
    """ICU UCharCategory, including letters 1..5 and numbers 9..11."""
    return _icu().category(ord(char))


@lru_cache(maxsize=2048)
def script_name(char: str) -> bytes:
    icu = _icu()
    status = _I32()
    code = icu.script(ord(char), ctypes.byref(status))
    _check(status)
    return icu.script_name(code)


def _transform(text: str, *, lower: bool) -> str:
    if text.isascii():
        return text.lower() if lower else text
    icu = _icu()
    _, units, length = _text_units(text)
    # Most case mappings and normalizations fit in the original UTF-16 length.
    capacity = length
    while True:
        buffer = (ctypes.c_uint16 * capacity)()
        status = _I32()
        if lower:
            size = icu.lower(buffer, capacity, units, length, b"", ctypes.byref(status))
        else:
            size = icu.normalize(icu.nfkc, units, length, buffer, capacity, ctypes.byref(status))
        if status.value == 15:  # U_BUFFER_OVERFLOW_ERROR
            capacity = size
            continue
        _check(status)
        return ctypes.string_at(buffer, size * 2).decode(_UTF16, "surrogatepass")


def lowercase(text: str) -> str:
    return _transform(text, lower=True)


def normalize_nfkc(text: str) -> str:
    return _transform(text, lower=False)


def locale_sort_key(text: str) -> bytes:
    icu = _icu()
    _, units, length = _text_units(text)
    size = icu.sort_key(icu.collator, units, length, None, 0)
    buffer = ctypes.create_string_buffer(size)
    written = icu.sort_key(icu.collator, units, length, buffer, size)
    if written != size or size < 1:
        raise RuntimeError("ICU returned an inconsistent collation key")
    return buffer.raw


def word_tokens(text: str) -> list[str]:
    icu = _icu()
    encoded, units, length = _text_units(text)
    status = _I32()
    # UBRK_WORD and the "und" locale used by OpenClaw's Intl.Segmenter.
    iterator = icu.open_breaker(1, b"und", units, length, ctypes.byref(status))
    _check(status)
    if not iterator:
        raise RuntimeError("ICU returned no word break iterator")
    try:
        words = []
        start = 0
        while (end := icu.next_break(iterator)) != -1:
            # ECMA-402 IsWordLike: NUMBER, LETTER, KANA and IDEO statuses.
            if icu.rule_status(iterator) >= 100:
                words.append(encoded[start * 2 : end * 2].decode(_UTF16, "surrogatepass"))
            start = end
        return words
    finally:
        icu.close_breaker(iterator)
