import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from memory_core.project_name import DIST_NAME, PACKAGE_NAME

ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _project() -> dict:
    return _pyproject()["project"]


def _third_party_import_roots() -> set[str]:
    roots: set[str] = set()
    for source in (ROOT / PACKAGE_NAME).rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots.add(node.module.split(".")[0])
    return roots - set(sys.stdlib_module_names) - {PACKAGE_NAME}


def test_core_dependencies_are_exactly_what_memory_core_imports():
    names = {re.split(r"[\s<>=!~;\[]", spec, maxsplit=1)[0] for spec in _project()["dependencies"]}

    assert names == _third_party_import_roots() == {"httpx"}


def test_demo_and_langgraph_are_the_only_extras_and_dev_tools_a_group():
    # The wheel's metadata advertises the demo extra and the langgraph extra (the stack the
    # LangGraph adapter is tested against; the adapter imports none of it). The provider the
    # example uses, pytest and ruff are the PEP 735 dev group, which `uv sync` installs in a
    # checkout.
    extras = _project()["optional-dependencies"]
    groups = _pyproject()["dependency-groups"]

    assert set(extras) == {"demo", "langgraph"}
    assert {spec.split(">=")[0] for spec in extras["demo"]} == {"fastapi", "jinja2", "uvicorn"}
    assert {spec.split(">=")[0] for spec in extras["langgraph"]} == {"langgraph", "langchain-core"}
    assert set(groups) == {"dev"}
    assert {spec.split(">=")[0] for spec in groups["dev"]} == {
        f"{DIST_NAME}[demo]",
        f"{DIST_NAME}[langgraph]",
        "langchain-openai",
        "pytest",
        "ruff",
    }


def test_importing_the_langgraph_adapter_loads_no_framework():
    script = (
        "import sys\n"
        "import memory_core.adapters.langgraph\n"
        "loaded = {'langchain_core', 'langgraph', 'langchain_openai', 'openai'} & set(sys.modules)\n"
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
