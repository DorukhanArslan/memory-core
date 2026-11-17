from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from equivalence.automation_job_dreaming import run_sdk, validate_raw
from equivalence.automation_job_dreaming_inputs import dreaming_input
from memory_core.automation import FileAutomationStore
from memory_core.consolidation.dreaming_automation import KEY, repair_dreaming_jobs


def test_preview_of_absent_store_leaves_workspace_empty(tmp_path):
    store = FileAutomationStore(tmp_path)
    assert repair_dreaming_jobs(store, {}, preview=True) is None
    assert list(tmp_path.iterdir()) == []


def test_invalid_managed_rows_survive_disabled_repair(tmp_path):
    store = FileAutomationStore(tmp_path)
    light = dreaming_input()["scenarios"][-1]["jobs"][0]
    invalid = {**light, "id": "invalid", "declarationKey": KEY, "state": {"nextRunAtMs": -1}}
    rows = [None, light, invalid]
    store.path.parent.mkdir()
    store.path.write_text(json.dumps({"version": 1, "scratch": {}, "jobs": rows}))
    result = repair_dreaming_jobs(store, {"dreaming": {"enabled": False}})
    assert len(result["changes"]) == 1
    assert any("invalid persisted job" in warning for warning in result["warnings"])
    assert json.loads(store.path.read_bytes())["jobs"] == [None, invalid]


def test_relocated_dreaming_backup_preserves_identity_and_rejects_tampering(tmp_path):
    case = {"input": dreaming_input()}
    recorded, retained = tmp_path / "original", tmp_path / "retained"
    output = run_sdk(case, recorded)
    [raw] = json.loads((recorded / "python-raw.json").read_bytes())
    shutil.move(recorded, retained)
    validate_raw(case, raw, output, original=False, recorded_directory=recorded, retained_directory=retained)

    bad = deepcopy(raw)
    bad["scenarios"][0]["store"] = str(tmp_path / "outside.json")
    with pytest.raises(ValueError):
        validate_raw(case, bad, output, original=False, recorded_directory=recorded, retained_directory=retained)

    backups = raw["scenarios"][-1]["backupSha256"]
    [original_file] = backups
    backup = retained / Path(original_file).relative_to(recorded)
    backup.write_bytes(backup.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed since capture"):
        validate_raw(case, raw, output, original=False, recorded_directory=recorded, retained_directory=retained)
