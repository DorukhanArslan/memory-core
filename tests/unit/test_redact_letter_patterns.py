"""Letter property tokens keep the existing syntax, flags and safety owners."""
import pytest

from memory_core.redact_user_patterns import compile_config_regex, compile_redact_pattern
from memory_core.unicode_letter_property import LETTER_PROPERTY_ALIASES


@pytest.mark.parametrize("alias", sorted(LETTER_PROPERTY_ALIASES))
def test_exact_letter_alias_is_one_unicode_atom_with_existing_capture_semantics(alias):
    compiled = compile_config_regex(rf"(prefix:)(\p{{{alias}}}+)", "gu")
    assert compiled.reason is None
    assert compiled.regex.regex.fullmatch("prefix:Α漢字𐐀").groups() == ("prefix:", "Α漢字𐐀")
    assert compiled.regex.regex.fullmatch("prefix:123") is None


@pytest.mark.parametrize("source", [r"[a-\p{L}]", r"[\p{Letter}-z]", r"[a-\P{gc=L}]"])
def test_property_set_cannot_be_used_as_a_range_endpoint(source):
    assert compile_config_regex(source, "u").reason == "invalid-regex"


def test_materialized_complement_is_folded_before_outer_class_negation():
    property_complement = compile_config_regex(r"\P{L}", "iu").regex.regex
    outer_negation = compile_config_regex(r"[^\p{L}]", "iu").regex.regex
    # These are different native /u operations: the combining mark folds to
    # Greek iota after the property complement is materialized.
    for char in ("\u0345", "ι", "Ι"):
        assert property_complement.fullmatch(char)
        assert outer_negation.fullmatch(char) is None


def test_property_inside_class_keeps_literals_and_astral_units_in_unicode_mode():
    compiled = compile_config_regex(r"[\p{General_Category=Letter}0-9_]+", "u")
    assert compiled.regex.regex.fullmatch("Αa0_𐐀")
    assert compiled.regex.regex.fullmatch("\ud800") is None


def test_existing_safety_and_nonunicode_escape_paths_are_preserved():
    assert compile_config_regex(r"(\p{L}+)+$", "u").reason == "unsafe-nested-repetition"
    assert compile_config_regex(r"\p{L}").regex.regex.fullmatch("p{L}")
    assert compile_redact_pattern(r"/\p{L}/u").regex.unicode is True
    assert compile_config_regex(r"\p{Lu}", "u").reason == "unsupported-syntax"
    assert compile_config_regex(r"[\p{ASCII}&&\p{Letter}]", "v").reason == "unsupported-syntax"
