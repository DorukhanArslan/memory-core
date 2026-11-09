"""Pinned-engine Letter facts and complement-before-fold class serialization."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest

from memory_core import _unicode_letter_ranges as facts
from memory_core.project_name import PACKAGE_NAME
from memory_core.redact_user_patterns import compile_config_regex
from memory_core.unicode_letter_property import LETTER_PROPERTY_ALIASES, letter_property_class_body
from scripts.generate_unicode_letter_ranges import render_module


# SHA256 of one byte per code point, 0x000000..0x10ffff inclusive, observed
# independently from the exact pinned Node24.16.0/ICU78.3 original RegExp engine.
_BITMAPS = [
    (r"\p{L}", "u", "4ae2f94163fc830c400817221b1d9abae228de884b29eb2da047b1f699b64df1"),
    (r"\p{L}", "iu", "5c50ffabfdcbf25c62b5b8b84faf68c4add92236348001cb607c7a4325677039"),
    (r"\P{L}", "u", "8de2a63e1aa36c532d4a80008c9eb150ca67b5c5c7f7eb08812fc4eea51d0ed5"),
    (r"\P{L}", "iu", "9b256bcb956feb067a79a9e8b551cb20ca63279d25e02813a7f76b781e629a6c"),
    (r"[\p{L}]", "u", "4ae2f94163fc830c400817221b1d9abae228de884b29eb2da047b1f699b64df1"),
    (r"[\p{L}]", "iu", "5c50ffabfdcbf25c62b5b8b84faf68c4add92236348001cb607c7a4325677039"),
    (r"[\P{L}]", "u", "8de2a63e1aa36c532d4a80008c9eb150ca67b5c5c7f7eb08812fc4eea51d0ed5"),
    (r"[\P{L}]", "iu", "9b256bcb956feb067a79a9e8b551cb20ca63279d25e02813a7f76b781e629a6c"),
    (r"[^\p{L}]", "u", "8de2a63e1aa36c532d4a80008c9eb150ca67b5c5c7f7eb08812fc4eea51d0ed5"),
    (r"[^\p{L}]", "iu", "e15589a188ebdde3e822160e0f80e3355ec554ee74426171c62348ff86acc482"),
    (r"[^\P{L}]", "u", "4ae2f94163fc830c400817221b1d9abae228de884b29eb2da047b1f699b64df1"),
    (r"[^\P{L}]", "iu", "e2172e264f62aeff8ec49624983d88a690180a5276fb11ff09b127c77e29ba95"),
]


def test_facts_pin_exact_engine_and_complete_merged_letter_ranges():
    assert (facts.NODE_VERSION, facts.ICU_VERSION, facts.UNICODE_VERSION) == ("v24.16.0", "78.3", "17.0")
    assert facts.NODE_BINARY_SHA256 == "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"
    assert len(facts.UNICODE_LETTER_RANGES) == 684
    assert sum(last - first + 1 for first, last in facts.UNICODE_LETTER_RANGES) == facts.LETTER_CODEPOINT_COUNT == 145672
    previous = -2
    for first, last in facts.UNICODE_LETTER_RANGES:
        assert 0 <= first <= last <= 0x10FFFF and first > previous + 1
        previous = last
    encoded = json.dumps(facts.UNICODE_LETTER_RANGES, separators=(", ", ": ")).encode("ascii")
    assert hashlib.sha256(encoded).hexdigest() == facts.RANGES_JSON_SHA256 == (
        "26c5b6818af32e29fab028eb7e9c1b29a156a9a51ca0fef59b9fddb81d8025a9")


def test_generator_reproduces_runtime_module_and_package_path_from_name():
    generated = render_module({"node": facts.NODE_VERSION, "icu": facts.ICU_VERSION,
                               "unicode": facts.UNICODE_VERSION, "ranges": facts.UNICODE_LETTER_RANGES})
    path = Path(facts.__file__).resolve()
    assert path.parent.name == PACKAGE_NAME
    assert generated == path.read_text(encoding="utf-8")
    notice = path.parents[1] / "LICENSE.unicode"
    assert "UNICODE LICENSE V3" in notice.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: Unicode-3.0" in notice.read_text(encoding="utf-8")


def test_only_exact_six_aliases_in_unicode_mode_are_supported():
    assert LETTER_PROPERTY_ALIASES == {
        "L", "Letter", "gc=L", "gc=Letter", "General_Category=L", "General_Category=Letter"}
    for name in LETTER_PROPERTY_ALIASES:
        assert letter_property_class_body(name, unicode_mode=True) is letter_property_class_body("L", unicode_mode=True)
        assert letter_property_class_body(name, unicode_mode=False) is None
    for name in ("letter", "l", "IsLetter", "GeneralCategory=L", "gc=letter", "gc = L", "Script=Greek",
                 "Lowercase_Letter", "Emoji", "Any", "L&", "L}", "L}.*", ""):
        assert letter_property_class_body(name, unicode_mode=True) is None


@pytest.fixture(scope="module")
def all_codepoints():
    return "".join(map(chr, range(0x110000)))


@pytest.mark.parametrize("source,flags,expected", _BITMAPS, ids=[f"{source}/{flags}" for source, flags, _ in _BITMAPS])
def test_entire_codepoint_bitmap_matches_pinned_native_engine(source, flags, expected, all_codepoints):
    compiled = compile_config_regex(source, flags)
    assert compiled.reason is None
    pattern = compiled.regex.regex
    bitmap = bytearray(0x110000)
    for match in pattern.finditer(all_codepoints):
        bitmap[match.start():match.end()] = b"\1" * (match.end() - match.start())
    assert hashlib.sha256(bitmap).hexdigest() == expected


def test_complement_precedes_fold_and_keeps_astral_and_unpaired_boundaries():
    letters = letter_property_class_body("L", unicode_mode=True)
    nonletters = letter_property_class_body("L", unicode_mode=True, negate=True)
    # U0345 is a mark whose simple case fold is Greek iota. Both properties can
    # include its fold-equivalence class under /iu; outer class negation cannot.
    for char in ("\u0345", "ι", "Ι"):
        assert re.fullmatch("[" + nonletters + "]", char, re.I)
        assert re.fullmatch("[^" + letters + "]", char, re.I) is None
    assert re.fullmatch("[" + letters + "]", "𐐀")
    assert re.fullmatch("[" + letters + "]", "\ud800") is None
    assert re.fullmatch("[" + nonletters + "]", "\ud800")
