import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def _third_party_import_roots() -> set[str]:
    roots: set[str] = set()
    for source in (ROOT / "memory-core").rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots.add(node.module.split(".")[0])
    return roots - set(sys.stdlib_module_names) - {"memory-core"}


def test_core_dependencies_are_exactly_what_memory_core_imports():
    names = {re.split(r"[\s<>=!~;\[]", spec, maxsplit=1)[0] for spec in _project()["dependencies"]}

    assert names == _third_party_import_roots() == {"httpx"}


def test_demo_dependencies_are_an_extra():
    extras = _project()["optional-dependencies"]

    assert {spec.split(">=")[0] for spec in extras["demo"]} == {"fastapi", "jinja2", "uvicorn"}
    assert "memory-core[demo]" in extras["dev"]


def test_importing_memory_core_loads_no_demo_dependency():
    script = (
        "import sys\n"
        "import memory_core, memory_core.host\n"
        "loaded = {'fastapi', 'starlette', 'jinja2', 'uvicorn', 'pydantic'} & set(sys.modules)\n"
        "assert not loaded, loaded\n"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
