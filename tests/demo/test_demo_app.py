"""Lab backend contract tests (DESIGN §4): shapes, guards, events and honesty labels.

Every test builds its own :class:`LabRuntime` under ``tmp_path``; no network, no
keys from ``.env`` (the env names are blanked), deterministic stub engines.
"""

from __future__ import annotations

import json
import re
import tempfile
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


def test_shell_and_static_assets_must_be_revalidated(client):
    # A rebuilt Lab must never run against a stylesheet or module the browser cached earlier.
    for path in ("/", "/static/styles.css", "/static/lab/app.js"):
        response = client.get(path)

        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-cache", path


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
    assert lab.root.parent == Path(tempfile.gettempdir())
    assert lab.live_root.name == "memory-core-live-task-demo-workspace"


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
    assert "HEARTBEAT.md" not in entries and "TOOLS.md" not in entries
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
    assert entries["USER.md"]["excludedReason"] == "subagent: yalnız AGENTS.md"


def test_files_with_the_upstream_layout_mark_extensions_outside_the_layout(client):
    client.get("/api/lab/state")

    entries = {entry["path"]: entry for entry in client.get("/api/lab/files", params={"layout": "upstream"}).json()}

    assert entries["PROACTIVE_PREFERENCES.md"]["badges"] == ["outside_layout"]
    assert entries["user"]["badges"] == ["outside_layout"]


def test_files_name_retired_files_and_unreadable_ones(client, lab):
    client.get("/api/lab/state")
    (lab.root / "TOOLS.md").write_text("## Tools\n- rg\n", encoding="utf-8")
    (lab.root / "HEARTBEAT.md").write_text("- check inbox\n", encoding="utf-8")
    (lab.root / "IDENTITY.md").unlink()
    (lab.root / "IDENTITY.md").symlink_to(lab.root / "SOUL.md")

    entries = {entry["path"]: entry for entry in client.get("/api/lab/files").json()}

    assert entries["TOOLS.md"]["badges"] == ["outside_layout", "retired"]
    assert entries["TOOLS.md"]["migration"] == "tools_md"
    assert "AGENTS.md ## Tools" in entries["TOOLS.md"]["retiredNote"]
    assert entries["HEARTBEAT.md"]["badges"] == ["outside_layout", "retired"]
    assert "migration" not in entries["HEARTBEAT.md"]
    assert "unreadable" in entries["IDENTITY.md"]["badges"]
    assert entries["IDENTITY.md"]["unreadableReason"] == "symlink path component not allowed"


def test_tools_md_migration_endpoint_merges_into_agents_md(client, lab):
    client.get("/api/lab/state")
    agents_before = (lab.root / "AGENTS.md").read_text(encoding="utf-8")
    (lab.root / "TOOLS.md").write_text("- kitchen camera: wide angle\n", encoding="utf-8")

    result = client.post("/api/lab/workspace/migrate-tools-md").json()

    assert result["merged"] is True and result["warnings"] == []
    assert result["archivePath"].startswith(".memory-core/backups/tools-md-migration/main-")
    assert not (lab.root / "TOOLS.md").exists()
    agents = (lab.root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith(agents_before.rstrip("\n"))
    assert agents.endswith(
        "### Local notes (migrated from TOOLS.md)\n\n- kitchen camera: wide angle\n"
    )
    events = [event["type"] for event in lab.bus.recent()]
    assert "workspace.tools_md_migrated" in events
    again = client.post("/api/lab/workspace/migrate-tools-md").json()
    assert again == {"changes": [], "warnings": [], "archivePath": None, "merged": None}


def test_prompt_preview_reports_a_leftover_tools_md_until_it_is_migrated(client, lab):
    # collectToolsMdMigrationFindings: TOOLS.md is not loaded at v2026.9.6, so the inspector
    # names it as a doctor finding instead of dropping it silently.
    client.get("/api/lab/state")
    (lab.root / "TOOLS.md").write_text("- ssh host: build-1\n", encoding="utf-8")

    before = preview(client, sessionKind="main")

    assert "TOOLS.md" not in names(before) and "build-1" not in before["promptText"]
    (finding,) = before["migrationFindings"]
    assert finding["requirement"] == "legacy-tools-md" and finding["severity"] == "warning"
    assert finding["message"] == 'Agent "main" still stores local tool notes in TOOLS.md.'
    assert finding["fixHint"] == "Run memory_core.bootstrap.migrate_tools_md() to merge TOOLS.md into AGENTS.md."
    client.post("/api/lab/workspace/migrate-tools-md")
    after = preview(client, sessionKind="main")
    assert after["migrationFindings"] == []
    assert "build-1" in after["promptText"]


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
    assert results["pin"].startswith("eb377ac59e6")
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
    assert payload["oracleRepo"] == {
        "path": str(tmp_path / "no-such-checkout"), "exists": False, "head": None, "pinned": False,
    }
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


# --- chat turns: the host tool loop -------------------------------------------------------


class StubEngine:
    """Deterministic engine: each round is (content, tool calls); records what it was sent."""

    name = "stub"
    provider = "stub"
    model = "stub-model"

    def __init__(self, rounds, *, usage=None, flush_output=None):
        self.rounds = list(rounds)
        self.calls = []
        self.usage = usage if usage is not None else {"promptTokens": 1_000, "completionTokens": 50, "totalTokens": 1_050}
        self.flush_output = flush_output
        self.flush_calls = []

    def stream_chat(self, messages, *, tools=None):
        self.calls.append({"messages": [dict(message) for message in messages], "tools": tools})
        content, calls = self.rounds.pop(0) if self.rounds else ("done", [])
        if content:
            yield {"type": "delta", "text": content}
        yield {"type": "message", "content": content, "toolCalls": calls, "usage": self.usage,
               "finishReason": "tool_calls" if calls else "stop"}

    def flush(self, *, system_prompt, prompt, transcript, target):
        from demo.chat_engine import FlushModelOutput

        self.flush_calls.append({"system_prompt": system_prompt, "prompt": prompt,
                                 "transcript": transcript, "target": target})
        return self.flush_output(target) if self.flush_output else FlushModelOutput(raw_text="NO_REPLY")


def tool_call(call_id, name, arguments):
    return {"id": call_id, "name": name, "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments)}


def use_engine(monkeypatch, engine):
    import demo.lab_api as lab_api

    monkeypatch.setattr(lab_api, "resolve_chat_engine", lambda lab, payload: engine)
    return engine


def send(client, message="Merhaba", **extra):
    response = client.post("/api/lab/chat/stream", json={"message": message, "sessionKind": "main", **extra})
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


def frames_of(frames, event):
    return [frame["data"] for frame in frames if frame["event"] == event]


def test_chat_without_a_key_fails_with_no_api_key(client):
    response = client.post("/api/lab/chat/stream", json={"message": "Merhaba", "sessionKind": "main"})

    assert response.status_code == 400
    assert response.json()["code"] == "no_api_key"


def test_chat_rejects_an_empty_message_and_an_unknown_kind(client):
    assert client.post("/api/lab/chat/stream", json={"message": " "}).json()["code"] == "invalid_message"
    assert client.post("/api/lab/chat/stream", json={"message": "x", "sessionKind": "boss"}).json()["code"] == "invalid_kind"


def test_scripted_engine_is_explicit_labelled_and_offers_no_tools(client):
    from demo.chat_engine import SCRIPTED_REPLY

    frames = send(client, "Merhaba", engine="scripted")

    done = frames_of(frames, "turn_done")[0]
    assert done["turn"]["engine"] == {"provider": "scripted", "model": "lab-script", "scripted": True}
    assert done["turn"]["assistant"] == SCRIPTED_REPLY
    assert done["detail"]["prompt"]["tools"] == []
    assert frames_of(frames, "tool_call") == []


def test_tool_loop_dispatches_curation_and_memory_tools(client, lab, monkeypatch):
    engine = use_engine(monkeypatch, StubEngine([
        ("", [tool_call("c1", "upsert_user_directive", {"text": "Always answer briefly, in bullet points."}),
              tool_call("c2", "memory_search", {"query": "bullet"})]),
        ("Tamam.", []),
    ]))

    frames = send(client, "Bundan sonra kısa ve madde madde cevap ver.")

    order = [frame["event"] for frame in frames if frame["event"] in {"tool_call", "tool_result", "curation", "assistant_delta", "turn_done"}]
    assert order == ["tool_call", "tool_result", "curation", "tool_call", "tool_result", "assistant_delta", "turn_done"]
    offered = [tool["function"]["name"] for tool in engine.calls[0]["tools"]]
    assert offered[:2] == ["memory_search", "memory_get"]
    assert "upsert_user_directive" in offered and "add_memory_entry" in offered
    assert engine.calls[1]["messages"][-1] == {
        "role": "tool", "tool_call_id": "c2",
        "content": json.dumps({"results": [], "provider": "none", "model": "fts-only", "citations": "on"}),
    }
    assert "- Always answer briefly, in bullet points." in (lab.root / "USER.md").read_text(encoding="utf-8")
    detail = frames_of(frames, "turn_done")[0]["detail"]
    assert [stage["name"] for stage in detail["stages"]] == [
        "ensure", "compaction", "flush_decision", "flush", "reindex", "recall", "prompt", "stream", "persist",
    ]
    assert detail["stages"][1] == {"name": "compaction", "status": "skip", "ms": 0, "detail": "Lab compaction yok (bilinen açık)"}
    assert detail["curation"][0]["kind"] == "user_directive"
    assert detail["curation"][0]["flag"] == "curated_memory_writes"
    assert "before" not in detail["curation"][0]
    assert {"type": "write", "label": "USER.md +1", "target": "USER.md", "source": "curation", "extension": True} in detail["chips"]
    assert [(diff["path"], diff["source"]) for diff in detail["diffs"]] == [("USER.md", "curation")]
    assert "## Memory Recall" in engine.calls[0]["messages"][0]["content"]
    types = event_types(client)
    assert types.index("chat.turn.started") < types.index("curation.written") < types.index("chat.turn.completed")


def test_tool_loop_returns_refusals_and_bad_arguments_to_the_model(client, lab, monkeypatch):
    use_engine(monkeypatch, StubEngine([
        ("", [tool_call("c1", "upsert_user_directive", {"text": "x" * 4_100}),
              tool_call("c2", "memory_get", "{not json"),
              tool_call("c3", "write", {"path": "USER.md"})]),
        ("Olmadı.", []),
    ]))

    frames = send(client, "Uzun bir tercih kaydet.")

    results = {item["id"]: item for item in frames_of(frames, "tool_result")}
    assert results["c1"]["ok"] is False and results["c1"]["result"]["status"] == "error"
    assert results["c1"]["curation"]["refused"] is True
    assert "invalid JSON arguments" in results["c2"]["result"]["error"]
    assert results["c3"]["result"]["error"] == "tool write is not available"
    detail = frames_of(frames, "turn_done")[0]["detail"]
    assert any(chip["type"] == "refused" for chip in detail["chips"])
    assert lab.curated_writes[0]["refused"] is True
    assert "curation.refused" in event_types(client)
    assert (lab.root / "USER.md").read_text(encoding="utf-8") == DEMO_WORKSPACE_TEMPLATES["USER.md"]


def test_tool_loop_is_bounded(client, monkeypatch):
    from demo.lab_tools import MAX_TOOL_ROUNDS

    engine = use_engine(monkeypatch, StubEngine(
        [("", [tool_call(f"c{i}", "memory_search", {"query": "x"})]) for i in range(MAX_TOOL_ROUNDS)] + [("Son.", [])]
    ))

    frames = send(client, "Döngü")

    assert len(engine.calls) == MAX_TOOL_ROUNDS + 1
    assert engine.calls[-1]["tools"] is None
    detail = frames_of(frames, "turn_done")[0]["detail"]
    assert detail["toolLoop"]["capped"] is True
    assert detail["assistant"] == "Son."


def test_curation_flags_gate_the_offered_tools(client, lab, monkeypatch):
    engine = use_engine(monkeypatch, StubEngine([("a", [])], usage={}))
    lab.settings.flags["curation.user_md"] = False
    send(client, "bir")
    offered = [tool["function"]["name"] for tool in engine.calls[0]["tools"]]
    assert "upsert_user_directive" not in offered and "add_memory_entry" in offered

    engine.rounds = [("b", [])]
    lab.settings.flags["curated_memory_writes"] = False
    send(client, "iki")
    offered = [tool["function"]["name"] for tool in engine.calls[1]["tools"]]
    assert offered == ["memory_search", "memory_get"]


def test_memory_search_tool_calls_record_short_term_recalls(client, lab, monkeypatch):
    client.get("/api/lab/state")
    (lab.root / "memory" / f"{lab.today()}.md").write_text("- Redis 7.2 staging upgrade\n", encoding="utf-8")
    use_engine(monkeypatch, StubEngine([("", [tool_call("c1", "memory_search", {"query": "Redis"})]), ("7.2", [])]))

    frames = send(client, "Hangi sürüm?")

    result = frames_of(frames, "tool_result")[0]["result"]
    assert result["results"][0]["path"] == f"memory/{lab.today()}.md"
    store = lab.root / "memory" / ".dreams" / "short-term-recall.json"
    assert "Redis" in store.read_text(encoding="utf-8")


def test_curated_write_revert_only_while_the_file_is_unchanged(client, lab, monkeypatch):
    use_engine(monkeypatch, StubEngine([
        ("", [tool_call("c1", "add_memory_entry", {"section": "Decisions", "text": "SQLite for the payment service."})]),
        ("Tamam.", []),
        ("", [tool_call("c2", "add_memory_entry", {"section": "Decisions", "text": "Postgres elsewhere."})]),
        ("Tamam.", []),
    ]))
    send(client, "Karar al.")
    first = lab.curated_writes[0]["id"]
    assert "SQLite" in (lab.root / "MEMORY.md").read_text(encoding="utf-8")

    reverted = client.post("/api/lab/curation/revert", json={"writeId": first})
    again = client.post("/api/lab/curation/revert", json={"writeId": first})

    assert reverted.status_code == 200
    assert not (lab.root / "MEMORY.md").exists()
    assert again.status_code == 409 and again.json()["code"] == "already_reverted"

    send(client, "Bir karar daha.")
    second = lab.curated_writes[1]["id"]
    (lab.root / "MEMORY.md").write_text((lab.root / "MEMORY.md").read_text(encoding="utf-8") + "- edited\n", encoding="utf-8")
    conflict = client.post("/api/lab/curation/revert", json={"writeId": second})
    assert conflict.status_code == 409 and conflict.json()["code"] == "conflict"
    assert "- edited" in conflict.json()["current"]["content"]
    assert client.post("/api/lab/curation/revert", json={"writeId": "../x"}).status_code == 400
    assert client.post("/api/lab/curation/revert", json={"writeId": "cw99"}).status_code == 404


def test_chat_provider_errors_are_redacted_and_recorded(client, lab, monkeypatch):
    import httpx

    secret = "request-scoped-secret-value-123"

    class FailingEngine(StubEngine):
        def stream_chat(self, messages, *, tools=None):
            request = httpx.Request("POST", "http://127.0.0.1:9/v1/chat/completions")
            raise httpx.ConnectError(f"connection refused while sending {secret}", request=request)
            yield  # pragma: no cover

    use_engine(monkeypatch, FailingEngine([]))

    response = client.post(
        "/api/lab/chat/stream",
        json={"message": "Merhaba", "sessionKind": "main", "openai": {"apiKey": secret}},
    )

    assert secret not in response.text
    error = frames_of(parse_sse(response.text), "error")[0]
    assert error["code"] == "provider_unreachable"
    assert error["error"].startswith("chat send failed: ConnectError")
    assert "[redacted]" in error["error"]
    assert error["stage"] == "stream" and error["redacted"] is True
    detail = client.get(f"/api/lab/turns/{error['turnId']}").json()
    assert detail["failedStage"] == "stream"
    assert {"type": "error", "label": "hata: stream"} in detail["chips"]
    assert "chat.turn.failed" in event_types(client)
    assert secret not in client.get("/api/lab/events", params={"once": "true"}).text


# --- flush before the turn (D1) ----------------------------------------------------------


def daily_write(text):
    from demo.chat_engine import FlushModelOutput, FlushWriteCall

    def output(target):
        return FlushModelOutput(raw_text=f"write({target})", writes=(FlushWriteCall(path=target, content=text, call_id="f1"),))

    return output


def test_flush_runs_before_the_main_turn_once_per_compaction_cycle(client, lab, monkeypatch):
    # v2026.9.6 derives reserve and soft threshold from the window (flush-plan.ts):
    # reserve min(20,000, 5,333 // 4) = 1,333; soft min(4,000, (5,333 - 1,333) // 2) = 2,000;
    # threshold 5,333 - 1,333 - 2,000 = 2,000.
    lab.settings.context_window_tokens = 5_333
    engine = use_engine(monkeypatch, StubEngine(
        [("Bir.", []), ("İki.", []), ("Üç.", [])],
        usage={"promptTokens": 1_990, "completionTokens": 40, "totalTokens": 2_030},
        flush_output=daily_write("- Redis 7.2 staging upgrade done."),
    ))
    client.get("/api/lab/state")
    before = {name: (lab.root / name).read_text(encoding="utf-8") for name in ("AGENTS.md", "SOUL.md", "USER.md")}

    first = send(client, "Bugün staging ortamında Redis'i 7.2 sürümüne yükselttik.")
    second = send(client, "CI süresi 14 dakikadan 9 dakikaya indi.")
    third = send(client, "Yarın yük testi var.")

    decisions = [frames_of(frames, "flush")[0]["decision"] for frames in (first, second, third)]
    assert [item["reason"] for item in decisions] == ["missing_tokens", "token_threshold", "already_flushed"]
    assert decisions[1]["threshold"] == 2_000
    assert (decisions[1]["reserveTokensFloor"], decisions[1]["softThresholdTokens"]) == (1_333, 2_000)
    assert decisions[1]["totalTokens"] == 1_990 + 40 + decisions[1]["promptTokenEstimate"]
    assert decisions[1]["tokenSource"] == "provider usage"
    assert len(engine.flush_calls) == 1
    flush_call = engine.flush_calls[0]
    assert flush_call["target"] == f"memory/{lab.today()}.md"
    assert "NO_REPLY" in flush_call["prompt"] and "read-only" in flush_call["system_prompt"]
    order = [frame["event"] for frame in second if frame["event"] in {"flush", "assistant_delta"}]
    assert order == ["flush", "flush", "assistant_delta"]
    detail = frames_of(second, "turn_done")[0]["detail"]
    stages = {stage["name"]: stage for stage in detail["stages"]}
    assert stages["flush"]["status"] == "ok"
    assert detail["flush"]["run"]["wrote"] is True
    assert detail["prompt"]["flush"]["target"] == f"memory/{lab.today()}.md"
    assert {"type": "flush", "label": "flush → günlük", "target": f"memory/{lab.today()}.md", "source": "flush"} in detail["chips"]
    visible = [(diff["path"], diff["source"]) for diff in detail["diffs"] if not diff["hidden"]]
    assert visible == [(f"memory/{lab.today()}.md", "flush")]
    assert ("memory/.dreams/short-term-recall.json", "recall") in [
        (diff["path"], diff["source"]) for diff in detail["diffs"] if diff["hidden"]
    ]
    assert (lab.root / "memory" / f"{lab.today()}.md").read_text(encoding="utf-8").rstrip().endswith("- Redis 7.2 staging upgrade done.")
    assert {name: (lab.root / name).read_text(encoding="utf-8") for name in before} == before
    assert not (lab.root / "MEMORY.md").exists()
    third_stages = {stage["name"]: stage for stage in frames_of(third, "turn_done")[0]["detail"]["stages"]}
    assert third_stages["flush"] == {"name": "flush", "status": "skip", "ms": 0, "detail": "already_flushed"}
    snapshot = client.get("/api/lab/state").json()["flush"]
    assert snapshot["alreadyFlushed"] is True and snapshot["note"].startswith("Lab never compacts")
    # The tag's session-entry state (8ee1d046d33 #115299): the flushed cycle lives in memoryFlush.
    assert snapshot["memoryFlush"] == {"kind": "succeeded", "compactionCount": 0}
    assert snapshot["memoryFlushCompactionCount"] == 0
    types = event_types(client)
    assert types.index("flush.decided") < types.index("flush.written")


def test_flush_writes_only_the_daily_file(client, lab, monkeypatch):
    from demo.chat_engine import FlushModelOutput, FlushWriteCall

    lab.settings.context_window_tokens = 5_333
    use_engine(monkeypatch, StubEngine(
        [("Bir.", []), ("İki.", [])],
        usage={"promptTokens": 5_000, "completionTokens": 10, "totalTokens": 5_010},
        flush_output=lambda target: FlushModelOutput(
            raw_text="write(MEMORY.md)", writes=(FlushWriteCall(path="MEMORY.md", content="- nope", call_id="f1"),)
        ),
    ))

    send(client, "bir")
    frames = send(client, "iki")

    run = frames_of(frames, "turn_done")[0]["detail"]["flush"]["run"]
    assert run["wrote"] is False and run["parsed"]["error"]
    assert not (lab.root / "MEMORY.md").exists()
    assert "flush.no_write" in event_types(client)


def test_flush_decision_without_usage_is_labelled_an_estimate(client, lab, monkeypatch):
    use_engine(monkeypatch, StubEngine([("Bir.", []), ("İki.", [])], usage={}))

    send(client, "bir")
    frames = send(client, "iki")

    decision = frames_of(frames, "flush")[0]["decision"]
    assert decision["reason"] == "under_threshold"
    assert decision["tokenSource"].startswith("estimate (chars/4")
    assert decision["contextWindowTokens"] == 200_000
    assert decision["contextWindowSource"] == "upstream DEFAULT_CONTEXT_TOKENS"


def test_heartbeat_kind_skips_the_flush(client, monkeypatch):
    use_engine(monkeypatch, StubEngine([("ok", [])]))

    frames = send(client, "HEARTBEAT", sessionKind="heartbeat")

    assert frames_of(frames, "flush")[0]["decision"]["reason"] == "runtime_skip:heartbeat"


def test_manual_flush_is_forced_once_per_cycle(client, lab, monkeypatch):
    use_engine(monkeypatch, StubEngine([("Bir.", [])], flush_output=daily_write("- Manual flush note.")))
    send(client, "Not: yük testi yarın.")

    first = client.post("/api/chat/flush", json={"forced": True}).json()
    second = client.post("/api/chat/flush", json={"forced": True}).json()

    assert first["decision"]["reason"] == "lab_forced"
    assert first["decision"]["trigger"]["reason"] in {"under_threshold", "missing_tokens"}
    assert first["flush"]["parsed"]["shouldWrite"] is True and first["flush"]["wrote"] is True
    assert second["decision"] == {**second["decision"], "shouldRun": False, "reason": "already_flushed"}
    assert second["flush"] is None
    assert (lab.root / "memory" / f"{lab.today()}.md").read_text(encoding="utf-8").count("Manual flush note") == 1


def test_manual_flush_needs_a_model(client):
    response = client.post("/api/chat/flush", json={"forced": True})

    assert response.status_code == 400
    assert response.json()["code"] == "no_api_key"


# --- prompt inspector: session kinds, bootstrap mode, truncation ---------------------------


def preview(client, **payload):
    response = client.post("/api/lab/prompt/preview", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def names(view):
    return [file["name"] for file in view["files"]]


def test_prompt_preview_follows_the_upstream_session_filters(client, lab):
    client.get("/api/lab/state")
    (lab.root / "MEMORY.md").write_text("# Memory\n\n- fact\n", encoding="utf-8")
    (lab.root / "PROACTIVE_PREFERENCES.md").write_text("# PROACTIVE_PREFERENCES.md\n\n- ask first\n", encoding="utf-8")

    main = preview(client, sessionKind="main")
    subagent = preview(client, sessionKind="subagent")
    cron = preview(client, sessionKind="cron")
    group = preview(client, sessionKind="group")
    compat = preview(client, sessionKind="main", layout="upstream")

    assert names(main) == ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "PROACTIVE_PREFERENCES.md", "MEMORY.md"]
    assert "dynamicText" not in main
    assert main["stableText"].startswith("# Project Context")
    assert main["recall"]["memoryRecallSection"][0] == "## Memory Recall"
    assert main["preview"] is True and "upsert_user_directive" in main["tools"]
    assert names(subagent) == ["AGENTS.md"]
    subagent_reasons = {item["name"]: item["reason"] for item in subagent["excluded"]}
    assert subagent_reasons["USER.md"] == "subagent: yalnız AGENTS.md"
    assert subagent_reasons["MEMORY.md"] == (
        "subagent: kök MEMORY.md özel olmayan oturumda (subagent, cron, group, channel) "
        "yüklenmez (upstream #119198)"
    )
    assert subagent["recall"]["memoryRecallSection"] == []
    assert names(cron) == ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "PROACTIVE_PREFERENCES.md"]
    assert {item["name"]: item["reason"] for item in cron["excluded"]}["MEMORY.md"].startswith(
        "cron: kök MEMORY.md özel olmayan oturumda"
    )
    # d06fc25a0c5 (#119198): root MEMORY.md stays out of non-private sessions (subagent,
    # cron, group, channel).
    assert "MEMORY.md" not in names(group)
    assert {item["name"]: item["reason"] for item in group["excluded"]}["MEMORY.md"].startswith(
        "group: kök MEMORY.md özel olmayan oturumda (subagent, cron, group, channel) yüklenmez"
    )
    assert "PROACTIVE_PREFERENCES.md" not in names(compat)
    assert compat["layout"] == "upstream"


def test_prompt_preview_shows_the_pending_bootstrap_only_where_upstream_does(client, lab):
    client.post("/api/lab/workspace/reset", json={"mode": "fresh"})

    main = preview(client, sessionKind="main")
    heartbeat = preview(client, sessionKind="heartbeat")
    cron = preview(client, sessionKind="cron")

    assert main["bootstrapStatus"] == "pending"
    assert main["bootstrapMode"] == "full"
    assert "hook-content" in main["bootstrapModeReason"]
    assert main["bootstrapText"].startswith("## Bootstrap Pending")
    assert "BOOTSTRAP.md" in names(main)
    assert main["workspaceNotes"] == ["Reminder: commit your changes in this workspace after edits."]
    for view in (heartbeat, cron):
        assert view["bootstrapMode"] == "none"
        assert "BOOTSTRAP.md" not in names(view)
        assert {item["name"]: item["reason"] for item in view["excluded"]}.get("BOOTSTRAP.md") in {
            "bootstrap modu none", "cron: yalnız AGENTS.md, IDENTITY.md, PROACTIVE_PREFERENCES.md, SOUL.md, USER.md",
        }
    assert heartbeat["heartbeatSection"][0] == "## Heartbeats"


def test_prompt_preview_reports_truncation_and_the_total_budget(client, lab):
    client.get("/api/lab/state")
    (lab.root / "SOUL.md").write_text("# SOUL.md\n\n" + "Be direct and precise. " * 1_200, encoding="utf-8")
    (lab.root / "AGENTS.md").write_text("# AGENTS.md\n\n" + "- You must never skip validation.\n" * 800, encoding="utf-8")

    view = preview(client, sessionKind="main")
    tight = preview(client, sessionKind="main", totalMaxChars=12_000)

    soul = next(file for file in view["files"] if file["name"] == "SOUL.md")
    assert soul["truncated"] is True and soul["chars"] <= 20_000
    assert "[...truncated, read SOUL.md for full content...]" in view["stableText"]
    assert "[Policy digest from AGENTS.md]" in view["stableText"]
    assert view["truncationWarningLines"][0].startswith("SOUL.md: ") or view["truncationWarningLines"][0].startswith("AGENTS.md: ")
    assert "AGENTS.md was truncated; read the full AGENTS.md before relying on scoped policy." in view["truncationWarningLines"]
    assert view["truncationNotice"] and "[Bootstrap truncation warning]" in view["bootstrapText"]
    assert tight["budget"]["injectedChars"] <= 12_000
    assert "toplam bütçe doldu" in {item["reason"] for item in tight["excluded"]}
    entries = {entry["path"]: entry for entry in client.get("/api/lab/files").json()}
    assert entries["SOUL.md"]["truncation"]["cause"] == "max/file"
    assert entries["SOUL.md"]["truncation"]["warningLine"].startswith("SOUL.md: ")


def test_truncation_warning_once_mode_is_kept_per_session(client, lab, monkeypatch):
    client.get("/api/lab/state")
    (lab.root / "SOUL.md").write_text("x" * 25_000, encoding="utf-8")
    lab.settings.warning_mode = "once"
    use_engine(monkeypatch, StubEngine([("bir", []), ("iki", [])]))

    first = frames_of(send(client, "bir"), "turn_done")[0]["detail"]
    second = frames_of(send(client, "iki"), "turn_done")[0]["detail"]

    assert first["prompt"]["truncationWarning"]["shown"] is True
    assert any(chip["type"] == "truncation" for chip in first["chips"])
    assert second["prompt"]["truncationWarning"]["shown"] is False
    assert second["prompt"]["truncationWarningLines"] == []
    assert not any(chip["type"] == "truncation" for chip in second["chips"])


def test_context_injection_never_skips_the_files(client):
    client.get("/api/lab/state")

    view = preview(client, sessionKind="main", contextInjection="never")

    assert view["injectionSkipped"] is True
    assert view["files"] == []
    reasons = {item["name"]: item["reason"] for item in view["excluded"]}
    assert reasons.pop("BOOTSTRAP.md") == "bootstrap tamamlandı"
    assert set(reasons.values()) == {"contextInjection: enjeksiyon atlandı"}


@pytest.mark.parametrize(
    "payload",
    [{"sessionKind": "boss"}, {"runKind": "x"}, {"contextMode": "tiny"}, {"contextInjection": "sometimes"},
     {"maxChars": 0}, {"totalMaxChars": "many"}, {"layout": "other"}],
)
def test_prompt_preview_validates_its_options(client, payload):
    client.get("/api/lab/state")

    assert client.post("/api/lab/prompt/preview", json=payload).status_code == 400


def test_chat_turn_prompt_matches_the_messages_sent(client, lab, monkeypatch):
    engine = use_engine(monkeypatch, StubEngine([("tamam", [])]))

    detail = frames_of(send(client, "Merhaba", sessionKind="subagent"), "turn_done")[0]["detail"]

    sent = engine.calls[0]["messages"]
    assert detail["prompt"]["messages"] == sent
    assert sent[0]["role"] == "system" and "## Memory Recall" not in sent[0]["content"]
    assert sent[-1] == {"role": "user", "content": "Merhaba"}
    assert names(detail["prompt"]) == ["AGENTS.md"]
    assert detail["sessionKey"].startswith("lab:subagent:")
    assert detail["recall"] is None
    assert {stage["name"]: stage["status"] for stage in detail["stages"]}["recall"] == "skip"


# --- sessions: /new and /reset -------------------------------------------------------------


def test_bare_new_writes_session_memory_and_loads_the_startup_context(client, lab, monkeypatch):
    from memory_core.bootstrap import BARE_SESSION_RESET_PROMPT_BASE

    engine = use_engine(monkeypatch, StubEngine([("Not aldım.", []), ("Merhaba!", []), ("16:00.", [])]))
    client.get("/api/lab/state")
    daily = lab.root / "memory" / f"{lab.today()}.md"
    daily.write_text("- Müşteri demosu 16:00'ya alındı.\n", encoding="utf-8")
    send(client, "Bugün müşteri demosunu 16:00'ya aldık.")
    old_key = client.get("/api/lab/state").json()["session"]["key"]
    daily_before = daily.read_text(encoding="utf-8")

    result = client.post("/api/lab/session/new", json={"command": "new", "sessionKind": "main"}).json()

    memory_path = result["sessionMemory"]["path"]
    assert re.fullmatch(rf"memory/{lab.today()}-\d{{4}}\.md", memory_path)
    content = (lab.root / memory_path).read_text(encoding="utf-8")
    assert content.startswith("# Session: ")
    assert f"- **Session Key**: {old_key}" in content
    assert "- **Source**: lab" in content
    assert "## Conversation Summary" in content
    assert "user: Bugün müşteri demosunu 16:00'ya aldık." in content
    assert "assistant: Not aldım." in content
    assert result["sessionMemory"]["rawLines"] is True and "D2" in result["sessionMemory"]["label"]
    assert daily.read_text(encoding="utf-8") == daily_before
    assert result["sessionKey"] != old_key and result["bare"] is True
    assert result["startup"]["text"].startswith("[Startup context loaded by runtime]\n")
    assert result["startup"]["files"] == [f"memory/{lab.today()}.md", memory_path]
    assert result["resetPrompt"]["text"].startswith(BARE_SESSION_RESET_PROMPT_BASE + "\nCurrent time: ")
    assert result["resetPrompt"]["bootstrapMode"] == "none"
    types = event_types(client)
    assert {"session_memory.written", "session.new", "startup_context.loaded"} <= set(types)

    reset_frames = send(client, "", reset=True)
    reset_detail = frames_of(reset_frames, "turn_done")[0]["detail"]
    sent_user = engine.calls[1]["messages"][-1]
    assert sent_user["role"] == "user"
    assert sent_user["content"] == f"{result['startup']['text']}\n\n{result['resetPrompt']['text']}"
    assert reset_detail["user"] == "[memory-core session new]"
    assert reset_detail["prompt"]["startup"] == result["startup"]
    assert any(chip["type"] == "startup" for chip in reset_detail["chips"])
    assert {stage["name"]: stage["status"] for stage in reset_detail["stages"]}["recall"] == "skip"

    next_detail = frames_of(send(client, "Nerede kalmıştık?"), "turn_done")[0]["detail"]
    assert next_detail["prompt"]["startup"] is None
    assert engine.calls[2]["messages"][-3]["content"] == "[memory-core session new]"


def test_new_with_text_writes_the_file_but_loads_no_startup_context(client, lab):
    client.get("/api/lab/state")
    (lab.root / "memory" / f"{lab.today()}.md").write_text("- a note\n", encoding="utf-8")

    result = client.post("/api/lab/session/new", json={"command": "reset", "text": "Selam, yeni konu."}).json()

    assert result["bare"] is False
    assert result["startup"] is None and result["resetPrompt"] is None
    assert (lab.root / result["sessionMemory"]["path"]).exists()
    assert "## Conversation Summary" not in result["sessionMemory"]["content"]
    assert "startup_context.loaded" not in event_types(client)
    no_pending = client.post("/api/lab/chat/stream", json={"message": "", "reset": True, "sessionKind": "main"})
    assert no_pending.status_code == 400 and no_pending.json()["code"] == "no_pending_reset"


def test_bare_new_while_bootstrap_is_pending_uses_the_limited_prompt(client, lab):
    from memory_core.bootstrap.startup import BARE_SESSION_RESET_PROMPT_BOOTSTRAP_LIMITED

    client.post("/api/lab/workspace/reset", json={"mode": "fresh"})

    result = client.post("/api/lab/session/new", json={"command": "new"}).json()

    assert result["resetPrompt"]["bootstrapMode"] == "limited"
    assert result["resetPrompt"]["text"].startswith(BARE_SESSION_RESET_PROMPT_BOOTSTRAP_LIMITED)
    assert result["startup"] is None


def test_session_new_validates_the_command(client):
    assert client.post("/api/lab/session/new", json={"command": "wipe"}).json()["code"] == "invalid_command"
    assert client.post("/api/lab/session/new", json={"command": "new", "sessionKind": "x"}).status_code == 400


# --- heartbeat -------------------------------------------------------------------------------

# The Lab no longer seeds HEARTBEAT.md (v2026.9.6 retired it; the heartbeat view still reads
# one a user writes until the monitor-scratch port). This header is the Lab's former seed text.
HEARTBEAT_HEADER = """# HEARTBEAT.md - Continuity Check

Before acting, re-read the workspace files that define current identity, user context, tools, and memory.
"""
TASKS = """
tasks:
  - name: gunluk-takip
    interval: 30m
    prompt: Bugünün günlük notunda açık bir takip maddesi var mı kontrol et. Yoksa yalnızca HEARTBEAT_OK yaz.
"""


def heartbeat_run(client, **payload):
    response = client.post("/api/lab/heartbeat/run", json=payload)
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


def test_heartbeat_state_parses_tasks_and_due_state(client, lab):
    client.get("/api/lab/state")
    (lab.root / "HEARTBEAT.md").write_text(HEARTBEAT_HEADER + TASKS + "  - name: broken\n", encoding="utf-8")

    state = client.get("/api/lab/heartbeat").json()

    assert state["file"] == {"path": "HEARTBEAT.md", "exists": True, "effectivelyEmpty": False}
    assert state["every"] == "30m" and state["everyMs"] == 1_800_000 and state["ackMaxChars"] == 300
    assert state["tasks"][0]["name"] == "gunluk-takip"
    assert state["tasks"][0]["due"] is True and state["tasks"][0]["lastRunMs"] is None
    assert state["unparsedTaskEntries"] == 1
    assert state["preflight"] == {"skipReason": None, "dueTasks": ["gunluk-takip"]}
    assert state["proactivePreferences"] == "empty"
    assert state["runs"] == []


def test_heartbeat_skips_an_empty_file_without_a_model_call(client, lab, monkeypatch):
    engine = use_engine(monkeypatch, StubEngine([("x", [])]))
    client.get("/api/lab/state")
    (lab.root / "HEARTBEAT.md").write_text("# HEARTBEAT.md\n\n<!-- boş -->\n", encoding="utf-8")

    frames = heartbeat_run(client)

    assert frames_of(frames, "skipped") == [{"reason": "empty-heartbeat-file", "runId": 1}]
    assert frames_of(frames, "flush")[0]["decision"]["reason"] == "runtime_skip:heartbeat"
    assert engine.calls == []
    types = event_types(client)
    assert "heartbeat.skipped" in types and "heartbeat.llm" not in types


def test_heartbeat_skip_without_a_key_needs_no_model(client, lab):
    client.get("/api/lab/state")
    (lab.root / "HEARTBEAT.md").write_text("# HEARTBEAT.md\n", encoding="utf-8")

    frames = heartbeat_run(client)

    assert frames_of(frames, "skipped")[0]["reason"] == "empty-heartbeat-file"


def test_heartbeat_without_a_key_reports_no_api_key_when_it_would_call_the_model(client):
    client.get("/api/lab/state")

    frames = heartbeat_run(client)

    assert frames_of(frames, "error")[0]["code"] == "no_api_key"


def test_heartbeat_runs_the_tool_loop_and_decides_delivery(client, lab, monkeypatch):
    client.get("/api/lab/state")
    (lab.root / "HEARTBEAT.md").write_text(HEARTBEAT_HEADER + TASKS, encoding="utf-8")
    (lab.root / "memory" / f"{lab.today()}.md").write_text("- Yarın 09:00 tedarikçiye fatura gönderilecek.\n", encoding="utf-8")
    (lab.root / "PROACTIVE_PREFERENCES.md").write_text("# PROACTIVE_PREFERENCES.md\n\n- Fatura takiplerini bildir.\n", encoding="utf-8")
    engine = use_engine(monkeypatch, StubEngine([
        ("", [tool_call("h1", "memory_search", {"query": "fatura"})]),
        ("Hatırlatma: yarın 09:00 tedarikçiye fatura gönderilecek.", []),
        ("HEARTBEAT_OK", []),
    ]))

    first = heartbeat_run(client)

    prompt = frames_of(first, "prompt")[0]
    assert prompt["userMessage"].startswith("Run the following periodic tasks (only those due based on their intervals):")
    assert "After completing all due tasks, reply HEARTBEAT_OK." in prompt["userMessage"]
    assert "\nCurrent time: " in prompt["userMessage"]
    assert prompt["systemSection"].startswith("## Heartbeats")
    assert prompt["files"].index("USER.md") < prompt["files"].index("PROACTIVE_PREFERENCES.md")
    # HEARTBEAT.md is read by the heartbeat itself, never injected as a bootstrap file.
    assert "HEARTBEAT.md" not in prompt["files"] and "TOOLS.md" not in prompt["files"]
    assert "BOOTSTRAP.md" not in prompt["files"]
    assert "memory_search" in prompt["tools"]
    assert "## Heartbeats" in engine.calls[0]["messages"][0]["content"]
    result = frames_of(first, "tool_result")[0]["result"]
    assert result["results"][0]["path"] == f"memory/{lab.today()}.md"
    decision = frames_of(first, "decision")[0]
    assert decision["delivered"] is True and decision["text"].startswith("Hatırlatma")
    run = frames_of(first, "done")[0]["run"]
    assert run["dueTasks"] == ["gunluk-takip"]
    assert run["taskState"]["gunluk-takip"] == run["virtualNowMs"]

    waiting = client.get("/api/lab/heartbeat").json()
    assert waiting["tasks"][0]["due"] is False
    assert waiting["preflight"]["skipReason"] == "no-tasks-due"
    skipped = heartbeat_run(client)
    assert frames_of(skipped, "skipped")[0]["reason"] == "no-tasks-due"

    clock = client.post("/api/lab/clock", json={"offsetMs": 31 * 60 * 1000}).json()
    assert clock["offsetMs"] == 31 * 60 * 1000
    acked = heartbeat_run(client)
    assert frames_of(acked, "decision")[0] == {
        "shouldSkip": True, "text": "", "didStrip": True, "remainderChars": 0, "delivered": False, "ackMaxChars": 300,
    }
    session = lab.session("heartbeat")
    assert session.messages[0] == {"role": "user", "content": "[memory-core heartbeat poll]"}
    runs = client.get("/api/lab/heartbeat").json()["runs"]
    assert [item.get("skipped") for item in runs] == [None, "no-tasks-due", None]
    assert {"heartbeat.run", "heartbeat.llm", "heartbeat.decided", "clock.changed"} <= set(event_types(client))


def test_heartbeat_light_context_injects_no_bootstrap_file(client, lab, monkeypatch):
    # applyContextModeFilter at v2026.9.6: lightweight runs get no bootstrap files at all.
    use_engine(monkeypatch, StubEngine([("HEARTBEAT_OK", [])]))
    client.get("/api/lab/state")

    frames = heartbeat_run(client, lightContext=True)

    assert frames_of(frames, "prompt")[0]["files"] == []


@pytest.mark.parametrize(
    ("text", "skip"),
    [("HEARTBEAT_OK", True), ("**HEARTBEAT_OK**.", True), ("All good. HEARTBEAT_OK", True), ("Alert: disk full", False)],
)
def test_heartbeat_strip_parser(client, text, skip):
    result = client.post("/api/lab/heartbeat/strip", json={"text": text}).json()

    assert result["shouldSkip"] is skip


def test_clock_validates_and_resets(client):
    assert client.post("/api/lab/clock", json={"offsetMs": "soon"}).status_code == 400
    assert client.post("/api/lab/clock", json={"offsetMs": 10**12}).status_code == 400
    assert client.post("/api/lab/clock", json={"reset": True}).json()["offsetMs"] == 0


# --- search playground and embeddings (Q9) -----------------------------------------------


class RecordingEmbeddings:
    """Test-only stand-in for the OpenAI-compatible provider (never used at runtime)."""

    instances = []

    def __init__(self, *, api_key, model, base_url, timeout=30.0):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.provider_id = "openai-compatible"
        self.error = None
        self.calls = 0
        RecordingEmbeddings.instances.append(self)

    def cache_key_data(self):
        return {"provider": self.provider_id, "baseUrl": self.base_url, "model": self.model}

    def _vector(self, text):
        return [float(len(text) % 7 + 1), float(text.count("a") + 1), 1.0]

    def embed_query(self, text):
        self.calls += 1
        if RecordingEmbeddings.error:
            raise RuntimeError(RecordingEmbeddings.error)
        return self._vector(text)

    def embed_documents(self, texts):
        self.calls += 1
        if RecordingEmbeddings.error:
            raise RuntimeError(RecordingEmbeddings.error)
        return [self._vector(text) for text in texts]


@pytest.fixture
def embeddings(monkeypatch):
    import demo.lab_runtime as lab_runtime

    RecordingEmbeddings.instances = []
    RecordingEmbeddings.error = None
    monkeypatch.setattr(lab_runtime, "OpenAICompatibleEmbeddingProvider", RecordingEmbeddings)
    return RecordingEmbeddings


def seed_notes(client, lab):
    client.get("/api/lab/state")
    (lab.root / "memory" / f"{lab.today()}.md").write_text(
        "- Müşteri demosu 16:00'ya alındı.\n- Haftalık sürüm toplantısı perşembe 10:30.\n", encoding="utf-8"
    )


def test_default_lab_is_fts_only_and_never_builds_an_embedder(client, lab, embeddings):
    seed_notes(client, lab)

    result = client.post("/api/search", json={"query": "perşembe", "maxResults": 5, "minScore": 0}).json()
    hybrid = client.post("/api/search", json={"query": "perşembe", "mode": "hybrid"})
    status = client.get("/api/lab/index/status").json()

    assert result["mode"] == "text"
    assert result["provider"] == "none" and result["model"] == "fts-only"
    assert result["embeddings"]["mode"] == "fts-only"
    assert result["embeddings"]["label"] == "yalnız FTS"
    assert "openrouter.ai" in result["embeddings"]["reason"]
    assert result["results"][0]["vectorScore"] is None or result["results"][0]["vectorScore"] == 0
    assert result["results"][0]["citation"].startswith(f"Source: memory/{lab.today()}.md#L")
    assert result["identity"]["status"] == "valid"
    assert result["reindexed"] is True and isinstance(result["ms"], int)
    assert hybrid.status_code == 400 and hybrid.json()["code"] == "fts_only"
    assert status["embeddings"]["mode"] == "fts-only" and status["deadlineMs"] == 15_000
    assert embeddings.instances == []
    assert "embedding.request" not in event_types(client)


def test_demo_runtime_never_imports_fake_embeddings():
    demo_dir = Path(demo_app.__file__).parent
    offenders = [path.name for path in demo_dir.glob("*.py") if "FakeEmbeddingProvider" in path.read_text(encoding="utf-8")]

    assert offenders == []


def test_an_embedding_endpoint_enables_hybrid_search(client, lab, embeddings, monkeypatch):
    seed_notes(client, lab)
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL", "https://embeddings.example/v1")
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY", "embedding-env-key-value")

    result = client.post("/api/search", json={"query": "toplantı", "mode": "hybrid"}).json()
    text = client.post("/api/search", json={"query": "toplantı", "mode": "text"}).json()

    assert result["mode"] == "hybrid" and result["provider"] == "openai-compatible"
    assert result["embeddings"] == {
        "mode": "hybrid", "provider": "openai-compatible", "baseUrl": "https://embeddings.example/v1",
        "model": "text-embedding-3-small", "keySource": "env", "reason": None, "label": "hibrit",
    }
    assert result["results"] and result["results"][0]["vectorScore"] is not None
    assert text["provider"] == "none"
    assert "embedding.request" in event_types(client)
    assert "embedding-env-key-value" not in json.dumps(result)


def test_the_chat_key_is_never_sent_to_another_embedding_host(lab, monkeypatch):
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL", "https://embeddings.example/v1")

    resolution = lab.resolve_embedding({"openai": {"apiKey": "chat-key", "baseUrl": "https://chat.example/v1"}})

    assert resolution.mode == "fts-only" and resolution.api_key == ""


def test_embedding_failures_put_search_on_cooldown_without_provider_calls(client, lab, embeddings, monkeypatch):
    seed_notes(client, lab)
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL", "https://embeddings.example/v1")
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY", "embedding-env-key-value")
    client.post("/api/search", json={"query": "demo", "mode": "hybrid"})
    embeddings.error = "connection refused embedding-env-key-value"

    failed = client.post("/api/search", json={"query": "toplantı", "mode": "hybrid"}).json()
    mark = client.get("/api/lab/state").json()["lastEventId"]
    calls_before = sum(instance.calls for instance in embeddings.instances)
    again = client.post("/api/search", json={"query": "toplantı", "mode": "hybrid"}).json()

    assert failed["unavailable"] is True and failed["disabled"] is True
    assert failed["warning"] == "Memory search is unavailable due to an embedding/provider error."
    assert failed["action"] == "Check embedding provider configuration and retry memory_search."
    assert "embedding-env-key-value" not in json.dumps(failed)
    assert failed["cooldown"]["remainingMs"] > 55_000
    assert again["unavailable"] is True
    assert sum(instance.calls for instance in embeddings.instances) == calls_before
    later = event_types(client, mark)
    assert "search.cooldown" in later and "embedding.request" not in later


@pytest.mark.parametrize(
    ("payload", "message"),
    [({"query": ""}, "query required"), ({"query": "x", "maxResults": 0}, "maxResults must be a positive integer")],
)
def test_search_contract_errors_are_verbatim(client, payload, message):
    client.get("/api/lab/state")

    response = client.post("/api/search", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == message and body["code"] == "tool_input_error"
    assert body["toolError"] == {"status": "error", "tool": "memory_search", "error": message}


# --- consolidation --------------------------------------------------------------------------


def test_consolidation_view_lists_candidates_gates_and_curated_writes(client, lab, monkeypatch):
    seed_notes(client, lab)
    use_engine(monkeypatch, StubEngine([
        ("", [tool_call("c1", "add_memory_entry", {"section": "Decisions", "text": "SQLite for payments."})]),
        ("ok", []), ("ok", []), ("ok", []),
    ]))
    send(client, "Karar: SQLite.")
    for question in ("perşembe toplantı", "sürüm toplantısı ne zaman", "haftalık sürüm perşembe"):
        send(client, question)

    view = client.get("/api/lab/consolidation").json()

    assert view["curated"][0]["path"] == "MEMORY.md" and "before" not in view["curated"][0]
    assert view["gates"]["minScore"] == 0.8 and view["gates"]["minRecallCount"] == 3
    assert view["gates"]["minUniqueQueries"] == 3 and view["gates"]["limit"] == 5
    assert view["weights"] == {"frequency": 0.24, "relevance": 0.30, "diversity": 0.15, "recency": 0.15,
                               "consolidation": 0.10, "conceptual": 0.06}
    assert view["shortTerm"]["entries"] >= 1
    candidate = view["candidates"][0]
    assert set(candidate["components"]) >= {"frequency", "relevance", "phaseBoost"}
    assert set(candidate["gates"]) == {"score", "recall", "unique", "age"}
    assert candidate["selected"] is (not candidate["reasons"])
    assert view["labels"]["scored"].startswith("paket (memory_core.consolidation)")
    # The label quotes docs/parity_matrix.md; Promotion gates is `partial` since the v2026.9.6
    # re-pin (2026-09-27).
    assert "Promotion gates: partial" in view["labels"]["scored"]


def test_promotion_dreaming_audit_and_repair_emit_events(client, lab):
    seed_notes(client, lab)

    promote = client.post("/api/memory/promote", json={}).json()
    dream = client.post("/api/dreaming/run", json={"phase": "light"}).json()
    audit = client.get("/api/memory/audit").json()
    repair = client.post("/api/memory/repair", json={}).json()
    bad_phase = client.post("/api/dreaming/run", json={"phase": "nap"})

    assert promote["promotion"]["target"] == "MEMORY.md"
    assert promote["promotion"]["parsed"]["shouldWrite"] is False
    assert dream["dreamingSweep"]["phase"] == "light"
    assert audit["memoryAudit"]["issues"] == [] or isinstance(audit["memoryAudit"]["issues"], list)
    assert "memoryRepair" in repair and "memoryAudit" in repair
    assert bad_phase.status_code == 400
    assert {"promotion.swept", "dreaming.swept", "audit.completed", "repair.completed"} <= set(event_types(client))
    view = client.get("/api/lab/consolidation").json()
    assert view["lastPromotion"]["target"] == "MEMORY.md" and view["lastDreaming"]["phase"] == "light"


def test_promotion_writes_gated_recalls_into_memory_md_with_source_promotion(client, lab, monkeypatch):
    from memory_core.consolidation import record_short_term_recalls

    client.get("/api/lab/state")
    daily = lab.root / "memory" / "2026-05-03.md"
    daily.write_text("# 2026-05-03\n\n- User was fired from work.\n", encoding="utf-8")
    base_ms = 1_777_824_000_000
    for offset, query in enumerate(["job loss", "fired from work", "work situation", "career event", "employment status"]):
        record_short_term_recalls(
            config=lab.config(),
            query=query,
            results=[{"source": "memory", "path": "memory/2026-05-03.md", "startLine": 3, "endLine": 3,
                      "snippet": "- User was fired from work.", "score": 1}],
            now_ms=base_ms + offset * 86_400_000,
        )
    monkeypatch.setattr(lab, "now_ms", lambda: base_ms + 4 * 86_400_000)

    promotion = client.post("/api/memory/promote", json={}).json()["promotion"]

    assert promotion["parsed"]["shouldWrite"] is True
    assert promotion["evaluatedCandidates"][0]["reasons"] == []
    assert promotion["evaluatedCandidates"][0]["selected"] is True
    assert "User was fired from work." in (lab.root / "MEMORY.md").read_text(encoding="utf-8")
    changes = {change["path"]: change for change in client.get("/api/lab/diff", params={"since": "reset"}).json()}
    assert changes["MEMORY.md"]["sources"][0]["source"] == "promotion"


# --- settings and provider checks -------------------------------------------------------------


def test_settings_defaults_follow_d4_and_q9(client):
    from demo.chat_engine import DEFAULT_OPENAI_MODEL

    settings = client.get("/api/lab/settings").json()

    assert settings["chat"]["baseUrl"] == "https://openrouter.ai/api/v1"
    assert settings["chat"]["model"] == DEFAULT_OPENAI_MODEL == "openai/gpt-6-luna"
    assert settings["chat"]["defaultModel"]["checkedAt"] == "2026-09-26"
    assert settings["chat"]["keySource"] == "none"
    assert settings["embedding"]["mode"] == "fts-only"
    assert settings["layout"] == "memory-core"
    assert settings["budgets"] == {"maxChars": 20_000, "totalMaxChars": 60_000, "warningMode": "always",
                                   "defaults": {"maxChars": 20_000, "totalMaxChars": 60_000, "warningMode": "always"}}
    assert settings["flush"]["mode"] == "threshold" and settings["flush"]["threshold"] == 176_000
    assert (settings["flush"]["reserveTokensFloor"], settings["flush"]["softThresholdTokens"]) == (20_000, 4_000)
    assert settings["flush"]["defaults"] == {"reserveTokensFloor": 20_000, "softThresholdTokens": 4_000}
    assert settings["heartbeat"] == {"every": "30m", "everyMs": 1_800_000, "ackMaxChars": 300, "lightContext": False}
    assert settings["flags"]["curation.user_md"] == {"on": True, "label": "USER.md direktifleri", "extension": True}
    assert settings["timezone"] == "Europe/Istanbul"


def test_settings_env_key_is_reported_by_source_only(client, monkeypatch):
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", "env-chat-key-value-123")

    body = client.get("/api/lab/settings").text

    assert json.loads(body)["chat"]["keySource"] == "env"
    assert "env-chat-key-value-123" not in body


def test_settings_update_applies_and_emits(client, lab):
    updated = client.put("/api/lab/settings", json={
        "chat": {"model": "openai/gpt-6-sol", "baseUrl": "https://llm.example/v1/"},
        "layout": "upstream",
        "budgets": {"totalMaxChars": 12_000, "warningMode": "once"},
        "contextInjection": "continuation-skip",
        "flush": {"mode": "threshold", "contextWindowTokens": 5_333},
        "heartbeat": {"every": "10m", "ackMaxChars": 50, "lightContext": True},
        "flags": {"lab_file_editing": False},
    }).json()

    assert updated["chat"]["model"] == "openai/gpt-6-sol" and updated["chat"]["baseUrl"] == "https://llm.example/v1"
    assert updated["layout"] == "upstream" and lab.layout.name == "openclaw"
    assert updated["budgets"]["totalMaxChars"] == 12_000 and updated["budgets"]["warningMode"] == "once"
    assert updated["flush"]["threshold"] == 2_000
    assert (updated["flush"]["reserveTokensFloor"], updated["flush"]["softThresholdTokens"]) == (1_333, 2_000)
    assert updated["heartbeat"]["everyMs"] == 600_000
    assert updated["flags"]["lab_file_editing"]["on"] is False
    assert "settings.changed" in event_types(client)
    client.get("/api/lab/state")
    assert client.get("/api/lab/file", params={"path": "USER.md"}).json()["writable"] is False
    reset = client.put("/api/lab/settings", json={"budgets": {"totalMaxChars": None}, "flush": {"contextWindowTokens": None}}).json()
    assert reset["budgets"]["totalMaxChars"] == 60_000 and reset["flush"]["contextWindowTokens"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"chat": {"apiKey": "x"}},
        {"embedding": {"apiKey": "x"}},
        {"flush": {"mode": "per_turn"}},
        {"layout": "custom"},
        {"budgets": {"maxChars": -1}},
        {"budgets": {"warningMode": "sometimes"}},
        {"heartbeat": {"every": "soon"}},
        {"flags": {"unknown_flag": True}},
        {"chat": {"baseUrl": "ftp://x"}},
        {"surprise": 1},
    ],
)
def test_settings_update_rejects_keys_and_bad_values(client, payload):
    response = client.put("/api/lab/settings", json=payload)

    assert response.status_code == 400
    assert response.json()["code"] in {"key_not_accepted", "invalid_setting"}


def test_provider_check_redacts_the_key_and_records_the_status(client, monkeypatch):
    secret = "check-key-value-456"

    class FailingCheck(StubEngine):
        def check(self):
            raise RuntimeError(f"401 invalid key {secret}")

    use_engine(monkeypatch, FailingCheck([]))

    result = client.post("/api/lab/provider/check", json={"openai": {"apiKey": secret}}).json()

    assert result["ok"] is False and result["redacted"] is True
    assert secret not in json.dumps(result)
    assert client.get("/api/lab/settings").json()["chat"]["lastCheck"]["ok"] is False
    embedding = client.post("/api/lab/provider/check", json={"embedding": {}}).json()
    assert embedding == {**embedding, "ok": False, "mode": "fts-only", "target": "embedding"}
    assert "provider.check" in event_types(client)


# --- live SDK task ------------------------------------------------------------------------------


def live_turn(client, message, **ids):
    response = client.post("/api/live-task/turn-stream", json={"sessionId": "demo_session", "subjectId": "demo_subject", "message": message, **ids})
    assert response.status_code == 200
    return parse_sse(response.text)


def test_live_task_scripted_flow_reports_its_engine_and_redacts_the_summary(client, lab):
    state = client.post("/api/live-task/reset", json={}).json()
    assert state["engine"] == {"mode": "scripted", "keySource": "none", "model": "workflow-script"}
    assert state["workflow"]["current_step"] == "verify_identity"
    assert "identityFiles" not in state
    assert state["workspace"] == str(lab.live_root) != str(lab.root)

    first = live_turn(client, "Merhaba, randevumu değiştirmek istiyorum.")
    types = [frame["event"] for frame in first]
    for expected in ("live_turn_started", "memory_recall_completed", "prompt_assembled", "text_delta", "sentence", "live_turn_completed"):
        assert expected in types
    assert types[-1] == "live_task_state"
    provider = [frame["data"]["data"] for frame in first if frame["event"] == "provider_event"]
    assert {"type": "llm", "provider": "scripted", "model": "workflow-script"} in provider
    for message in ("Kimlik doğrulaması için müşteri numaram 4821.", "Yarın saat 14:30 olabilir mi?", "Evet, onaylıyorum."):
        live_turn(client, message)
    final = client.get("/api/live-task/state").json()
    assert final["workflow"]["current_step"] == "completed"
    assert final["workflow"]["business_action"]["type"] == "appointment_rescheduled"

    summary = client.post("/api/live-task/summary", json={}).json()["summary"]

    assert summary["wrote"] is True and summary["redacted"] is True
    daily = lab.live_root / "subjects" / "demo_subject" / summary["path"]
    assert "4821" not in daily.read_text(encoding="utf-8")
    assert "[kimlik bilgisi gizlendi]" in daily.read_text(encoding="utf-8")
    bus_types = event_types(client)
    assert "live.sentence" in bus_types and "live.session_summary" in bus_types


def test_live_task_state_reports_the_env_key_engine(client, monkeypatch):
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", "env-live-key-value")

    body = client.get("/api/live-task/state").text

    assert json.loads(body)["engine"]["mode"] == "llm"
    assert "env-live-key-value" not in body


def test_live_task_turn_failure_redacts_the_request_key(client, monkeypatch):
    import demo.lab_kept_api as kept

    key = "request-scoped-live-key-123"

    class FailingEngine:
        model = "test-model"

        def raw_chat_stream(self, messages):
            del messages
            raise RuntimeError(f"401 Unauthorized: invalid api key {key}")
            yield ""  # pragma: no cover

    monkeypatch.setattr(kept, "live_engine", lambda lab, payload: FailingEngine())
    client.post("/api/live-task/reset", json={})

    response = client.post(
        "/api/live-task/turn-stream",
        json={"message": "Merhaba", "openai": {"apiKey": key}},
    )

    frames = parse_sse(response.text)
    failed = [frame for frame in frames if frame["event"] == "live_turn_failed"]
    assert failed and "[redacted]" in failed[0]["data"]["data"]["error"]
    assert key not in response.text
    assert key not in client.get("/api/lab/events", params={"once": "true"}).text


# --- no key value in any response, error or event --------------------------------------------


def test_no_key_value_leaks_into_any_response_or_event(client, lab, embeddings, monkeypatch):
    import demo.lab_kept_api as kept

    env_chat = "env-chat-secret-000111"
    env_embedding = "env-embedding-secret-000222"
    request_chat = "request-chat-secret-000333"
    request_embedding = "request-embedding-secret-000444"
    secrets = (env_chat, env_embedding, request_chat, request_embedding)
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", env_chat)
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY", env_embedding)
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL", "https://embeddings.example/v1")

    class LeakyEngine(StubEngine):
        def stream_chat(self, messages, *, tools=None):
            raise RuntimeError(f"upstream said: bad keys {env_chat} {request_chat}")
            yield  # pragma: no cover

        def check(self):
            raise RuntimeError(f"401 for {request_chat}")

    class LeakyLive:
        model = "m"

        def raw_chat_stream(self, messages):
            raise RuntimeError(f"live failure {env_chat}")
            yield ""  # pragma: no cover

        def raw_chat_text(self, messages):
            raise RuntimeError(f"summary failure {request_chat}")

    use_engine(monkeypatch, LeakyEngine([]))
    monkeypatch.setattr(kept, "live_engine", lambda lab, payload: LeakyLive())
    embeddings.error = f"embedding failure {env_embedding} {request_embedding}"
    keys = {"openai": {"apiKey": request_chat}, "embedding": {"apiKey": request_embedding}}
    bodies = []

    def call(method, path, **kwargs):
        response = getattr(client, method)(path, **kwargs)
        bodies.append(response.text)
        return response

    call("get", "/api/lab/state")
    (lab.root / "memory" / f"{lab.today()}.md").write_text("- note\n", encoding="utf-8")
    call("post", "/api/lab/chat/stream", json={"message": "Merhaba", **keys})
    call("post", "/api/search", json={"query": "note", "mode": "hybrid", **keys})
    call("post", "/api/reindex", json={"mode": "hybrid", **keys})
    call("get", "/api/lab/index/status")
    call("get", "/api/lab/settings")
    call("post", "/api/lab/provider/check", json={"openai": {"apiKey": request_chat}})
    call("post", "/api/lab/provider/check", json={"embedding": {"apiKey": request_embedding}})
    call("put", "/api/lab/settings", json={"chat": {"apiKey": request_chat}})
    call("post", "/api/lab/heartbeat/run", json=keys)
    call("post", "/api/chat/flush", json={"forced": True, **keys})
    call("post", "/api/live-task/reset", json={})
    call("post", "/api/live-task/turn-stream", json={"message": "Merhaba", **keys})
    call("post", "/api/live-task/summary", json=keys)
    call("post", "/api/memory/promote", json=keys)
    call("post", "/api/dreaming/run", json={"phase": "deep", **keys})
    call("get", "/api/lab/consolidation")
    call("get", "/api/lab/turns/1")
    call("get", "/api/lab/events", params={"once": "true"})

    for body in bodies:
        for secret in secrets:
            assert secret not in body
    assert any("[redacted]" in body for body in bodies)
