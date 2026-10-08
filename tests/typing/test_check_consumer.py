"""Failure boundaries of the external consumer diagnostic gate."""

import importlib.util
import subprocess
from pathlib import Path

import pytest


RUNNER = Path(__file__).with_name("check_consumer.py")


def runner():
    assert RUNNER.is_file(), "the installed-consumer validation runner is missing"
    spec = importlib.util.spec_from_file_location("check_consumer", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result(code, text):
    return subprocess.CompletedProcess([], code, stdout=text, stderr="")


def test_negative_contract_requires_the_expected_error_codes_and_lines(tmp_path):
    fixture = tmp_path / "invalid_public_api.py"
    fixture.write_text("bad()  # E: arg-type\n", encoding="utf-8")
    gate = runner()
    gate.validate_result(result(1, f"{fixture}:1: error: wrong argument  [arg-type]\n"), fixture)
    for wrong in (result(0, ""),
                  result(1, f"{fixture}:1: error: package has no marker  [import-untyped]\n"),
                  result(1, f"{fixture}:2: error: wrong argument  [arg-type]\n"),
                  result(2, "mypy: invalid configuration\n")):
        with pytest.raises(RuntimeError):
            gate.validate_result(wrong, fixture)


def test_positive_contract_rejects_checker_errors_and_unparsed_output(tmp_path):
    fixture = tmp_path / "public_api.py"
    fixture.write_text("valid()\n", encoding="utf-8")
    gate = runner()
    gate.validate_result(result(0, ""), fixture)
    for wrong in (result(1, f"{fixture}:1: error: inferred Any  [assert-type]\n"),
                  result(0, "unexpected checker output\n")):
        with pytest.raises(RuntimeError):
            gate.validate_result(wrong, fixture)
