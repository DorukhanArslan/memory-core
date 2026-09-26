"""Lab backend contract tests (DESIGN §4): shapes, guards, events and honesty labels.

Every test builds its own :class:`LabRuntime` under ``tmp_path``; no network, no
keys from ``.env`` (the env names are blanked), deterministic stub engines.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import demo.app as demo_app
from demo.app import SHELL_CONTENT_SECURITY_POLICY, create_app
from demo.lab_runtime import LAB_WORKSPACE_DIRNAME, LabRuntime
from demo.parity_results import build_parity_results, classify_test_source
from demo.workspace_context import DEMO_WORKSPACE_TEMPLATES

KEY_ENV_NAMES = (
    "MEMORY_CORE_DEMO_OPENAI_API_KEY",
    "MEMORY_CORE_DEMO_OPENAI_BASE_URL",
    "MEMORY_CORE_DEMO_OPENAI_MODEL",
    "MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY",
    "MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL",
    "MEMORY_CORE_DEMO_OPENAI_EMBEDDING_MODEL",
)


@pytest.fixture(autouse=True)
def _no_provider_env(monkeypatch):
    for name in KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def lab(tmp_path: Path) -> LabRuntime:
    return LabRuntime(tmp_path)


@pytest.fixture
def client(lab: LabRuntime) -> TestClient:
    return TestClient(create_app(lab))


def parse_sse(body: str) -> list[dict]:
    frames = []
    for block in body.strip().split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        event = "message"
        data_lines = []
        event_id = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))
            elif line.startswith("id: "):
                event_id = int(line.removeprefix("id: "))
        frames.append({"event": event, "id": event_id, "data": json.loads("\n".join(data_lines))})
    return frames


def event_types(client: TestClient, since: int = 0) -> list[str]:
    response = client.get("/api/lab/events", params={"once": "true"}, headers={"Last-Event-ID": str(since)})
    return [frame["data"]["type"] for frame in parse_sse(response.text)]


# --- shell and structure ------------------------------------------------------------------


def test_shell_route_sets_the_content_security_policy(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == SHELL_CONTENT_SECURITY_POLICY
    assert "script-src 'self'" in SHELL_CONTENT_SECURITY_POLICY
    assert "frame-ancestors 'none'" in SHELL_CONTENT_SECURITY_POLICY


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/memory-system"),
        ("get", "/api/chat/state"),
        ("post", "/api/chat/reset"),
        ("post", "/api/chat/send"),
        ("post", "/api/chat/send-stream"),
    ],
)
def test_removed_endpoints_are_gone(client, method, path):
    response = getattr(client, method)(path, **({"json": {}} if method == "post" else {}))

    assert response.status_code in {404, 405}


def test_module_app_uses_the_renamed_temp_workspace():
    lab = demo_app.app.state.lab

    assert lab.root.name == LAB_WORKSPACE_DIRNAME == "memory-core-lab-workspace"
    assert lab.root.parent == Path(os.environ.get("TMPDIR", "/tmp")).resolve() or lab.root.is_absolute()
    assert "memory-core" not in str(lab.root)


def test_endpoint_calls_never_create_a_repo_demo_workspace(client):
    client.get("/api/lab/state")
    client.get("/api/lab/files")

    assert not (demo_app.PROJECT_ROOT / "demo" / "workspace").exists()


def test_state_snapshot_shape(client, lab):
    snapshot = client.get("/api/lab/state").json()

    assert snapshot["workspace"] == {
        "root": str(lab.root),
        "layout": "memory-core",
        "layoutName": "memory-core",
        "exists": True,
    }
    assert snapshot["timezone"] == "Europe/Istanbul"
    assert snapshot["bootstrap"]["status"] == "complete"
    assert snapshot["session"]["kind"] == "main"
    assert snapshot["session"]["key"].startswith("lab:main:")
    assert snapshot["identityName"] == "memory-core"
    assert snapshot["turns"] == []
    assert isinstance(snapshot["lastEventId"], int)
    assert snapshot["layoutOrder"]["loadOrder"][0] == "AGENTS.md"


def test_invalid_session_kind_is_rejected(client):
    response = client.get("/api/lab/state", params={"sessionKind": "../main"})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_kind"


# --- workspace reset and seeding ------------------------------------------------------------


def test_seeded_reset_writes_only_the_lab_templates(client, lab):
    client.post("/api/lab/workspace/reset", json={"mode": "seeded"})

    for name, template in DEMO_WORKSPACE_TEMPLATES.items():
        path = lab.root / name
        if name == "BOOTSTRAP.md":
            assert not path.exists()  # setup evidence (memory/) completes the ritual
            continue
        assert path.read_text(encoding="utf-8") == template
    assert not (lab.root / "MEMORY.md").exists()
    assert (lab.root / "memory").is_dir()
    assert list((lab.root / "memory").iterdir()) == []
    assert (lab.root / "PROACTIVE_PREFERENCES.md").read_text(encoding="utf-8") == ""


def test_fresh_reset_leaves_the_bootstrap_ritual_pending(client, lab):
    snapshot = client.post("/api/lab/workspace/reset", json={"mode": "fresh"}).json()

    assert snapshot["bootstrap"]["status"] == "pending"
    assert (lab.root / "BOOTSTRAP.md").read_text(encoding="utf-8") == DEMO_WORKSPACE_TEMPLATES["BOOTSTRAP.md"]
    entries = {entry["path"]: entry for entry in client.get("/api/lab/files").json()}
    assert "pending" in entries["BOOTSTRAP.md"]["badges"]
    assert "injected" in entries["BOOTSTRAP.md"]["badges"]
    assert "memory" not in entries


def test_reset_with_keep_memory_keeps_memory_files(client, lab):
    client.post("/api/lab/workspace/reset", json={"mode": "seeded"})
    (lab.root / "MEMORY.md").write_text("# Memory\n\n- kept fact\n", encoding="utf-8")
    (lab.root / "memory" / "2026-09-25.md").write_text("- kept note\n", encoding="utf-8")
    (lab.root / "USER.md").write_text("changed\n", encoding="utf-8")

    client.post("/api/lab/workspace/reset", json={"mode": "fresh", "keepMemory": True})

    assert (lab.root / "MEMORY.md").read_text(encoding="utf-8") == "# Memory\n\n- kept fact\n"
    assert (lab.root / "memory" / "2026-09-25.md").exists()
    assert (lab.root / "USER.md").read_text(encoding="utf-8") == DEMO_WORKSPACE_TEMPLATES["USER.md"]
    assert not (lab.root / "BOOTSTRAP.md").exists()


def test_invalid_reset_mode_is_rejected(client):
    response = client.post("/api/lab/workspace/reset", json={"mode": "everything"})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_mode"


def test_kept_seed_endpoint_wraps_the_seeded_reset(client, lab):
    assert client.post("/api/seed").json() == {"ok": True}
    assert (lab.root / "memory").is_dir()
    assert not (lab.root / "MEMORY.md").exists()


# --- explorer entries ----------------------------------------------------------------------


def test_files_report_badges_from_the_workspace_context(client, lab):
    client.get("/api/lab/state")
    (lab.root / "notes.txt").write_text("outside\n", encoding="utf-8")
    (lab.root / "memory" / f"{lab.today()}.md").write_text("- today\n", encoding="utf-8")
    (lab.root / "memory" / f"{lab.today()}-1210.md").write_text("# Session\n", encoding="utf-8")

    entries = {entry["path"]: entry for entry in client.get("/api/lab/files").json()}

    assert entries["AGENTS.md"]["badges"] == ["injected"]
    assert entries["AGENTS.md"]["loadIndex"] == 1
    assert entries["AGENTS.md"]["renderIndex"] == 1
    assert entries["HEARTBEAT.md"]["badges"] == ["injected", "dynamic"]
    assert entries["PROACTIVE_PREFERENCES.md"]["badges"] == ["extension", "empty"]
    assert entries["MEMORY.md"]["badges"] == ["absent"]
    assert entries["notes.txt"]["badges"] == ["outside_layout"]
    assert entries[f"memory/{lab.today()}.md"]["badges"] == ["today"]
    assert entries[f"memory/{lab.today()}-1210.md"]["kind"] == "memory_session"
    assert "BOOTSTRAP.md" not in entries
    assert entries["USER.md"]["sha256"] and entries["USER.md"]["chars"] > 0


def test_files_follow_the_session_kind_filter(client):
    client.get("/api/lab/state")

    entries = {entry["path"]: entry for entry in client.get("/api/lab/files", params={"sessionKind": "subagent"}).json()}

    assert entries["AGENTS.md"]["badges"] == ["injected"]
    assert "excluded" in entries["USER.md"]["badges"]
    assert entries["USER.md"]["excludedReason"] == "subagent: yalnız AGENTS.md, TOOLS.md"


def test_files_with_the_pin_layout_mark_extensions_outside_the_layout(client):
    client.get("/api/lab/state")

    entries = {entry["path"]: entry for entry in client.get("/api/lab/files", params={"layout": "pin"}).json()}

    assert entries["PROACTIVE_PREFERENCES.md"]["badges"] == ["outside_layout"]
    assert entries["user"]["badges"] == ["outside_layout"]


def test_files_reject_an_unknown_layout(client):
    response = client.get("/api/lab/files", params={"layout": "other"})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_layout"


# --- guarded file reads and writes ----------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("../outside.md", "outside_root"),
        ("memory/../../outside.md", "outside_root"),
        ("/etc/passwd", "outside_root"),
        ("memory\\2026-09-26.md", "invalid_path"),
        ("", "invalid_path"),
        ("./USER.md", "outside_root"),
    ],
)
def test_file_read_rejects_paths_outside_the_root(client, path, code):
    client.get("/api/lab/state")

    response = client.get("/api/lab/file", params={"path": path})

    assert response.status_code == 400
    assert response.json()["code"] == code


def test_file_read_and_write_reject_symlinks(client, lab, tmp_path):
    client.get("/api/lab/state")
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n", encoding="utf-8")
    (lab.root / "linked.md").symlink_to(outside)
    (lab.root / "memory" / "linkdir").symlink_to(tmp_path, target_is_directory=True)

    read = client.get("/api/lab/file", params={"path": "linked.md"})
    via_dir = client.get("/api/lab/file", params={"path": "memory/linkdir/outside.md"})
    write = client.put(
        "/api/lab/file",
        json={"path": "memory/linkdir/outside.md", "content": "x", "baseSha256": None},
    )

    assert read.status_code == via_dir.status_code == write.status_code == 400
    assert {read.json()["code"], via_dir.json()["code"], write.json()["code"]} == {"symlink"}
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_file_read_reports_missing_files_and_directories(client):
    client.get("/api/lab/state")

    missing = client.get("/api/lab/file", params={"path": "memory/2020-01-01.md"})
    directory = client.get("/api/lab/file", params={"path": "memory"})

    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    assert directory.status_code == 400 and directory.json()["code"] == "not_a_file"


def test_file_read_shape(client, lab):
    client.get("/api/lab/state")

    payload = client.get("/api/lab/file", params={"path": "USER.md"}).json()

    assert payload["path"] == "USER.md"
    assert payload["content"] == DEMO_WORKSPACE_TEMPLATES["USER.md"]
    assert len(payload["sha256"]) == 64
    assert payload["chars"] == len(DEMO_WORKSPACE_TEMPLATES["USER.md"])
    assert payload["writable"] is True
    assert "readOnlyReason" not in payload


def test_hidden_and_outside_layout_files_are_read_only(client, lab):
    client.get("/api/lab/state")
    (lab.root / "notes.txt").write_text("x\n", encoding="utf-8")

    notes = client.get("/api/lab/file", params={"path": "notes.txt"}).json()
    write = client.put("/api/lab/file", json={"path": "notes.txt", "content": "y", "baseSha256": notes["sha256"]})
    hidden = client.put("/api/lab/file", json={"path": ".memory-core/x.json", "content": "{}", "baseSha256": None})

    assert notes["writable"] is False and notes["readOnlyReason"]
    assert write.status_code == 403 and write.json()["code"] == "read_only"
    assert hidden.status_code == 403


def test_stale_base_sha_returns_409_with_the_current_content(client, lab):
    client.get("/api/lab/state")
    current = client.get("/api/lab/file", params={"path": "USER.md"}).json()
    (lab.root / "USER.md").write_text("changed on disk\n", encoding="utf-8")

    response = client.put(
        "/api/lab/file",
        json={"path": "USER.md", "content": "mine\n", "baseSha256": current["sha256"]},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "conflict"
    assert body["current"]["content"] == "changed on disk\n"
    assert len(body["current"]["sha256"]) == 64
    assert (lab.root / "USER.md").read_text(encoding="utf-8") == "changed on disk\n"


def test_save_returns_the_diff_and_its_events(client, lab):
    client.get("/api/lab/state")
    current = client.get("/api/lab/file", params={"path": "USER.md"}).json()

    response = client.put(
        "/api/lab/file",
        json={"path": "USER.md", "content": current["content"] + "- Prefer short answers.\n",
              "baseSha256": current["sha256"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert "+- Prefer short answers." in body["diff"]
    assert [event["type"] for event in body["events"]][:2] == ["file.changed", "file.saved"]
    assert body["events"][0]["data"]["source"] == "editor"
    assert body["sha256"] != current["sha256"]


def test_save_creates_a_new_memory_file_only_without_a_base(client, lab):
    client.get("/api/lab/state")

    created = client.put("/api/lab/file", json={"path": "memory/notes/topic.md", "content": "- a\n", "baseSha256": None})
    again = client.put("/api/lab/file", json={"path": "memory/notes/topic.md", "content": "- b\n", "baseSha256": None})

    assert created.status_code == 200
    assert again.status_code == 409
    assert (lab.root / "memory" / "notes" / "topic.md").read_text(encoding="utf-8") == "- a\n"


def test_identity_edit_completes_bootstrap_in_upstream_event_order(client, lab):
    client.post("/api/lab/workspace/reset", json={"mode": "fresh"})
    start = client.get("/api/lab/state").json()["lastEventId"]
    identity = client.get("/api/lab/file", params={"path": "IDENTITY.md"}).json()

    response = client.put(
        "/api/lab/file",
        json={
            "path": "IDENTITY.md",
            "content": identity["content"].replace(
                "Vibe: pragmatic memory lab assistant", "Vibe: kısa ve net test asistanı"
            ),
            "baseSha256": identity["sha256"],
        },
    )

    assert response.status_code == 200
    types = event_types(client, start)
    ordered = [t for t in types if t in {"file.saved", "bootstrap.completed", "bootstrap.file_deleted"}]
    assert ordered == ["file.saved", "bootstrap.completed", "bootstrap.file_deleted"]
    assert not (lab.root / "BOOTSTRAP.md").exists()
    assert client.get("/api/lab/state").json()["bootstrap"]["status"] == "complete"
    deleted = [
        change for change in client.get("/api/lab/diff", params={"since": "reset"}).json()
        if change["path"] == "BOOTSTRAP.md"
    ]
    assert deleted[0]["status"] == "deleted"
    assert deleted[0]["sources"][0]["source"] == "lifecycle"


def test_diff_preview_reports_the_budget_impact(client, lab):
    client.get("/api/lab/state")

    response = client.post(
        "/api/lab/file/diff-preview", json={"path": "SOUL.md", "content": "x" * 25_000}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["charsAfter"] == 25_000
    assert body["budget"] == {"maxChars": 20_000, "wouldTruncate": True, "injectedAfter": body["budget"]["injectedAfter"], "rawAfter": 25_000}
    assert body["budget"]["injectedAfter"] <= 20_000
    assert body["diff"].startswith("--- a/SOUL.md")


# --- diffs, marks and reverts -----------------------------------------------------------------


def test_diff_mark_and_revert_restore_the_baseline(client, lab):
    client.get("/api/lab/state")
    mark = client.post("/api/lab/diff/mark").json()["markId"]
    current = client.get("/api/lab/file", params={"path": "SOUL.md"}).json()
    client.put("/api/lab/file", json={"path": "SOUL.md", "content": "new soul\n", "baseSha256": current["sha256"]})
    client.put("/api/lab/file", json={"path": "memory/extra.md", "content": "- x\n", "baseSha256": None})

    changes = {change["path"]: change for change in client.get("/api/lab/diff", params={"since": f"mark:{mark}"}).json()}
    reverted = client.post("/api/lab/diff/revert", json={"path": "SOUL.md", "since": f"mark:{mark}"})
    removed = client.post("/api/lab/diff/revert", json={"path": "memory/extra.md", "since": f"mark:{mark}"})

    assert changes["SOUL.md"]["status"] == "modified"
    assert changes["memory/extra.md"]["status"] == "added"
    assert changes["SOUL.md"]["sources"][0]["source"] == "editor"
    assert reverted.status_code == removed.status_code == 200
    assert (lab.root / "SOUL.md").read_text(encoding="utf-8") == current["content"]
    assert not (lab.root / "memory" / "extra.md").exists()
    assert client.get("/api/lab/diff", params={"since": f"mark:{mark}"}).json() == []


@pytest.mark.parametrize("since", ["", "turn:abc", "mark:../x", "yesterday"])
def test_diff_rejects_invalid_baselines(client, since):
    client.get("/api/lab/state")

    response = client.get("/api/lab/diff", params={"since": since})

    assert response.status_code == 400


def test_diff_reports_a_missing_baseline(client):
    client.get("/api/lab/state")

    response = client.get("/api/lab/diff", params={"since": "turn:99"})

    assert response.status_code == 404
    assert response.json()["code"] == "no_baseline"


def test_turn_detail_validates_the_id(client):
    assert client.get("/api/lab/turns/abc").status_code == 400
    assert client.get("/api/lab/turns/7").status_code == 404


# --- event stream ------------------------------------------------------------------------------


def test_event_stream_resumes_after_last_event_id(client):
    client.post("/api/lab/workspace/reset", json={"mode": "seeded"})
    everything = parse_sse(client.get("/api/lab/events", params={"once": "true"}).text)
    middle = everything[len(everything) // 2]["id"]

    resumed = parse_sse(
        client.get("/api/lab/events", params={"once": "true"}, headers={"Last-Event-ID": str(middle)}).text
    )

    assert [frame["id"] for frame in resumed] == [frame["id"] for frame in everything if frame["id"] > middle]
    assert all(frame["event"] == "message" for frame in resumed)
    first = everything[0]["data"]
    assert set(first) >= {"id", "ts", "type", "category", "summary", "data"}


def test_event_stream_reports_a_gap_older_than_the_ring(lab):
    for index in range(1_100):
        lab.bus.emit("lab.test", summary=str(index))
    client = TestClient(create_app(lab))

    frames = parse_sse(
        client.get("/api/lab/events", params={"once": "true"}, headers={"Last-Event-ID": "5"}).text
    )

    assert frames[0]["data"]["type"] == "lab.resync"
    assert frames[0]["id"] is None
    assert len(frames) == 1 + 1_000


def test_events_carry_zaman_categories(client):
    client.post("/api/lab/workspace/reset", json={"mode": "fresh"})

    frames = parse_sse(client.get("/api/lab/events", params={"once": "true"}).text)

    categories = {frame["data"]["type"]: frame["data"]["category"] for frame in frames}
    assert categories["file.changed"] == "dosya"
    assert categories["bootstrap.seeded"] == "bootstrap"
    assert categories["workspace.reset"] == "dosya"


# --- parity results ------------------------------------------------------------------------------


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
<testcase classname="tests.integration.test_openclaw_ts_oracle" name="test_real_openclaw_oracle_flush_plan_matches_python_defaults" time="1.5"/>
<testcase classname="tests.integration.test_openclaw_ts_oracle" name="test_real_openclaw_oracle_memory_search_all_balances_memory_and_wiki" time="2.0"/>
<testcase classname="tests.integration.test_openclaw_ts_oracle" name="test_real_openclaw_oracle_parse_heartbeat_tasks_matches_python" time="0.5"><failure message="boom"/></testcase>
<testcase classname="tests.integration.test_memory_tools" name="test_memory_get_reads_line_window[a]" time="0.1"><skipped message="x"/></testcase>
</testsuite></testsuites>
"""


def test_parity_results_split_python_eq_ts_from_ts_literal(tmp_path):
    junit = tmp_path / "oracle.xml"
    junit.write_text(JUNIT, encoding="utf-8")

    results = build_parity_results(junit, commit="abc123", generated_at="2026-09-26T00:00:00Z")

    assert results["commit"] == "abc123"
    assert results["pin"].startswith("4c42815348")
    assert results["totals"] == {"passed": 2, "failed": 1, "skipped": 1}
    by_area = {area["area"]: area for area in results["byArea"]}
    assert by_area["flush"]["evidence"] == {"python_eq_ts": {"passed": 1, "failed": 0, "skipped": 0}}
    assert by_area["memory_search"]["evidence"] == {"ts_literal": {"passed": 1, "failed": 0, "skipped": 0}}
    assert by_area["heartbeat"]["failed"] == 1
    assert by_area["memory_get"]["tests"][0]["nodeid"] == (
        "tests/integration/test_memory_tools.py::test_memory_get_reads_line_window[a]"
    )
    assert by_area["memory_get"]["tests"][0]["evidence"] == "python_literal"
    assert results["durationS"] == 4.1


def test_evidence_classification_reads_local_imports():
    source = '''
from demo.openclaw_oracle import OpenClawOracle

def _oracle():
    return OpenClawOracle(repo_path=None)

def test_direct():
    from memory_core.memory_budget import compact_memory_for_budget
    _oracle().run({})
    compact_memory_for_budget

def test_literal():
    assert _oracle().run({}) == {"ok": True}

def test_python_only():
    from memory_core.flags import FeatureFlags
    FeatureFlags()
'''

    assert classify_test_source(source) == {
        "test_direct": "python_eq_ts",
        "test_literal": "ts_literal",
        "test_python_only": "python_literal",
    }


def test_parity_endpoint_reads_the_results_file_and_the_matrix(client, tmp_path, monkeypatch):
    junit = tmp_path / "oracle.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    out = tmp_path / "parity-results.json"
    out.write_text(json.dumps(build_parity_results(junit, commit="abc")), encoding="utf-8")
    monkeypatch.setenv("MEMORY_CORE_LAB_PARITY_RESULTS", str(out))
    monkeypatch.setenv("OPENCLAW_ORACLE_REPO", str(tmp_path / "no-such-checkout"))

    payload = client.get("/api/lab/parity").json()

    assert payload["results"]["totals"]["passed"] == 2
    assert payload["resultsPath"] == str(out)
    assert payload["oracleRepo"] == {"path": str(tmp_path / "no-such-checkout"), "exists": False, "head": None}
    assert payload["matrix"] and set(payload["matrix"][0]) == {
        "area", "openclawSource", "pythonSource", "oracleOperation", "status", "knownGaps", "nextTest", "priority",
    }
    assert len(payload["commands"]) == 2


def test_parity_endpoint_without_results(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_CORE_LAB_PARITY_RESULTS", str(tmp_path / "missing.json"))

    assert client.get("/api/lab/parity").json()["results"] is None


# --- kept endpoints ------------------------------------------------------------------------------


def test_prompt_preview_endpoint(client):
    response = client.post("/api/prompt-preview", json={"tools": ["memory_search"], "citationsMode": "off"})

    assert response.status_code == 200
    assert response.json()["lines"][0] == "## Memory Recall"


def test_invalid_prompt_preview_payload_returns_json_error(client):
    response = client.post("/api/prompt-preview", json={"tools": "memory_search"})

    assert response.status_code == 400
    assert response.json()["error"] == "tools must be a list"


def test_memory_get_endpoint_reads_workspace_memory(client, lab):
    client.get("/api/lab/state")
    (lab.root / "MEMORY.md").write_text("# Memory\n\n- fact one\n- fact two\n", encoding="utf-8")

    payload = client.post("/api/get", json={"path": "MEMORY.md", "from": 3, "lines": 1}).json()

    assert payload["text"].startswith("- fact one\n")


def test_live_task_rejects_unsafe_ids(client):
    for payload in ({"sessionId": "../../escaped"}, {"subjectId": "a/b"}, {"sessionId": "x" * 65}):
        response = client.post("/api/live-task/reset", json=payload)
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_id"
    turn = client.post("/api/live-task/turn-stream", json={"sessionId": "../x", "message": "Merhaba"})
    summary = client.post("/api/live-task/summary", json={"subjectId": "..", "message": "x"})
    assert turn.status_code == summary.status_code == 400
