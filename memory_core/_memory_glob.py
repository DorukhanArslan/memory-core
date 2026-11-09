"""Node 24's Linux POSIX glob string semantics over a Python glob parser.

Filesystem admission stays with the caller. Brace expansion and extglob parsing
come from bracex/wcmatch; path preprocessing, UTF-16 wildcard width and Unicode
POSIX classes follow the actual Node owner used by the pinned reference.
"""
from __future__ import annotations

from functools import lru_cache
import re

import bracex
from wcmatch import glob

from memory_core._memory_glob_unicode import RANGES

_POSIX = re.compile(r'\[:(' + '|'.join((*RANGES, 'ascii', 'xdigit')) + r'):\]')


def _units(value: str) -> str:
    if value.isascii():
        return value
    raw = value.encode('utf-16-le', 'surrogatepass')
    return ''.join(chr(int.from_bytes(raw[index:index + 2], 'little')) for index in range(0, len(raw), 2))


def _characters(value: str) -> str:
    if value.isascii():
        return value
    raw = b''.join(ord(char).to_bytes(2, 'little') for char in value)
    return raw.decode('utf-16-le', 'surrogatepass')


@lru_cache(maxsize=None)
def _class_ranges(name: str) -> str:
    def escaped(value):
        char = chr(value)
        return '\\' + char if char in '\\[]-!^' else char

    # Matching happens one path segment at a time. A literal slash in a glob
    # bracket would make wcmatch parse another path segment instead of a class.
    ranges = ((left, right) for start, end in RANGES[name]
              for left, right in ((start, min(end, 46)), (max(start, 48), end)) if left <= right)
    return ''.join(escaped(start) if start == end else escaped(start) + '-' + escaped(end)
                   for start, end in ranges)


def _unicode_classes(pattern: str) -> tuple[str, bool]:
    result, index, unicode = '', 0, False
    while index < len(pattern):
        if pattern[index] != '[':
            result += pattern[index]
            index += 1
            continue
        start, index = index, index + 1
        content, category = '[', False
        if index < len(pattern) and pattern[index] in '!^':
            content += pattern[index]
            index += 1
        if index < len(pattern) and pattern[index] == ']':
            content += ']'
            index += 1
        while index < len(pattern) and pattern[index] != ']':
            token = _POSIX.match(pattern, index)
            if token:
                name = token[1]
                content += _class_ranges(name) if name in RANGES else token[0]
                category |= name in RANGES
                index = token.end()
            else:
                content += pattern[index]
                index += 1
        if index == len(pattern):
            result += pattern[start:]
            break
        result += content + ']'
        unicode |= category
        index += 1
    return result, unicode


def _segment(candidate: str, pattern: str) -> bool:
    pattern, unicode = _unicode_classes(pattern)
    if not unicode:
        candidate, pattern = _units(candidate), _units(pattern)
    return glob.globmatch(candidate, pattern, flags=glob.EXTGLOB, limit=0)


def _path_patterns(pattern: str) -> list[tuple[str, ...]]:
    queue = [pattern.split('/')]
    complete = []
    seen = set()
    while queue:
        parts = queue.pop()
        reduced = []
        for index, part in enumerate(parts):
            if reduced and part == '**' and reduced[-1] == '**':
                continue
            if part == '..' and reduced and reduced[-1] not in {'', '.', '..', '**'}:
                reduced.pop()
                if not reduced and index + 1 < len(parts) and parts[index + 1] == '**':
                    reduced.append('.')
            elif (part != '.' or index in {0, len(parts) - 1}) and (part or index in {0, len(parts) - 1}):
                reduced.append(part)
        key = tuple(reduced)
        if key in seen:
            continue
        seen.add(key)
        for index, part in enumerate(reduced[:-3]):
            if part == '**' and reduced[index + 1] == '..' and all(
                item not in {'', '.', '..'} for item in reduced[index + 2:index + 4]
            ):
                queue.append(reduced[:index] + reduced[index + 1:])
                queue.append(reduced[:index + 1] + reduced[index + 2:])
                break
        else:
            complete.append(key)
    return complete


@lru_cache(maxsize=2048)
def _expanded_patterns(pattern: str) -> tuple[tuple[str, ...], ...]:
    if len(_units(pattern)) > 65536:
        return ()
    return tuple(parts for expanded in bracex.expand(_units(pattern), keep_escapes=True, limit=0)
                 for parts in _path_patterns(_characters(expanded)))


def matches_posix_glob(candidate: str, pattern: str) -> bool:
    """Match an already-normalized relative path, without reading the filesystem."""
    if not candidate or not pattern:
        return False
    path = tuple(candidate.split('/'))
    for parts in _expanded_patterns(pattern):
        @lru_cache(maxsize=None)
        def match(file_index: int, pattern_index: int) -> bool:
            if pattern_index == len(parts):
                return file_index == len(path)
            current = parts[pattern_index]
            if current == '**':
                if pattern_index == len(parts) - 1:
                    return file_index < len(path) and all(not part.startswith('.') for part in path[file_index:])
                if match(file_index, pattern_index + 1):
                    return True
                return (file_index < len(path) and not path[file_index].startswith('.')
                        and match(file_index + 1, pattern_index))
            if file_index == len(path):
                return False
            return _segment(path[file_index], current) and match(file_index + 1, pattern_index + 1)

        if match(0, 0):
            return True
    return False
