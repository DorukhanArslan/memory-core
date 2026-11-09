"""Owned fixture and raw authority guards; these grant no native proof credit."""
from copy import deepcopy
import json
import os

import pytest

from equivalence.get_contract import run_get_contract
from equivalence.get_fixture_filesystem import (
    derive_get_filesystem_observation,
    owned_get_extra_paths,
    owned_get_input_path,
    snapshot_get_fixture,
    validate_get_filesystem_observation,
    validate_python_get_filesystem_evidence,
)
from equivalence.storage_path_contract import build_storage_path_contract_cases
from equivalence.storage_path_acceptance import STORAGE_PATH_ACCEPTANCE_POINTS


def _roots(tmp_path):
    for name in ("workspace", "outside"):
        (tmp_path / name).mkdir()
    return tmp_path


def _pair(base):
    return {"before": snapshot_get_fixture(base), "after": snapshot_get_fixture(base)}


def test_reviewed_matrix_registers_both_points_on_every_required_whole_tool_family():
    cases = build_storage_path_contract_cases()
    assert cases == build_storage_path_contract_cases()
    assert len(cases) == len({case["id"] for case in cases}) == 11
    assert sum(len(case["input"]["steps"]) for case in cases) == 99
    assert all(case["operation"] == "get-contract-runtime" and case["input"]["kind"] == "tool"
               and case["requirement"] == "storage.path-safety" and case["covers"] == list(STORAGE_PATH_ACCEPTANCE_POINTS)
               and case["input"]["observeFilesystem"] is True for case in cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases


def test_owned_tokens_preserve_the_exact_hostile_suffix(tmp_path):
    assert owned_get_input_path("$WORKSPACE/memory/../../outside/a.md", tmp_path) == (
        str(tmp_path / "workspace") + "/memory/../../outside/a.md"
    )
    assert owned_get_input_path("../outside/a.md", tmp_path, require_owned=True) == "../outside/a.md"
    assert owned_get_input_path("memory/%2e%2e/a.md", tmp_path, require_owned=True) == "memory/%2e%2e/a.md"
    assert owned_get_input_path("$OUTSIDE/a.md", tmp_path) == str(tmp_path / "outside") + "/a.md"


@pytest.mark.parametrize("argument", ["$WORKSPACE/../../a.md", "$OUTSIDE/../../a.md", "../../a.md", "/etc/passwd"])
def test_snapshot_profile_never_reads_unowned_argument_paths(tmp_path, argument):
    with pytest.raises(ValueError, match="owned fixture"):
        owned_get_input_path(argument, tmp_path, require_owned=True)


def test_trusted_pattern_configuration_is_forwarded_without_becoming_model_authority(tmp_path):
    roots = [{"path": "$OUTSIDE", "pattern": "public/**/*.md"}]
    assert owned_get_extra_paths(roots, tmp_path) == [
        {"path": str(tmp_path / "outside"), "pattern": "public/**/*.md"},
    ]
    assert roots == [{"path": "$OUTSIDE", "pattern": "public/**/*.md"}]
    with pytest.raises(ValueError):
        owned_get_extra_paths([{"path": "../../unowned", "pattern": "**"}], tmp_path)


def test_snapshot_retains_complete_bytes_symlinks_stats_and_actual_hardlink_identity(tmp_path):
    base = _roots(tmp_path)
    original = base / "outside/a.md"
    original.write_bytes(bytes(range(256)))
    (base / "workspace/hard.md").hardlink_to(original)
    (base / "workspace/link.md").symlink_to(original)
    os.mkfifo(base / "workspace/pipe.md")
    raw = _pair(base)
    observed = derive_get_filesystem_observation(raw)
    assert observed["hardlinksBefore"] == [["outside/a.md", "workspace/hard.md"]]
    assert observed["before"]["workspace/pipe.md"]["kind"] == "fifo"
    assert observed["before"]["workspace/link.md"]["target"] == str(original)
    assert observed["contentUnchanged"] is observed["writeStatsUnchanged"] is True
    file = next(entry for entry in raw["before"]["entries"] if entry["path"] == "outside/a.md")
    assert set(file["rawStat"]) == {key for key in dir(original.lstat()) if key.startswith("st_")}
    assert int(file["openedStat"]["st_ino"]) == original.lstat().st_ino
    public = deepcopy(observed)
    public["before"]["workspace/link.md"]["target"] = "$FIXTURE/outside/a.md"
    public["after"]["workspace/link.md"]["target"] = "$FIXTURE/outside/a.md"
    validate_get_filesystem_observation(raw, public, str(base))


def test_actual_file_write_remains_visible_in_content_and_write_stats(tmp_path):
    base = _roots(tmp_path)
    file = base / "workspace/a.md"
    file.write_bytes(b"before")
    raw = {"before": snapshot_get_fixture(base)}
    file.write_bytes(b"after")
    raw["after"] = snapshot_get_fixture(base)
    observed = derive_get_filesystem_observation(raw)
    assert observed["contentUnchanged"] is observed["writeStatsUnchanged"] is False


def test_access_time_is_retained_but_read_side_effects_do_not_claim_a_write(tmp_path):
    base = _roots(tmp_path)
    (base / "workspace/a.md").write_bytes(b"a")
    raw = _pair(base)
    entry = next(row for row in raw["after"]["entries"] if row["path"] == "workspace/a.md")
    entry["rawStat"]["st_atime_ns"] = str(int(entry["rawStat"]["st_atime_ns"]) + 10)
    assert derive_get_filesystem_observation(raw)["writeStatsUnchanged"] is True
    assert entry["rawStat"]["st_atime_ns"] != next(
        row for row in raw["before"]["entries"] if row["path"] == "workspace/a.md"
    )["rawStat"]["st_atime_ns"]


@pytest.mark.parametrize("field", ["bytesBase64", "rawStat", "openedStat"])
def test_raw_content_or_identity_tampering_cannot_retain_an_unchanged_public_result(tmp_path, field):
    base = _roots(tmp_path)
    (base / "workspace/a.md").write_bytes(b"a")
    raw = _pair(base)
    observed = derive_get_filesystem_observation(raw)
    file = next(entry for entry in raw["after"]["entries"] if entry["path"] == "workspace/a.md")
    if field == "bytesBase64":
        file[field] = "Yg=="
    else:
        file[field]["st_ino"] = "0"
    with pytest.raises(ValueError):
        validate_get_filesystem_observation(raw, observed, str(base))


def test_sdk_matrix_preserves_raw_envelopes_arguments_and_owned_trees(tmp_path):
    for case in build_storage_path_contract_cases():
        evidence = tmp_path / case["id"]
        result = run_get_contract(case["input"], evidence_directory=evidence)
        raw = json.loads((evidence / "python-raw.json").read_text())
        validate_python_get_filesystem_evidence(raw, case["input"], result)
        unchanged = case["input"].get("readRace") is None
        assert result["filesystem"]["contentUnchanged"] is unchanged
        assert result["filesystem"]["writeStatsUnchanged"] is unchanged
        if len(raw) > 1:
            altered = deepcopy(raw)
            altered[0]["params"] = {"path": "repaired.md"}
            with pytest.raises(ValueError, match="arguments"):
                validate_python_get_filesystem_evidence(altered, case["input"], result)


def test_omitting_even_read_side_effect_stat_fields_cannot_retain_snapshot_authority(tmp_path):
    base = _roots(tmp_path)
    raw = _pair(base)
    observed = derive_get_filesystem_observation(raw)
    del raw["after"]["entries"][0]["rawStat"]["st_atime_ns"]
    with pytest.raises(ValueError, match="Every actual Python stat"):
        validate_get_filesystem_observation(raw, observed, str(base))


@pytest.mark.parametrize("tamper", ["events", "environment", "target", "snapshot-identity"])
def test_real_race_mutation_cannot_lose_dispatch_environment_or_snapshot_identity(tmp_path, tamper):
    from equivalence.get_read_race_profile import build_storage_path_read_race_cases

    case = build_storage_path_read_race_cases()[0]
    public = run_get_contract(case["input"], evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())
    validate_python_get_filesystem_evidence(raw, case["input"], public)
    record = raw[-1]
    if tamper == "events":
        record["readRace"]["events"] = ["arm", "disarm"]
    elif tamper == "environment":
        record["readRace"]["environment"]["dispatch"]["VITEST"] = "true"
    elif tamper == "target":
        record["readRace"]["mutation"]["target"] = "/unowned/secret.md"
    else:
        entry = next(row for row in record["filesystem"]["before"]["entries"]
                     if row["path"] == "workspace/memory/race.md")
        entry["rawStat"]["st_ino"] = entry["openedStat"]["st_ino"] = "0"
    with pytest.raises(ValueError):
        validate_python_get_filesystem_evidence(raw, case["input"], public)
