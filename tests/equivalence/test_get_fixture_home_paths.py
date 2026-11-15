"""Owned path-identity codec checks; no memory engine or acceptance credit."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

from equivalence.get_contract import map_get_fixture_paths, run_get_contract
from equivalence.get_fixture_filesystem import validate_python_get_filesystem_evidence
from equivalence.storage_path_contract import build_storage_path_contract_cases

ROOT = Path(__file__).resolve().parents[2]
BASE, HOME, SHORT = "/home/example/run/fixture", "/home/example", "~/run/fixture"


def mapped(value, base=BASE, home=HOME):
    return map_get_fixture_paths(value, base, fixture_home=home)


def test_default_remains_absolute_only():
    value = [BASE, BASE + "/workspace", SHORT, SHORT + "/workspace"]
    assert map_get_fixture_paths(value, BASE) == ["$FIXTURE", "$FIXTURE/workspace", *value[2:]]


@pytest.mark.parametrize("base,home,short", [
    (BASE, HOME, SHORT), (HOME, HOME, "~"),
    ("/tmp/fixture", "/", "~/tmp/fixture"), ("/tmp/fixture", "", "~/tmp/fixture"),
])
def test_only_the_owned_whole_root_and_its_descendants_are_equivalent(base, home, short):
    assert mapped([base, base + "/workspace"], base, home) == ["$FIXTURE", "$FIXTURE/workspace"]
    assert mapped([short, short + "/workspace"], base, home) == ["$FIXTURE", "$FIXTURE/workspace"]


def test_embedded_error_paths_keep_fields_order_and_original_input():
    value = {SHORT + "/key": "literal key", "status": "error", "code": "outside-workspace",
             "error": f"Symlink escapes root ({SHORT}/workspace): {SHORT}/workspace/memory/outside",
             "paths": [BASE + "/second", SHORT + "/first"], "extra": [None, False, 0]}
    before = deepcopy(value)
    expected = {**value, "error": "Symlink escapes root ($FIXTURE/workspace): $FIXTURE/workspace/memory/outside",
                "paths": ["$FIXTURE/second", "$FIXTURE/first"]}
    assert mapped(value) == expected
    assert value == before and list(mapped(value)) == list(value)


def test_neighbor_roots_and_unowned_home_paths_stay_literal():
    value = [BASE + "-neighbor/file", SHORT + "-neighbor/file", "~/other/file", "~", "/elsewhere/file"]
    assert mapped(value) == value
    assert mapped("~/run/fixture/file", "/home/example-neighbor/run/fixture", HOME) == "~/run/fixture/file"


def test_replay_uses_recorded_home_instead_of_the_current_environment(monkeypatch):
    monkeypatch.setenv("HOME", "/different/replay-user")
    assert mapped(SHORT + "/workspace") == "$FIXTURE/workspace"


def test_trailing_home_shortens_children_without_inventing_a_bare_tilde_alias():
    assert mapped([HOME, "~", "~/child"], HOME, HOME + "/") == ["$FIXTURE", "~", "$FIXTURE/child"]


def test_control_escaping_applies_only_to_known_root_spellings():
    base = BASE + "\n"
    escaped, short = BASE + r"\u000a", SHORT + r"\u000a"
    assert mapped([base + "/child", escaped + "/child", short + "/child"], base) == ["$FIXTURE/child"] * 3
    # A real newline and a literal escape in the suffix remain different values.
    assert mapped(short + "/a\n", base) == "$FIXTURE/a\n"
    assert mapped(short + r"/a\u000a", base) == r"$FIXTURE/a\u000a"
    assert mapped("unrelated\ntext", base) == "unrelated\ntext"


@pytest.mark.parametrize("changed", ["word", "status", "suffix"])
def test_identity_mapping_cannot_hide_changed_error_behavior(changed):
    left = {"status": "error", "error": f"Symlink escapes root ({BASE}/workspace): {BASE}/workspace/outside"}
    right = {"status": "error", "error": f"Symlink escapes root ({SHORT}/workspace): {SHORT}/workspace/outside"}
    assert mapped(left) == mapped(right)
    if changed == "status":
        right["status"] = "ok"
    else:
        right["error"] = right["error"].replace("escapes", "enters") if changed == "word" else right["error"] + "-different"
    assert mapped(left) != mapped(right)


def test_mapping_is_idempotent():
    once = mapped({"paths": [BASE, SHORT + "/workspace"]})
    assert mapped(once) == once


def test_sdk_raw_replay_uses_its_recorded_home_and_rejects_a_borrowed_one(tmp_path, monkeypatch):
    saved_home = tmp_path / "recorded-home"
    saved_home.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(saved_home))
    monkeypatch.setenv("HOME", str(saved_home))
    case = next(case for case in build_storage_path_contract_cases()
                if case["id"] == "storage-path-contract-symlink-admission")
    evidence = tmp_path / "evidence"
    public = run_get_contract(case["input"], evidence_directory=evidence)
    raw = json.loads((evidence / "python-raw.json").read_text())
    assert all(row["fixtureHome"] == str(saved_home) for row in raw)
    monkeypatch.setenv("HOME", "/different/replay-user")
    validate_python_get_filesystem_evidence(raw, case["input"], public)
    raw[0]["fixtureHome"] = "/borrowed/fixture-home"
    with pytest.raises(ValueError, match="Actual SDK arguments differ"):
        validate_python_get_filesystem_evidence(raw, case["input"], public)


def test_javascript_and_python_use_the_same_batched_identity_rules():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable; codec-only check grants no acceptance credit")
    vectors = [{"base": BASE, "home": None, "value": [BASE, SHORT]},
               {"base": BASE, "home": HOME, "value": [BASE + "/x", SHORT + "/x", SHORT + "-neighbor/x", "~/other"]},
               {"base": HOME, "home": HOME, "value": [HOME, "~", "~/x"]},
               {"base": HOME, "home": HOME + "/", "value": [HOME, "~", "~/x"]},
               {"base": "/tmp/fixture", "home": "", "value": ["/tmp/fixture", "~/tmp/fixture/x"]},
               {"base": "/tmp/fixture", "home": "/", "value": ["/tmp/fixture", "~/tmp/fixture/x"]},
               {"base": BASE + "\n", "home": HOME, "value": [BASE + r"\u000a/x", SHORT + "\\u000a/a\n"]}]
    module = (ROOT / "equivalence/get-contract-runtime.mjs").as_uri()
    script = ("import fs from 'node:fs';import {mapGetFixturePaths} from " + json.dumps(module)
              + ";const rows=JSON.parse(fs.readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(rows.map(r=>mapGetFixturePaths(r.value,r.base,r.home))));")
    actual = subprocess.run([node, "--input-type=module", "--eval", script], input=json.dumps(vectors),
                            capture_output=True, text=True, check=True, timeout=10, cwd=ROOT)
    expected = [mapped(row["value"], row["base"], row["home"]) for row in vectors]
    assert json.loads(actual.stdout) == expected
