"""Pure admission tests; no original Git helper or memory host executes here."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "equivalence/host-turn-barrier-v4-git-probe.mjs"
ORIGINAL = Path("/workspace/memory-core/.reference/release-runtime/node_modules/openclaw")
HELPER = "dist/git-root-DRBSRg7z.mjs"
HELPER_SHA = "7e7b5a2994f3ca326cb9ccb31393916d1d71fa5262a4e19e386eb920603a10fd"


@pytest.fixture(scope="module")
def node():
    value = os.environ.get("MEMORY_EQ_NODE")
    candidate = Path(value) if value else Path(
        "/workspace/memory-core/work/node-v24.16.0-linux-x64/bin/node")
    if not candidate.is_file():
        pytest.skip("No Node executable for labelled pure admission tests")
    return candidate.resolve()


def run(node, tmp_path, expression, value):
    script = (f"const probe=await import({json.dumps(PROBE.as_uri())});"
              "const value=JSON.parse(process.argv[1]);"
              f"const result=({expression});console.log(JSON.stringify(result));")
    result = subprocess.run(
        [str(node), "--input-type=module", "-e", script, json.dumps(value)],
        cwd=tmp_path, env={"PATH": str(node.parent) + os.pathsep + os.defpath,
                          "LANG": "C.UTF-8", "TZ": "UTC"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("wire", [
    '{"a":1,"a":2}', '{"a":1,"\\u0061":2}', '{"x":[{"a":1,"a":2}]}',
    '{"x":1e4000}', '{"x":NaN}', '{} {}',
])
def test_strict_input_rejects_ambiguous_or_nonfinite_json(node, tmp_path, wire):
    assert run(node, tmp_path,
               "(()=>{try{probe.strictJSON(value,32768);return false;}catch{return true;}})()",
               wire) is True


def test_strict_input_preserves_unicode_types_and_counts_actual_bytes(node, tmp_path):
    value = {"keys": {"a": True, "b": 0, "c": None}, "unicode": "ışık 😀"}
    wire = json.dumps(value, ensure_ascii=False)
    assert run(node, tmp_path, "probe.strictJSON(value,32768)", wire) == value
    assert run(node, tmp_path,
               "(()=>{try{probe.strictJSON(value,Buffer.byteLength(value)-1);return false;}"
               "catch{return true;}})()", wire) is True


@pytest.fixture
def paths(tmp_path):
    cwd, state = tmp_path / "cwd", tmp_path / "state"
    cwd.mkdir()
    state.mkdir()
    return {"cwd": str(cwd), "workspace": str(state / "workspace")}


def test_missing_workspace_leaf_is_an_actual_input_without_predicted_git_result(node, tmp_path, paths):
    (tmp_path / ".git").mkdir()
    assert run(node, tmp_path, "probe.validatePaths(value)", paths) == paths


@pytest.mark.parametrize("attack", ["relative", "traversal", "alias", "not-directory", "missing-parent", "extra"])
def test_actual_path_admission_rejects_aliases_and_escapes(node, tmp_path, paths, attack):
    value = dict(paths)
    if attack == "relative":
        value["cwd"] = "cwd"
    elif attack == "traversal":
        value["cwd"] += "/../cwd"
    elif attack == "alias":
        alias = tmp_path / "alias"
        alias.symlink_to(value["cwd"], target_is_directory=True)
        value["cwd"] = str(alias)
    elif attack == "not-directory":
        target = tmp_path / "file"
        target.write_bytes(b"labelled path fixture")
        value["cwd"] = str(target)
    elif attack == "missing-parent":
        value["workspace"] = str(tmp_path / "missing" / "workspace")
    else:
        value["expectedGitResult"] = None
    assert run(node, tmp_path,
               "(()=>{try{probe.validatePaths(value);return false;}catch{return true;}})()", value) is True


@pytest.fixture
def runtime(tmp_path):
    if not (ORIGINAL / HELPER).is_file():
        pytest.skip("No retained pinned helper bytes for source-only validation")
    folder = tmp_path / "labelled-runtime"
    helper = folder / HELPER
    helper.parent.mkdir(parents=True)
    shutil.copyfile(ORIGINAL / HELPER, helper)
    return {"runtimeRoot": str(folder), "packages": [{"location": "LABELLED_SOURCE_ONLY",
            "directory": str(folder), "files": [{"path": HELPER, "sha256": HELPER_SHA}]}]}


def test_source_table_admission_preserves_the_fixed_original_helper_identity(node, tmp_path, runtime):
    result = run(node, tmp_path,
                 "(()=>{const result=probe.buildImportAuthority(value);"
                 "return {helper:result.helper,size:result.permitted.size};})()", runtime)
    assert result["helper"] == {"package": "LABELLED_SOURCE_ONLY", "path": HELPER,
                                "absolutePath": str(Path(runtime["runtimeRoot"]) / HELPER),
                                "sha256": HELPER_SHA}
    assert result["size"] == 1


@pytest.mark.parametrize("attack", ["escape", "dot", "duplicate", "wrong-sha", "invalid-sha", "alias", "missing-main"])
def test_source_table_rejects_foreign_aliased_or_changed_authority(node, tmp_path, runtime, attack):
    value = deepcopy(runtime)
    package = value["packages"][0]
    if attack == "escape":
        package["files"].append({"path": "../outside.mjs", "sha256": "0" * 64})
    elif attack == "dot":
        package["files"].append({"path": "dist/./outside.mjs", "sha256": "0" * 64})
    elif attack == "duplicate":
        package["files"].append(deepcopy(package["files"][0]))
    elif attack == "wrong-sha":
        package["files"][0]["sha256"] = "0" * 64
    elif attack == "invalid-sha":
        package["files"][0]["sha256"] = "not-a-digest"
    elif attack == "alias":
        alias = tmp_path / "alias-runtime"
        alias.symlink_to(package["directory"], target_is_directory=True)
        package["directory"] = str(alias)
    else:
        other = tmp_path / "other-runtime"
        other.mkdir()
        value["runtimeRoot"] = str(other)
    assert run(node, tmp_path,
               "(()=>{try{probe.buildImportAuthority(value);return false;}catch{return true;}})()", value) is True


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "size"])
def test_evidence_sealing_rejects_unbounded_or_shared_source_files(node, tmp_path, attack):
    target = tmp_path / "source.mjs"
    target.write_bytes(b"LABELLED_SOURCE_ONLY\n")
    selected = target
    if attack == "symlink":
        selected = tmp_path / "source-alias.mjs"
        selected.symlink_to(target)
    elif attack == "hardlink":
        selected = tmp_path / "source-hardlink.mjs"
        selected.hardlink_to(target)
    assert run(node, tmp_path,
               "(()=>{try{probe.sealedFile(value.path,{limit:value.limit});return false;}"
               "catch{return true;}})()",
               {"path": str(selected), "limit": 1 if attack == "size" else 1024}) is True


def test_pinned_helper_function_source_digest_is_not_a_replacement_algorithm(node, tmp_path):
    if not (ORIGINAL / HELPER).is_file():
        pytest.skip("No retained pinned helper bytes for source-only validation")
    content = (ORIGINAL / HELPER).read_text()
    start = content.index("function findGitRoot(")
    source = content[start:content.index("\n}", start) + 2]
    result = run(node, tmp_path,
                 "({helper:probe.HELPER_SHA256,functionSource:probe.FUNCTION_SHA256})", None)
    assert result["helper"] == hashlib.sha256((ORIGINAL / HELPER).read_bytes()).hexdigest()
    assert result["functionSource"] == hashlib.sha256(source.encode()).hexdigest()


def test_cli_rejects_another_context_before_loading_any_original_module(node, tmp_path):
    context = tmp_path / "wrong-context.json"
    context.write_text('{"schemaVersion":1,"kind":"LABELLED_INVALID"}\n')
    result = subprocess.run([str(node), str(PROBE), str(context)], cwd=tmp_path,
        input='{"cwd":"/tmp","workspace":"/tmp"}',
        env={"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and result.stdout == ""
    failure = json.loads(result.stderr)
    assert failure["kind"] == "host-turn-barrier-v4-git-probe-failure"
    assert "context/profile" in failure["error"]["message"]
