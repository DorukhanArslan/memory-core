"""Fresh-process bootstrap calls; adapters contain filesystem and wire transport only."""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback

from equivalence.bootstrap_discovery_bindings import TEMPLATE_ARTIFACTS
from equivalence.get_contract import map_get_fixture_paths
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore

ROOT = Path(__file__).resolve().parents[1]


def _observe(value):
    if isinstance(value, BaseException):
        return _error(value, raw=True)
    if dataclasses.is_dataclass(value):
        return {"type": type(value).__qualname__, "fields": {
            field.name: _observe(getattr(value, field.name)) for field in dataclasses.fields(value)}}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"type": "bytes", "hex": value.hex()}
    if isinstance(value, MemoryArtifactProvenanceStore):
        return {"type": type(value).__qualname__, "fields": _observe(vars(value))}
    if isinstance(value, dict):
        return {str(key): _observe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_observe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return value


@contextmanager
def _observe_classification(raw):
    """Read-only return observation of the actual nested production owners."""
    from memory_core.bootstrap.classification import classify_workspace_memory_paths

    owners = {classify_workspace_memory_paths.__code__: "classify_workspace_memory_paths",
              MemoryArtifactProvenanceStore.read.__code__: "MemoryArtifactProvenanceStore.read"}
    previous = sys.getprofile()

    def observer(frame, event, value):
        if event == "return" and frame.f_code in owners:
            arguments = {name: frame.f_locals[name] for name in frame.f_code.co_varnames[:frame.f_code.co_argcount + frame.f_code.co_kwonlyargcount]}
            raw.setdefault("classificationCalls", []).append({"owner": owners[frame.f_code],
                "request": _observe(arguments), "result": _observe(value), "returnedNone": value is None})
        if previous is not None:
            previous(frame, event, value)

    sys.setprofile(observer)
    try:
        yield
    finally:
        sys.setprofile(previous)


def _error(error, *, raw=False, seen=None):
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"type": "circular-reference"}
    seen.add(id(error))
    result = {"name": type(error).__name__, "message": str(error), **_observe(vars(error))}
    for name in ("errno", "strerror", "filename", "filename2", "winerror"):
        if getattr(error, name, None) is not None:
            result[name] = _observe(getattr(error, name))
    if error.__cause__ is not None:
        result["cause"] = _error(error.__cause__, raw=raw, seen=seen)
    if raw:
        result.update(args=_observe(error.args), traceback="".join(traceback.format_exception(error)))
        if error.__context__ is not None:
            result["context"] = _error(error.__context__, raw=True, seen=seen)
    return result


def _wire_file(value):
    return {"name": value.name, "path": value.path,
            **({"content": value.content} if value.content is not None else {}), "missing": value.missing}


def _path(root, relative):
    if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
            or ".." in Path(relative).parts or "\\" in relative):
        raise ValueError("Bootstrap fixture paths must remain in their declared owned root")
    return root / relative


def _tree(root):
    rows = []
    if not root.exists():
        return rows
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        value = path.lstat()
        kind = "symlink" if stat.S_ISLNK(value.st_mode) else "directory" if stat.S_ISDIR(value.st_mode) else "file" if stat.S_ISREG(value.st_mode) else "other"
        row = {"path": path.name, "kind": kind, "stat": {"sequence": list(value), "fields": {
            name: getattr(value, name) for name in dir(value) if name.startswith("st_")}}}
        if kind == "symlink":
            row["target"] = os.readlink(path)
        elif kind == "file":
            row["bytes"] = _observe(path.read_bytes())
        rows.append(row)
        if kind == "directory":
            for child in _tree(path):
                rows.append({**child, "path": str(Path(path.name) / child["path"])})
    return rows


def _phase(request):
    import memory_core
    from memory_core.bootstrap.files import load_workspace_bootstrap_files, filter_bootstrap_files
    from memory_core.bootstrap.layout import OPENCLAW_COMPAT_LAYOUT, MEMORY_CORE_WORKSPACE_LAYOUT
    from memory_core.bootstrap.lifecycle import (
        initialize_agent_workspace, read_workspace_setup_state, bootstrap_status, is_workspace_setup_completed,
    )

    if set(request) != {"directory", "input"} or Path(memory_core.__file__).resolve().parents[1] != ROOT:
        raise ValueError("A bootstrap child must import this checkout and receive only its owned root and literal input")
    root, value = Path(request["directory"]), request["input"]
    if (value.get("kind") != "workspace-bootstrap" or value.get("layout") not in {"openclaw", "memory-core"}
            or not isinstance(value.get("steps"), list)):
        raise ValueError("An actual bootstrap child requires a literal layout and ordered steps")
    if any("setup" in step for step in value["steps"]):
        raise ValueError("A private setup-state mutator is outside this public bootstrap profile")
    templates = value.get("packagedTemplates", {})
    if set(templates) != set(TEMPLATE_ARTIFACTS) or any(
        hashlib.sha256(templates[name].encode()).hexdigest() != authority["sha256"]
        for name, authority in TEMPLATE_ARTIFACTS.items()
    ):
        raise ValueError("The common literal template bytes must match the authenticated package")
    workspace, outside = root / "workspace", root / "outside"
    workspace.mkdir()
    outside.mkdir()
    layout = OPENCLAW_COMPAT_LAYOUT if value["layout"] == "openclaw" else MEMORY_CORE_WORKSPACE_LAYOUT
    raw = {"kind": value["kind"], "input": deepcopy(value), "fixtureBase": str(root), "pid": os.getpid(),
           "ppid": os.getppid(), "implementationRoot": str(ROOT), "layout": _observe(layout),
           "environmentKeys": sorted(os.environ),
           "stateFormat": "memory-core-workspace-state-json", "packagedTemplates": deepcopy(templates),
           "writes": [], "calls": [], "snapshots": []}

    def write(files, label, *, destination=workspace, octets=False):
        for relative, content in files.items():
            path = _path(destination, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = bytes(content) if octets else content.encode("utf-8")
            path.write_bytes(data)
            raw["writes"].append({"label": label, "path": str(path), "input": deepcopy(content), "octets": octets})

    def call(label, owner, arguments, invoke):
        record = {"label": label, "owner": owner, "request": _observe(arguments)}
        raw["calls"].append(record)
        try:
            result = invoke()
            record.update(returnedNone=result is None, result=_observe(result))
            return result, None
        except Exception as error:
            record["error"] = _error(error, raw=True)
            return None, error

    for relative in value.get("directories", []):
        path = _path(workspace, relative)
        path.mkdir(parents=True, exist_ok=True)
        raw["writes"].append({"operation": "mkdir", "path": str(path)})
    write(value.get("outsideFiles", {}), "initial-outside", destination=outside)
    write(value.get("files", {}), "initial")
    write(value.get("fileBytes", {}), "initial-bytes", octets=True)
    for relative, specification in value.get("fileSizes", {}).items():
        fill, size = specification["fill"], specification["size"]
        if type(fill) is not int or not 0 <= fill <= 255 or type(size) is not int or not 0 <= size <= 2097153:
            raise ValueError("The declared sized fixture is outside its bounded byte transport")
        path = _path(workspace, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes([fill]) * size)
        raw["writes"].append({"operation": "sized-file", "path": str(path), "input": specification})
    for relative, target in value.get("symlinks", {}).items():
        if target["scope"] not in {"workspace", "outside"}:
            raise ValueError("A symlink fixture requires its explicit owned target scope")
        path = _path(workspace, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        source = _path(workspace if target["scope"] == "workspace" else outside, target["path"])
        path.symlink_to(source)
        raw["writes"].append({"operation": "symlink", "path": str(path), "target": str(source)})
    for relative, source_relative in value.get("hardlinks", {}).items():
        path, source = _path(workspace, relative), _path(workspace, source_relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, path)
        raw["writes"].append({"operation": "hardlink", "path": str(path), "source": str(source)})
    public_steps = []
    provenance = MemoryArtifactProvenanceStore(root / "state" / "bootstrap-artifact-provenance.sqlite")
    for step in value["steps"]:
        label = step["label"]
        write(step.get("writes", {}), label)
        for relative in step.get("removes", []):
            path = _path(workspace, relative)
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            raw["writes"].append({"label": label, "operation": "remove", "path": str(path)})
        ensure = None
        if "ensure" in step:
            literal = step["ensure"]
            arguments = {"layout": layout, "templates": templates,
                         "ensure_bootstrap_files": literal.get("ensureBootstrapFiles", False),
                         "skip_optional": literal.get("skipOptionalBootstrapFiles", False), "now_ms": value["nowMs"]}
            if "templates" in literal:
                arguments["creation_templates"] = literal["templates"]
            arguments.update({key: item for key, item in literal.items()
                              if key not in {"ensureBootstrapFiles", "templates", "skipOptionalBootstrapFiles"}})
            result, error = call(label, "initialize_agent_workspace", {"root": workspace, **arguments},
                                 lambda: initialize_agent_workspace(workspace, **arguments))
            ensure = {"error": _error(error)} if error else {"bootstrapPending": result.bootstrap_pending}
        loaded, load_error = call(label, "load_workspace_bootstrap_files", {"root": workspace, "layout": layout},
                                  lambda: load_workspace_bootstrap_files(workspace, layout))
        runs = []
        for run in step.get("runs", []):
            warnings = []
            run_loaded, error = call(label, "load_workspace_bootstrap_files", {"root": workspace, "layout": layout},
                                     lambda: load_workspace_bootstrap_files(workspace, layout))
            if error is None:
                completed, error = call(label, "is_workspace_setup_completed", {"root": workspace},
                                        lambda: is_workspace_setup_completed(workspace))
            if error is None:
                arguments = {"root": workspace, "layout": layout, "session_kind": run["sessionKind"],
                             "setup_completed": completed, "context_mode": run.get("contextMode", "full"), "warn": warnings.append}
                arguments.update({key: item for key, item in run.items() if key in {"config", "bootstrapUserProfileId"}})
                if "config" in run:
                    arguments["artifact_provenance"] = provenance

                def invoke_filter():
                    with _observe_classification(raw):
                        return filter_bootstrap_files(run_loaded, **arguments)

                files, error = call(label, "filter_bootstrap_files", {key: item for key, item in arguments.items() if key != "warn"},
                                    invoke_filter)
            runs.append({"request": deepcopy(run), **({"error": _error(error)} if error else {"files": [_wire_file(file) for file in files]}),
                         "warnings": warnings})
        state, state_error = call(label, "read_workspace_setup_state", {"root": workspace}, lambda: read_workspace_setup_state(workspace))
        status, status_error = call(label, "bootstrap_status", {"root": workspace, "layout": layout}, lambda: bootstrap_status(workspace, layout))
        completed, completed_error = call(label, "is_workspace_setup_completed", {"root": workspace}, lambda: is_workspace_setup_completed(workspace))
        raw["snapshots"].append({"label": label, "state": {"error": _error(state_error, raw=True)} if state_error else _observe(state),
                                 "workspace": _tree(workspace), "outside": _tree(outside),
                                 "workspaceEntries": [str(path.relative_to(workspace)) for path in workspace.rglob("*")],
                                 "outsideEntries": [str(path.relative_to(outside)) for path in outside.rglob("*")]})
        public_steps.append({"label": label, "ensure": ensure,
                             **({"loadError": _error(load_error)} if load_error else {"loaded": [_wire_file(file) for file in loaded]}),
                             "runs": runs, "bootstrapStatus": {"error": _error(status_error)} if status_error else status,
                             "setupCompleted": {"error": _error(completed_error)} if completed_error else completed})
    raw["artifactProvenance"] = {"path": str(provenance.path), "initialized": provenance.path.exists()}
    if provenance.path.exists():
        records, error = call("final-observation", "MemoryArtifactProvenanceStore.list",
                              {"workspace_dir": workspace, "store": provenance}, lambda: provenance.list(workspace))
        raw["artifactProvenance"].update({"error": _error(error, raw=True)} if error else {"records": _observe(records)})
    raw["hostState"] = _tree(root / "state")
    raw["hostStateEntries"] = [str(path.relative_to(root / "state")) for path in (root / "state").rglob("*")]
    return {"result": map_get_fixture_paths({"provider": "none", "steps": public_steps}, root), "raw": raw}


def run_bootstrap_discovery(arguments, *, evidence_directory=None):
    """Run one actual SDK flow in a fresh credential-free process."""
    value = deepcopy(arguments)
    raw = {"kind": "bootstrap-discovery-sdk-process", "coordinatorPid": os.getpid(), "input": value, "child": None}
    with tempfile.TemporaryDirectory(prefix="python-bootstrap-discovery-") as temporary:
        root = Path(temporary)
        request = {"directory": str(root), "input": value}
        wire = json.dumps(request, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        environment = {"PATH": os.defpath, "LANG": "en_US.UTF-8", "TZ": "UTC", "PYTHONPATH": str(ROOT)}
        argv = [sys.executable, "-m", "equivalence.bootstrap_discovery_sdk", "--phase"]
        record = {"request": request, "requestJson": wire, "requestSha256": hashlib.sha256(wire.encode()).hexdigest(),
                  "argv": argv, "environmentKeys": sorted(environment)}
        raw.update(fixtureBase=str(root), child=record)
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", cwd=ROOT, env=environment)
            record["pid"] = process.pid
            stdout, stderr = process.communicate(wire, timeout=60)
            record.update(exit={"code": process.returncode, "signal": None}, stdout=stdout, stderr=stderr)
            if process.returncode:
                raise RuntimeError("The actual SDK bootstrap child failed; original stdout/stderr are retained")
            observation = json.loads(stdout)
            record["observation"] = observation
            if (observation["raw"]["pid"] != process.pid or observation["raw"]["ppid"] != os.getpid()
                    or observation["raw"]["implementationRoot"] != str(ROOT)):
                raise ValueError("The SDK bootstrap flow lost its actual child or checkout identity")
            return observation["result"]
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            record.update(exit={"code": process.returncode, "signal": None}, stdout=stdout, stderr=stderr)
            raise
        finally:
            if evidence_directory is not None:
                evidence_directory = Path(evidence_directory)
                evidence_directory.mkdir(parents=True, exist_ok=True)
                (evidence_directory / "python-raw.json").write_text(json.dumps([raw], ensure_ascii=True, allow_nan=False, indent=2) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] != ["--phase"]:
        raise SystemExit("Use the isolated bootstrap phase entry")
    try:
        output = _phase(json.load(sys.stdin))
        json.dump(output, sys.stdout, ensure_ascii=True, allow_nan=False)
        sys.stdout.write("\n")
    except Exception as error:
        json.dump({"fatal": _error(error, raw=True), "pid": os.getpid()}, sys.stdout, ensure_ascii=True, allow_nan=False)
        sys.stdout.write("\n")
        raise
