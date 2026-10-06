"""Port of OpenClaw's ``redactSensitiveText(text, {mode: "tools"})`` at v2026.9.6.

Upstream: ``src/logging/redact.ts`` with ``redact-patterns.ts``, ``redact-pem.ts``,
``redact-bounded.ts``, ``redact-pattern-runtime.ts``,
``packages/acp-core/src/structured-auth-redaction.ts`` and the URL query-name check of
``packages/net-policy/src/redact-sensitive-url.ts``. ``buildSessionEntry`` runs every exported
session text through it (``session_entry.py`` calls :func:`redact_sensitive_text`).

:func:`redact_model_visible_secrets` (``redactModelVisibleSecrets``, the host redactor of the
Responses converter's tool-result text) sits on top of it: the tool-payload subset of the same
patterns plus field-name masks over records (see the section at the end of this module).

The pattern sources are the upstream JavaScript sources verbatim (``DEFAULT_REDACT_STRING_PATTERNS``
and the prefilter sources); :func:`translate_js_regex` rewrites them into Python ``re`` syntax
with ECMAScript semantics:

- ``\\s`` is the ECMAScript WhiteSpace set, ``.`` excludes CR/LF/LS/PS, ``$`` is end of input only
  (no ``m`` flag), ``\\w``/``\\d``/``\\b`` are ASCII, and ``i`` folds ASCII letters only
  (``re.ASCII``); the ``/iu`` prefilter adds U+017F and U+212A to the ``s``/``k`` letters.
- ``\\p{C}`` and ``\\p{Z}`` come from tables generated with Node 24 (Unicode 17), not from
  ``unicodedata`` (Python 3.11 ships Unicode 14, where newer assigned characters read as ``Cn``).
- The patterns that run without the ``u`` flag see UTF-16 code units: the text is split into
  surrogate halves for that stage (:func:`to_units`), so ``{0,40}`` gaps, ``maskToken`` lengths and
  chunk boundaries count units like JavaScript. The ``u``-flag stages (structured authorization
  parameters, URL query, form bodies) run over code points.
- The one variable-length lookbehind (``(?<!;base64,[A-Za-z0-9+/=]*)``, used by the base64-safe
  vendor prefixes) is a post-match check; the registry of exact secret values
  (``redactRegisteredSecretValues``) is not ported (a host has no such registry).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import lru_cache
from typing import Any, NamedTuple

from memory_core.bootstrap._js import JS_IU_WORD_CLASS, JS_SPACE_CLASS, js_trim

DEFAULT_REDACT_MIN_LENGTH = 18
DEFAULT_REDACT_KEEP_START = 6
DEFAULT_REDACT_KEEP_END = 4
REDACT_REGEX_CHUNK_THRESHOLD = 32_768
REDACT_REGEX_CHUNK_SIZE = 16_384

# --- Unicode tables ---------------------------------------------------------------------------
# ``\p{C}`` (Cc|Cf|Cs|Co|Cn) and ``\p{Z}`` as Node 24 / ICU (Unicode 17) answers them; the oracle
# test regenerates both from the pinned runtime and compares.
_UNICODE_C_RANGES = (
    "0-1f,7f-9f,ad,378-379,380-383,38b,38d,3a2,530,557-558,58b-58c,590,5c8-5cf,5eb-5ee,5f5-605,"
    "61c,6dd,70e-70f,74b-74c,7b2-7bf,7fb-7fc,82e-82f,83f,85c-85d,85f,86b-86f,890-896,8e2,984,"
    "98d-98e,991-992,9a9,9b1,9b3-9b5,9ba-9bb,9c5-9c6,9c9-9ca,9cf-9d6,9d8-9db,9de,9e4-9e5,"
    "9ff-a00,a04,a0b-a0e,a11-a12,a29,a31,a34,a37,a3a-a3b,a3d,a43-a46,a49-a4a,a4e-a50,a52-a58,"
    "a5d,a5f-a65,a77-a80,a84,a8e,a92,aa9,ab1,ab4,aba-abb,ac6,aca,ace-acf,ad1-adf,ae4-ae5,"
    "af2-af8,b00,b04,b0d-b0e,b11-b12,b29,b31,b34,b3a-b3b,b45-b46,b49-b4a,b4e-b54,b58-b5b,b5e,"
    "b64-b65,b78-b81,b84,b8b-b8d,b91,b96-b98,b9b,b9d,ba0-ba2,ba5-ba7,bab-bad,bba-bbd,bc3-bc5,"
    "bc9,bce-bcf,bd1-bd6,bd8-be5,bfb-bff,c0d,c11,c29,c3a-c3b,c45,c49,c4e-c54,c57,c5b,c5e-c5f,"
    "c64-c65,c70-c76,c8d,c91,ca9,cb4,cba-cbb,cc5,cc9,cce-cd4,cd7-cdb,cdf,ce4-ce5,cf0,cf4-cff,"
    "d0d,d11,d45,d49,d50-d53,d64-d65,d80,d84,d97-d99,db2,dbc,dbe-dbf,dc7-dc9,dcb-dce,dd5,dd7,"
    "de0-de5,df0-df1,df5-e00,e3b-e3e,e5c-e80,e83,e85,e8b,ea4,ea6,ebe-ebf,ec5,ec7,ecf,eda-edb,"
    "ee0-eff,f48,f6d-f70,f98,fbd,fcd,fdb-fff,10c6,10c8-10cc,10ce-10cf,1249,124e-124f,1257,1259,"
    "125e-125f,1289,128e-128f,12b1,12b6-12b7,12bf,12c1,12c6-12c7,12d7,1311,1316-1317,135b-135c,"
    "137d-137f,139a-139f,13f6-13f7,13fe-13ff,169d-169f,16f9-16ff,1716-171e,1737-173f,1754-175f,"
    "176d,1771,1774-177f,17de-17df,17ea-17ef,17fa-17ff,180e,181a-181f,1879-187f,18ab-18af,"
    "18f6-18ff,191f,192c-192f,193c-193f,1941-1943,196e-196f,1975-197f,19ac-19af,19ca-19cf,"
    "19db-19dd,1a1c-1a1d,1a5f,1a7d-1a7e,1a8a-1a8f,1a9a-1a9f,1aae-1aaf,1ade-1adf,1aec-1aff,1b4d,"
    "1bf4-1bfb,1c38-1c3a,1c4a-1c4c,1c8b-1c8f,1cbb-1cbc,1cc8-1ccf,1cfb-1cff,1f16-1f17,1f1e-1f1f,"
    "1f46-1f47,1f4e-1f4f,1f58,1f5a,1f5c,1f5e,1f7e-1f7f,1fb5,1fc5,1fd4-1fd5,1fdc,1ff0-1ff1,1ff5,"
    "1fff,200b-200f,202a-202e,2060-206f,2072-2073,208f,209d-209f,20c2-20cf,20f1-20ff,218c-218f,"
    "242a-243f,244b-245f,2b74-2b75,2cf4-2cf8,2d26,2d28-2d2c,2d2e-2d2f,2d68-2d6e,2d71-2d7e,"
    "2d97-2d9f,2da7,2daf,2db7,2dbf,2dc7,2dcf,2dd7,2ddf,2e5e-2e7f,2e9a,2ef4-2eff,2fd6-2fef,3040,"
    "3097-3098,3100-3104,3130,318f,31e6-31ee,321f,a48d-a48f,a4c7-a4cf,a62c-a63f,a6f8-a6ff,"
    "a7dd-a7f0,a82d-a82f,a83a-a83f,a878-a87f,a8c6-a8cd,a8da-a8df,a954-a95e,a97d-a97f,a9ce,"
    "a9da-a9dd,a9ff,aa37-aa3f,aa4e-aa4f,aa5a-aa5b,aac3-aada,aaf7-ab00,ab07-ab08,ab0f-ab10,"
    "ab17-ab1f,ab27,ab2f,ab6c-ab6f,abee-abef,abfa-abff,d7a4-d7af,d7c7-d7ca,d7fc-f8ff,fa6e-fa6f,"
    "fada-faff,fb07-fb12,fb18-fb1c,fb37,fb3d,fb3f,fb42,fb45,fdd0-fdef,fe1a-fe1f,fe53,fe67,"
    "fe6c-fe6f,fe75,fefd-ff00,ffbf-ffc1,ffc8-ffc9,ffd0-ffd1,ffd8-ffd9,ffdd-ffdf,ffe7,ffef-fffb,"
    "fffe-ffff,1000c,10027,1003b,1003e,1004e-1004f,1005e-1007f,100fb-100ff,10103-10106,"
    "10134-10136,1018f,1019d-1019f,101a1-101cf,101fe-1027f,1029d-1029f,102d1-102df,102fc-102ff,"
    "10324-1032c,1034b-1034f,1037b-1037f,1039e,103c4-103c7,103d6-103ff,1049e-1049f,104aa-104af,"
    "104d4-104d7,104fc-104ff,10528-1052f,10564-1056e,1057b,1058b,10593,10596,105a2,105b2,105ba,"
    "105bd-105bf,105f4-105ff,10737-1073f,10756-1075f,10768-1077f,10786,107b1,107bb-107ff,"
    "10806-10807,10809,10836,10839-1083b,1083d-1083e,10856,1089f-108a6,108b0-108df,108f3,"
    "108f6-108fa,1091c-1091e,1093a-1093e,1095a-1097f,109b8-109bb,109d0-109d1,10a04,10a07-10a0b,"
    "10a14,10a18,10a36-10a37,10a3b-10a3e,10a49-10a4f,10a59-10a5f,10aa0-10abf,10ae7-10aea,"
    "10af7-10aff,10b36-10b38,10b56-10b57,10b73-10b77,10b92-10b98,10b9d-10ba8,10bb0-10bff,"
    "10c49-10c7f,10cb3-10cbf,10cf3-10cf9,10d28-10d2f,10d3a-10d3f,10d66-10d68,10d86-10d8d,"
    "10d90-10e5f,10e7f,10eaa,10eae-10eaf,10eb2-10ec1,10ec8-10ecf,10ed9-10ef9,10f28-10f2f,"
    "10f5a-10f6f,10f8a-10faf,10fcc-10fdf,10ff7-10fff,1104e-11051,11076-1107e,110bd,110c3-110cf,"
    "110e9-110ef,110fa-110ff,11135,11148-1114f,11177-1117f,111e0,111f5-111ff,11212,11242-1127f,"
    "11287,11289,1128e,1129e,112aa-112af,112eb-112ef,112fa-112ff,11304,1130d-1130e,11311-11312,"
    "11329,11331,11334,1133a,11345-11346,11349-1134a,1134e-1134f,11351-11356,11358-1135c,"
    "11364-11365,1136d-1136f,11375-1137f,1138a,1138c-1138d,1138f,113b6,113c1,113c3-113c4,113c6,"
    "113cb,113d6,113d9-113e0,113e3-113ff,1145c,11462-1147f,114c8-114cf,114da-1157f,115b6-115b7,"
    "115de-115ff,11645-1164f,1165a-1165f,1166d-1167f,116ba-116bf,116ca-116cf,116e4-116ff,"
    "1171b-1171c,1172c-1172f,11747-117ff,1183c-1189f,118f3-118fe,11907-11908,1190a-1190b,11914,"
    "11917,11936,11939-1193a,11947-1194f,1195a-1199f,119a8-119a9,119d8-119d9,119e5-119ff,"
    "11a48-11a4f,11aa3-11aaf,11af9-11aff,11b0a-11b5f,11b68-11bbf,11be2-11bef,11bfa-11bff,11c09,"
    "11c37,11c46-11c4f,11c6d-11c6f,11c90-11c91,11ca8,11cb7-11cff,11d07,11d0a,11d37-11d39,11d3b,"
    "11d3e,11d48-11d4f,11d5a-11d5f,11d66,11d69,11d8f,11d92,11d99-11d9f,11daa-11daf,11ddc-11ddf,"
    "11dea-11edf,11ef9-11eff,11f11,11f3b-11f3d,11f5b-11faf,11fb1-11fbf,11ff2-11ffe,1239a-123ff,"
    "1246f,12475-1247f,12544-12f8f,12ff3-12fff,13430-1343f,13456-1345f,143fb-143ff,14647-160ff,"
    "1613a-167ff,16a39-16a3f,16a5f,16a6a-16a6d,16abf,16aca-16acf,16aee-16aef,16af6-16aff,"
    "16b46-16b4f,16b5a,16b62,16b78-16b7c,16b90-16d3f,16d7a-16e3f,16e9b-16e9f,16eb9-16eba,"
    "16ed4-16eff,16f4b-16f4e,16f88-16f8e,16fa0-16fdf,16fe5-16fef,16ff7-16fff,18cd6-18cfe,"
    "18d1f-18d7f,18df3-1afef,1aff4,1affc,1afff,1b123-1b131,1b133-1b14f,1b153-1b154,1b156-1b163,"
    "1b168-1b16f,1b2fc-1bbff,1bc6b-1bc6f,1bc7d-1bc7f,1bc89-1bc8f,1bc9a-1bc9b,1bca0-1cbff,"
    "1ccfd-1ccff,1ceb4-1ceb9,1ced1-1cedf,1cef1-1ceff,1cf2e-1cf2f,1cf47-1cf4f,1cfc4-1cfff,"
    "1d0f6-1d0ff,1d127-1d128,1d173-1d17a,1d1eb-1d1ff,1d246-1d2bf,1d2d4-1d2df,1d2f4-1d2ff,"
    "1d357-1d35f,1d379-1d3ff,1d455,1d49d,1d4a0-1d4a1,1d4a3-1d4a4,1d4a7-1d4a8,1d4ad,1d4ba,1d4bc,"
    "1d4c4,1d506,1d50b-1d50c,1d515,1d51d,1d53a,1d53f,1d545,1d547-1d549,1d551,1d6a6-1d6a7,"
    "1d7cc-1d7cd,1da8c-1da9a,1daa0,1dab0-1deff,1df1f-1df24,1df2b-1dfff,1e007,1e019-1e01a,1e022,"
    "1e025,1e02b-1e02f,1e06e-1e08e,1e090-1e0ff,1e12d-1e12f,1e13e-1e13f,1e14a-1e14d,1e150-1e28f,"
    "1e2af-1e2bf,1e2fa-1e2fe,1e300-1e4cf,1e4fa-1e5cf,1e5fb-1e5fe,1e600-1e6bf,1e6df,1e6f6-1e6fd,"
    "1e700-1e7df,1e7e7,1e7ec,1e7ef,1e7ff,1e8c5-1e8c6,1e8d7-1e8ff,1e94c-1e94f,1e95a-1e95d,"
    "1e960-1ec70,1ecb5-1ed00,1ed3e-1edff,1ee04,1ee20,1ee23,1ee25-1ee26,1ee28,1ee33,1ee38,1ee3a,"
    "1ee3c-1ee41,1ee43-1ee46,1ee48,1ee4a,1ee4c,1ee50,1ee53,1ee55-1ee56,1ee58,1ee5a,1ee5c,1ee5e,"
    "1ee60,1ee63,1ee65-1ee66,1ee6b,1ee73,1ee78,1ee7d,1ee7f,1ee8a,1ee9c-1eea0,1eea4,1eeaa,"
    "1eebc-1eeef,1eef2-1efff,1f02c-1f02f,1f094-1f09f,1f0af-1f0b0,1f0c0,1f0d0,1f0f6-1f0ff,"
    "1f1ae-1f1e5,1f203-1f20f,1f23c-1f23f,1f249-1f24f,1f252-1f25f,1f266-1f2ff,1f6d9-1f6db,"
    "1f6ed-1f6ef,1f6fd-1f6ff,1f7da-1f7df,1f7ec-1f7ef,1f7f1-1f7ff,1f80c-1f80f,1f848-1f84f,"
    "1f85a-1f85f,1f888-1f88f,1f8ae-1f8af,1f8bc-1f8bf,1f8c2-1f8cf,1f8d9-1f8ff,1fa58-1fa5f,"
    "1fa6e-1fa6f,1fa7d-1fa7f,1fa8b-1fa8d,1fac7,1fac9-1facc,1fadd-1fade,1faeb-1faee,1faf9-1faff,"
    "1fb93,1fbfb-1ffff,2a6e0-2a6ff,2b81e-2b81f,2ceae-2ceaf,2ebe1-2ebef,2ee5e-2f7ff,2fa1e-2ffff,"
    "3134b-3134f,3347a-e00ff,e01f0-10ffff"
)
_UNICODE_Z_RANGES = (
    "20,a0,1680,2000-200a,2028-2029,202f,205f,3000"
)


def _range_class_body(ranges: str) -> str:
    parts: list[str] = []
    for token in ranges.split(","):
        low, _, high = token.partition("-")
        parts.append(f"\\U{int(low, 16):08x}" + (f"-\\U{int(high, 16):08x}" if high else ""))
    return "".join(parts)


UNICODE_C_CLASS_BODY = _range_class_body(_UNICODE_C_RANGES)
UNICODE_Z_CLASS_BODY = _range_class_body(_UNICODE_Z_RANGES)
_INVISIBLE_TAIL = "\\u00A0\\u1680\\u2000-\\u200A\\u202F\\u205F\\u3000\\u115F\\u1160\\u3164\\uFFA0"
# Placeholders in the JS sources, replaced after translation (the bodies are already Python).
_PLACEHOLDERS = {
    "@INV@": UNICODE_C_CLASS_BODY + _INVISIBLE_TAIL,
    "@SEP@": UNICODE_C_CLASS_BODY + UNICODE_Z_CLASS_BODY + "\\u115F\\u1160\\u3164\\uFFA0",
}

# --- UTF-16 views -----------------------------------------------------------------------------
_ASTRAL_RE = re.compile("[\U00010000-\U0010ffff]")
_SURROGATE_PAIR_RE = re.compile("[\ud800-\udbff][\udc00-\udfff]")


def _split_astral(match: re.Match[str]) -> str:
    value = ord(match.group(0)) - 0x10000
    return chr(0xD800 + (value >> 10)) + chr(0xDC00 + (value & 0x3FF))


def _join_pair(match: re.Match[str]) -> str:
    high, low = match.group(0)
    return chr(0x10000 + ((ord(high) - 0xD800) << 10) + (ord(low) - 0xDC00))


def to_units(text: str) -> str:
    """The string as UTF-16 code units: astral characters become two surrogate characters."""
    return text if text.isascii() else _ASTRAL_RE.sub(_split_astral, text)


def from_units(text: str) -> str:
    """Join adjacent surrogate halves back into code points."""
    return text if text.isascii() else _SURROGATE_PAIR_RE.sub(_join_pair, text)


def _slice_units_safe(text: str, start: int, end: int | None = None) -> str:
    """``sliceUtf16Safe`` over a unit string (``len`` is the UTF-16 length)."""
    length = len(text)
    begin = max(length + start, 0) if start < 0 else min(start, length)
    stop = length if end is None else (max(length + end, 0) if end < 0 else min(end, length))
    if stop <= begin:
        return ""
    if 0 < begin < length and "\udc00" <= text[begin] <= "\udfff" and "\ud800" <= text[begin - 1] <= "\udbff":
        begin += 1
    if 0 < stop < length and "\ud800" <= text[stop - 1] <= "\udbff" and "\udc00" <= text[stop] <= "\udfff":
        stop -= 1
    return text[begin:stop] if stop > begin else ""


# --- JS regex source -> Python ----------------------------------------------------------------
_BASE64_LOOKBEHIND = "(?<!;base64,[A-Za-z0-9+/=]*)"


def translate_js_regex(
    source: str, *, word_iu: bool = False, expand_sk: bool = False
) -> tuple[str, bool]:
    """Rewrite ECMAScript regex source into Python ``re`` source (see the module docstring).

    ``word_iu`` makes ``\\w`` and ``\\b`` the ``/iu`` word set; ``expand_sk`` widens ``s`` and
    ``k`` (literal or inside letter classes) to include U+017F and U+212A (``/iu`` case folding).
    Returns the source and whether the base64 lookbehind was removed (it is checked by
    :func:`_base64_lookbehind_ok` after the match).
    """
    word = JS_IU_WORD_CLASS if word_iu else "A-Za-z0-9_"
    out: list[str] = []
    lookbehind = False
    i = 0
    length = len(source)
    while i < length:
        char = source[i]
        if source.startswith(_BASE64_LOOKBEHIND, i):
            lookbehind = True
            i += len(_BASE64_LOOKBEHIND)
        elif char == "\\":
            escaped = source[i + 1]
            if escaped == "s":
                out.append(f"[{JS_SPACE_CLASS}]")
            elif escaped == "S":
                out.append(f"[^{JS_SPACE_CLASS}]")
            elif escaped == "d":
                out.append("[0-9]")
            elif escaped == "D":
                out.append("[^0-9]")
            elif escaped == "w":
                out.append(f"[{word}]")
            elif escaped == "W":
                out.append(f"[^{word}]")
            elif escaped == "b" and word_iu:
                out.append(f"(?:(?<=[{word}])(?![{word}])|(?<![{word}])(?=[{word}]))")
            elif escaped == "B" and word_iu:
                out.append(f"(?:(?<=[{word}])(?=[{word}])|(?<![{word}])(?![{word}]))")
            else:
                out.append(char + escaped)
            i += 2
        elif char == "[":
            j = i + 1
            negated = source[j] == "^"
            if negated:
                j += 1
            body: list[str] = []
            while source[j] != "]":
                if source[j] == "\\":
                    escaped = source[j + 1]
                    if escaped == "s":
                        body.append(JS_SPACE_CLASS)
                    elif escaped == "d":
                        body.append("0-9")
                    elif escaped == "w":
                        body.append(word)
                    elif escaped in "SDW":
                        raise ValueError(f"negated escape in class: {source!r}")
                    else:
                        body.append(source[j : j + 2])
                    j += 2
                else:
                    body.append(source[j])
                    j += 1
            text = "".join(body)
            if expand_sk:
                letters = re.sub(r"\\.", "", text)
                extra = ""
                if re.search(r"a-z|A-Z|[sS]", letters):
                    extra += "\\u017f"
                if re.search(r"a-z|A-Z|[kK]", letters):
                    extra += "\\u212a"
                text = extra + text  # leading: a trailing member could form a range with "-"
            out.append("[" + ("^" if negated else "") + text + "]")
            i = j + 1
        elif char == ".":
            out.append("[^\\n\\r\\u2028\\u2029]")
            i += 1
        elif char == "$":
            out.append("\\Z")
            i += 1
        elif expand_sk and char in "sS":
            out.append("[sSſ]")
            i += 1
        elif expand_sk and char in "kK":
            out.append("[kKK]")
            i += 1
        else:
            out.append(char)
            i += 1
    translated = "".join(out)
    for placeholder, replacement in _PLACEHOLDERS.items():
        translated = translated.replace(placeholder, replacement)
    return translated, lookbehind


def _compile_js(
    source: str, flags: str, *, word_iu: bool = False, expand_sk: bool = False
) -> tuple[re.Pattern[str], bool]:
    translated, lookbehind = translate_js_regex(source, word_iu=word_iu, expand_sk=expand_sk)
    regex_flags = re.ASCII | (re.IGNORECASE if "i" in flags else 0)
    return re.compile(translated, regex_flags), lookbehind


_BASE64_LOOKBEHIND_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")


def _base64_lookbehind_ok(text: str, position: int) -> bool:
    """``(?<!;base64,[A-Za-z0-9+/=]*)`` evaluated at ``position``."""
    cursor = position
    while cursor > 0 and text[cursor - 1] in _BASE64_LOOKBEHIND_CHARS:
        cursor -= 1
    return not (cursor >= 8 and text[cursor - 8 : cursor] == ";base64,")


_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def js_decode_uri_component(value: str) -> str:
    """``decodeURIComponent``; ``ValueError`` where JavaScript throws ``URIError``."""
    if "%" not in value:
        return value

    def read_byte(at: int) -> int:
        digits = value[at + 1 : at + 3]
        if value[at : at + 1] != "%" or len(digits) != 2 or not all(c in _HEX_DIGITS for c in digits):
            raise ValueError("URI malformed")
        return int(digits, 16)

    out: list[str] = []
    i = 0
    length = len(value)
    while i < length:
        char = value[i]
        if char != "%":
            out.append(char)
            i += 1
            continue
        first = read_byte(i)
        i += 3
        if first < 0x80:
            out.append(chr(first))
            continue
        if first < 0xC0 or first >= 0xF8:
            raise ValueError("URI malformed")
        count = 2 if first < 0xE0 else 3 if first < 0xF0 else 4
        octets = [first]
        for _ in range(count - 1):
            octets.append(read_byte(i))
            i += 3
        try:
            out.append(bytes(octets).decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("URI malformed") from exc
    return "".join(out)


def _js_template(template: str) -> str:
    """Resolve ``${NAME}`` references against this module's constants, like ``String.raw``."""
    return re.sub(r"\$\{(\w+)\}", lambda m: globals()[m.group(1)], template)


_t = _js_template

# --- packages/acp-core structured-auth-redaction.ts constants ---------------------------------
HTTP_AUTH_SCHEME_PATTERN = r'''[A-Za-z0-9!#$%&'*+.^_`|~-]+'''
HTTP_AUTH_OPAQUE_CREDENTIAL_PATTERN = r'''(?:\[REDACTED\]|[^\s\\"',;&#?<>)}\]]+)'''
HTTP_AUTH_SERIALIZED_TAB_PATTERN = r'''\\{1,64}t'''
HTTP_AUTH_SERIALIZED_INDENT_PATTERN = _t(r'''(?:[ \t]+|${HTTP_AUTH_SERIALIZED_TAB_PATTERN})''')
HTTP_AUTH_OPTIONAL_VALUE_WHITESPACE_PATTERN = _t(r'''(?:[ \t]*\r?\n${HTTP_AUTH_SERIALIZED_INDENT_PATTERN}|[ \t]*\\{1,64}r\\{1,64}n${HTTP_AUTH_SERIALIZED_INDENT_PATTERN}|[ \t]*\\{1,64}n${HTTP_AUTH_SERIALIZED_INDENT_PATTERN}|[ \t]*${HTTP_AUTH_SERIALIZED_TAB_PATTERN}[ \t]*|[ \t]*)''')
HTTP_AUTH_REQUIRED_VALUE_WHITESPACE_PATTERN = _t(r'''(?:[ \t]*\r?\n${HTTP_AUTH_SERIALIZED_INDENT_PATTERN}|[ \t]*\\{1,64}r\\{1,64}n${HTTP_AUTH_SERIALIZED_INDENT_PATTERN}|[ \t]*\\{1,64}n${HTTP_AUTH_SERIALIZED_INDENT_PATTERN}|[ \t]*${HTTP_AUTH_SERIALIZED_TAB_PATTERN}[ \t]*|[ \t]+)''')
HTTP_AUTH_LEGACY_VALUE_WHITESPACE_PATTERN = _t(r'''(?:[ \t\r\n]*|[ \t]*\\{1,64}r\\{1,64}n(?:[ \t]*|${HTTP_AUTH_SERIALIZED_TAB_PATTERN})|[ \t]*\\{1,64}n(?:[ \t]*|${HTTP_AUTH_SERIALIZED_TAB_PATTERN})|[ \t]*${HTTP_AUTH_SERIALIZED_TAB_PATTERN}[ \t]*)''')
HTTP_AUTH_HEADER_BOUNDARY_PATTERN = r'''(^|[^A-Za-z0-9_-]|\\{1,64}[rn])'''
HTTP_AUTH_SERIALIZED_QUOTE_PATTERN = r'''(?:\\{1,64}["']|["']|)'''
FORM_BODY_KEY_INVISIBLE_CHARS = "@INV@"
PEM_REDACT_PATTERN_SOURCE = r'''-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----'''
_PEM_SOURCE = PEM_REDACT_PATTERN_SOURCE

# --- src/logging/redact-patterns.ts (verbatim JavaScript sources) -----------------------------
PAYMENT_CREDENTIAL_ENV_KEYS = _t(r'''CARD[_-]?NUMBER|CARD[_-]?CVC|CARD[_-]?CVV|CVC|CVV|SECURITY[_-]?CODE|PAYMENT[_-]?CREDENTIAL|SHARED[_-]?PAYMENT[_-]?TOKEN''')
PAYMENT_CREDENTIAL_QUERY_KEYS = _t(r'''card[-_]?number|card[-_]?cvc|card[-_]?cvv|cvc|cvv|security[-_]?code|payment[-_]?credential|shared[-_]?payment[-_]?token''')
PAYMENT_CREDENTIAL_JSON_KEYS = _t(r'''cardNumber|card_number|cardCvc|card_cvc|cardCvv|card_cvv|cvc|cvv|securityCode|security_code|paymentCredential|payment_credential|sharedPaymentToken|shared_payment_token''')
AWS_SECRET_ACCESS_KEY_FIELD_KEYS = _t(r'''aws[-_]?secret[-_]?access[-_]?key|awsSecretAccessKey|SecretAccessKey''')
AUTH_QUERY_KEYS = _t(r'''access[-_]?token|auth[-_]?token|hook[-_]?token|refresh[-_]?token|id[-_]?token|api[-_]?key|apikey|client[-_]?secret|app[-_]?secret|private[-_]?key|${AWS_SECRET_ACCESS_KEY_FIELD_KEYS}|credential|authorization|token|key|secret|password|pass|passwd|auth|jwt|session|code|signature|x[-_]?amz[-_]?(?:signature|security[-_]?token)''')
FORM_BODY_FIRST_PAIR_KEYS = _t(r'''${AUTH_QUERY_KEYS}|app[-_]?secret|credential|${PAYMENT_CREDENTIAL_QUERY_KEYS}''')
STANDALONE_ASSIGNMENT_SECRET_KEYS = _t(r'''access_token|refresh_token|id_token|auth[-_]?token|hook[-_]?token|api[-_]?key|client[-_]?secret|app[-_]?secret|private[-_]?key|authorization|jwt|token|secret|password|pass|passwd|credential|${PAYMENT_CREDENTIAL_QUERY_KEYS}''')
CONFIG_ASSIGNMENT_SECRET_KEYS = _t(r'''access[-_]?token|refresh[-_]?token|id[-_]?token|auth[-_]?token|hook[-_]?token|api[-_]?(?:key|secret)|client[-_]?secret|app[-_]?secret|private[-_]?key|secret[-_]?key|key[-_]?material|authorization|jwt|token|secret|password|passphrase|pass|passwd|credential|${PAYMENT_CREDENTIAL_QUERY_KEYS}''')
CONFIG_DIRECT_ASSIGNMENT_SECRET_KEYS = _t(r'''access-token|refresh-token|id-token|auth-token|hook-token|api[-_]?(?:key|secret)|secret[-_]?key|key[-_]?material|passphrase''')
CONFIG_PREFIXED_PASSWORD_ASSIGNMENT_SECRET_KEYS = _t(r'''password|passphrase|pass|passwd''')
CLI_SECRET_FLAG_KEYS = _t(r'''${AWS_SECRET_ACCESS_KEY_FIELD_KEYS}|api[-_]?key|hook[-_]?token|access[-_]?token|refresh[-_]?token|id[-_]?token|token|secret|password|passwd|credential|private[-_]?key|client[-_]?secret|${PAYMENT_CREDENTIAL_QUERY_KEYS}''')
ENV_ASSIGNMENT_REDACT_PATTERN = _t(r'''/\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|${PAYMENT_CREDENTIAL_ENV_KEYS})\b\s*[=:]\s*(["']?)([^\s"'\\]+)\1/g''')
ESCAPED_ENV_ASSIGNMENT_REDACT_PATTERN = _t(r'''/\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|${PAYMENT_CREDENTIAL_ENV_KEYS})\b\s*[=:]\s*\\+(["'])([^\s"'\\]+)\\+\1/g''')
# Quoted values may contain the other quote characters; only the matching closing quote ends
# the value. The unquoted variant accepts one leading quote so unterminated values still mask.
STANDALONE_ASSIGNMENT_QUOTED_REDACT_PATTERN = _t(r'''(^|[\s,;({\["])(?:${STANDALONE_ASSIGNMENT_SECRET_KEYS})=(["'\x60])((?:(?!\2)[^\r\n])+)\2''')
STANDALONE_ASSIGNMENT_REDACT_PATTERN = _t(r'''(^|[\s,;({\["])(?:${STANDALONE_ASSIGNMENT_SECRET_KEYS})=(["'\x60]?[^\s&#"'\x60<>]+)''')
CONFIG_QUOTED_ASSIGNMENT_SECRET_KEYS = _t(r'''access[-_]?token|refresh[-_]?token|id[-_]?token|auth[-_]?token|hook[-_]?token|api[-_]?(?:key|secret)|secret[-_]?key|key[-_]?material|authorization|jwt|token|secret|password|passphrase|pass|passwd|${PAYMENT_CREDENTIAL_QUERY_KEYS}''')
CONFIG_QUOTED_ASSIGNMENT_REDACT_PATTERN = _t(r'''/(^|[\s,{])(?:(?:${CONFIG_QUOTED_ASSIGNMENT_SECRET_KEYS})(?:\s*:\s*|\s+=\s*|=\s*)|[a-z0-9][a-z0-9._-]{0,79}[-_](?:${CONFIG_PREFIXED_PASSWORD_ASSIGNMENT_SECRET_KEYS})\s*[:=]\s*|[a-z0-9_.-]{1,80}\.(?:${CONFIG_ASSIGNMENT_SECRET_KEYS})\s*[:=]\s*)(["'\x60])((?:(?!\2)[^\r\n])+)\2/g''')
CONFIG_ASSIGNMENT_REDACT_PATTERN = _t(r'''/(^|[\s,{])(?:${CONFIG_ASSIGNMENT_SECRET_KEYS})(?:\s*:\s*|\s+=\s*|=\s+)([^\s#"'\x60<>]+)/g''')
CONFIG_DIRECT_ASSIGNMENT_REDACT_PATTERN = _t(r'''/(^|[\s,{])(?:${CONFIG_DIRECT_ASSIGNMENT_SECRET_KEYS})=([^\s#"'\x60<>]+)/g''')
CONFIG_PREFIXED_PASSWORD_ASSIGNMENT_REDACT_PATTERN = _t(r'''/(^|[\s,{])[a-z0-9][a-z0-9._-]{0,79}[-_](?:${CONFIG_PREFIXED_PASSWORD_ASSIGNMENT_SECRET_KEYS})\s*[:=]\s*([^\s#"'\x60<>]+)/g''')
CONFIG_NAMESPACED_ASSIGNMENT_REDACT_PATTERN = _t(r'''/(^|[\s,{])[a-z0-9_.-]{1,80}\.(?:${CONFIG_ASSIGNMENT_SECRET_KEYS})\s*[:=]\s*([^\s#"'\x60<>]+)/g''')
STRUCTURED_JSON_SECRET_REDACT_PATTERN = _t(r'''"(?:apiKey|api_key|apiToken|api_token|bearerToken|bearer_token|token|secret|password|passwd|${AWS_SECRET_ACCESS_KEY_FIELD_KEYS}|credential|authorization|proxy-authorization|cookie|set-cookie|x-api-key|x-auth-token|accessToken|access_token|refreshToken|refresh_token|idToken|id_token|authToken|auth_token|clientSecret|client_secret|privateKey|private_key|secret_value|raw_secret|secret_input|key_material)"\s*:\s*"([^"]+)"''')
STRUCTURED_JSON_PAYMENT_REDACT_PATTERN = _t(r'''"(?:${PAYMENT_CREDENTIAL_JSON_KEYS})"\s*:\s*"([^"]+)"''')
AMBIGUOUS_QUOTED_SECRET_FIELD_REDACT_PATTERN = _t(r'''(^|[\s,{])["']?(?:api[-_]key|access[-_]token|refresh[-_]token|id[-_]token|authToken|auth[-_]token|clientSecret|client[-_]secret|appSecret|app[-_]secret|private[-_]key|credential|authorization|secret[-_]value|raw[-_]secret|secret[-_]input|key[-_]material)["']?\s*[:=]\s*(["'])([^"'\r\n]+)\2''')
AMBIGUOUS_QUOTED_AUTH_FIELD_REDACT_PATTERN = _t(r'''(^|[\s,{])["']?(?:authorization|proxy-authorization|cookie|set-cookie|x-api-key|x-auth-token)["']?\s*[:=]\s*(["'])([^"'\r\n]+)\2''')
# Pure-base64 prefixes require a non-alphanumeric boundary and skip explicit data-URL payloads.
BASE64_SAFE_TOKEN_BOUNDARY = _t(r'''(^|[^A-Za-z0-9])(?<!;base64,[A-Za-z0-9+/=]*)''')
IDENTIFIER_SAFE_TOKEN_BOUNDARY = _t(r'''(^|[^A-Za-z0-9_])''')
TELEGRAM_BOT_TOKEN_REDACT_PATTERN = _t(r'''\bbot(\d{6,}:[A-Za-z0-9_-]{20,})\b''')
TELEGRAM_TOKEN_REDACT_PATTERN = _t(r'''\b(\d{6,}:[A-Za-z0-9_-]{20,})\b''')
CREDENTIAL_STYLE_HEADER_KEYS = "x-goog-api-key|api-key|apikey|x-api-token|x-access-token"
GATEWAY_SECURITY_HEADER_KEYS = "X-OpenClaw-Token|x-pomerium-jwt-assertion|X-Api-Key|X-Auth-Token"
# Colons identify HTTP headers. Equals assignments may be form bodies, so stop only before an
# actual following `&key=` pair; otherwise opaque credential punctuation stays fully masked.
LOG_HEADER_BOUNDARY_PATTERN = _t(r'''(^|[^A-Za-z0-9_?&-]|\\{1,64}[rn])''')
CREDENTIAL_STYLE_COLON_HEADER_REDACT_PATTERN = _t(r'''${LOG_HEADER_BOUNDARY_PATTERN}(?:${CREDENTIAL_STYLE_HEADER_KEYS})${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}[ \t]*:${HTTP_AUTH_OPTIONAL_VALUE_WHITESPACE_PATTERN}${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}([^\s\\"',;]+)''')
CREDENTIAL_STYLE_EQUALS_ASSIGNMENT_REDACT_PATTERN = _t(r'''${LOG_HEADER_BOUNDARY_PATTERN}(?:${CREDENTIAL_STYLE_HEADER_KEYS})${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}[ \t]*=${HTTP_AUTH_OPTIONAL_VALUE_WHITESPACE_PATTERN}${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}([^\s\\"',;]+)''')
GATEWAY_SECURITY_COLON_HEADER_REDACT_PATTERN = _t(r'''${LOG_HEADER_BOUNDARY_PATTERN}(?:${GATEWAY_SECURITY_HEADER_KEYS})\s*:\s*([^\s"',;]+)''')
GATEWAY_SECURITY_EQUALS_ASSIGNMENT_REDACT_PATTERN = _t(r'''${LOG_HEADER_BOUNDARY_PATTERN}(?:${GATEWAY_SECURITY_HEADER_KEYS})\s*=\s*([^\s"',;]+)''')
FORM_AWARE_EQUALS_ASSIGNMENT_PATTERN_SOURCES = frozenset([
  CREDENTIAL_STYLE_EQUALS_ASSIGNMENT_REDACT_PATTERN,
  GATEWAY_SECURITY_EQUALS_ASSIGNMENT_REDACT_PATTERN,
])
HTTP_AUTH_HEADER_REDACT_PATTERNS = [
  _t(r'''${HTTP_AUTH_HEADER_BOUNDARY_PATTERN}Proxy-Authorization${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}[ \t]*[:=]${HTTP_AUTH_OPTIONAL_VALUE_WHITESPACE_PATTERN}${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}${HTTP_AUTH_SCHEME_PATTERN}${HTTP_AUTH_REQUIRED_VALUE_WHITESPACE_PATTERN}(${HTTP_AUTH_OPAQUE_CREDENTIAL_PATTERN})'''),
  _t(r'''${HTTP_AUTH_HEADER_BOUNDARY_PATTERN}Proxy-Authorization${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}[ \t]*[:=]${HTTP_AUTH_OPTIONAL_VALUE_WHITESPACE_PATTERN}${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}(${HTTP_AUTH_OPAQUE_CREDENTIAL_PATTERN})[ \t]*(?=${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}(?:$|[,;)}\]]|\r?\n(?![ \t])))'''),
  _t(r'''${HTTP_AUTH_HEADER_BOUNDARY_PATTERN}Authorization${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}[ \t]*[:=]${HTTP_AUTH_OPTIONAL_VALUE_WHITESPACE_PATTERN}${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}(?!(?:Bearer|Basic|Bot)(?=${HTTP_AUTH_REQUIRED_VALUE_WHITESPACE_PATTERN}))${HTTP_AUTH_SCHEME_PATTERN}${HTTP_AUTH_REQUIRED_VALUE_WHITESPACE_PATTERN}(${HTTP_AUTH_OPAQUE_CREDENTIAL_PATTERN})'''),
  _t(r'''${HTTP_AUTH_HEADER_BOUNDARY_PATTERN}Authorization${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}[ \t]*[:=]${HTTP_AUTH_OPTIONAL_VALUE_WHITESPACE_PATTERN}${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}(?!(?:Bearer|Basic|Bot)(?=${HTTP_AUTH_REQUIRED_VALUE_WHITESPACE_PATTERN}))(${HTTP_AUTH_OPAQUE_CREDENTIAL_PATTERN})[ \t]*(?=${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}(?:$|[,;)}\]]|\r?\n(?![ \t])))'''),
  CREDENTIAL_STYLE_COLON_HEADER_REDACT_PATTERN,
  CREDENTIAL_STYLE_EQUALS_ASSIGNMENT_REDACT_PATTERN,
]
AUTHORIZATION_BEARER_REDACT_PATTERN = _t(r'''Authorization${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}[ \t]*[:=]${HTTP_AUTH_LEGACY_VALUE_WHITESPACE_PATTERN}${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}Bearer${HTTP_AUTH_REQUIRED_VALUE_WHITESPACE_PATTERN}(${HTTP_AUTH_OPAQUE_CREDENTIAL_PATTERN})''')
AUTHORIZATION_BASIC_REDACT_PATTERN = _t(r'''Authorization${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}[ \t]*[:=]${HTTP_AUTH_LEGACY_VALUE_WHITESPACE_PATTERN}${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}Basic${HTTP_AUTH_REQUIRED_VALUE_WHITESPACE_PATTERN}(${HTTP_AUTH_OPAQUE_CREDENTIAL_PATTERN})''')
AUTHORIZATION_BOT_REDACT_PATTERN = _t(r'''Authorization${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}[ \t]*[:=]${HTTP_AUTH_LEGACY_VALUE_WHITESPACE_PATTERN}${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}Bot${HTTP_AUTH_REQUIRED_VALUE_WHITESPACE_PATTERN}(${HTTP_AUTH_OPAQUE_CREDENTIAL_PATTERN})''')
STANDALONE_BEARER_REDACT_PATTERN = _t(r'''\bBearer\s+([-A-Za-z0-9._~+/=]{18,})(?![-A-Za-z0-9._~+/=])''')
SHELL_REFERENCE_PRESERVING_PATTERN_SOURCES = frozenset([
  ENV_ASSIGNMENT_REDACT_PATTERN,
  ESCAPED_ENV_ASSIGNMENT_REDACT_PATTERN,
  STANDALONE_ASSIGNMENT_QUOTED_REDACT_PATTERN,
  STANDALONE_ASSIGNMENT_REDACT_PATTERN,
])
CHUNK_UNSAFE_PATTERN_SOURCES = frozenset([
  TELEGRAM_BOT_TOKEN_REDACT_PATTERN,
  TELEGRAM_TOKEN_REDACT_PATTERN,
  AUTHORIZATION_BEARER_REDACT_PATTERN,
  AUTHORIZATION_BASIC_REDACT_PATTERN,
  AUTHORIZATION_BOT_REDACT_PATTERN,
  STANDALONE_BEARER_REDACT_PATTERN,
  *HTTP_AUTH_HEADER_REDACT_PATTERNS,
])
DEFAULT_REDACT_FIELD_PATTERNS = [
  ENV_ASSIGNMENT_REDACT_PATTERN,
  ESCAPED_ENV_ASSIGNMENT_REDACT_PATTERN,
  STRUCTURED_JSON_SECRET_REDACT_PATTERN,
  STRUCTURED_JSON_PAYMENT_REDACT_PATTERN,
  AMBIGUOUS_QUOTED_SECRET_FIELD_REDACT_PATTERN,
  AMBIGUOUS_QUOTED_AUTH_FIELD_REDACT_PATTERN,
  _t(r'''--(?:${CLI_SECRET_FLAG_KEYS})=([^\s"']+)'''),
  _t(r'''--(?:${CLI_SECRET_FLAG_KEYS})\s+(?!(?:or|and)\b(?=\s+--))(["']?)([^\s"']+)\1'''),
  AUTHORIZATION_BEARER_REDACT_PATTERN,
  AUTHORIZATION_BASIC_REDACT_PATTERN,
  AUTHORIZATION_BOT_REDACT_PATTERN,
  *HTTP_AUTH_HEADER_REDACT_PATTERNS,
  GATEWAY_SECURITY_COLON_HEADER_REDACT_PATTERN,
  GATEWAY_SECURITY_EQUALS_ASSIGNMENT_REDACT_PATTERN,
  STANDALONE_BEARER_REDACT_PATTERN,
  _t(r'''\b(?:https?|wss?|ftp):\/\/[^\/\s:@]*:([^\/\s@]+)@'''),
  _t(r'''\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|rediss?|amqps?):\/\/[^:\s/@]*:([^@\s]+)@'''),
  _t(r'''(^|[\s,;])(?:${FORM_BODY_FIRST_PAIR_KEYS})=([^&\s]+)(?=&[A-Za-z_][A-Za-z0-9_.-]*=)'''),
  STANDALONE_ASSIGNMENT_QUOTED_REDACT_PATTERN,
  STANDALONE_ASSIGNMENT_REDACT_PATTERN,
  CONFIG_QUOTED_ASSIGNMENT_REDACT_PATTERN,
  CONFIG_ASSIGNMENT_REDACT_PATTERN,
  CONFIG_DIRECT_ASSIGNMENT_REDACT_PATTERN,
  CONFIG_PREFIXED_PASSWORD_ASSIGNMENT_REDACT_PATTERN,
  CONFIG_NAMESPACED_ASSIGNMENT_REDACT_PATTERN,
  _PEM_SOURCE,
  _t(r'''(^|[\s,{])["']?(?:${AWS_SECRET_ACCESS_KEY_FIELD_KEYS})["']?\s*[:=]\s*(["']?)([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])\2'''),
]
VENDOR_TOKEN_REDACT_PATTERNS = [
  _t(r'''\b(sk-[A-Za-z0-9_-]{8,})\b'''),
  _t(r'''(ghp_[A-Za-z0-9]{10,})'''),
  _t(r'''(github_pat_[A-Za-z0-9_]{10,})'''),
  _t(r'''(gho_[A-Za-z0-9]{10,})'''),
  _t(r'''(ghu_[A-Za-z0-9]{10,})'''),
  _t(r'''(ghs_[A-Za-z0-9]{10,})'''),
  _t(r'''(ghr_[A-Za-z0-9]{10,})'''),
  _t(r'''(glpat-[A-Za-z0-9._=\-]{20,})'''),
  _t(r'''(gloas-(?:[A-Fa-f0-9]{65,}|[A-Za-z0-9_-]{64}|[A-Fa-f0-9]{32,}))'''),
  _t(r'''(gldt-[A-Za-z0-9_-]{20,})'''),
  _t(r'''(glcbt-[A-Za-z0-9]{1,5}_[A-Za-z0-9_-]{20,})'''),
  _t(r'''(glptt-[A-Za-z0-9_-]{40,})'''),
  _t(r'''(glft-(?:[A-Za-z0-9_-]{20,}|[a-h0-9]+-[0-9]+_))'''),
  _t(r'''(glimt-[A-Za-z0-9_-]{25,})'''),
  _t(r'''(glagent-[A-Za-z0-9_-]{50,})'''),
  _t(r'''(glwt-[A-Za-z0-9_-]{20,})'''),
  _t(r'''(glsoat-[A-Za-z0-9_-]{20,})'''),
  _t(r'''(glffct-[A-Za-z0-9_-]{20,})'''),
  _t(r'''(glrt-[A-Za-z0-9._-]{20,})'''),
  _t(r'''(glrtr?-[A-Za-z0-9_-]{27,300}\.[0-9a-z]{2}\.[0-9a-z]{9})'''),
  _t(r'''(GR1348941[A-Za-z0-9_-]{20,})'''),
  _t(r'''(_gitlab_session=[A-Za-z0-9%._-]{20,})'''),
  _t(r'''(xox[baprs]-[A-Za-z0-9-]{10,})'''),
  _t(r'''(xapp-[A-Za-z0-9-]{10,})'''),
  _t(r'''(https:\/\/hooks\.slack\.com\/(?:services\/T[A-Z0-9]+\/B[A-Z0-9]+|workflows\/T[A-Z0-9]+\/A[A-Z0-9]+\/[0-9]{17,19})\/[A-Za-z0-9]{20,})'''),
  _t(r'''(https:\/\/discord(?:app)?\.com\/api\/webhooks\/[0-9]{17,20}\/[A-Za-z0-9_-]{60,})'''),
  _t(r'''discord(?:.|\n|\r){0,40}?\b([A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27})\b'''),
  _t(r'''(gsk_[A-Za-z0-9_-]{10,})'''),
  _t(r'''(AIza[0-9A-Za-z\-_]{20,})'''),
  _t(r'''(ya29\.[0-9A-Za-z_\-./+=]{10,})'''),
  _t(r'''(1//0[0-9A-Za-z_\-./+=]{10,})'''),
  _t(r'''(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'''),
  _t(r'''(pplx-[A-Za-z0-9_-]{10,})'''),
  _t(r'''(fal_[A-Za-z0-9_-]{10,})'''),
  _t(r'''${IDENTIFIER_SAFE_TOKEN_BOUNDARY}(fc-[A-Za-z0-9]{10,})'''),
  _t(r'''(bb_live_[A-Za-z0-9_-]{10,})'''),
  _t(r'''${BASE64_SAFE_TOKEN_BOUNDARY}(gAAAA[A-Za-z0-9_=-]{20,})'''),
  _t(r'''(sk_live_[A-Za-z0-9]{10,})'''),
  _t(r'''(sk_test_[A-Za-z0-9]{10,})'''),
  _t(r'''(rk_live_[A-Za-z0-9]{10,})'''),
  _t(r'''(SG\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'''),
  _t(r'''(npm_[A-Za-z0-9]{10,})'''),
  _t(r'''(pypi-[A-Za-z0-9_-]{10,})'''),
  _t(r'''(dop_v1_[A-Za-z0-9]{10,})'''),
  _t(r'''(doo_v1_[A-Za-z0-9]{10,})'''),
  _t(r'''(dor_v1_[A-Za-z0-9]{10,})'''),
  _t(r'''(dp\.(?:ct|pt|sa|scim|audit)\.[A-Za-z0-9]{40,44})'''),
  _t(r'''(dp\.st\.[A-Za-z0-9]{40,44})'''),
  _t(r'''(dp\.st\.[a-z0-9_-]{2,35}\.[A-Za-z0-9]{40,44})'''),
  _t(r'''(dckr_(?:pat|oat)_[A-Za-z0-9_-]{27,32})'''),
  _t(r'''(bkua_[a-z0-9]{40})'''),
  _t(r'''(CCIPAT_[A-Za-z0-9]{22}_[A-Fa-f0-9]{40})'''),
  _t(r'''(sbp_[a-z0-9]{40})'''),
  _t(r'''${BASE64_SAFE_TOKEN_BOUNDARY}(dapi[0-9a-f]{32}(?:-\d)?)'''),
  _t(r'''(dd[pw]_[A-Za-z0-9]{36})'''),
  _t(r'''(glsa_[A-Za-z0-9_]{41})'''),
  _t(r'''(glc_eyJ[A-Za-z0-9+/=]{60,160})'''),
  _t(r'''(nfp_[A-Za-z0-9_]{36})'''),
  _t(r'''(CFPAT-[A-Za-z0-9_\-]{40,})'''),
  _t(r'''${BASE64_SAFE_TOKEN_BOUNDARY}(ATCTT3xFfG[A-Za-z0-9+/=_-]+=[A-Za-z0-9]{8})'''),
  _t(r'''${BASE64_SAFE_TOKEN_BOUNDARY}(ATATT[A-Za-z0-9+/=_-]+=[A-Za-z0-9]{8})'''),
  _t(r'''${BASE64_SAFE_TOKEN_BOUNDARY}(ATBB[A-Za-z0-9_=.-]{16,})'''),
  _t(r'''(BBDC-[A-Za-z0-9+/@_-]{40,50})'''),
  _t(r'''(HRKU-AA[A-Za-z0-9_-]{20,})'''),
  _t(r'''(pat-(?:eu|na)1-[A-Za-z0-9]{8}\-[A-Za-z0-9]{4}\-[A-Za-z0-9]{4}\-[A-Za-z0-9]{4}\-[A-Za-z0-9]{12})'''),
  _t(r'''(apify_api_[A-Za-z0-9\-]{20,})'''),
  _t(r'''(FlyV1 fm\d+_[A-Za-z0-9+/=,_-]{100,})'''),
  _t(r'''(fio-u-[A-Za-z0-9_-]{40,})'''),
  _t(r'''(^|[^A-Za-z0-9_])(am_[A-Za-z0-9_-]{10,})'''),
  _t(r'''(^|[^A-Za-z0-9_])(sk_[A-Za-z0-9_]{10,})'''),
  _t(r'''(tvly-[A-Za-z0-9]{10,})'''),
  _t(r'''(exa_[A-Za-z0-9]{10,})'''),
  _t(r'''(syt_[A-Za-z0-9]{10,})'''),
  _t(r'''(retaindb_[A-Za-z0-9]{10,})'''),
  _t(r'''(hsk-[A-Za-z0-9]{10,})'''),
  _t(r'''(mem0_[A-Za-z0-9]{10,})'''),
  _t(r'''(brv_[A-Za-z0-9]{10,})'''),
  _t(r'''(xai-[A-Za-z0-9]{30,})'''),
  _t(r'''${IDENTIFIER_SAFE_TOKEN_BOUNDARY}(fw-[A-Za-z0-9]{30,})'''),
  _t(r'''${IDENTIFIER_SAFE_TOKEN_BOUNDARY}(fw_[A-Za-z0-9]{30,})'''),
  _t(r'''${IDENTIFIER_SAFE_TOKEN_BOUNDARY}(fpk_[A-Za-z0-9]{30,})'''),
  _t(r'''${BASE64_SAFE_TOKEN_BOUNDARY}(AKIA[A-Z0-9]{16})'''),
  _t(r'''${BASE64_SAFE_TOKEN_BOUNDARY}(ASIA[A-Z0-9]{16})'''),
  _t(r'''(AKID[A-Za-z0-9]{10,})'''),
  _t(r'''(LTAI[A-Za-z0-9]{10,})'''),
  _t(r'''(hf_[A-Za-z0-9]{10,})'''),
  _t(r'''(api_org_[A-Za-z0-9]{20,})'''),
  _t(r'''(r8_[A-Za-z0-9]{10,})'''),
  TELEGRAM_BOT_TOKEN_REDACT_PATTERN,
  TELEGRAM_TOKEN_REDACT_PATTERN,
]


BODY_SECRET_KEYS = frozenset(
    {
        "access_token",
        "auth_token",
        "awssecretaccesskey",
        "aws_secret_access_key",
        "hook_token",
        "refresh_token",
        "id_token",
        "token",
        "api_key",
        "apikey",
        "client_secret",
        "app_secret",
        "password",
        "pass",
        "passwd",
        "auth",
        "jwt",
        "session",
        "code",
        "signature",
        "x_amz_signature",
        "x_amz_security_token",
        "secret",
        "secretaccesskey",
        "credential",
        "private_key",
        "authorization",
        "key",
        "card_number",
        "card_cvc",
        "card_cvv",
        "cvc",
        "cvv",
        "security_code",
        "payment_credential",
        "shared_payment_token",
    }
)

# packages/net-policy/src/redact-sensitive-url.ts SENSITIVE_URL_QUERY_PARAM_NAMES.
SENSITIVE_URL_QUERY_PARAM_NAMES = frozenset(
    {
        "token",
        "key",
        "api_key",
        "apikey",
        "secret",
        "access_token",
        "auth_token",
        "password",
        "pass",
        "passwd",
        "auth",
        "jwt",
        "session",
        "id_token",
        "code",
        "client_secret",
        "app_secret",
        "hook_token",
        "refresh_token",
        "signature",
        "x_amz_signature",
        "x_amz_security_token",
        "private_key",
        "credential",
        "authorization",
        "sig",
        "x_api_key",
        "x_access_token",
        "x_auth_token",
    }
)

DEFAULT_REDACT_STRING_PATTERNS: tuple[str, ...] = (
    *DEFAULT_REDACT_FIELD_PATTERNS,
    *VENDOR_TOKEN_REDACT_PATTERNS,
)

# --- Fast-path gate (DEFAULT_REDACT_PREFILTER_SOURCES, verbatim; /iu) --------------------------
DEFAULT_REDACT_PREFILTER_SOURCES: tuple[str, ...] = (
    # Sensitive key names shared by the env/JSON/query/form/header/assignment families.
    _t(r'''KEY|TOKEN|SECRET|PASSWORD|PASSWD|AUTH|COOKIE|SIGNATURE|CREDENTIAL|CARD|CVC|CVV|PAYMENT|PRIVATE KEY'''),
    _t(r'''security[-_]?code|\bpass\s*[=:]|\bpassphrase\s*[=:]|_(?:password|pass|passphrase|passwd)\s*[=:]|jwt\s*[=:]|session=|code=|\bsig\s*='''),
    _t(r'''\bBearer\s+'''),
    _t(r''':\/\/[^\/\s:@]*:[^\s@]+@'''),
    _t(r'''sk-|gh[opsur]_|github_pat_|glpat-|gloas-|gldt-|glcbt-|glptt-|glft-|glimt-|glagent-|glwt-|glsoat-|glffct-|glrt-|glrtr-|GR1348941|_gitlab_session=|xox[baprs]-|xapp-|hooks\.slack\.com|discord|gsk_|AIza|ya29\.|1\/\/0|eyJ|pplx-|fal_|fc-|bb_live_|gAAAA|[sr]k_(?:live|test)_|SG\.|npm_|pypi-|do[opr]_v1_|dp\.(?:ct|pt|sa|st|scim|audit)\.|dckr_|bkua_|CCIPAT_|sbp_|dapi[0-9a-f]|dd[pw]_|glsa_|nfp_|CFPAT-|ATCTT3|ATATT|ATBB|BBDC-|HRKU-|pat-(?:eu|na)1-|apify_api_|FlyV1|fio-u-|tvly-|exa_|syt_|retaindb_|mem0_|brv_|xai-|fw-|fw_|fpk_'''),
    _t(r'''(?:^|[^A-Za-z0-9_])(?:am_|sk_)'''),
    _t(r'''A[KS]IA[A-Z0-9]|AKID|LTAI|hf_|api_org_|r8_'''),
    _t(r'''\bbot\d{6,}:|\b\d{6,}:[A-Za-z0-9_-]{20,}'''),
    # Obfuscated form/URL keys: percent escapes can rewrite any key letter, while plus or
    # invisible splices break the literal key-name triggers above mid-word.
    _t(r'''%[0-9A-Fa-f]{2}[${FORM_BODY_KEY_INVISIBLE_CHARS}+A-Za-z0-9_%.-]*='''),
    # Search at the required assignment separator (two lookbehind alternatives upstream).
    _t(r'''=(?<=(?:\+|[${FORM_BODY_KEY_INVISIBLE_CHARS}])(?:[${FORM_BODY_KEY_INVISIBLE_CHARS}+]*[A-Za-z0-9_%.-])+[${FORM_BODY_KEY_INVISIBLE_CHARS}+]*=)|=(?<=[A-Za-z0-9_%.-][${FORM_BODY_KEY_INVISIBLE_CHARS}+]+=)'''),
)
# Python has no variable-length lookbehind: "an `=` preceded by X" is "X followed by `=`" for a
# presence test, so the last source is replaced by its forward equivalent.
_PREFILTER_FORWARD_LAST = _t(
    r'''(?:\+|[${FORM_BODY_KEY_INVISIBLE_CHARS}])(?:[${FORM_BODY_KEY_INVISIBLE_CHARS}+]*[A-Za-z0-9_%.-])+[${FORM_BODY_KEY_INVISIBLE_CHARS}+]*=|[A-Za-z0-9_%.-][${FORM_BODY_KEY_INVISIBLE_CHARS}+]+='''
)


@lru_cache(maxsize=1)
def _prefilter_re() -> re.Pattern[str]:
    sources = (*DEFAULT_REDACT_PREFILTER_SOURCES[:-1], _PREFILTER_FORWARD_LAST)
    regex, _ = _compile_js("(?:" + "|".join(sources) + ")", "i", word_iu=True, expand_sk=True)
    return regex


# --- AWS secret access key matcher (redact-patterns.ts matchAwsSecretAccessKeys) --------------
_AWS_VALUE_RE = re.compile(
    "(?=[A-Za-z0-9/+=]{0,39}[A-Z])(?=[A-Za-z0-9/+=]{0,39}[a-z])"
    "(?=[A-Za-z0-9/+=]{0,39}[0-9/+=])(?=[A-Za-z0-9/+=]{0,39}[G-Zg-z/+=])[A-Za-z0-9/+=]{40}"
)
_AWS_RUN_RE = re.compile("[A-Za-z0-9/+=]{40}")
_AWS_WHITESPACE_RE = re.compile(f"[{JS_SPACE_CLASS}]")
_AWS_SCHEME_CHAR_RE = re.compile("[A-Za-z0-9+.-]")
_AWS_SCHEME_START_RE = re.compile("[A-Za-z]")
_AWS_VALUE_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/+=")
_AWS_CLOSING_DELIMITERS = {'"': '"', "'": "'", "`": "`", "<": ">", "(": ")", "[": "]", "{": "}"}


def _could_match_aws_secret_access_key(text: str) -> bool:
    return len(text) >= 40 and bool(_AWS_RUN_RE.search(text)) and bool(_AWS_VALUE_RE.search(text))


class _UrlContext:
    __slots__ = (
        "start",
        "end",
        "authority_end",
        "port_start",
        "port_valid",
        "has_at",
        "query_or_fragment",
        "closing",
        "closing_escape_depth",
    )

    def __init__(self, start: int, end: int, closing: str | None, closing_escape_depth: int) -> None:
        self.start = start
        self.end = end
        self.authority_end = -1
        self.port_start = -1
        self.port_valid = True
        self.has_at = False
        self.query_or_fragment = False
        self.closing = closing
        self.closing_escape_depth = closing_escape_depth


def _char_at(text: str, index: int) -> str:
    return text[index] if 0 <= index < len(text) else ""


def _match_aws_secret_access_keys(text: str) -> Iterator[tuple[str, list[str], int]]:
    if not _could_match_aws_secret_access_key(text):
        return
    run_start = -1
    scheme_start = -1
    url: _UrlContext | None = None
    backslashes = 0
    runs: list[tuple[int, int, int, _UrlContext | None]] = []  # start, end, origin, url
    for index in range(len(text) + 1):
        char = _char_at(text, index)
        whitespace = index == len(text) or bool(_AWS_WHITESPACE_RE.fullmatch(char))
        escape_depth = backslashes
        backslashes = backslashes + 1 if char == "\\" else 0
        if char and char in _AWS_VALUE_CHARS:
            if run_start == -1:
                run_start = index
        elif run_start != -1:
            if index - run_start == 40:
                runs.append((run_start, index, run_start, url))
            elif index - run_start > 40 and char == "@" and _char_at(text, index - 41) == "/":
                runs.append((index - 40, index, run_start, url))
            run_start = -1
        if whitespace:
            if url:
                url.end = min(url.end, index)
            for run_begin, run_end, origin, context in runs:
                public_url = bool(
                    context
                    and not context.has_at
                    and context.port_valid
                    and (
                        context.port_start == -1
                        or (context.end if context.authority_end == -1 else context.authority_end)
                        > context.port_start + 1
                    )
                )
                before = _char_at(text, run_begin - 1)
                after = _char_at(text, run_end)
                slash_credential = run_begin != origin
                # Preserve the existing malformed credential spanning a numeric port and path.
                port_credential = bool(
                    context
                    and context.port_start != -1
                    and origin == context.port_start + 1
                    and context.authority_end > origin
                    and run_end > context.authority_end
                    and after == "@"
                )
                if (
                    (not slash_credential and (before == "_" or (before != "" and before in _AWS_VALUE_CHARS)))
                    or after == "_"
                    or text[origin - 8 : origin] == ";base64,"
                    or (
                        public_url
                        and not port_credential
                        and context is not None
                        and run_begin >= context.start
                        and run_end <= context.end
                    )
                ):
                    continue
                matched = text[run_begin:run_end]
                if _AWS_VALUE_RE.search(matched):
                    yield matched, [matched], run_begin
            runs.clear()
            scheme_start = -1
            url = None
            continue
        if url is not None and index >= url.start:
            # A quoted/marked value ends independently of punctuation inside raw userinfo.
            if char == url.closing and escape_depth == url.closing_escape_depth:
                url.end = min(url.end, index)
                url = None
            else:
                if char in "?#\"'<>`|()[]{}":
                    url.end = min(url.end, index)
                url.query_or_fragment = url.query_or_fragment or char in "?#"
                if url.authority_end == -1:
                    url.has_at = url.has_at or char == "@"
                    if char in "/?#":
                        url.authority_end = index
                    elif index < url.end:
                        if char == ":":
                            url.port_valid = url.port_valid and url.port_start == -1
                            url.port_start = index
                        elif url.port_start != -1 and (char < "0" or char > "9"):
                            url.port_valid = False
        if _AWS_SCHEME_CHAR_RE.fullmatch(char):
            if scheme_start == -1:
                scheme_start = index
        else:
            if (
                (url is None or (index >= url.end and not url.query_or_fragment))
                and char == ":"
                and text.startswith("//", index + 1)
                and scheme_start != -1
                and _AWS_SCHEME_START_RE.fullmatch(text[scheme_start])
            ):
                opening = _char_at(text, scheme_start - 1)
                closing_escape_depth = 0
                offset = scheme_start - 2
                while offset >= 0 and text[offset] == "\\":
                    closing_escape_depth += 1
                    offset -= 1
                url = _UrlContext(
                    index + 3,
                    len(text),
                    _AWS_CLOSING_DELIMITERS.get(opening) if opening else None,
                    closing_escape_depth,
                )
            scheme_start = -1


# --- PEM matcher (redact-pem.ts, complete-match mode) -----------------------------------------
class _PemScanner:
    __slots__ = ("offset", "phase", "dashes", "keyword", "keyword_offset", "start", "suffix")

    def __init__(self) -> None:
        self.offset = 0
        self.phase = "search"
        self.dashes = 0
        self.keyword = "BEGIN "
        self.keyword_offset = 0
        self.start = 0
        self.suffix = ""


def _pem_reset(scanner: _PemScanner, char: str) -> None:
    scanner.phase = "search"
    scanner.dashes = 1 if char == "-" else 0
    scanner.suffix = ""


def _pem_delimiters(text: str, scanner: _PemScanner) -> Iterator[tuple[str, int, int]]:
    index = 0
    length = len(text)
    while index < length:
        if scanner.phase == "search" and scanner.dashes == 0:
            next_dash = text.find("-", index)
            if next_dash == -1:
                scanner.offset += length - index
                return
            scanner.offset += next_dash - index
            index = next_dash
        raw = text[index]
        char = chr(ord(raw) - 32) if "a" <= raw <= "z" else raw
        offset = scanner.offset
        scanner.offset += 1
        if scanner.phase == "search":
            if char == "-":
                scanner.dashes = min(5, scanner.dashes + 1)
            elif scanner.dashes == 5 and char in "BE":
                scanner.phase = "keyword"
                scanner.keyword = "BEGIN " if char == "B" else "END "
                scanner.keyword_offset = 1
                scanner.start = offset - 5
            else:
                scanner.dashes = 0
        elif scanner.phase == "keyword":
            if char != scanner.keyword[scanner.keyword_offset : scanner.keyword_offset + 1]:
                _pem_reset(scanner, char)
            else:
                scanner.keyword_offset += 1
                if scanner.keyword_offset == len(scanner.keyword):
                    scanner.phase = "label"
                    scanner.suffix = ""
        elif scanner.phase == "label":
            if "A" <= char <= "Z" or char == " ":
                # The label is unbounded; only its fixed terminal phrase matters.
                scanner.suffix = (scanner.suffix + char)[-len("PRIVATE KEY") :]
            elif char == "-" and scanner.suffix == "PRIVATE KEY":
                scanner.phase = "close"
                scanner.dashes = 1
            else:
                _pem_reset(scanner, char)
        else:  # close
            if char != "-":
                _pem_reset(scanner, char)
            else:
                scanner.dashes += 1
                if scanner.dashes == 5:
                    scanner.phase = "search"
                    scanner.suffix = ""
                    # An unmatched delimiter can share these dashes with the next opener.
                    yield ("begin" if scanner.keyword == "BEGIN " else "end"), scanner.start, offset + 1
        index += 1


def _match_pem(text: str) -> Iterator[tuple[str, list[str], int]]:
    scanner = _PemScanner()
    open_block: tuple[int, int] | None = None
    match_end = 0
    for kind, start, end in _pem_delimiters(text, scanner):
        if open_block is None:
            if kind == "begin" and start >= match_end:
                open_block = (start, end)
            continue
        # The public expression requires at least one character between delimiters.
        if kind != "end" or start <= open_block[1]:
            continue
        block_start, block_end = open_block[0], end
        open_block = None
        match_end = end
        begin = max(0, block_start)
        if block_end <= begin:
            continue
        yield text[begin:block_end], [], begin


def redact_pem_block(block: str, marker: str) -> str:
    lines = [line for line in re.split(r"\r?\n", block) if line]
    if len(lines) < 2:
        return "***"
    return f"{lines[0]}\n{marker}\n{lines[-1]}"


# --- Pattern table ------------------------------------------------------------------------------
class _Pattern:
    __slots__ = ("source", "regex", "lookbehind", "matcher", "shell_reference", "form_aware", "chunk_unsafe")

    def __init__(
        self,
        source: str,
        *,
        regex: re.Pattern[str] | None = None,
        lookbehind: bool = False,
        matcher: Any = None,
        shell_reference: bool = False,
        form_aware: bool = False,
        chunk_unsafe: bool = False,
    ) -> None:
        self.source = source
        self.regex = regex
        self.lookbehind = lookbehind
        self.matcher = matcher
        self.shell_reference = shell_reference
        self.form_aware = form_aware
        self.chunk_unsafe = chunk_unsafe


_LITERAL_PATTERN_RE = re.compile(r"^/(.+)/([gimsuy]*)\Z")


def _parse_pattern(raw: str) -> _Pattern:
    if raw == PEM_REDACT_PATTERN_SOURCE:
        return _Pattern(raw, matcher=_match_pem)
    literal = _LITERAL_PATTERN_RE.match(raw)
    # parseRedactPatternSource: a bare string is case-insensitive, a /literal/ keeps its flags.
    source, flags = (literal.group(1), literal.group(2)) if literal else (raw, "gi")
    regex, lookbehind = _compile_js(source, flags)
    return _Pattern(
        raw,
        regex=regex,
        lookbehind=lookbehind,
        shell_reference=raw in SHELL_REFERENCE_PRESERVING_PATTERN_SOURCES,
        form_aware=raw in FORM_AWARE_EQUALS_ASSIGNMENT_PATTERN_SOURCES,
        chunk_unsafe=(
            raw.startswith(BASE64_SAFE_TOKEN_BOUNDARY)
            or raw.startswith(IDENTIFIER_SAFE_TOKEN_BOUNDARY)
            or raw in CHUNK_UNSAFE_PATTERN_SOURCES
        ),
    )


@lru_cache(maxsize=1)
def _default_patterns() -> tuple[_Pattern, ...]:
    return (
        *(_parse_pattern(raw) for raw in DEFAULT_REDACT_STRING_PATTERNS),
        _Pattern("aws-secret-access-key", matcher=_match_aws_secret_access_keys),
    )


# --- Masking ------------------------------------------------------------------------------------
def _mask_token_units(token: str) -> str:
    """``maskToken`` over a unit string."""
    if token == "***":
        return token
    if len(token) < DEFAULT_REDACT_MIN_LENGTH:
        return "***"
    start = _slice_units_safe(token, 0, DEFAULT_REDACT_KEEP_START)
    end = _slice_units_safe(token, -DEFAULT_REDACT_KEEP_END)
    return f"{start}…{end}"


def mask_token(token: str) -> str:
    """``maskToken``: under 18 UTF-16 units ``***``, else first 6 + ``…`` + last 4 (surrogate safe)."""
    return from_units(_mask_token_units(to_units(token)))


_SECRET_VALUE_TRAILING_DELIMITER_RE = re.compile("([\"'`,;)}\\]]+)\\Z")
_SECRET_VALUE_SUFFIX_RE = re.compile("[\"'`,;)}\\]]*\\Z")
_SECRET_VALUE_QUOTE_CHARS = frozenset("\"'`")


class _SecretSplit(NamedTuple):
    maskable: str
    suffix: str
    mask_start: int
    mask_end: int


def _split_secret_value_for_mask(token: str) -> _SecretSplit:
    opening_quote = token[:1]
    if opening_quote in _SECRET_VALUE_QUOTE_CHARS and opening_quote:
        closing_quote_index = token.rfind(opening_quote)
        if closing_quote_index > 0:
            suffix = token[closing_quote_index + 1 :]
            if _SECRET_VALUE_SUFFIX_RE.match(suffix):
                return _SecretSplit(token[1:closing_quote_index], suffix, 0, closing_quote_index + 1)
        without_quote = token[1:]
        trailing_match = _SECRET_VALUE_TRAILING_DELIMITER_RE.search(without_quote)
        trailing = trailing_match.group(1) if trailing_match else ""
        cut = bool(trailing) and len(trailing) < len(without_quote)
        maskable = without_quote[: -len(trailing)] if cut else without_quote
        return _SecretSplit(maskable, trailing if cut else "", 0, 1 + len(maskable))
    trailing_match = _SECRET_VALUE_TRAILING_DELIMITER_RE.search(token)
    trailing = trailing_match.group(1) if trailing_match else ""
    maskable = token[: -len(trailing)] if trailing and len(trailing) < len(token) else token
    return _SecretSplit(maskable, "" if maskable == token else trailing, 0, len(maskable))


_FORM_PAIR_BOUNDARY_RE = re.compile("&[A-Za-z_][A-Za-z0-9_.-]*=")


def _split_form_aware_credential_value(token: str) -> tuple[str, str]:
    boundary = _FORM_PAIR_BOUNDARY_RE.search(token)
    return (token, "") if boundary is None else (token[: boundary.start()], token[boundary.start() :])


def _mask_secret_value(token: str, *, hinted: bool = False) -> str:
    maskable, suffix, _, _ = _split_secret_value_for_mask(token)
    return f"{_mask_token_units(maskable) if hinted else '***'}{suffix}"


# --- Structured authorization parameters (structured-auth-redaction.ts) -------------------------
_AUTH_PARAM_NAME_RE = re.compile("[A-Za-z0-9!#$%&'*+.^_`|~-]+")
_AWS_SCOPE_VALUE_RE = re.compile("[A-Za-z0-9!#$%&'*+.^_`|~:/-]+")
_SIGNED_HEADERS_RE = re.compile(
    "(?::)?[A-Za-z0-9!#$%&'*+.^_`|~-]+(?:;:?[A-Za-z0-9!#$%&'*+.^_`|~-]+)*"
)
_AUTH_HEADER_PREVIOUS_RE = re.compile("[A-Za-z0-9_-]")


@lru_cache(maxsize=1)
def _structured_auth_header_re() -> re.Pattern[str]:
    source = _t(
        r"${HTTP_AUTH_HEADER_BOUNDARY_PATTERN}(?:Proxy-)?Authorization${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}"
        r"[ \t]*[:=]${HTTP_AUTH_OPTIONAL_VALUE_WHITESPACE_PATTERN}${HTTP_AUTH_SERIALIZED_QUOTE_PATTERN}"
        r"(${HTTP_AUTH_SCHEME_PATTERN})${HTTP_AUTH_REQUIRED_VALUE_WHITESPACE_PATTERN}"
    )
    return _compile_js(source, "gi", word_iu=True, expand_sk=True)[0]  # /giu folds s and k


def _skip_horizontal_whitespace(value: str, start: int) -> int:
    cursor = start
    while _char_at(value, cursor) in (" ", "\t"):
        cursor += 1
    return cursor


def _read_serialized_line_end(value: str, start: int) -> int | None:
    cursor = start
    slash_count = 0
    while slash_count < 64 and _char_at(value, cursor) == "\\":
        slash_count += 1
        cursor += 1
    if slash_count == 0:
        return None
    if _char_at(value, cursor) == "n":
        return cursor + 1
    if _char_at(value, cursor) != "r":
        return None
    cursor += 1
    slash_count = 0
    while slash_count < 64 and _char_at(value, cursor) == "\\":
        slash_count += 1
        cursor += 1
    return cursor + 1 if slash_count > 0 and _char_at(value, cursor) == "n" else None


def _read_serialized_tab_end(value: str, start: int) -> int | None:
    cursor = start
    slash_count = 0
    while slash_count < 64 and _char_at(value, cursor) == "\\":
        slash_count += 1
        cursor += 1
    return cursor + 1 if slash_count > 0 and _char_at(value, cursor) == "t" else None


def _skip_auth_whitespace(value: str, start: int) -> int:
    cursor = start
    while True:
        cursor = _skip_horizontal_whitespace(value, cursor)
        tab_end = _read_serialized_tab_end(value, cursor)
        if tab_end is not None:
            cursor = tab_end
            continue
        if _char_at(value, cursor) == "\r" and _char_at(value, cursor + 1) == "\n":
            line_end: int | None = cursor + 2
        elif _char_at(value, cursor) == "\n":
            line_end = cursor + 1
        else:
            line_end = _read_serialized_line_end(value, cursor)
        if line_end is None or (
            _char_at(value, line_end) not in (" ", "\t") and _read_serialized_tab_end(value, line_end) is None
        ):
            return cursor
        cursor = line_end


def _read_auth_param_name(value: str, start: int) -> tuple[str, int] | None:
    match = _AUTH_PARAM_NAME_RE.match(value, start)
    return (match.group(0).lower(), start + len(match.group(0))) if match else None


def _is_auth_header_start(value: str, index: int) -> bool:
    previous = _char_at(value, index - 1)
    serialized_line_boundary = False
    if previous in ("n", "r"):
        slash_cursor = index - 2
        slash_count = 0
        while slash_count < 64 and _char_at(value, slash_cursor) == "\\":
            slash_count += 1
            slash_cursor -= 1
        serialized_line_boundary = slash_count > 0
    if not serialized_line_boundary and previous != "" and _AUTH_HEADER_PREVIOUS_RE.fullmatch(previous):
        return False
    proxy_name = "proxy-authorization"
    direct_name = "authorization"
    candidate = value[index : index + len(proxy_name)].lower()
    if candidate == proxy_name:
        name = proxy_name
    elif candidate.startswith(direct_name):
        name = direct_name
    else:
        return False
    cursor = index + len(name)
    slash_count = 0
    while slash_count < 64 and _char_at(value, cursor) == "\\":
        slash_count += 1
        cursor += 1
    if _char_at(value, cursor) in ('"', "'"):
        cursor += 1
    elif slash_count > 0:
        return False
    cursor = _skip_horizontal_whitespace(value, cursor)
    return _char_at(value, cursor) in (":", "=")


def _find_next_auth_param_start(value: str, start: int) -> int | None:
    cursor = start
    while True:
        cursor = _skip_auth_whitespace(value, cursor)
        if cursor > start and _is_auth_header_start(value, cursor):
            return None
        if cursor >= len(value) or value[cursor] in ("\r", "\n", ";"):
            return None
        if value[cursor] == ",":
            cursor += 1
            continue
        param = _read_auth_param_name(value, cursor)
        if param:
            equals = _skip_auth_whitespace(value, param[1])
            if _char_at(value, equals) == "=" and _char_at(value, equals + 1) != "=":
                return cursor
        while cursor < len(value):
            whitespace_end = _skip_auth_whitespace(value, cursor)
            if whitespace_end > cursor:
                cursor = whitespace_end
                continue
            if cursor > start and _is_auth_header_start(value, cursor):
                return None
            char = value[cursor]
            if char in ("\r", "\n", ";"):
                return None
            cursor += 1
            if char == ",":
                break


def _uses_auth_params(scheme: str) -> bool:
    return scheme in ("digest", "hawk") or scheme.startswith("aws4-")


_AUTH_FIELD_END_CHARS = frozenset("\r\n;\\\"'}]")


def _find_auth_field_end(value: str, start: int) -> int:
    cursor = start
    while cursor < len(value):
        whitespace_end = _skip_auth_whitespace(value, cursor)
        if whitespace_end > cursor:
            cursor = whitespace_end
            continue
        if cursor > start and _is_auth_header_start(value, cursor):
            break
        if value[cursor] in _AUTH_FIELD_END_CHARS:
            break
        cursor += 1
    return cursor


def _read_param_value(value: str, start: int, *, aws_scope: bool, signed_headers: bool) -> int | None:
    escaped_quote_slash_count = 0
    while _char_at(value, start + escaped_quote_slash_count) == "\\":
        escaped_quote_slash_count += 1
    escaped_quotes = escaped_quote_slash_count > 0 and _char_at(value, start + escaped_quote_slash_count) == '"'
    quote = value[start] if _char_at(value, start) in ('"', "'") else None
    if quote or escaped_quotes:
        cursor = start + (escaped_quote_slash_count + 1 if escaped_quotes else 1)
        while cursor < len(value):
            if value[cursor] in ("\r", "\n"):
                whitespace_end = _skip_auth_whitespace(value, cursor)
                if whitespace_end == cursor:
                    break
                cursor = whitespace_end
                continue
            if escaped_quotes and value[cursor] == "\\":
                slash_end = cursor + 1
                while _char_at(value, slash_end) == "\\":
                    slash_end += 1
                if _char_at(value, slash_end) == '"':
                    slash_count = slash_end - cursor
                    if slash_count % (2 * (escaped_quote_slash_count + 1)) == escaped_quote_slash_count:
                        return slash_end + 1
                    cursor = slash_end + 1
                    continue
                cursor = slash_end
                continue
            if not escaped_quotes and value[cursor] == "\\" and cursor + 1 < len(value):
                cursor += 2
                continue
            if not escaped_quotes and value[cursor] == quote:
                return cursor + 1
            cursor += 1
        return cursor if cursor > start + 1 else None
    if signed_headers:
        match = _SIGNED_HEADERS_RE.match(value, start)
        if not match:
            return None
        end = start + len(match.group(0))
        following = _char_at(value, end)
        return end if following in ("", ",", " ", "\t", "\r", "\n") else None
    match = (_AWS_SCOPE_VALUE_RE if aws_scope else _AUTH_PARAM_NAME_RE).match(value, start)
    return start + len(match.group(0)) if match else None


def find_structured_auth_param_ranges(value: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for header in _structured_auth_header_re().finditer(value):
        scheme = (header.group(2) or "").lower()
        cursor = header.start() + len(header.group(0))
        range_start = cursor
        range_end = cursor
        direct_param = _read_auth_param_name(value, cursor)
        direct_equals = _skip_auth_whitespace(value, direct_param[1]) if direct_param else None
        if (
            direct_param is None
            or direct_equals is None
            or _char_at(value, direct_equals) != "="
            or _char_at(value, direct_equals + 1) == "="
        ):
            first_non_whitespace = _skip_auth_whitespace(value, cursor)
            # An opaque token followed by `, status=...` is not an auth-param list.
            if _char_at(value, first_non_whitespace) != "," and not _uses_auth_params(scheme):
                continue
            first_param_start = _find_next_auth_param_start(value, cursor)
            if first_param_start is None:
                continue
            cursor = first_param_start
        while True:
            param = _read_auth_param_name(value, cursor)
            if param is None:
                break
            cursor = _skip_auth_whitespace(value, param[1])
            if _char_at(value, cursor) != "=":
                break
            cursor = _skip_auth_whitespace(value, cursor + 1)
            value_end = _read_param_value(
                value,
                cursor,
                aws_scope=scheme.startswith("aws4-") and param[0] == "credential",
                signed_headers=param[0] == "signedheaders",
            )
            if value_end is None:
                next_param_start = _find_next_auth_param_start(value, cursor)
                if next_param_start is not None:
                    cursor = next_param_start
                    continue
                range_end = max(range_end, _find_auth_field_end(value, cursor))
                break
            range_end = value_end
            separator = _skip_auth_whitespace(value, value_end)
            if _char_at(value, separator) != ",":
                if _char_at(value, separator) != "" and _char_at(value, separator) not in _AUTH_FIELD_END_CHARS:
                    next_param_start = _find_next_auth_param_start(value, separator)
                    if next_param_start is not None:
                        cursor = next_param_start
                        continue
                    range_end = max(range_end, _find_auth_field_end(value, separator))
                break
            next_param_start = _find_next_auth_param_start(value, separator + 1)
            if next_param_start is None:
                break
            cursor = next_param_start
        if range_end > range_start:
            ranges.append((range_start, range_end))
    return ranges


def redact_structured_auth_headers(value: str, replacement: str) -> str:
    ranges = find_structured_auth_param_ranges(value)
    if not ranges:
        return value
    merged: list[list[int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        parts.append(value[cursor:start])
        parts.append(replacement)
        cursor = end
    parts.append(value[cursor:])
    return "".join(parts)


# --- URL / form-body assignments (redact.ts, redact-sensitive-url.ts) ---------------------------
_URL_QUERY_NAME_SEPARATOR_RE = re.compile(f"[{_PLACEHOLDERS['@SEP@']}+]")
_SUFFIXED_OR_SCOPED_TOKEN_QUERY_PARAM_RE = re.compile("(?:^|_)token(?:_[a-f0-9]{16,})?\\Z")
_MAX_NESTED_URL_REDACTION_DEPTH = 8


def _normalize_url_query_param_name(name: str) -> tuple[str, bool]:
    current = _URL_QUERY_NAME_SEPARATOR_RE.sub("", name)

    def lowered(text: str) -> str:
        return js_trim(text).lower().replace("-", "_")

    for _ in range(_MAX_NESTED_URL_REDACTION_DEPTH + 1):
        try:
            decoded = _URL_QUERY_NAME_SEPARATOR_RE.sub("", js_decode_uri_component(current))
        except ValueError:
            return lowered(current), "%" in current
        if decoded == current:
            return lowered(current), False
        current = decoded
    return lowered(current), "%" in current


def is_sensitive_url_query_param_name(name: str) -> bool:
    value, unresolved_encoding = _normalize_url_query_param_name(name)
    return (
        unresolved_encoding
        or value in SENSITIVE_URL_QUERY_PARAM_NAMES
        or bool(_SUFFIXED_OR_SCOPED_TOKEN_QUERY_PARAM_RE.search(value))
    )


def _normalize_sensitive_key_name(value: str) -> str:
    stripped = _FORM_BODY_KEY_SEPARATOR_RE.sub("", value)
    try:
        decoded = _FORM_BODY_KEY_SEPARATOR_RE.sub("", js_decode_uri_component(stripped))
    except ValueError:
        return stripped.lower().replace("-", "_")
    return decoded.lower().replace("-", "_")


def _is_sensitive_body_key(key: str) -> bool:
    return is_sensitive_url_query_param_name(key) or _normalize_sensitive_key_name(key) in BODY_SECRET_KEYS


_FORM_BODY_KEY = r"[${FORM_BODY_KEY_INVISIBLE_CHARS}+]*(?:[A-Za-z_]|%[0-9A-Fa-f]{2})(?:[A-Za-z0-9_.-]|%[0-9A-Fa-f]{2}|[${FORM_BODY_KEY_INVISIBLE_CHARS}+])*"
_FORM_BODY_VALUE = r"[^&\s<>]*"
_URL_QUERY_VALUE = r"[^&#\s<>]*"


def _form_re(source: str, flags: str = "") -> re.Pattern[str]:
    return _compile_js(_t(source), flags, word_iu=True, expand_sk="i" in flags)[0]


_FORM_BODY_KEY_OBFUSCATION_RE = _form_re("[${FORM_BODY_KEY_INVISIBLE_CHARS}+]")
_FORM_BODY_KEY_SEPARATOR_RE = _form_re("[@SEP@+]")
_FORM_BODY_PERCENT_ESCAPE_RE = re.compile("%[0-9A-Fa-f]{2}")
_FORM_BODY_PAIR = _FORM_BODY_KEY + "=" + _FORM_BODY_VALUE
_FORM_BODY_RE = _form_re("^" + _FORM_BODY_PAIR + "(?:&" + _FORM_BODY_PAIR + ")+$")
_FORM_BODY_SUBSTRING_RE = _form_re(
    "(^|[\\s:({\\[,=\"'\\x60])(" + _FORM_BODY_PAIR + "(?:&" + _FORM_BODY_PAIR + ")+)"
)
_ENCODED_FORM_PAIR_RE = _form_re(
    "(^|[\\s:({\\[,=\"'\\x60&])(" + _FORM_BODY_KEY + ")=(" + _FORM_BODY_VALUE + ")"
)
_FORM_BODY_CONTEXT_SINGLE_PAIR_RE = _form_re(
    "(\\b(?:body|form(?:[-_\\s]?body)?)\\s*[:=]\\s*([\"'\\x60]?))("
    + _FORM_BODY_KEY
    + ")=("
    + _FORM_BODY_VALUE
    + ")([\"'\\x60]?)",
    "i",
)
_URL_QUERY_PAIR_RE = _form_re("([?&])(" + _FORM_BODY_KEY + ")=(" + _URL_QUERY_VALUE + ")")
_FORM_BODY_LINE_BREAK_SPLIT_RE = re.compile("(\r\n|\r|\n)")
_FORM_BODY_LINE_BREAK_SEGMENT_RE = re.compile("(?:\r\n|\r|\n)\\Z")


def _has_encoded_or_invisible_form_key(key: str) -> bool:
    return bool(_FORM_BODY_PERCENT_ESCAPE_RE.search(key)) or _FORM_BODY_KEY_OBFUSCATION_RE.sub("", key) != key


def _visit_sensitive_assignments(text: str, kind: str, visit: Any) -> None:
    if not text or (kind == "url" and "?" not in text):
        return
    if kind == "encoded" and "%" not in text and _FORM_BODY_KEY_OBFUSCATION_RE.sub("", text) == text:
        return
    if kind == "context" and "=" not in text and ":" not in text:
        return

    def visit_pair(key: str, token: str, value_offset: int) -> None:
        if kind == "encoded" and not _has_encoded_or_invisible_form_key(key):
            return
        if not _is_sensitive_body_key(key):
            return
        maskable, _, mask_start, mask_end = _split_secret_value_for_mask(token)
        visit(value_offset + mask_start, value_offset + mask_end, maskable)

    if kind == "form":
        cursor = 0
        for pair in text.split("&"):
            equals_index = pair.find("=")
            if equals_index >= 0:
                visit_pair(pair[:equals_index], pair[equals_index + 1 :], cursor + equals_index + 1)
            cursor += len(pair) + 1
        return
    pattern = (
        _URL_QUERY_PAIR_RE
        if kind == "url"
        else _ENCODED_FORM_PAIR_RE
        if kind == "encoded"
        else _FORM_BODY_CONTEXT_SINGLE_PAIR_RE
    )
    key_index = 3 if kind == "context" else 2
    for match in pattern.finditer(text):
        prefix = match.group(1) or ""
        key = match.group(key_index) or ""
        visit_pair(key, match.group(key_index + 1) or "", match.start() + len(prefix) + len(key) + 1)


def _redact_assignment_values(text: str, kind: str) -> str:
    parts: list[str] = []
    cursor = 0

    def visit(start: int, end: int, maskable: str) -> None:
        nonlocal cursor
        parts.append(text[cursor:start])
        parts.append(mask_token(maskable) if kind == "url" else "***")
        cursor = end

    _visit_sensitive_assignments(text, kind, visit)
    return "".join(parts) + text[cursor:] if parts else text


def _redact_form_body_line(text: str) -> str:
    if not text:
        return text
    context_redacted = _redact_assignment_values(_redact_assignment_values(text, "encoded"), "context")
    if "&" not in context_redacted:
        return context_redacted
    if _FORM_BODY_RE.match(context_redacted):
        return _redact_assignment_values(context_redacted, "form")

    def replace_substring(match: re.Match[str]) -> str:
        prefix, body = match.group(1), match.group(2)
        redacted_body = _redact_assignment_values(body, "form")
        return match.group(0) if redacted_body == body else f"{prefix}{redacted_body}"

    redacted = _FORM_BODY_SUBSTRING_RE.sub(replace_substring, context_redacted)
    return _redact_assignment_values(_redact_assignment_values(redacted, "encoded"), "context")


def _redact_form_body(text: str) -> str:
    # Every form grammar requires a literal assignment separator, including encoded keys.
    if "=" not in text:
        return text
    if _FORM_BODY_LINE_BREAK_SPLIT_RE.search(text):
        return "".join(
            segment if _FORM_BODY_LINE_BREAK_SEGMENT_RE.match(segment) else _redact_form_body_line(segment)
            for segment in _FORM_BODY_LINE_BREAK_SPLIT_RE.split(text)
        )
    return _redact_form_body_line(text)


# --- Pattern replacement -----------------------------------------------------------------------
_SHELL_KEY_RE = re.compile("[A-Z_][A-Z0-9_]*\\Z")
_SHELL_BARE_RE = re.compile("\\$([A-Z_][A-Z0-9_]*)\\Z")
_SHELL_BRACED_RE = re.compile("\\$\\{([A-Z_][A-Z0-9_]*)(?::[-=?+])?\\}\\Z")
_ENV_ASSIGNMENT_KEY_RE = re.compile(f"\\b([A-Z_][A-Z0-9_]*)\\b[{JS_SPACE_CLASS}]*[=:]")
_EMPTY_EXPANSION_TAIL_RE = re.compile("[-=?+]\\}\\Z")


def _is_shell_reference_to_key(key: str, value: str) -> bool:
    if not _SHELL_KEY_RE.match(key):
        return False
    bare = _SHELL_BARE_RE.match(value)
    if bare:
        return bare.group(1) == key
    braced = _SHELL_BRACED_RE.match(value)
    return braced is not None and braced.group(1) == key


def _should_preserve_shell_reference_match(match: str, token: str) -> bool:
    found = _ENV_ASSIGNMENT_KEY_RE.search(match)
    return _is_shell_reference_to_key(found.group(1), token) if found else False


def _redact_match(
    match: str,
    groups: list[str],
    offset: int,
    pattern: _Pattern,
    regex_match: re.Match[str] | None,
) -> str:
    if "PRIVATE KEY-----" in match:
        return redact_pem_block(match, "…redacted…")
    selected_index = -1
    selected_value = match
    for index, value in enumerate(groups):
        if value:
            selected_index = index
            selected_value = value
    if selected_value == "***":
        return match
    if selected_value == match:
        token_index = 0
    elif regex_match is not None and selected_index >= 0:
        token_index = regex_match.start(selected_index + 1) - offset
    else:
        token_index = match.rfind(selected_value)
    if token_index < 0:
        return match
    token = selected_value
    secret, suffix = _split_form_aware_credential_value(token) if pattern.form_aware else (token, "")
    # An earlier pass may already have replaced this value with ***.
    if _split_secret_value_for_mask(secret).maskable == "***":
        return match
    if pattern.shell_reference and (
        _should_preserve_shell_reference_match(match, token) or _EMPTY_EXPANSION_TAIL_RE.match(token)
    ):
        return match
    masked = _mask_token_units(token) if pattern.shell_reference else f"{_mask_secret_value(secret, hinted=True)}{suffix}"
    return match[:token_index] + masked + match[token_index + len(token) :]


def _replace_regex(text: str, pattern: _Pattern) -> str:
    regex = pattern.regex
    assert regex is not None
    if not pattern.lookbehind:
        return regex.sub(
            lambda m: _redact_match(m.group(0), [g or "" for g in m.groups()], m.start(), pattern, m),
            text,
        )
    # Variable-length lookbehind after group 1: the outcome depends only on the start position, so
    # a rejected match resumes the search one character later, like the regex engine would.
    parts: list[str] = []
    last = 0
    position = 0
    while position <= len(text):
        match = regex.search(text, position)
        if match is None:
            break
        if not _base64_lookbehind_ok(text, match.end(1)):
            position = match.start() + 1
            continue
        parts.append(text[last : match.start()])
        parts.append(
            _redact_match(match.group(0), [g or "" for g in match.groups()], match.start(), pattern, match)
        )
        last = match.end()
        position = match.end() if match.end() > match.start() else match.end() + 1
    if not parts:
        return text
    parts.append(text[last:])
    return "".join(parts)


def _replace_bounded(text: str, pattern: _Pattern) -> str:
    if len(text) <= REDACT_REGEX_CHUNK_THRESHOLD:
        return _replace_regex(text, pattern)
    # Chunking may miss matches spanning chunk boundaries; chunk-unsafe patterns skip this path.
    output: list[str] | None = None
    for index in range(0, len(text), REDACT_REGEX_CHUNK_SIZE):
        chunk = text[index : index + REDACT_REGEX_CHUNK_SIZE]
        replaced = _replace_regex(chunk, pattern)
        if output is not None:
            output.append(replaced)
        elif replaced != chunk:
            output = [text[:index], replaced]
    return "".join(output) if output is not None else text


def _apply_pattern(text: str, pattern: _Pattern) -> str:
    if pattern.regex is not None:
        return _replace_regex(text, pattern) if pattern.chunk_unsafe else _replace_bounded(text, pattern)
    parts: list[str] = []
    end = 0
    for match, groups, offset in pattern.matcher(text):
        parts.append(text[end:offset])
        parts.append(_redact_match(match, groups, offset, pattern, None))
        end = offset + len(match)
    return "".join(parts) + text[end:] if parts else text


def _redact_text(text: str, patterns: tuple[_Pattern, ...] | None = None) -> str:
    """``redactText(text, patterns)`` (default: the full default pattern table)."""
    staged = _redact_form_body(
        _redact_assignment_values(redact_structured_auth_headers(text, "***"), "url")
    )
    units = to_units(staged)
    for pattern in _default_patterns() if patterns is None else patterns:
        units = _apply_pattern(units, pattern)
    return from_units(units)


def _could_match_default_redact_patterns(text: str) -> bool:
    return bool(_prefilter_re().search(text)) or _could_match_aws_secret_access_key(text)


def redact_sensitive_text(text: str) -> str:
    """``redactSensitiveText(text, {mode: "tools"})`` with an empty secret registry."""
    if not text:
        return text
    joined = from_units(text)
    if not _could_match_default_redact_patterns(joined):
        return text
    return _redact_text(joined)


# --- redactModelVisibleSecrets (structured, model-visible tool output) ----------------------------
# ``redactModelVisibleSecrets(value)`` is ``redactSecretsWithOptions(value, {mode: "tools",
# patterns: TOOL_PAYLOAD_REDACT_PATTERNS, sensitiveFieldPatterns: DEFAULT_REDACT_PATTERNS})``: a
# string goes through ``redactSensitiveText`` with the tool-payload pattern subset; a record or
# array is walked, and every string under a key goes through ``redactSensitiveFieldValue`` (the
# subset, or the full table under a sensitive key, then app-specific passwords, then a whole-value
# mask for a sensitive key); numbers and booleans under a sensitive key become ``***``.
# Not ported: the exact-secret registry (``redactRegisteredSecretValues``, empty here) and the
# ``logging.redactPatterns`` / full-context configuration (none is read, so the defaults apply).
_JS_I = re.IGNORECASE | re.ASCII
STRUCTURED_SECRET_FIELD_RE = re.compile(
    _t(
        r"(?:api[-_]?key|apiKey|api[-_]?token|apiToken|bearer[-_]?token|bearerToken|token|secret|password|passwd|${AWS_SECRET_ACCESS_KEY_FIELD_KEYS}|credential|authorization|private[-_]?key|privateKey|access[-_]?token|accessToken|refresh[-_]?token|refreshToken|id[-_]?token|idToken|auth[-_]?token|authToken|client[-_]?secret|clientSecret|app[-_]?secret|appSecret|secret[-_]?value|secretValue|raw[-_]?secret|rawSecret|secret[-_]?input|secretInput|key|key[-_]?material|keyMaterial|jwt|session|signature|cookie|set[-_]?cookie|${PAYMENT_CREDENTIAL_QUERY_KEYS}|${PAYMENT_CREDENTIAL_JSON_KEYS})"
    ),
    _JS_I,
)
STRUCTURED_SECRET_ENV_FIELD_RE = re.compile(
    _t(
        r"(?:(?:[A-Z0-9]+[_-])+(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)|API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|${PAYMENT_CREDENTIAL_ENV_KEYS})"
    ),
    _JS_I,
)
STRUCTURED_APP_PASSWORD_FIELD_RE = re.compile(
    r"(?:apple|icloud|app[-_]?specific[-_]?password|appSpecificPassword|application[-_]?password"
    r"|text|content|message|error|errorMessage|detail|details|reason)",
    _JS_I,
)
_STRUCTURED_INTERNAL_SOURCE_PATH_VALUE_RE = re.compile(r"\$WORKSPACE_DIR/[A-Za-z0-9._/-]+\.jsonl")
_APP_SPECIFIC_PASSWORD_RE = re.compile(r"\b([a-z]{4}-[a-z]{4}-[a-z]{4}-[a-z]{4})\b", re.ASCII)
_BENIGN_APP_PASSWORD_WORDS = frozenset(
    ("case", "claw", "demo", "file", "main", "name", "open", "path", "slug", "test")
)
_TRANSPORT_CODE_RES = (
    re.compile(r"\beconnrefused\b", _JS_I),
    re.compile(r"\beconnreset\b|\beconnaborted\b|\benetreset\b|\bepipe\b", _JS_I),
    re.compile(r"\benotfound\b|\beai_again\b", _JS_I),
    re.compile(r"\benetunreach\b|\behostunreach\b|\behostdown\b", _JS_I),
)
_TOOL_PAYLOAD_AMBIGUOUS_ASSIGNMENT_PATTERNS = frozenset(
    (
        ENV_ASSIGNMENT_REDACT_PATTERN,
        ESCAPED_ENV_ASSIGNMENT_REDACT_PATTERN,
        STRUCTURED_JSON_SECRET_REDACT_PATTERN,
        AMBIGUOUS_QUOTED_SECRET_FIELD_REDACT_PATTERN,
        AMBIGUOUS_QUOTED_AUTH_FIELD_REDACT_PATTERN,
        STANDALONE_ASSIGNMENT_QUOTED_REDACT_PATTERN,
        STANDALONE_ASSIGNMENT_REDACT_PATTERN,
        CONFIG_QUOTED_ASSIGNMENT_REDACT_PATTERN,
        CONFIG_ASSIGNMENT_REDACT_PATTERN,
        CONFIG_DIRECT_ASSIGNMENT_REDACT_PATTERN,
        CONFIG_PREFIXED_PASSWORD_ASSIGNMENT_REDACT_PATTERN,
        CONFIG_NAMESPACED_ASSIGNMENT_REDACT_PATTERN,
    )
)
# ``TOOL_PAYLOAD_REDACT_PATTERNS``: model-visible tool output is often source code, so the
# assignment families that match on key names alone are dropped; recognizable token shapes,
# headers, PEM blocks, payment JSON and the AWS matcher stay.
TOOL_PAYLOAD_REDACT_STRING_PATTERNS: tuple[str, ...] = tuple(
    raw
    for raw in DEFAULT_REDACT_STRING_PATTERNS
    if raw not in _TOOL_PAYLOAD_AMBIGUOUS_ASSIGNMENT_PATTERNS
)


@lru_cache(maxsize=1)
def _tool_payload_patterns() -> tuple[_Pattern, ...]:
    return (
        *(_parse_pattern(raw) for raw in TOOL_PAYLOAD_REDACT_STRING_PATTERNS),
        _Pattern("aws-secret-access-key", matcher=_match_aws_secret_access_keys),
    )


def is_sensitive_field_key(key: str) -> bool:
    """``isSensitiveFieldKey``."""
    return (
        STRUCTURED_SECRET_FIELD_RE.fullmatch(key) is not None
        or STRUCTURED_SECRET_ENV_FIELD_RE.fullmatch(key) is not None
    )


def _is_known_transport_error_code(value: str) -> bool:
    for pattern in _TRANSPORT_CODE_RES:
        found = pattern.search(value)
        if found is not None and found.group(0) == value:
            return True
    return False


def _path_ends_with(path: list[str], suffix: tuple[str, ...]) -> bool:
    return len(path) >= len(suffix) and tuple(path[len(path) - len(suffix) :]) == suffix


def _should_redact_structured_authorization_code(
    normalized_key: str, path: tuple[str, ...], transport_code: str | None = None
) -> bool:
    """``shouldRedactStructuredAuthorizationCode`` (structured-authorization-code.ts)."""
    if normalized_key != "code":
        return False
    parts = [part.lower() for part in path]
    if len(parts) == 1 or any(
        _path_ends_with(parts, suffix)
        for suffix in (
            ("error", "code"),
            ("nodeerror", "code"),
            ("status", "code"),
            ("details", "code"),
            ("warnings", "code"),
        )
    ):
        return False
    return not (
        transport_code is not None
        and len(parts) > 1
        and all(part == "cause" for part in parts[:-1])
        and _is_known_transport_error_code(transport_code)
    )


def _is_public_share_id_path(path: tuple[str, ...]) -> bool:
    if not path or path[-1].lower() != "id":
        return False
    parent = path[-2].lower().replace("-", "").replace("_", "") if len(path) >= 2 else None
    return parent == "publicshare"


def _redact_app_specific_passwords(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if any(part.lower() in _BENIGN_APP_PASSWORD_WORDS for part in token.split("-")):
            return match.group(0)
        return mask_token(token)

    units = to_units(text)
    if len(units) <= REDACT_REGEX_CHUNK_THRESHOLD:
        return from_units(_APP_SPECIFIC_PASSWORD_RE.sub(replace, units))
    output: list[str] | None = None
    for index in range(0, len(units), REDACT_REGEX_CHUNK_SIZE):
        chunk = units[index : index + REDACT_REGEX_CHUNK_SIZE]
        replaced = _APP_SPECIFIC_PASSWORD_RE.sub(replace, chunk)
        if output is not None:
            output.append(replaced)
        elif replaced != chunk:
            output = [units[:index], replaced]
    return from_units("".join(output)) if output is not None else text


def _preserves_structured_reference(key: str, value: str) -> bool:
    return (
        key.lower() == "session"
        and _STRUCTURED_INTERNAL_SOURCE_PATH_VALUE_RE.fullmatch(value) is not None
    ) or _is_shell_reference_to_key(key, value)


def _should_redact_structured_string_field(
    key: str, value: str, path: tuple[str, ...], object_path: bool
) -> bool:
    return _should_redact_structured_authorization_code(
        key.lower(), path, value if object_path else None
    ) or (is_sensitive_field_key(key) and not _preserves_structured_reference(key, value))


def _should_redact_structured_primitive_field(key: str, path: tuple[str, ...]) -> bool:
    return (
        _is_public_share_id_path(path)
        or _should_redact_structured_authorization_code(key.lower(), path)
        or is_sensitive_field_key(key)
    )


def redact_model_visible_field_value(
    key: str, value: str, path: tuple[str, ...] | None = None, object_path: bool = True
) -> str:
    """``redactSensitiveFieldValueWithOptions`` under the model-visible tool-payload policy."""
    path = (key,) if path is None else path
    if _is_public_share_id_path(path):
        return mask_token(value)
    patterns = _default_patterns() if is_sensitive_field_key(key) else _tool_payload_patterns()
    joined = from_units(value)
    redacted = (
        _redact_text(joined, patterns) if _could_match_default_redact_patterns(joined) else joined
    )
    changed = redacted != joined
    if changed or STRUCTURED_APP_PASSWORD_FIELD_RE.fullmatch(key) is not None:
        app_redacted = _redact_app_specific_passwords(redacted)
        if app_redacted != joined:
            return app_redacted
    if changed:
        return redacted
    if _should_redact_structured_string_field(key, value, path, object_path):
        return mask_token(value)
    return value


def _js_object_key_order(keys: list[str]) -> list[str]:
    """Own property order of a JS object: array-index keys ascending, then insertion order."""
    index_keys = [
        key for key in keys if re.fullmatch(r"0|[1-9][0-9]{0,9}", key) and int(key) < 2**32 - 1
    ]
    index_set = set(index_keys)
    return sorted(index_keys, key=int) + [key for key in keys if key not in index_set]


def _redact_structured_value(
    key: str, value: Any, seen: set[int], path: tuple[str, ...], object_path: bool
) -> Any:
    if isinstance(value, str):
        return redact_model_visible_field_value(key, value, path, object_path)
    if value is None:
        return value
    if isinstance(value, bool | int | float):
        return "***" if _should_redact_structured_primitive_field(key, path) else value
    if isinstance(value, list | tuple):
        if id(value) in seen:
            return "[Circular]"
        seen.add(id(value))
        out = [_redact_structured_value(key, entry, seen, path, False) for entry in value]
        seen.discard(id(value))
        return out
    if isinstance(value, dict):
        if id(value) in seen:
            return "[Circular]"
        seen.add(id(value))
        out_dict = {
            name: _redact_structured_value(name, value[name], seen, (*path, name), object_path)
            for name in _js_object_key_order(list(value))
        }
        seen.discard(id(value))
        return out_dict
    return value


def redact_model_visible_secrets(value: Any) -> Any:
    """``redactModelVisibleSecrets``: tool-payload patterns for strings, field-name masks for records.

    A string is redacted as text (the tool-payload subset of the default patterns, no field
    context). A dict or list is copied with every string redacted under its key (a sensitive key
    uses the full pattern table and masks an unchanged value whole), numbers and booleans under a
    sensitive key replaced by ``***``, and ``None`` kept.
    """
    if isinstance(value, str):
        if not value:
            return value
        joined = from_units(value)
        if not _could_match_default_redact_patterns(joined):
            return value
        return _redact_text(joined, _tool_payload_patterns())
    if value is None or not isinstance(value, dict | list | tuple):
        return value
    return _redact_structured_value("", value, set(), (), True)
