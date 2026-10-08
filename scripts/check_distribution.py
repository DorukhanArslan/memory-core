"""Build and exercise both distributions outside the checkout (requires uv and dev tools)."""

from __future__ import annotations

import ast
from email import message_from_bytes
from email.message import Message
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

from memory_core.project_name import DIST_NAME, PACKAGE_NAME

ROOT = Path(__file__).resolve().parents[1]


def validate_files(files: set[str], *, kind: str) -> None:
    """Validate normalized file names without extracting an untrusted archive."""
    required = {f"{PACKAGE_NAME}/__init__.py", f"{PACKAGE_NAME}/py.typed"}
    notice = "LICENSE.openclaw"
    if kind == "sdist":
        # Hatch always includes its VCS ignore file in an sdist.
        # https://hatch.pypa.io/latest/plugins/builder/sdist/#default-file-selection
        allowed_root = {"pyproject.toml", "README.md", "CHANGELOG.md", "PKG-INFO",
                        ".gitignore", notice}
        required |= {"pyproject.toml", notice}
    elif kind == "wheel":
        allowed_root = set()
        notices = {p for p in files if p.endswith(f".dist-info/licenses/{notice}")}
        if len(notices) != 1:
            raise ValueError(f"Missing artifact file: {notice}")
        required |= notices
    else:
        raise ValueError(f"Unknown artifact kind: {kind}")
    for name in files:
        path = PurePosixPath(name)
        core_file = (
            path.parts[0] == PACKAGE_NAME
            and (name.endswith(".py") or name == f"{PACKAGE_NAME}/py.typed")
        )
        wheel_metadata = (
            kind == "wheel" and len(path.parts) >= 2
            and path.parts[0].endswith(".dist-info")
            and "/".join(path.parts[1:]) in {
                "METADATA", "WHEEL", "RECORD", f"licenses/{notice}",
            }
        )
        if ".." in path.parts or path.is_absolute() or not (
            core_file or wheel_metadata or name in allowed_root
        ):
            raise ValueError(f"Unexpected artifact file: {name}")
    for name in sorted(required - files):
        raise ValueError(f"Missing artifact file: {name}")


def validate_metadata(metadata: Message, *, name: str, version: str) -> None:
    for key, expected in (("Name", name), ("Version", version), ("Requires-Python", ">=3.11")):
        if metadata.get(key) != expected:
            raise ValueError(f"{key}: expected {expected!r}, got {metadata.get(key)!r}")
    if set(metadata.get_all("License-File", [])) != {"LICENSE.openclaw"}:
        raise ValueError("Missing upstream License-File metadata")
    if set(metadata.get_all("Provides-Extra", [])) != {"demo", "langgraph"}:
        raise ValueError("Unexpected optional extras")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    expected = {("", re.sub(r"\s+", "", spec)) for spec in project["dependencies"]}
    for extra, specs in project["optional-dependencies"].items():
        expected.update((extra, re.sub(r"\s+", "", spec)) for spec in specs)
    actual = set()
    for requirement in metadata.get_all("Requires-Dist", []):
        spec, separator, marker = requirement.partition(";")
        extra = ""
        if separator:
            match = re.fullmatch(r"\s*extra\s*==\s*['\"]([^'\"]+)['\"]\s*", marker)
            if match is None:
                raise ValueError(f"Unexpected dependency marker: {marker}")
            extra = match[1]
        actual.add((extra, re.sub(r"\s+", "", spec)))
    if actual != expected:
        raise ValueError(f"Artifact dependencies differ from declaration: {actual ^ expected}")


def inspect_distribution(artifact: Path, *, version: str) -> None:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            files = {p for p in archive.namelist() if not p.endswith("/")}
            validate_files(files, kind="wheel")
            metadata_path = next(p for p in files if p.endswith(".dist-info/METADATA"))
            notice_path = next(p for p in files if p.endswith("/LICENSE.openclaw"))
            metadata = archive.read(metadata_path)
            notice = archive.read(notice_path)
    else:
        with tarfile.open(artifact) as archive:
            members = {p.name: p for p in archive.getmembers() if not p.isdir()}
            prefix = f"{PACKAGE_NAME}-{version}/"
            if not all(p.startswith(prefix) and member.isfile() for p, member in members.items()):
                raise ValueError("Unexpected sdist root or non-regular file")
            validate_files({p.removeprefix(prefix) for p in members}, kind="sdist")
            metadata = archive.extractfile(members[prefix + "PKG-INFO"]).read()
            notice = archive.extractfile(members[prefix + "LICENSE.openclaw"]).read()
    validate_metadata(message_from_bytes(metadata), name=DIST_NAME, version=version)
    if notice != (ROOT / "LICENSE.openclaw").read_bytes():
        raise ValueError("Upstream license notice changed in artifact")


# This program runs with -I from scratch, using only the installed artifact and core deps.
# The text fixture is shared with tests/unit/test_host_kit_dispatch.py.
SMOKE = '''
import importlib
import importlib.metadata
import importlib.util
from pathlib import Path
import pkgutil
import sys
import tempfile
import tomllib

package_name, dist_name, version, checkout = sys.argv[1:]
core = importlib.import_module(package_name)
assert core.__version__ == importlib.metadata.version(dist_name) == version
assert Path(checkout).resolve() not in Path(core.__file__).resolve().parents
assert Path(core.__file__).with_name("py.typed").is_file()
for name in core.__all__:
    getattr(core, name)
for module in pkgutil.walk_packages(core.__path__, core.__name__ + "."):
    importlib.import_module(module.name)
for optional in ("fastapi", "jinja2", "uvicorn", "langgraph", "langchain_core", "openai"):
    assert importlib.util.find_spec(optional) is None, optional

with tempfile.TemporaryDirectory() as scratch:
    root = Path(scratch)
    flags = core.FeatureFlags(vector_search=False, temporal_decay=False)
    kit = core.HostKit.open(root, config=core.MemoryConfig(workspace_dir=root, flags=flags))
    kit.memory.workspace.append_daily_memory(
        "memory/2026-09-25.md", "- The zephyrquartz project is paused."
    )
    kit.memory.store.reindex(kit.memory.workspace)
    state = core.SessionState.new(session_key="agent:main:main", session_id="s1")
    turn = kit.before_turn(state)
    found = kit.dispatch("memory_search", {"query": "zephyrquartz"}, session=turn.session)
    assert [hit["path"] for hit in found["results"]] == ["memory/2026-09-25.md"], found
    retrieved = kit.dispatch("memory_get", {"path": "memory/2026-09-25.md"}, session=turn.session)
    assert retrieved["status"] == "ok", retrieved
    assert retrieved["text"].strip() == "- The zephyrquartz project is paused.", retrieved
    record = kit.after_turn(turn.session, transcript=(), usage=core.TurnUsage(1, 1))
    assert record.session.session_id == "s1" and record.flush is None
print("installed core imports and FTS host lifecycle passed")
'''


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> None:
    version_tree = ast.parse((ROOT / PACKAGE_NAME / "__init__.py").read_text(encoding="utf-8"))
    version = next(
        ast.literal_eval(node.value)
        for node in version_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    )
    # Avoid inheriting editable-package search paths into artifact consumers.
    env = dict(os.environ)
    for name in ("PYTHONPATH", "MYPYPATH", "UV_PROJECT", "UV_PROJECT_ENVIRONMENT"):
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix=f"{DIST_NAME}-distribution-") as scratch:
        work = Path(scratch)
        dist = work / "dist"
        _run(["uv", "build", str(ROOT), "--python", sys.executable, "--out-dir", str(dist)],
             cwd=work, env=env)
        wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ValueError(f"Expected one wheel and one sdist, got {wheels + sdists}")
        artifacts = wheels + sdists
        smoke = work / "smoke.py"
        smoke.write_text(SMOKE, encoding="utf-8")
        for i, artifact in enumerate(artifacts):
            inspect_distribution(artifact, version=version)
            venv = work / f"install-{i}"
            _run(["uv", "venv", "--no-project", "--python", sys.executable, str(venv)],
                 cwd=work, env=env)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            _run(["uv", "pip", "install", "--python", str(python), str(artifact)], cwd=work, env=env)
            _run(["uv", "pip", "check", "--python", str(python)], cwd=work, env=env)
            _run([str(python), "-I", str(smoke), PACKAGE_NAME, DIST_NAME, version, str(ROOT)],
                 cwd=work, env=env)
            _run([sys.executable, str(ROOT / "tests/typing/check_consumer.py"),
                  "--python-executable", str(python)], cwd=work, env=env)
            print(f"PASS {artifact.name}: contents, notice, metadata, core install, API types", flush=True)


if __name__ == "__main__":
    main()
