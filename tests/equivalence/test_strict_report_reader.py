"""Strict streaming syntax controls; no captures or original engine execution."""
import json
from pathlib import Path
import sys

import pytest

from equivalence.strict_report_reader import Reader


@pytest.mark.parametrize("chunk", [1, 2, 7, 31, 1024])
def test_streamed_root_arrays_are_individually_delivered_without_losing_whole_values(tmp_path, chunk):
    value = {"header": {"unicode": "é🐈", "literal": "quote\\\""},
             "cases": [{"whole": [False, 0, None, 1.25e-8]}, {"nested": {"retained": True}}],
             "empty": [], "tail": "retained"}
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n")
    seen = []
    reader = Reader(path, chunk)
    reader.top(lambda key, item, array: seen.append((key, item, array)))
    assert reader.stream.closed
    assert seen == [("header", value["header"], False), ("cases", value["cases"][0], True),
                    ("cases", value["cases"][1], True), ("cases", None, "array-done"),
                    ("empty", None, "array-done"), ("tail", "retained", False)]


@pytest.mark.parametrize("wire", [
    '[]', '{} {}', '{"ignored":{"key":1,"key":2}}', '{"cases":[],"cases":[]}',
    '{"cases":[{"ignored":NaN}]}', '{"ignored":Infinity}', '{"ignored":1e4000}',
    '{"cases":[{},]}', '{"cases":[],}', '{"cases" []}', '{"cases":[{}] trailing}',
    '{"value":truefalse}', '{"value":01}', '{"value":"unterminated}', '{',
])
@pytest.mark.parametrize("chunk", [1, 13])
def test_ignored_areas_duplicates_nonfinite_trailing_and_invalid_syntax_all_fail(tmp_path, wire, chunk):
    path = tmp_path / "invalid.json"
    path.write_text(wire)
    reader = Reader(path, chunk)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        reader.top(lambda *args: None)
    assert reader.stream.closed


def test_long_number_prefix_can_become_finite_without_changing_integer_process_limits(tmp_path):
    before = sys.get_int_max_str_digits()
    path = tmp_path / "numeric.json"
    path.write_text('{"value":' + '1' * 4500 + 'e-4499}')
    values = []
    Reader(path, 41).top(lambda key, value, array: values.append(value))
    assert len(values) == 1 and 1 < values[0] < 2
    assert sys.get_int_max_str_digits() == before


def test_callback_failure_still_closes_the_original_reader(tmp_path):
    path = tmp_path / "callback.json"
    path.write_text('{"cases":[{},{}]}')
    reader = Reader(path, 2)
    def refused(*args):
        raise RuntimeError("Labelled admission refusal")
    with pytest.raises(RuntimeError, match="admission"):
        reader.top(refused)
    assert reader.stream.closed


@pytest.mark.parametrize("chunk", [0, -1, True, None, "1"])
def test_invalid_chunk_bounds_do_not_open_a_reader(tmp_path, chunk):
    with pytest.raises(ValueError, match="positive integer"):
        Reader(Path(tmp_path) / "unopened.json", chunk)
