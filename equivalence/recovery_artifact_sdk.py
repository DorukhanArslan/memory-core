"""Observe public SDK audit/repair returns and physical files before repeating a repair."""
import base64
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
from tempfile import mkdtemp

from equivalence.dream_light import canonical
from equivalence.recovery_repair_fixtures import artifact_cases, seed_entries

ARCHIVE_NAME = re.compile(r"(\.openclaw-repair/dreaming/[^/]+/(?:session-corpus|session-ingestion\.json|DREAMS\.md|dreams\.md))\.[a-f0-9-]{36}(?=/|$)")


def public_paths(value, workspace, recall, lock):
    if isinstance(value, list):
        return [public_paths(v, workspace, recall, lock) for v in value]
    if isinstance(value, dict):
        return {k: public_paths(v, workspace, recall, lock) for k, v in value.items()}
    if value == recall:
        return "$RECALL"
    if value == lock:
        return "$LOCK"
    if isinstance(value, str) and value.startswith(workspace + "/"):
        return "$WORKSPACE/" + ARCHIVE_NAME.sub(r"\1.$UUID", value[len(workspace)+1:])
    return value


def run_sdk(value, *, evidence_directory):
    from memory_core.config import MemoryConfig
    from memory_core.consolidation import (audit_dreaming_artifacts, audit_short_term_promotion_artifacts,
                                          repair_dreaming_artifacts, repair_short_term_promotion_artifacts)
    from memory_core.consolidation._util import iso_ms, write_json_atomic
    from memory_core.consolidation.store import phase_signal_store_path, promotion_lock_path, recall_store_path
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

    if not any(canonical(value) == canonical(c["input"]) for c in artifact_cases()):
        raise ValueError("Unknown SDK recovery fixture")
    directory = Path(evidence_directory).resolve()
    directory.mkdir(exist_ok=True, parents=True)
    workspace = Path(mkdtemp(prefix="sdk-recovery-", dir=directory))
    config = MemoryConfig(workspace_dir=workspace)
    recall, signals, lock = recall_store_path(workspace), phase_signal_store_path(workspace), promotion_lock_path(workspace)
    result = {"observations": []}
    raw = {"input": value, "root": str(workspace), "stages": [], "blobs": {}, "observations": result["observations"]}
    sdk_files = ("consolidation/__init__.py", "consolidation/audit.py", "consolidation/dreaming_repair.py",
                 "consolidation/session_repair.py", "consolidation/store.py", "consolidation/store_normalization.py",
                 "consolidation/light_phase.py", "consolidation/concepts.py", "consolidation/recall.py")
    import memory_core
    package_root = Path(memory_core.__file__).resolve().parent
    if package_root != Path(__file__).resolve().parents[1]/"memory_core":
        raise ValueError("Recovery imported an SDK outside the reviewed checkout")
    raw["sdkFiles"] = {name: sha256((package_root/name).read_bytes()).hexdigest() for name in sdk_files}
    now = value["nowMs"]
    for relative, body in value["files"].items():
        file = workspace / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(body, encoding="utf-8", newline="")
    for target, entries in ((recall, seed_entries(value)), (signals, value["signals"])):
        target.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(target, {"version": 1, "updatedAt": value["updatedAt"], "entries": entries})
    if data := value["lock"]:
        write_json_atomic(lock, {"ownerToken": data["owner"], "createdAt": iso_ms(data["acquiredAt"])})
    def stage(operation, returned):
        tree, docs = {}, {}
        for p in sorted(workspace.rglob("*")):
            if p.is_dir():
                continue
            body = p.read_bytes()
            sha = sha256(body).hexdigest()
            relative = p.relative_to(workspace).as_posix()
            tree[relative] = sha
            if sha not in raw["blobs"]:
                raw["blobs"][sha] = base64.b64encode(gzip.compress(body, mtime=0)).decode()
            if p not in (recall, signals, lock) and not relative.endswith(".lock.guard"):
                docs[ARCHIVE_NAME.sub(r"\1.$UUID", relative)] = body.decode("utf8")
        observed = None
        if lock.exists():
            from memory_core.consolidation._util import parse_ms
            actual = json.loads(lock.read_text())
            observed = {"owner": actual["ownerToken"], "acquiredAt": parse_ms(actual["createdAt"], -1)}
        raw["stages"].append({"operation": operation, "returned": deepcopy(returned), "tree": tree})
        result["observations"].append({"operation": operation, "returned": public_paths(returned, str(workspace), str(recall), str(lock)),
            "documents": docs, "lock": observed, "recall": json.loads(recall.read_bytes()), "signals": json.loads(signals.read_bytes())})
    def audit():
        if value["kind"] == "corpus":
            return audit_dreaming_artifacts(workspace)
        return audit_short_term_promotion_artifacts(config, now, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY).as_dict()
    try:
        stage("audit", audit())
        if value["repair"]:
            for _ in range(2):
                if value["kind"] == "corpus":
                    repaired = repair_dreaming_artifacts(workspace, now_ms=now, archive_diary=value["archiveDiary"])
                else:
                    repaired = repair_short_term_promotion_artifacts(config, now, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY).as_dict()
                stage("repair", repaired)
                stage("audit", audit())
        return result
    finally:
        (directory/"python-raw.json").write_text(json.dumps([raw], separators=(",",":")), encoding="utf-8")
