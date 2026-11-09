"""The private-mark source profile accepts only original same-tree owners."""
from copy import deepcopy
import hashlib
import os
import subprocess

import pytest

from equivalence.trust_redaction_source_probe import PROFILE, authenticate_capture


@pytest.fixture()
def authenticated_graph(tmp_path):
    required = ["src/logging/redact.ts", "src/logging/redact-internal-state.ts", "src/logging/logger.ts",
                "src/logging/secret-redaction-registry.ts", "src/agents/transcript-redact.ts", "tsconfig.json"]
    sources = []
    for name in required:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original test graph member " + name)
        sources.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    env = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    for arguments in (["init", "-q"], ["add", "."], ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Original fixture", "--no-verify"]):
        subprocess.run(["git", *arguments], cwd=tmp_path, env=env, check=True, capture_output=True)
    capture = {"profile": PROFILE, "sourceFallback": False, "compiledOpenClawModulesAllowed": False,
               "sources": sources, "dependencySources": []}
    return tmp_path, capture


def test_original_committed_source_graph_is_admitted(authenticated_graph):
    root, capture = authenticated_graph
    authenticate_capture(root, {"packages": []}, capture)


@pytest.mark.parametrize("field", ["profile", "sourceFallback", "compiledOpenClawModulesAllowed"])
def test_unexpected_profile_or_cross_graph_fallback_is_rejected(authenticated_graph, field):
    root, capture = authenticated_graph
    capture[field] = "unexpected"
    with pytest.raises(ValueError, match="source policy authority"):
        authenticate_capture(root, {"packages": []}, capture)


def test_edited_source_cannot_be_admitted_by_rehashing_the_working_tree(authenticated_graph):
    root, capture = authenticated_graph
    source = capture["sources"][0]
    path = root / source["path"]
    path.write_text("modified source")
    source["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="pinned Git object"):
        authenticate_capture(root, {"packages": []}, capture)


@pytest.mark.parametrize("path", ["dist/redact.mjs", "../outside.ts", "/absolute.ts"])
def test_compiled_or_escaped_source_member_is_rejected(authenticated_graph, path):
    root, capture = authenticated_graph
    capture["sources"].append({"path": path, "sha256": "0" * 64})
    with pytest.raises(ValueError, match="source graph member"):
        authenticate_capture(root, {"packages": []}, capture)


def test_duplicated_source_and_missing_private_mark_owner_are_rejected(authenticated_graph):
    root, capture = authenticated_graph
    duplicate = deepcopy(capture)
    duplicate["sources"].append(duplicate["sources"][0])
    with pytest.raises(ValueError, match="source graph member"):
        authenticate_capture(root, {"packages": []}, duplicate)
    capture["sources"] = [source for source in capture["sources"] if source["path"] != "src/logging/redact-internal-state.ts"]
    with pytest.raises(ValueError, match="same-identity policy owners"):
        authenticate_capture(root, {"packages": []}, capture)


def test_unverified_dependency_execution_is_rejected(authenticated_graph):
    root, capture = authenticated_graph
    capture["dependencySources"] = [{"package": "unverified", "path": "index.mjs", "sha256": "0" * 64}]
    with pytest.raises(RuntimeError):
        authenticate_capture(root, {"packages": []}, capture)
