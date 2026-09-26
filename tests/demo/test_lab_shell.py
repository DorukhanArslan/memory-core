"""Lab v2 shell: the Jinja shell, its static modules and the locked stylesheet strings.

The shell has no inline script or style (CSP-compatible), the client talks only to the
Lab API, and the OpenClaw name stays on the parity surface. Behaviour of the ES modules
is checked in the browser verification pass (DESIGN §8.6); these tests pin the contract
that can be read statically.
"""

from __future__ import annotations

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
