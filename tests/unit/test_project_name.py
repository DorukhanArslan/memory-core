"""One declaration of the project name, and the script that renames the project from it.

pyproject.toml declares the name; ``scripts/rename_project.py --check`` keeps the package
directory, the constant module, pyproject.toml, uv.lock and the runtime code consistent with it,
and ``--to`` renames the whole tree. Each rename here runs on a copy of the tracked tree, and
this file, like the script, spells no project name: both read it from the declaration.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "rename_project.py"
# OpenClaw's own memory component, whose name the project takes: a rename through it must
# leave every upstream spelling as it was.
UPSTREAM_COMPONENT = "memory-core"
PROBE_DIST, PROBE_DISPLAY = "probe-kit", "Probe Kit"

# Runs inside a renamed tree: the package imports under its new name, and the constant module,
# the runtime identity and the Lab report the new name forms.
PROBE = """
import json

import demo
from demo import lab_runtime
from probe_kit import project_name
from probe_kit.runtime_identity import PROBE_KIT_RUNTIME_IDENTITY as identity

print(json.dumps({
    "names": [
        project_name.DIST_NAME,
        project_name.DISPLAY_NAME,
        project_name.PACKAGE_NAME,
        project_name.UPPER_NAME,
        project_name.ENV_PREFIX,
        project_name.STATE_DIRNAME,
    ],
    "identity": [identity.runtime_context_begin, identity.heartbeat_transcript_prompt],
    "lab": [demo.LAB_TITLE, lab_runtime.LAB_WORKSPACE_DIRNAME, lab_runtime.CHAT_API_KEY_ENV],
}))
"""


def _load_script():
    spec = importlib.util.spec_from_file_location("rename_project_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rename_project = _load_script()


def _run(tree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/rename_project.py", *args],
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _copy_tracked_tree(target: Path) -> Path:
    for path in rename_project.tracked_files(ROOT):
        source = ROOT / path
        if source.is_file():
            (target / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / path)
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(["git", "add", "-A", "-f"], cwd=target, check=True)
    return target


def _tree_bytes(tree: Path) -> dict[str, bytes]:
    return {
        path: (tree / path).read_bytes()
        for path in rename_project.tracked_files(tree)
        if (tree / path).is_file()
    }


def _protected_by_file(tree: Path) -> dict[str, list[str]]:
    found = {}
    for path, data in _tree_bytes(tree).items():
        spans = rename_project.protected_spans(data.decode("utf-8", errors="replace"))
        if spans:
            text = data.decode("utf-8", errors="replace")
            found[path] = [text[start:end] for start, end in spans]
    return found


@pytest.fixture(scope="module")
def probe_tree(tmp_path_factory) -> Path:
    tree = _copy_tracked_tree(tmp_path_factory.mktemp("probe"))
    result = _run(tree, "--to", PROBE_DIST, "--display", PROBE_DISPLAY)
    assert result.returncode == 0, result.stdout + result.stderr
    return tree


def test_the_tree_passes_the_name_check():
    result = _run(ROOT, "--check")

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_probe_rename_renames_the_package_and_every_derived_name(probe_tree):
    probe = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=probe_tree,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )

    assert probe.returncode == 0, probe.stderr
    assert json.loads(probe.stdout) == {
        "names": ["probe-kit", "Probe Kit", "probe_kit", "PROBE_KIT", "PROBE_KIT_", ".probe-kit"],
        "identity": ["<<<BEGIN_PROBE_KIT_INTERNAL_CONTEXT>>>", "[Probe Kit heartbeat poll]"],
        "lab": ["Probe Kit Lab", "probe-kit-lab-workspace", "PROBE_KIT_DEMO_OPENAI_API_KEY"],
    }
    assert rename_project.read_declaration(probe_tree) == rename_project.ProjectName(
        PROBE_DIST, PROBE_DISPLAY
    )
    assert _run(probe_tree, "--check").returncode == 0


def test_a_probe_rename_leaves_no_old_spelling_and_every_upstream_spelling(probe_tree):
    old = rename_project.read_declaration(ROOT)
    renamed = _tree_bytes(probe_tree)
    stale = {
        path: [match.group() for match in rename_project.name_matches(data.decode("utf-8"), old)]
        for path, data in renamed.items()
        if rename_project.in_scope(path)
    }

    assert {path: found for path, found in stale.items() if found} == {}
    assert not (probe_tree / old.package).exists()
    assert _protected_by_file(probe_tree) == {
        path.replace(f"{old.package}/", "probe_kit/", 1)
        if path.startswith(f"{old.package}/")
        else path: spans
        for path, spans in _protected_by_file(ROOT).items()
    }
    original = _tree_bytes(ROOT)
    untouched = [path for path in original if not rename_project.in_scope(path)]
    assert untouched
    assert {path: renamed[path] == original[path] for path in untouched} == {
        path: True for path in untouched
    }


def test_a_rename_through_the_upstream_component_name_equals_a_direct_one(probe_tree, tmp_path):
    tree = _copy_tracked_tree(tmp_path)
    for args in (
        ("--to", "probe-a", "--display", "Probe A"),
        ("--to", UPSTREAM_COMPONENT),
        ("--to", PROBE_DIST, "--display", PROBE_DISPLAY),
    ):
        result = _run(tree, *args)
        assert result.returncode == 0, (args, result.stdout + result.stderr)

    direct, detour = _tree_bytes(probe_tree), _tree_bytes(tree)
    assert sorted(detour) == sorted(direct)
    assert [path for path in direct if detour[path] != direct[path]] == []


def test_a_rename_to_a_name_the_tree_already_spells_is_refused(tmp_path):
    tree = _copy_tracked_tree(tmp_path)

    result = _run(tree, "--to", "memory")

    assert result.returncode == 1
    assert "already spells memory" in result.stderr
    assert subprocess.run(["git", "diff", "--quiet"], cwd=tree, check=False).returncode == 0


def test_the_check_reports_a_drifted_constant_module_and_spelled_names(tmp_path):
    tree = _copy_tracked_tree(tmp_path)
    name = rename_project.read_declaration(tree)
    module = tree / name.package / rename_project.CONSTANT_MODULE
    module.write_text(
        module.read_text(encoding="utf-8").replace(
            f"DISPLAY_NAME = {json.dumps(name.display)}", 'DISPLAY_NAME = "Drift"'
        ),
        encoding="utf-8",
    )
    with (tree / "demo" / "lab_runtime.py").open("a", encoding="utf-8") as handle:
        handle.write(f'\nSPELLED = "{name.display} Lab"\n')
    # The camel form too, although the oracle runner's upstream local shares it.
    with (tree / "demo" / "static" / "lab" / "project.js").open("a", encoding="utf-8") as handle:
        handle.write(f'\nexport const SPELLED = "{name.spell("camel")}";\n')

    result = _run(tree, "--check")

    assert result.returncode == 1
    problems = result.stdout.splitlines()
    assert len(problems) == 3, problems
    assert "DISPLAY_NAME" in problems[0]
    assert problems[1].startswith("demo/lab_runtime.py:")
    assert problems[2].startswith("demo/static/lab/project.js:")


def test_the_check_lists_each_place_a_hand_edited_name_disagrees_with(tmp_path):
    tree = _copy_tracked_tree(tmp_path)
    name = rename_project.read_declaration(tree)
    pyproject = tree / rename_project.PYPROJECT
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            f'\nname = "{name.dist}"\n', f'\nname = "{PROBE_DIST}"\n', 1
        ),
        encoding="utf-8",
    )

    result = _run(tree, "--check")

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"pyproject.toml: the declared name is {PROBE_DIST}, but the display-name table is"
        f" [tool.{name.package}], not [tool.probe_kit]",
        "the package directory probe_kit/ is missing",
        "pyproject.toml: the dev dependency group does not hold 'probe-kit[demo]'",
        "pyproject.toml: [tool.hatch.version] path does not hold 'probe_kit/__init__.py'",
        "pyproject.toml: the wheel packages does not hold 'probe_kit'",
        "pyproject.toml: the sdist only-include does not hold 'probe_kit'",
        f"uv.lock: the project's own entry is [{name.dist!r}], not ['probe-kit']",
    ]
