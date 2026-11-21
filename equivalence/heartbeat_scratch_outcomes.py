"""Read-only migration-outcome comparison of authenticated whole Doctor observations.

Use both phases of an original Doctor case. Keep the raw packet and its existing
strict diagnostic comparison. Here the subject is what the repair wrote,
retained, moved or refused and its complete public reply. Findings/preview
diagnostic text belongs to the reconstruction condition. Their storage effects
are still observed. This comparison alone never awards the scratch condition.
"""
from __future__ import annotations

import base64
import errno
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID

from equivalence.heartbeat_doctor_probe import _root_comparison, _validate_public_observation


ARCHIVE = "state/backups/heartbeat-migration"
# Both owners use mkdtemp after the exact <agent>-<full source SHA>.md path.
# Node allocates six alphanumerics. The SDK can use that form or the eight
# [a-z0-9_] characters produced by Python mkdtemp. Other names stay literal.
ARCHIVE_STEM = r"([A-Za-z0-9._-]+-[0-9a-f]{64}\.md)\."
ARCHIVE_DIRECTORY = {
    "native": re.compile(ARCHIVE_STEM + r"[A-Za-z0-9]{6}"),
    "sdk": re.compile(ARCHIVE_STEM + r"(?:[A-Za-z0-9]{6}|[a-z0-9_]{8})"),
}


def _identity(value, identities):
    if value not in identities:
        identities[value] = len(identities) + 1
    return identities[value]


def _monitor(monitor, ids):
    if monitor == {"type": "undefined"}:
        return monitor
    job = monitor["jobId"]
    try:
        uuid = UUID(job)
    except ValueError:
        return monitor  # Explicit or malformed job names remain exact literals.
    if uuid.version != 4 or str(uuid) != job:
        return monitor
    return {**monitor, "jobId": {"generated": _identity(job, ids)}}


def _file_outcome(row, root, file_ids):
    value = {"kind": row["kind"]}
    if row["kind"] == "absent":
        return value
    physical = row["physical"]
    value["mode"] = row["mode"]
    if row["kind"] in {"file", "symlink"}:
        # A move of the original and a copy with the same bytes are different.
        value.update(fileId=_identity((physical["dev"], physical["ino"]), file_ids),
                     links=physical["nlink"])
    if "bytes" in row:
        data = base64.b64decode(row["bytes"]["base64"], validate=True)
        if row["bytes"]["type"] != "bytes" or physical["size"] != len(data):
            raise ValueError("invalid captured file size or byte transport")
        value.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    elif row["kind"] == "file" and "error" not in row:
        raise ValueError("missing file bytes")
    if "target" in row:
        value["target"] = _root_comparison(row["target"], root)
    if "error" in row:
        # File-observer error only. Public caller errors are retained in full.
        props = row["error"]["ownProperties"]
        code = props.get("code") or errno.errorcode.get(props.get("errno"))
        value["readError"] = code if code else row["error"]
    return value


def _tree_outcome(rows, root, file_ids, directory_ids, *, archive, side):
    result = {}
    by_path = {row["path"]: row for row in rows}
    if "." not in by_path or len(by_path) != len(rows):
        raise ValueError("incomplete or duplicate filesystem observation")
    for name, row in sorted(by_path.items()):
        if archive:
            directory, slash, rest = name.partition("/")
            match = ARCHIVE_DIRECTORY[side].fullmatch(directory)
            if match and by_path.get(directory, {}).get("kind") == "directory":
                # Require the claimed archive's stable sibling snapshot; retain
                # its full agent/digest stem and the relative child filename.
                stem = match.group(1)
                if by_path.get(stem, {}).get("kind") == "file":
                    suffix = _identity(directory, directory_ids)
                    name = f"{stem}.<generated-{suffix}>{slash}{rest}"
        result[name] = _file_outcome(row, root, file_ids)
    return result


def _check_archive_root(fixture_rows, archive_rows):
    # The archive must really be present at the host state path, even if an
    # adapter chooses to observe a different directory with the same contents.
    disk = {r["path"]: r for r in fixture_rows}
    subtree = {p.removeprefix(ARCHIVE + "/") if p != ARCHIVE else ".": row
               for p, row in disk.items() if p == ARCHIVE or p.startswith(ARCHIVE + "/")}
    observed = {row["path"]: row for row in archive_rows}
    if not subtree:
        return observed == {".": {"path": ".", "kind": "absent"}}
    return set(subtree) == set(observed) and all(
        {**row, "path": name} == observed[name] for name, row in subtree.items()
    )


def _project(case, observations, side):
    phases = case["phases"]
    if len(observations) != len(phases) or not phases:
        raise ValueError("missing migration phase")
    pids = [phase["raw"]["pid"] for phase in observations]
    roots = {phase["raw"]["fixtureDirectory"] for phase in observations}
    if len(set(pids)) != len(phases) or len(roots) != 1:
        raise ValueError("migration must reopen the same store in fresh processes")
    root = Path(roots.pop())
    job_ids, file_ids, directory_ids = {}, {}, {}
    results = []
    for fixture, observation in zip(phases, observations, strict=True):
        _validate_public_observation(observation, fixture)
        raw = observation["raw"]
        snapshots = []
        for snapshot in raw["snapshots"]:
            if set(snapshot["monitors"]) != {agent["id"] for agent in fixture["agents"]}:
                raise ValueError("monitor observations omit or add an agent")
            owners = {agent: _monitor(monitor, job_ids)
                      for agent, monitor in sorted(snapshot["monitors"].items())}
            source = _tree_outcome(snapshot["sourceTree"], root, file_ids, directory_ids, archive=False, side=side)
            archive = _tree_outcome(snapshot["archiveTree"], root, file_ids, directory_ids, archive=True, side=side)
            snapshots.append({"monitors": owners, "source": source, "archive": archive})
        returned = []
        for call in raw["calls"]:
            if call["operation"]["op"] in {"seedScratch", "repair"}:
                response = {"error": call["error"]} if "error" in call else call["result"]
                result = {"operation": call["operation"], "response": _root_comparison(response, root)}
                if call["operation"]["op"] == "seedScratch" and "error" not in call:
                    key = "writeRequest" if side == "native" else "request"
                    result["writeOwner"] = _monitor({"jobId": call[key]["jobId"]}, job_ids)["jobId"]
                returned.append(result)
        witnessed = _check_archive_root(raw["fixtureTreeAfterClose"], raw["snapshots"][-1]["archiveTree"])
        results.append({"returns": returned, "snapshots": snapshots, "archiveAtHostPath": witnessed})
    return results


def compare_doctor_outcomes(case, native_phases, sdk_phases):
    """Compare parsed, execution-validated native and SDK stdout envelopes."""
    native = _project(case, native_phases, "native")
    sdk = _project(case, sdk_phases, "sdk")
    matches = json.dumps(native, sort_keys=True) == json.dumps(sdk, sort_keys=True)
    return {"id": case["id"], "matches": matches and all(p["archiveAtHostPath"] for p in native + sdk),
            "native": native, "sdk": sdk}
