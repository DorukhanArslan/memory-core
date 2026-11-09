"""Real managed hosts and adversarial bootstrap/close observation guards."""
from copy import deepcopy
import json

import pytest

from equivalence.host_restart_managed import build_cases
from equivalence.host_restart_managed_evidence import validate_capture
from equivalence.host_restart_sdk import run_host_restart


@pytest.fixture(scope="module")
def captures(tmp_path_factory):
    root = tmp_path_factory.mktemp("real-managed-hosts")
    rows = []
    for case in build_cases():
        directory = root / case["id"]
        result = run_host_restart(case["input"], evidence_directory=directory)
        raw = json.loads((directory / "python-raw.json").read_text())[0]
        rows.append((case, raw, result))
    return rows


@pytest.mark.parametrize("index", range(4))
def test_real_managed_bootstrap_and_physical_close(captures, index):
    case, raw, result = captures[index]
    evidence = validate_capture(case, raw, result, native=False)
    assert evidence["managedColdBootstrapCustodyPassed"]
    assert evidence["acceptancePointsAwarded"] == 0


@pytest.mark.parametrize("attack", ["eager-repair", "no-repair", "wrong-parent", "force-false", "fake-revision", "lost-journal", "active-close", "unclosed"])
def test_rejects_self_consistent_fake_bootstrap_or_close(captures, attack):
    case, original, result = captures[0]
    raw = deepcopy(original)
    phase = raw["phases"][1]["observation"]["raw"]
    opened = phase["opens"][1]
    call = phase["turns"][1]["toolCalls"][0]
    after = call["managedLifecycleAfter"]
    repair = after["repairs"][-1]
    publication = next(operation for operation in after["operations"] if operation["name"] == "reindex")
    if attack == "eager-repair":
        opened["managedStatusAfterOpen"]["custom"]["indexIdentity"] = {"status": "valid"}
    elif attack == "no-repair":
        after["repairCount"] = call["managedLifecycleBefore"]["repairCount"]
    elif attack == "wrong-parent":
        repair["searchOperationId"] = publication["id"]
    elif attack == "force-false":
        publication["request"]["force"] = False
    elif attack == "fake-revision":
        publication["revisionAfter"] = publication["revisionBefore"]
    elif attack == "lost-journal":
        after["operationJournalTruncated"] = True
    elif attack == "active-close":
        phase["closeReceipts"][1]["after"]["activeOperations"] = 1
    elif attack == "unclosed":
        phase["closeReceipts"][1]["after"]["closed"] = False
    for child in raw["phases"]:
        child["stdout"] = json.dumps(child["observation"], ensure_ascii=False)
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=False)
