"""Real SDK process and wire guards; these cases still have no acceptance credit."""
import hashlib
import json
import os
import pytest

from equivalence.bootstrap_discovery_bindings import TEMPLATE_ARTIFACTS
from equivalence.bootstrap_discovery_fixtures import build_bootstrap_discovery_cases
from equivalence.bootstrap_discovery_sdk import ROOT, _error, _phase, run_bootstrap_discovery


@pytest.fixture(scope="module")
def captures(tmp_path_factory):
    directory = tmp_path_factory.mktemp("bootstrap-sdk-cases")
    result = {}
    for case in build_bootstrap_discovery_cases():
        evidence = directory / case["id"]
        public = run_bootstrap_discovery(case["input"], evidence_directory=evidence)
        raw, = json.loads((evidence / "python-raw.json").read_text())
        result[case["id"].removeprefix("bootstrap-discovery-")] = (case, public, raw)
    return result


def _observation(captures, suffix):
    return captures[suffix][2]["child"]["observation"]["raw"]


def test_fixed_literal_packet_has_no_expected_outputs_or_coverage_credit():
    cases = build_bootstrap_discovery_cases()
    assert len(cases) == 11 and len({case["id"] for case in cases}) == 11
    for case in cases:
        assert set(case) == {"id", "operation", "input", "covers", "requirement"}
        assert case["covers"] == [] and case["operation"] == "bootstrap-discovery-runtime"
        assert case["requirement"] == "prompt.bootstrap-discovery"
        assert not any("setup" in step for step in case["input"]["steps"])
        for name, artifact in TEMPLATE_ARTIFACTS.items():
            raw = case["input"]["packagedTemplates"][name].encode()
            assert len(raw) == artifact["bytes"] and hashlib.sha256(raw).hexdigest() == artifact["sha256"]
    cases[0]["input"]["packagedTemplates"]["USER.md"] = "changed"
    assert build_bootstrap_discovery_cases()[0]["input"]["packagedTemplates"]["USER.md"] != "changed"


def test_every_real_case_has_a_distinct_successfully_exited_sdk_process(captures):
    pids = set()
    for case, public, raw in captures.values():
        child = raw["child"]
        observation = child["observation"]["raw"]
        assert child["pid"] != os.getpid() and child["pid"] == observation["pid"]
        assert observation["ppid"] == raw["coordinatorPid"] == os.getpid()
        assert observation["implementationRoot"] == str(ROOT)
        assert child["exit"] == {"code": 0, "signal": None}
        assert child["request"]["input"] == observation["input"] == case["input"]
        assert hashlib.sha256(child["requestJson"].encode()).hexdigest() == child["requestSha256"]
        assert json.loads(child["stdout"]) == child["observation"]
        assert child["environmentKeys"] == ["LANG", "PATH", "PYTHONPATH", "TZ"]
        assert set(observation["environmentKeys"]) <= {"LANG", "PATH", "PYTHONPATH", "TZ", "LC_CTYPE"}
        assert public["provider"] == "none"
        assert len(public["steps"]) == len(case["input"]["steps"])
        pids.add(child["pid"])
    assert len(pids) == 11


def test_supported_ensure_and_state_use_complete_real_sdk_returns(captures):
    _, public, _ = captures["initial-whole-exports"]
    observation = _observation(captures, "initial-whole-exports")
    ensures = [call for call in observation["calls"] if call["owner"] == "initialize_agent_workspace"]
    assert len(ensures) == 3
    assert all(call["result"]["type"] == "WorkspaceInitResult" for call in ensures)
    assert set(ensures[0]["result"]["fields"]) == {
        "root", "created_files", "created_dirs", "bootstrap_seeded", "bootstrap_removed", "state", "bootstrap_status"}
    assert public["steps"][0]["ensure"] == {"bootstrapPending": ensures[0]["result"]["fields"]["bootstrap_status"] == "pending"}
    assert observation["stateFormat"] == "memory-core-workspace-state-json"
    state_file = next(row for row in observation["snapshots"][-1]["workspace"] if row["path"] == ".memory-core/workspace-state.json")
    state = json.loads(bytes.fromhex(state_file["bytes"]["hex"]))
    assert state["setupCompletedAt"] and state["bootstrapSeededAt"]
    assert public["steps"][-1]["setupCompleted"] is True
    assert public["steps"][-1]["loaded"][1]["name"] == "SOUL.md"
    assert public["steps"][-1]["loaded"][1] == {"name": "SOUL.md", "path": "$FIXTURE/workspace/SOUL.md", "missing": True}


def test_same_session_read_runs_real_loader_again_after_each_mutation(captures):
    _, public, _ = captures["same-session-repeat-after-write"]
    first, second, third = public["steps"]
    assert first["runs"][0]["request"]["sessionKey"] == second["runs"][0]["request"]["sessionKey"] == third["runs"][0]["request"]["sessionKey"]
    assert first["runs"][0]["files"][0]["content"] == "# Agent version A\n"
    assert second["runs"][0]["files"][0]["content"] == "# Agent version B\n"
    assert "USER.md" not in [file["name"] for file in third["runs"][0]["files"]]
    assert "MEMORY.md" in [file["name"] for file in third["runs"][0]["files"]]
    assert "MEMORY.md" not in [file["name"] for file in third["runs"][1]["files"]]
    calls = _observation(captures, "same-session-repeat-after-write")["calls"]
    assert len([call for call in calls if call["owner"] == "load_workspace_bootstrap_files"]) == 7
    assert len([call for call in calls if call["owner"] == "filter_bootstrap_files"]) == 4


def test_default_layout_extension_and_created_directories_are_never_dropped(captures):
    _, public, _ = captures["memory-core-layout-extension"]
    loaded = public["steps"][0]["loaded"]
    assert "PROACTIVE_PREFERENCES.md" in [file["name"] for file in loaded]
    observation = _observation(captures, "memory-core-layout-extension")
    ensured = next(call for call in observation["calls"] if call["owner"] == "initialize_agent_workspace")
    assert ensured["result"]["fields"]["created_dirs"] == ["user", "workspace"]
    assert {row["path"] for row in observation["snapshots"][0]["workspace"] if row["kind"] == "directory"} >= {"user", "workspace"}


@pytest.mark.parametrize("suffix,keyword,owner", [
    ("unsupported-purpose", "purpose", "initialize_agent_workspace"),
    ("unsupported-runtime-managed-provisioning", "provisioning", "initialize_agent_workspace"),
    ("unsupported-ensure-bootstrap-false", "ensureBootstrapFiles", "initialize_agent_workspace"),
    ("unsupported-configured-classification", "config", "filter_bootstrap_files"),
])
def test_unsupported_intents_execute_the_real_sdk_signature(captures, suffix, keyword, owner):
    observation = _observation(captures, suffix)
    call = next(call for call in observation["calls"] if call["owner"] == owner and "error" in call)
    assert call["error"]["name"] == "TypeError"
    assert keyword in call["error"]["message"] and "unexpected keyword argument" in call["error"]["message"]
    assert "traceback" in call["error"] and "args" in call["error"]
    assert keyword in call["request"]
    assert "seed_bootstrap" not in call["request"]


def test_guarded_io_keeps_complete_bytes_inode_link_and_unreadable_metadata(captures):
    _, public, _ = captures["guarded-available-file-reads"]
    observation = _observation(captures, "guarded-available-file-reads")
    rows = {row["path"]: row for row in observation["snapshots"][0]["workspace"]}
    assert set(rows) == set(observation["snapshots"][0]["workspaceEntries"])
    assert rows["AGENTS.md"]["stat"]["fields"]["st_nlink"] == 2
    assert rows["SOUL.md"]["kind"] == "directory"
    assert rows["IDENTITY.md"]["kind"] == rows["USER.md"]["kind"] == "symlink"
    assert rows["USER.md"]["target"].startswith(observation["fixtureBase"] + "/outside/")
    assert len(bytes.fromhex(rows["MEMORY.md"]["bytes"]["hex"])) == 2097153
    assert bytes.fromhex(rows["BOOTSTRAP.md"]["bytes"]["hex"]) == bytes([35, 32, 66, 111, 111, 116, 10, 255, 192, 175, 237, 160, 128])
    raw_loaded = next(call for call in observation["calls"] if call["owner"] == "load_workspace_bootstrap_files")["result"]
    assert all(item["fields"]["unreadable_reason"] for item in raw_loaded if item["fields"]["name"] != "BOOTSTRAP.md")
    assert set(raw_loaded[0]["fields"]) == {"name", "path", "content", "missing", "unreadable_reason", "personal_user"}
    assert observation["snapshots"][0]["outside"][0]["bytes"]["hex"]
    assert "\ufffd" in next(file["content"] for file in public["steps"][0]["loaded"] if file["name"] == "BOOTSTRAP.md")


def test_child_never_inherits_provider_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-never-forwarded")
    case = build_bootstrap_discovery_cases()[1]
    run_bootstrap_discovery(case["input"], evidence_directory=tmp_path)
    text = (tmp_path / "python-raw.json").read_text()
    raw, = json.loads(text)
    assert "OPENROUTER_API_KEY" not in raw["child"]["observation"]["raw"]["environmentKeys"]
    assert "fixture-never-forwarded" not in text


def test_child_rejects_extra_state_mutation_or_wrong_registry_inputs(tmp_path):
    case = build_bootstrap_discovery_cases()[0]
    with pytest.raises(ValueError, match="only its owned root"):
        _phase({"directory": str(tmp_path), "input": case["input"], "fakeFiles": []})
    case["input"]["steps"][0]["setup"] = {"version": 1}
    with pytest.raises(ValueError, match="private setup-state"):
        _phase({"directory": str(tmp_path), "input": case["input"]})


def test_fatal_errors_keep_nested_actual_cause_traceback_and_os_properties():
    try:
        try:
            raise OSError(5, "actual fixture IO failure", "/owned/fixture")
        except OSError as cause:
            raise RuntimeError("actual outer failure") from cause
    except RuntimeError as error:
        raw = _error(error, raw=True)
        public = _error(error)
    assert raw["cause"]["errno"] == 5 and raw["cause"]["filename"] == "/owned/fixture"
    assert "OSError" in raw["cause"]["traceback"]
    assert "traceback" not in public and "traceback" not in public["cause"]
    assert public["cause"]["message"] == raw["cause"]["message"]
