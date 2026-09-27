"""Lab v2 shell: the Jinja shell, its static modules and the locked stylesheet strings.

The shell has no inline script or style (CSP-compatible), the client talks only to the
Lab API, and the OpenClaw name stays on the parity surface. Behaviour of the ES modules
is checked in the browser verification pass (DESIGN §8.6); these tests pin the contract
that can be read statically.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from demo.app import app

DEMO_ROOT = Path(__file__).resolve().parents[2] / "demo"
LAB_ROOT = DEMO_ROOT / "static" / "lab"
LAB_MODULES = sorted(LAB_ROOT.rglob("*.js"))

SHELL_TESTIDS = (
    "app-shell",
    "top-bar",
    "rail",
    "explorer",
    "center",
    "inspector",
    "status-bar",
    "mobile-nav",
    "resizer-explorer",
    "resizer-inspector",
    "skip-link",
)
LOCKED_CSS = (
    "color-scheme: dark",
    "overflow: auto",
    "min-height: 100dvh",
    "grid-template-columns: minmax(0, 1.35fr) minmax(360px, 0.75fr)",
    "@media (max-width: 820px)",
    "@media (max-width: 640px)",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_shell_is_served_with_landmarks_and_testids(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert '<html lang="tr" data-theme="dark">' in html
    assert "<title>memory-core Lab</title>" in html
    for testid in SHELL_TESTIDS:
        assert f'data-testid="{testid}"' in html, testid
    for landmark in ('<header id="topbar"', '<nav id="rail"', '<aside id="explorer"', '<main id="center"', '<aside id="inspector"', '<footer id="statusbar"'):
        assert landmark in html
    assert 'aria-label="Görünümler"' in html
    assert 'aria-label="Sistem Dosyaları"' in html
    assert 'aria-label="Denetçi"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-live="assertive"' in html


def test_shell_loads_only_the_module_and_stylesheet(client: TestClient) -> None:
    html = client.get("/").text

    assert '<script type="module" src="/static/lab/app.js"></script>' in html
    assert '<link rel="stylesheet" href="/static/styles.css">' in html
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert scripts == ['<script type="module" src="/static/lab/app.js">']
    assert "<style" not in html
    assert " style=" not in html
    assert " onclick=" not in html
    assert "script-src 'self'" in html
    assert "style-src 'self'" in html
    assert "cdn" not in html.lower()


def test_shell_ships_the_icon_sprite(client: TestClient) -> None:
    html = client.get("/").text

    for name in ("mark", "message", "heart-pulse", "merge", "waveform", "scale", "flask", "sliders", "tool", "puzzle", "alert-triangle", "alert-octagon"):
        assert f'<symbol id="i-{name}"' in html, name


def test_stylesheet_keeps_the_locked_strings(client: TestClient) -> None:
    response = client.get("/static/styles.css")

    assert response.status_code == 200
    css = response.text
    for locked in LOCKED_CSS:
        assert locked in css, locked
    assert '@media (prefers-color-scheme: light)' in css
    assert ':root[data-theme="light"]' in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "transition: all" not in css
    assert "@import" not in css
    assert "url(http" not in css


def test_every_lab_module_is_served(client: TestClient) -> None:
    assert (LAB_ROOT / "app.js") in LAB_MODULES
    for module in LAB_MODULES:
        rel = module.relative_to(DEMO_ROOT / "static").as_posix()
        response = client.get(f"/static/{rel}")
        assert response.status_code == 200, rel
        assert "javascript" in response.headers["content-type"], rel


@pytest.mark.parametrize("module", LAB_MODULES, ids=lambda p: p.relative_to(LAB_ROOT).as_posix())
def test_lab_modules_build_dom_without_html_sinks(module: Path) -> None:
    source = module.read_text(encoding="utf-8")

    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "new Function", "eval("):
        assert sink not in source, sink
    assert "setAttribute('style'" not in source
    assert "https://" not in source


def test_lab_modules_resolve_their_imports() -> None:
    exports: dict[Path, set[str]] = {}
    for module in LAB_MODULES:
        source = module.read_text(encoding="utf-8")
        names = set(re.findall(r"export\s+(?:async\s+)?(?:function\*?|const|let|class)\s+([A-Za-z_$][\w$]*)", source))
        for group in re.findall(r"export\s*\{([^}]*)\}", source):
            names.update(part.split(" as ")[-1].strip() for part in group.split(",") if part.strip())
        exports[module.resolve()] = names
    for module in LAB_MODULES:
        source = module.read_text(encoding="utf-8")
        for names, target in re.findall(r"import\s*\{([^}]*)\}\s*from\s*'([^']+)'", source):
            path = (module.parent / target).resolve()
            assert path in exports, f"{module.name} imports missing {target}"
            for part in names.split(","):
                name = part.split(" as ")[0].strip()
                if name:
                    assert name in exports[path], f"{module.name}: {name} from {target}"


def test_openclaw_name_stays_on_the_parity_surface() -> None:
    for module in LAB_MODULES:
        source = module.read_text(encoding="utf-8")
        if module.name == "parity.js":
            continue
        for line in source.splitlines():
            if "OpenClaw" in line or "openclaw" in line:
                assert module.parent.name == "i18n" and ("'parity." in line or line.strip().startswith("//")), f"{module.name}: {line.strip()[:80]}"


def test_client_defaults_come_from_the_settings_endpoint() -> None:
    for module in LAB_MODULES:
        source = module.read_text(encoding="utf-8")
        assert "openrouter.ai/api" not in source, module.name
        assert "gpt-4o" not in source, module.name
        assert "localStorage.setItem('lab.key" not in source, module.name


def test_ui_copy_carries_no_internal_decision_ids() -> None:
    # Decision ids such as Q9 or D5 belong to the project notes, not to what the Lab shows.
    for module in LAB_MODULES:
        for line in module.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("//"):
                continue
            assert not re.search(r"\((?:Q|D)\d+\b", line), f"{module.name}: {line.strip()[:80]}"


def test_i18n_dictionaries_share_their_ids() -> None:
    def ids(name: str) -> set[str]:
        return set(re.findall(r"'([a-zA-Z][\w.-]*(?:\.[\w-]+)+)':", (LAB_ROOT / "i18n" / name).read_text(encoding="utf-8")))

    tr, en = ids("tr.js"), ids("en.js")
    assert tr
    assert tr == en
    used = set()
    for module in LAB_MODULES:
        if module.parent.name != "i18n":
            used.update(re.findall(r"\bt\('([^']+)'", module.read_text(encoding="utf-8")))
    assert used <= tr, sorted(used - tr)


def test_diff_row_sources_are_read_only_through_the_normaliser() -> None:
    """/api/lab/diff rows carry ``sources[]`` as objects; only ui/diff.js unpacks them."""
    for module in LAB_MODULES:
        rel = module.relative_to(LAB_ROOT).as_posix()
        for line in module.read_text(encoding="utf-8").splitlines():
            if re.search(r"\.sources\b", line):
                assert rel == "ui/diff.js" and "row?.sources" in line, f"{rel}: {line.strip()[:80]}"


# --- contract: fields the Lab modules read exist in the real backend payloads ---------------


@pytest.fixture
def lab_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from demo.app import create_app
    from demo.lab_runtime import LabRuntime

    for name in ("MEMORY_CORE_DEMO_OPENAI_API_KEY", "MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY"):
        monkeypatch.setenv(name, "")
    return TestClient(create_app(LabRuntime(tmp_path)))


def test_contract_diff_sources_are_objects_with_a_source_name(lab_client: TestClient) -> None:
    lab_client.post("/api/lab/workspace/reset", json={"mode": "fresh"})
    identity = lab_client.get("/api/lab/file", params={"path": "IDENTITY.md"}).json()
    lab_client.put(
        "/api/lab/file",
        json={"path": "IDENTITY.md", "content": identity["content"] + "\n", "baseSha256": identity["sha256"]},
    )

    rows = {row["path"]: row for row in lab_client.get("/api/lab/diff", params={"since": "reset"}).json()}

    # scenarios/checks.js fileDeleted(BOOTSTRAP.md, {source: lifecycle}) reads these fields.
    deleted = rows["BOOTSTRAP.md"]
    assert deleted["status"] == "deleted"
    assert isinstance(deleted["sources"][0], dict)
    assert {"source", "turnId", "ts", "eventId", "status"} <= set(deleted["sources"][0])
    assert "lifecycle" in [s["source"] for s in deleted["sources"]]
    assert {"path", "status", "diff", "added", "removed", "hidden"} <= set(rows["IDENTITY.md"])


def test_contract_parity_rows_and_commands(lab_client: TestClient) -> None:
    # views/parity.js reads these MatrixRow fields, `commands[]` and the results file keys.
    payload = lab_client.get("/api/lab/parity").json()

    assert {"pin", "oracleRepo", "node", "resultsPath", "results", "matrix", "commands"} <= set(payload)
    assert payload["commands"] and all(isinstance(cmd, str) for cmd in payload["commands"])
    row = payload["matrix"][0]
    assert set(row) == {"area", "openclawSource", "pythonSource", "oracleOperation", "status", "knownGaps", "nextTest", "priority"}
    assert isinstance(row["knownGaps"], str)
    assert {row["status"] for row in payload["matrix"]} <= {"match", "partial", "mismatch", "missing", "out of scope"}
    source = (LAB_ROOT / "views" / "parity.js").read_text(encoding="utf-8")
    for field in ("knownGaps", "oracleOperation", "byEvidence", "byArea", "evidenceKinds", "commands"):
        assert field in source, field
    for stale in ("m.evidence", "m.gaps", "'python_ts'", "x.comparison"):
        assert stale not in source, stale


def test_contract_file_entries_for_folders(lab_client: TestClient) -> None:
    # views/explorer.js groupFiles(): the memory folder entry heads the memory section; user/
    # and workspace/ are extension folders only when their badges say so.
    lab_client.post("/api/lab/workspace/reset", json={"mode": "seeded"})
    entries = lab_client.get("/api/lab/files").json()
    folders = {e["path"]: e for e in entries if e["kind"] == "folder"}

    assert folders["memory"]["badges"] == []
    assert folders["memory"]["note"] == "indexed, not injected"
    for name in ("user", "workspace"):
        if name in folders:
            assert folders[name]["badges"] in (["extension"], ["outside_layout"])
    source = (LAB_ROOT / "views" / "explorer.js").read_text(encoding="utf-8")
    assert "dir === 'memory'" in source


def test_no_debug_global_exposes_the_store() -> None:
    # store.keys holds page API keys; nothing may hang the store or the actions on window.
    for module in LAB_MODULES:
        source = module.read_text(encoding="utf-8")
        assert "window.__" not in source, module.name
        assert "globalThis." not in source, module.name


def test_event_stream_reads_default_messages_only() -> None:
    # /api/lab/events frames carry no `event:` line (docs/lab.md), so per-type listeners get nothing.
    source = (LAB_ROOT / "events.js").read_text(encoding="utf-8")
    assert "es.onmessage = handle" in source
    assert "addEventListener(" not in source
    store = (LAB_ROOT / "store.js").read_text(encoding="utf-8")
    assert "lab.resync" in store and "replayCutoff" in store


def test_settings_offer_no_per_turn_flush(lab_client: TestClient) -> None:
    # D1 removed the per-turn demo flush; the backend reports mode threshold and rejects others.
    assert lab_client.get("/api/lab/settings").json()["flush"]["mode"] == "threshold"
    assert lab_client.put("/api/lab/settings", json={"flush": {"mode": "per_turn"}}).status_code == 400
    for module in LAB_MODULES:
        assert "per_turn" not in module.read_text(encoding="utf-8"), module.name
    snapshot = lab_client.get("/api/lab/state").json()["flush"]
    shell = (LAB_ROOT / "views" / "shell.js").read_text(encoding="utf-8")
    for field in ("reserveTokensFloor", "softThresholdTokens", "contextWindowTokens", "alreadyFlushed", "compactionCount", "reason", "defaults"):
        assert field in snapshot, field
        assert field in shell, field
    # v2026.9.6: the window caps both terms; the tooltip shows the rules with the server's defaults.
    assert snapshot["defaults"] == {"reserveTokensFloor": 20_000, "softThresholdTokens": 4_000}
    assert "flush.reserveRule" in shell and "flush.softRule" in shell
    settings_view = (LAB_ROOT / "views" / "settings.js").read_text(encoding="utf-8")
    assert "settings-flush-derived" in settings_view and "s.flush?.reserveTokensFloor" in settings_view
    prompt_view = (LAB_ROOT / "inspector" / "prompt.js").read_text(encoding="utf-8")
    assert "dd.memoryFlush" in prompt_view and "dd.reserveTokensFloor" in prompt_view


def test_prompt_inspector_separates_the_flush_decision_from_the_flush_turn() -> None:
    # The decision reads "run"/"skip"; what happened comes from the run or the flush stage
    # (a scripted engine decides "run" and skips the turn). The time format is host-supplied.
    prompt_view = (LAB_ROOT / "inspector" / "prompt.js").read_text(encoding="utf-8")
    assert "dd.shouldRun ? t('flush.decideRun') : t('flush.decideSkip')" in prompt_view
    assert "x.name === 'flush'" in prompt_view and "st?.status === 'skip'" in prompt_view
    assert "prompt-flush-outcome" in prompt_view and "dd.timeFormat" in prompt_view
    assert "dd.shouldRun ? t('flush.ran')" not in prompt_view
    tr = (LAB_ROOT / "i18n" / "tr.js").read_text(encoding="utf-8")
    en = (LAB_ROOT / "i18n" / "en.js").read_text(encoding="utf-8")
    for key in ("flush.decideRun", "flush.decideSkip", "flush.outcome", "flush.skipped", "flush.failed",
                "flush.wrote", "flush.noWrite", "flush.timeFormat", "flush.timeFormatNote"):
        assert f"'{key}':" in tr and f"'{key}':" in en, key
    assert "'flush.decideRun': 'çalıştır'" in tr and "'flush.skipped': 'atlandı'" in tr
    assert "upstream detects the host" in en


def test_contract_heartbeat_fields(lab_client: TestClient) -> None:
    # views/heartbeat.js reads the unparsed count, its label and the keyless preflight.
    hb = lab_client.get("/api/lab/heartbeat").json()
    for field in ("unparsedTaskEntries", "preflight", "labels", "file", "tasks", "runs"):
        assert field in hb, field
    assert {"skipReason", "dueTasks"} <= set(hb["preflight"])
    source = (LAB_ROOT / "views" / "heartbeat.js").read_text(encoding="utf-8")
    assert "unparsedTaskEntries" in source and "unparsedCount" not in source
    assert "memoryTools" not in source
    assert "disabled: noKey" not in source


def test_how_it_works_disclosures_have_both_languages() -> None:
    # D6: one collapsed "Nasıl çalışır?" per view; every bullet id exists in TR and EN.
    kit = (LAB_ROOT / "ui" / "kit.js").read_text(encoding="utf-8")
    counts = dict(re.findall(r"(\w+): (\d+)", re.search(r"const HOW = \{([^}]*)\}", kit).group(1)))
    assert set(counts) == {"chat", "heartbeat", "consolidation", "live", "parity", "memory"}
    tr = (LAB_ROOT / "i18n" / "tr.js").read_text(encoding="utf-8")
    en = (LAB_ROOT / "i18n" / "en.js").read_text(encoding="utf-8")
    for view, n in counts.items():
        prefix = "parity.how" if view == "parity" else f"how.{view}"
        for key in [f"{prefix}.{i}" for i in range(1, int(n) + 1)] + [f"{prefix}.src"]:
            assert f"'{key}':" in tr and f"'{key}':" in en, key
    for module in ("views/chat.js", "views/heartbeat.js", "views/consolidation.js", "views/live.js", "views/parity.js", "inspector/memory.js"):
        assert "howItWorks(" in (LAB_ROOT / module).read_text(encoding="utf-8"), module


def test_contract_live_state_engine_and_provider_check_target(lab_client: TestClient) -> None:
    # views/live.js seeds the engine chip from state.engine; checks.js matches provider.check on target.
    state = lab_client.get("/api/live-task/state").json()
    assert state["engine"]["mode"] in ("llm", "scripted") and "model" in state["engine"]
    assert "identityFiles" not in state and "workspaceInjectedFiles" in state
    start = lab_client.get("/api/lab/state").json()["lastEventId"]
    result = lab_client.post("/api/lab/provider/check", json={"embedding": {}}).json()
    assert result["target"] == "embedding"
    body = lab_client.get("/api/lab/events", params={"once": "true"}, headers={"Last-Event-ID": str(start)}).text
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    check = [e for e in events if e["type"] == "provider.check"][-1]
    assert check["data"]["target"] == "embedding"
    assert "e.data?.target === which" in (LAB_ROOT / "scenarios" / "checks.js").read_text(encoding="utf-8")
    assert "st.engine.mode" in (LAB_ROOT / "views" / "live.js").read_text(encoding="utf-8")


def test_s11_window_and_its_arithmetic_match_the_flush_plan() -> None:
    # S11 sets a test window; its expect text spells out the v2026.9.6 derivation, which must
    # equal what the backend computes for that window (flush-plan.ts, agent-runner-memory.ts).
    from memory_core.memory_flush import build_memory_flush_plan, resolve_memory_flush_threshold

    catalog = (LAB_ROOT / "scenarios" / "catalog.js").read_text(encoding="utf-8")
    window = int(re.search(r"id: 'S11'.*?contextWindowTokens: (\d+)", catalog, re.DOTALL).group(1))
    plan = build_memory_flush_plan(workspace_dir=None, context_window_tokens=window)
    threshold = resolve_memory_flush_threshold(
        context_window_tokens=window,
        reserve_tokens_floor=plan.reserve_tokens_floor,
        soft_threshold_tokens=plan.soft_threshold_tokens,
    )
    en = (LAB_ROOT / "i18n" / "en.js").read_text(encoding="utf-8")
    tr = (LAB_ROOT / "i18n" / "tr.js").read_text(encoding="utf-8")

    assert (window, plan.reserve_tokens_floor, plan.soft_threshold_tokens, threshold) == (5_333, 1_333, 2_000, 2_000)
    assert "threshold = 5,333 − 1,333 − 2,000 = 2,000 tokens" in en
    assert "eşik = 5.333 − 1.333 − 2.000 = 2.000 token" in tr
    assert "26,000" not in en and "26.000" not in tr
