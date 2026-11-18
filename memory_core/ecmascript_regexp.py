"""ECMAScript regular expressions for configured rules. Only data enters the embedded engine."""
from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass
import json
import re
from threading import local

import quickjs

# Each iterator owns its RegExp and lastIndex. Thread-local helpers hold no text
# or matcher state, so multiple and nested redaction calls do not share a cursor.
_START = r"""wire => {
  const [source, flags, text, position, mode] = JSON.parse(wire);
  let actualFlags = flags;
  for (const flag of "dg") if (!actualFlags.includes(flag)) actualFlags += flag;
  if (mode !== "search" && !actualFlags.includes("y")) actualFlags += "y";
  const re = new RegExp(mode === "full" ? "(?:" + source + ")(?![\\s\\S])" : source, actualFlags);
  re.lastIndex = position;
  const matches = text.matchAll(re);
  return () => {
    const batch = [];
    while (batch.length < 128) {
      const next = matches.next();
      if (next.done) break;
      batch.push(next.value.indices);
      if (mode !== "search") break;
    }
    return JSON.stringify(batch);
  };
}"""
_VALID = r"""wire => {
  const [source, flags] = JSON.parse(wire);
  try { new RegExp(source, flags); return true; }
  catch (error) { if (error instanceof SyntaxError) return false; throw error; }
}"""
_ASTRAL = re.compile("[\U00010000-\U0010ffff]")
_state = local()


def _helpers():
    if not hasattr(_state, "context"):
        ctx = quickjs.Context()
        _state.context = ctx
        _state.valid = ctx.eval(_VALID)
        _state.start = ctx.eval(_START)
    return _state


@dataclass(frozen=True)
class ECMAMatch:
    string: str
    spans: tuple[tuple[int, int], ...]

    def start(self, group: int = 0) -> int:
        return self.spans[group][0]

    def end(self, group: int = 0) -> int:
        return self.spans[group][1]

    def span(self, group: int = 0) -> tuple[int,int]:
        return self.spans[group]

    def group(self, group: int = 0) -> str | None:
        start, end = self.spans[group]
        return self.string[start:end] if start >= 0 else None

    def groups(self, default=None) -> tuple:
        return tuple(self.string[a:b] if a >= 0 else default for a, b in self.spans[1:])


@dataclass(frozen=True)
class ECMAPattern:
    pattern: str
    flags: str

    def valid(self) -> bool:
        return _helpers().valid(json.dumps([self.pattern,self.flags], ensure_ascii=True))

    def _matches(self, text: str, position: int, mode: str) -> Iterator[ECMAMatch]:
        position=max(0,position)
        if position>len(text):
            return
        astral=[m.start() for m in _ASTRAL.finditer(text)]
        # The engine reports UTF-16 code-unit offsets. Incoming text for a
        # non-Unicode redactor already contains explicit surrogate units.
        second_units=[pos+index+1 for index,pos in enumerate(astral)]
        unit_position=position+bisect_left(astral,position)
        wire=json.dumps([self.pattern,self.flags,text,unit_position,mode],ensure_ascii=True,separators=(",",":"))
        batch=_helpers().start(wire)
        while True:
            rows=json.loads(batch())
            for spans in rows:
                groups=tuple((-1,-1) if span is None else
                    (span[0]-bisect_left(second_units,span[0]),span[1]-bisect_left(second_units,span[1])) for span in spans)
                yield ECMAMatch(text,groups)
            if len(rows)<128:
                return

    def finditer(self, text: str, pos: int = 0) -> Iterator[ECMAMatch]:
        return self._matches(text,pos,"search")

    def search(self, text: str, pos: int = 0) -> ECMAMatch | None:
        return next(self._matches(text,pos,"search"),None)

    def match(self, text: str, pos: int = 0) -> ECMAMatch | None:
        return next(self._matches(text,pos,"match"),None)

    def fullmatch(self, text: str, pos: int = 0) -> ECMAMatch | None:
        return next(self._matches(text,pos,"full"),None)
