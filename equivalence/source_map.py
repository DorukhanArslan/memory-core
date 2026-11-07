"""Validate the source inventory without granting behavioral-equivalence credit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from equivalence.harness import ROOT, _command, _committed_digest


def describe_module(content: str) -> dict:
    """Inventory literal source dependencies and exported declarations, including types.

    This is a source index, not a transitive dependency resolver. Variable-based
    plugin imports and runtime callbacks still require their declared host tests.
    """
    dependencies = set(re.findall(
        r"(?m)^import\s+(?:type\s+)?[^;]*?\bfrom\s+['\"]([^'\"]+)['\"]", content))
    dependencies.update(re.findall(r"(?m)^import\s+['\"]([^'\"]+)['\"]", content))
    dependencies.update(re.findall(
        r"(?m)^export\s+(?:type\s+)?(?:\{[^}]*\}|\*)\s+from\s+['\"]([^'\"]+)['\"]", content))
    dependencies.update(re.findall(r"\b(?:import|require)\(\s*['\"]([^'\"]+)['\"]", content))
    exports = re.findall(
        r"(?m)^export\s+(?:default\s+)?(?:async\s+)?"
        r"(?:function|class|const|let|var|interface|type|enum)\s+([\w$]+)", content)
    return {"sourceImports": sorted(dependencies), "exportedDeclarations": sorted(set(exports))}


def _file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str):
        raise ValueError("Source locations require string paths.")
    path = PurePosixPath(relative)
    if (not relative or path.is_absolute() or ".." in path.parts or "\\" in relative
            or path.as_posix() != relative):
        raise ValueError("Source locations require canonical relative paths.")
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()) or not result.is_file():
        raise ValueError("A mapped source file is missing or outside its root.")
    return result


def _location(root: Path, location: dict) -> None:
    if not isinstance(location, dict) or not all(isinstance(location.get(key), str) and location[key]
               for key in ("path", "symbol", "anchor")):
        raise ValueError("Each source location needs a path, symbol and literal anchor.")
    content = _file(root, location["path"]).read_text(encoding="utf-8")
    offset = content.find(location["anchor"])
    if (offset < 0 or type(location.get("line")) is not int
            or location["line"] != content[:offset].count("\n") + 1):
        raise ValueError("A mapped source anchor or line has moved.")


def validate_source_map(inventory: dict, scope: dict, target: dict, *,
                        python_root: Path = ROOT, checkout: Path | None = None) -> dict:
    if not all(isinstance(value, dict) for value in (inventory, scope, target)):
        raise ValueError("Source inventory and contracts must be objects.")
    if (inventory.get("schemaVersion") != 1
            or inventory.get("reference") != {key: target[key] for key in ("tag", "commit")}
            or inventory.get("scopeSha256") != hashlib.sha256(
                (ROOT / "equivalence/scope.json").read_bytes()).hexdigest()):
        raise ValueError("The source map does not identify the fixed reference and scope.")
    required = {row["id"]: row for row in scope["requirements"]}
    rows = inventory.get("requirements")
    if (not isinstance(rows, list) or len(rows) != len(required)
            or any(not isinstance(row, dict) for row in rows)
            or {row.get("id") for row in rows} != set(required)):
        raise ValueError("The source map must contain every contract exactly once.")
    if checkout is not None:
        if _command(["git", "rev-parse", "HEAD"], cwd=checkout) != target["commit"]:
            raise ValueError("The inventory requires the exact pinned reference commit.")
        if Path(_command(["git", "rev-parse", "--show-toplevel"], cwd=checkout)).resolve() != checkout.resolve():
            raise ValueError("The reference must identify its Git checkout root.")
        if _command(["git", "status", "--porcelain", "--untracked-files=no"], cwd=checkout):
            raise ValueError("The inventory requires an unmodified reference checkout.")
    referenced = set()
    for row in rows:
        expected = [point["id"] for point in required[row["id"]]["acceptance"]]
        if row.get("acceptancePoints") != expected:
            raise ValueError("A mapped contract has missing or foreign acceptance points.")
        if row.get("implementation") not in {"present", "partial", "host-owned", "missing"}:
            raise ValueError("Python source presence must be classified explicitly.")
        if not isinstance(row.get("notes"), list) or not all(isinstance(n, str) for n in row["notes"]):
            raise ValueError("Inventory notes must be explicit source observations.")
        if not isinstance(row.get("upstream"), list) or not row["upstream"]:
            raise ValueError("Every contract needs an actual upstream source location.")
        if not isinstance(row.get("python"), list) or (
                not row["python"] and row["implementation"] not in {"host-owned", "missing"}):
            raise ValueError("An absent Python counterpart must remain explicit.")
        for location in row["python"]:
            _location(python_root, location)
        for location in row["upstream"]:
            referenced.add(location["path"])
            if checkout is not None:
                _location(checkout, location)
    modules = inventory.get("upstreamModules")
    if (not isinstance(modules, list) or len(modules) != len(referenced)
            or any(not isinstance(module, dict) for module in modules)
            or {module.get("path") for module in modules} != referenced):
        raise ValueError("The upstream module inventory must cover exactly the mapped source files.")
    for module in modules:
        digest = module.get("sha256")
        if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not isinstance(module.get("sourceImports"), list)
                or not isinstance(module.get("exportedDeclarations"), list)):
            raise ValueError("Mapped modules require source hashes and dependency/export inventories.")
        if checkout is not None:
            content = _file(checkout, module["path"]).read_bytes()
            if (hashlib.sha256(content).hexdigest() != digest
                    or _committed_digest(checkout, module["path"]) != digest):
                raise ValueError("A mapped module differs from its pinned Git source.")
            observed = describe_module(content.decode("utf-8"))
            if any(module[key] != observed[key] for key in observed):
                raise ValueError("The declared source dependencies or exports have changed.")
    return {"kind": "source-inventory-validation", "contracts": len(rows),
            "acceptancePoints": sum(len(row["acceptancePoints"]) for row in rows),
            "upstreamModules": len(modules), "referenceVerified": checkout is not None,
            "behaviorVerified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args()
    try:
        inventory = json.loads((ROOT / "equivalence/source-map.json").read_text())
        scope = json.loads((ROOT / "equivalence/scope.json").read_text())
        target = json.loads((ROOT / "equivalence/reference.json").read_text())
        result = validate_source_map(inventory, scope, target, checkout=args.reference.resolve())
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({"kind": "source-inventory-validation", "status": "invalid",
                          "behaviorVerified": False}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
