"""Source-loader guards use labelled modules, never memory parity evidence."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from equivalence.harness import ROOT, _oracle


NODE = shutil.which("node")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def alias_checkout(tmp_path):
    root = tmp_path / "labelled-source-fixture"
    root.mkdir()
    _git(root, "init", "-q")

    def prepare(specifier, mapping, *, tracked=True, extra=None):
        caller = root / "extensions/memory-core/src/memory/keyword-query.ts"
        caller.parent.mkdir(parents=True, exist_ok=True)
        caller.write_text("export { labelledProbe as buildFtsQuery } from "
                          + json.dumps(specifier) + ";\n")
        (root / "tsconfig.json").write_text(json.dumps({"compilerOptions": {"paths": mapping}}))
        for relative, contents in (extra or {}).items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        _git(root, "add", ".")
        _git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-qm", "Labelled source resolution fixture")
        if not tracked:
            path = root / "packages/ai/src/utils/diagnostics.ts"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("export function labelledProbe() { return 'untracked'; }\n")
        return root

    return prepare


def _run(root):
    if NODE is None:
        pytest.skip("Node is required for the source-loader transport guard")
    return _oracle(Path(NODE), ROOT / "equivalence/oracle.mjs", root, [{
        "id": "labelled-alias", "operation": "fts-query", "input": {"text": "opaque"},
    }], 20)


@pytest.mark.parametrize("specifier,target,mapping", [
    ("@openclaw/ai/diagnostics", "packages/ai/src/utils/diagnostics.ts", {
        "@openclaw/ai/diagnostics": ["./packages/ai/src/utils/diagnostics.ts"],
    }),
    ("@openclaw/net-policy/ip", "packages/net-policy/src/ip.ts", {
        "@openclaw/net-policy/ip": ["./packages/net-policy/src/ip.ts"],
    }),
    ("openclaw/plugin-sdk/labelled-runtime", "src/plugin-sdk/labelled-runtime.ts", {
        "openclaw/plugin-sdk/*": ["./src/plugin-sdk/*.ts"],
    }),
])
def test_declared_aliases_execute_the_tracked_owner_and_retain_mapping_evidence(
    alias_checkout, specifier, target, mapping,
):
    root = alias_checkout(specifier, mapping, extra={target:
        "export function labelledProbe(text) { return {text, kind:'labelled-source-fixture'}; }\n"})
    result = _run(root)
    assert result["results"] == [{"id": "labelled-alias", "ok": True, "result": {
        "text": "opaque", "kind": "labelled-source-fixture",
    }}]
    assert {row["path"] for row in result["sources"]} == {
        "tsconfig.json", "extensions/memory-core/src/memory/keyword-query.ts", target,
    }


@pytest.mark.parametrize("mapping", [
    {"@openclaw/ai/diagnostics": ["./packages/ai/src/../../../../outside.ts"]},
    {"@openclaw/ai/diagnostics": ["./packages/ai/src/a.ts", "./packages/ai/src/b.ts"]},
    {"@openclaw/ai/diagnostics": ["/private/outside.ts"]},
    {"@openclaw/ai/diagnostics": ["./packages/ai/src/utils/diagnostics.ts"]},
])
def test_aliases_cannot_admit_untracked_ambiguous_or_escaping_modules(alias_checkout, mapping):
    root = alias_checkout("@openclaw/ai/diagnostics", mapping, tracked=False)
    row = _run(root)["results"][0]
    assert row["ok"] is False
    assert "result" not in row
    assert "workspace source mapping" in row["error"]["message"].lower()


def test_source_comparisons_deny_fetches_before_native_fixture_code_runs(alias_checkout):
    root = alias_checkout("@openclaw/ai/diagnostics", {
        "@openclaw/ai/diagnostics": ["./packages/ai/src/utils/diagnostics.ts"],
    }, extra={"packages/ai/src/utils/diagnostics.ts":
        "export async function labelledProbe() { return await fetch('https://example.invalid/'); }\n"})
    row = _run(root)["results"][0]
    assert row["ok"] is False
    assert row["error"]["message"] == "Network fetches are disabled in model-free source comparisons"
