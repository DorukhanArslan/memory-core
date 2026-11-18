"""Replay flush against archived file bytes and explicitly attested empty directories."""
import base64
from contextlib import contextmanager
import hashlib
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import FunctionType

import followup_flush as live
from equivalence.flush_plan_target_evidence import seed_tree
from equivalence.flush_plan_target_sdk import snapshot


@contextmanager
def workspace_view(directory, case, raw, side):
    """Reopen all original files. ZIPs may omit a directory with no archived descendants."""
    source = directory / "workspace"
    live.require(not source.is_symlink() and (not source.exists() or source.is_dir()),
                 "Invalid archived flush workspace")
    physical = snapshot(source) if source.exists() else {}
    final = raw["final"]
    empty = {"kind": "directory"}
    for name, entry in final.items():
        path = PurePosixPath(name)
        live.require(str(path) == name and path.parts and not path.is_absolute() and ".." not in path.parts
                     and "\\" not in name and (entry == empty or set(entry) == {"kind", "base64"} and entry["kind"] == "file"),
                     "Unsafe or ambiguous recorded flush workspace entry")
    live.require(all(final.get(name) == entry for name, entry in physical.items()), "Unexpected archived flush file or directory")
    missing = sorted(final.keys() - physical.keys())
    seed = seed_tree(case["input"])
    required = {p for p in case["input"]["directories"]}
    if side == "python":
        for name in ("user", "workspace"):
            live.require(raw["beforeMaintenance"].get(name) == empty, "Missing SDK bootstrap directory observation")
            required.add(name)
    live.require(all(final.get(name) == empty for name in required), "Recorded flush directory changed kind or disappeared")
    allowed = required | {name for name, entry in seed.items() if entry == empty}
    live.require(all(name in allowed and final[name] == empty for name in missing), "Unarchived flush file or unknown directory")
    root_missing = not source.exists()
    if root_missing:
        live.require(side == "native" and raw["initial"] == final == seed and (case["input"]["flush"].get("enabled") is False or required),
                     "An unexpected flush workspace vanished")
    with TemporaryDirectory(prefix="review-archived-flush-") as tmp:
        view = Path(tmp) / "workspace"
        view.mkdir()
        for name, entry in sorted(final.items()):
            target = view / name
            if entry == empty:
                target.mkdir()
            else:
                target.write_bytes(base64.b64decode(physical[name]["base64"], validate=True))
        yield view.parent, {"filesReopened": sum(entry["kind"] == "file" for entry in physical.values()),
                            "archivedTreeSha256": hashlib.sha256(live.family.canonical(physical)).hexdigest(),
                            "emptyDirectoriesFromOriginalCapture": missing,
                            "workspaceRootFromOriginalCapture": root_missing}
    live.require(not source.is_symlink() and root_missing == (not source.exists())
                 and physical == (snapshot(source) if source.exists() else {}), "Archived flush workspace changed during review")


def replay_flush(data, cases, args, runtime):
    receipts = {}

    def checked(validator, side):
        def validate(case, public, raw, directory, *extra):
            with workspace_view(directory, case, raw[0], side) as (view, receipt):
                validator(case, public, raw, view, *extra)
            receipts.setdefault(case["id"], {})[side] = receipt
        return validate

    # Reuse the sealed file, collector and process checks at their original paths.
    # Only the two final physical workspace snapshots use the private readback view.
    original = live.replay_flush
    replay = FunctionType(original.__code__, {**original.__globals__,
                          "validate_native": checked(live.validate_native, "native"),
                          "validate_sdk": checked(live.validate_sdk, "python")}, original.__name__)
    results = replay(data, cases, args, runtime)
    for row in results:
        observed = receipts[row["id"]]
        live.require(set(observed) == {"native", "python"}, "Incomplete archived flush comparison")
        row["archivedWorkspace"] = observed
    return results
