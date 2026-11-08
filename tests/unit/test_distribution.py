"""Reject artifacts which could leak checkout files or lose installation metadata."""

from email.message import Message

import pytest

from scripts.check_distribution import validate_files, validate_metadata


def test_wheel_rejects_private_or_checkout_files():
    valid = {
        "memory_core/__init__.py", "memory_core/py.typed",
        "memory_core-0.2.0.dist-info/METADATA",
        "memory_core-0.2.0.dist-info/licenses/LICENSE.openclaw",
    }
    validate_files(valid, kind="wheel")
    for forbidden in (".env", "workspace/MEMORY.md", "demo/app.py", "trace/live.jsonl"):
        with pytest.raises(ValueError, match="Unexpected artifact file"):
            validate_files(valid | {forbidden}, kind="wheel")


def test_artifacts_require_types_and_upstream_notice():
    for kind, valid in (
        ("wheel", {"memory_core/__init__.py", "memory_core/py.typed",
                   "memory_core-0.2.0.dist-info/licenses/LICENSE.openclaw"}),
        ("sdist", {"memory_core/__init__.py", "memory_core/py.typed", "LICENSE.openclaw",
                   "pyproject.toml", "README.md", "CHANGELOG.md", "PKG-INFO", ".gitignore"}),
    ):
        validate_files(valid, kind=kind)
        for required in ("memory_core/py.typed", next(p for p in valid if p.endswith("LICENSE.openclaw"))):
            with pytest.raises(ValueError, match="Missing artifact file"):
                validate_files(valid - {required}, kind=kind)


def test_metadata_rejects_missing_or_accidental_runtime_dependencies():
    metadata = Message()
    metadata["Name"] = "memory-core"
    metadata["Version"] = "0.2.0"
    metadata["Requires-Python"] = ">=3.11"
    metadata["License-File"] = "LICENSE.openclaw"
    metadata["Provides-Extra"] = "demo"
    metadata["Provides-Extra"] = "langgraph"
    metadata["Requires-Dist"] = "httpx>=0.27"
    metadata["Requires-Dist"] = "zstandard>=0.23; python_version < '3.14'"
    metadata["Requires-Dist"] = 'fastapi>=0.115; extra == "demo"'
    metadata["Requires-Dist"] = 'jinja2>=3.1; extra == "demo"'
    metadata["Requires-Dist"] = 'uvicorn>=0.30; extra == "demo"'
    metadata["Requires-Dist"] = 'langgraph>=1.2; extra == "langgraph"'
    metadata["Requires-Dist"] = 'langchain-core>=1.6; extra == "langgraph"'
    validate_metadata(metadata, name="memory-core", version="0.2.0")
    for requirement in (
        "fastapi>=0.115", 'pytest>=8.3; python_version >= "3.11"',
        'fastapi>=0.115; sys_platform == "win32"',
        'zstandard>=0.23; python_version < "3.15"',
    ):
        bad = Message()
        for key, value in metadata.items():
            bad[key] = value
        bad["Requires-Dist"] = requirement
        with pytest.raises(ValueError, match="dependencies|marker"):
            validate_metadata(bad, name="memory-core", version="0.2.0")
    del metadata["Requires-Dist"]
    metadata["Requires-Dist"] = "httpx>=0.27"
    with pytest.raises(ValueError, match="dependencies"):
        validate_metadata(metadata, name="memory-core", version="0.2.0")


def test_metadata_requires_the_requested_version():
    metadata = Message()
    metadata["Name"] = "memory-core"
    metadata["Version"] = "0.1.0"
    with pytest.raises(ValueError, match="Version"):
        validate_metadata(metadata, name="memory-core", version="0.2.0")
