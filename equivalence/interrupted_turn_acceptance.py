"""Real next-open behavior after a host write loses its tool-result receipt."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

from equivalence import recovery_failure
from equivalence.dream_light import canonical

OPERATION = "interrupted-turn-recovery-runtime"
POINT = "recovery.failure-publication.boundaries"
DAILY_PATH = "memory/2026-11-27.md"
_DRIVER = (
    "Local host session, first write interrupted by process death before or after its actual "
    "filesystem effect and before the persistent tool result. Reconstruct the same session in a "
    "different process and submit a new user message with the SDK's explicit OpenClaw recovery policy."
)
_POLICY = (
    "Compare complete UTF-8 contents or absence at both named paths; ordered original call IDs "
    "and their tool-result IDs, error flags and content blocks in the on-disk transcript at cut, "
    "cold reopen and final inspection; all original-call results in the first new model input; "
    "every tool execution ID and delivered reply in the new turn. Write and add_memory_entry or "
    "append_daily_note are the respective public producers for the same requested bytes. Bind each "
    "original tool identity and arguments within its actual transport and keep both raw histories. "
    "Scope is the next-open publication boundary. Provider envelopes and unrelated history fields "
    "belong to their existing contracts. The default SDK still requires acknowledgment."
)
# The registered inputs were fixed before their SDK observations. The first-note bytes were
# published with the earlier host-turn inputs. The next note uses its own daily writer.
_CASES = (
    ("unchanged-chat", "after-write", None, False),
    ("edited-chat", "after-write", "A local edit kept after the interrupted turn.\n", False),
    ("edited-new-write", "after-write", "A local edit kept after the interrupted turn.\n", True),
    ("unwritten-new-write", "before-write", None, True),
)


def build_cases():
    cases = []
    for tag, cut, external, write in _CASES:
        original_text = "My drink preference is marblekumquat-416 tea without sugar."
        next_text = "A separate note written during this new turn."
        request = {
            "identity": {"agentId": "main", "sessionId": "interrupted-publication-session",
                         "sessionKey": "agent:main:interrupted-publication"},
            "nowMs": 1794268800000, "sdkPolicy": "openclaw", "cut": cut, "externalEdit": external,
            "original": {"callId": "tbbsave0", "prompt": "Remember my drink preference.",
                         "relativePath": "MEMORY.md", "section": "Preferences", "text": original_text,
                         "content": "## Preferences\n\n- " + original_text + "\n"},
            "followup": {"prompt": f"Write a separate note in {DAILY_PATH}." if write else "What is 2 + 2? No tools needed.",
                         "reply": "Separate note saved." if write else "Four.",
                         "write": {"callId": "followupindependent", "relativePath": DAILY_PATH,
                                   "date": "2026-11-27", "text": next_text, "content": next_text + "\n"} if write else None},
        }
        cases.append({"id": "interrupted-turn-reopen-" + tag, "operation": OPERATION,
                      "requirement": recovery_failure.REQUIREMENT, "covers": [POINT], "input": request,
                      "driverScope": _DRIVER, "normalizationPolicy": _POLICY})
    return cases


DEFINITIONS_SHA256 = "665bbc6c7f1c1576b95e7826e5a92bc098b056f9dddd926f22e34ea60f6c1d37"


def validate_registration(rows):
    members = [r for r in rows if r["operation"] == OPERATION or POINT in r["covers"]]
    if members and sha256(canonical(members)).hexdigest() != DEFINITIONS_SHA256:
        raise ValueError("Interrupted-turn recovery requires all four original inputs in order")


def confirms_boundary(case, public):
    """Require the observable cut and useful next turn in addition to matching rows."""
    request = case["input"]
    original, followup = request["original"], request["followup"]
    original_id = original["callId"]
    cut_bytes = original["content"] if request["cut"] == "after-write" else None
    surviving = cut_bytes if request["externalEdit"] is None else request["externalEdit"]
    write = followup["write"]
    missing = {"id": original_id, "isError": True,
               "content": [{"type": "text", "text": "[openclaw] missing tool result in session history; "
                           "inserted synthetic error result for transcript repair."}]}
    # A post-admission compiled transcript can contain the *error* result if the
    # original runtime persists its repaired branch. Physical rows on both sides
    # are compared in full under the registered projection, including that field.
    return (public["cut"] == {"files": {"original": cut_bytes, "independent": None},
                              "originalCalls": [original_id], "originalResults": []}
            and public["reopen"] == {"files": {"original": surviving, "independent": None},
                                     "originalCalls": [original_id], "originalResults": []}
            and canonical(public["firstModelOriginalResults"]) == canonical([missing])
            and public["newTurnToolCalls"] == ([write["callId"]] if write else [])
            and public["replies"] == [followup["reply"]]
            and public["final"]["files"] == {"original": surviving, "independent": write["content"] if write else None}
            and public["final"]["originalCalls"] == [original_id]
            and canonical(public["final"]["originalResults"]) in (canonical([]), canonical([missing])))


# In the same full report, require both a cold retry after an index failure and
# the flush owner's real exhaustion / next-cycle behavior in addition to the
# six publishers whose original interruption/outcome cases were already frozen.
_RETRY_CASES = {
    "query-sync-boundaries-joined-failure-persistent-cold-recovery": "031d589d652a60cf7923958b677562a49e3b209b9402ddab32a829d597b9643d",
    "query-sync-boundaries-warm-failure-natural-retry": "c6af5cb8488332a63c423c0c83057ffd2f668fad713510c196e5967baf3f5de8",
    "flush-execution-model-failure-exhaustion": "d12a8b782febc569e9fe695e7890156c9ace9c6c70022d3fec4b9164fdeb184a",
    "flush-runtime-retry-exhaustion-and-next-cycle": "ba759190dc07f4b5235152c1a903d7af2cc3f4a42b1042ab2a7802d67d5141b7",
}


def prerequisites_complete(rows):
    if not recovery_failure.family_complete(rows):
        return False
    indexed = {row["id"]: row for row in rows}
    try:
        for ident, expected in _RETRY_CASES.items():
            row = indexed[ident]
            definition = {key: row[key] for key in ("id", "requirement", "operation", "input", "covers")}
            if (sha256(canonical(definition)).hexdigest() != expected or row["status"] != "matched"
                    or row["referenceMode"] != "authenticated-official-release"
                    or ("openclaw" in row and canonical(row["openclaw"]) != canonical(row["python"]))):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _valid_receipt(case, evidence):
    keys = {"id", "publicMatch", "nativeSha256", "sdkSha256", "directory"}
    return (isinstance(evidence, dict) and evidence.keys() == keys and evidence["id"] == case["id"]
            and type(evidence["publicMatch"]) is bool
            and all(isinstance(evidence[key], str) and re.fullmatch(r"[0-9a-f]{64}", evidence[key])
                    for key in ("nativeSha256", "sdkSha256"))
            and isinstance(evidence["directory"], str) and Path(evidence["directory"]).name == evidence["directory"]
            and evidence["directory"].startswith(case["id"] + "-"))


def family_complete(rows):
    if not prerequisites_complete(rows):
        return False
    cases = build_cases()
    selected = [r for r in rows if r.get("operation") == OPERATION or POINT in r.get("covers", ())]
    if len(selected) != len(cases) or sha256(canonical(cases)).hexdigest() != DEFINITIONS_SHA256:
        return False
    try:
        for row, case in zip(selected, cases, strict=True):
            if (canonical({k: row[k] for k in case}) != canonical(case) or row["status"] != "matched"
                    or row["referenceMode"] != "authenticated-official-release" or row["runtimeEvidenceValidated"] is not True
                    or not _valid_receipt(case, row["interruptedTurnEvidence"]) or row["interruptedTurnEvidence"]["publicMatch"] is not True
                    or canonical(row["openclaw"]) != canonical(row["python"]) or not confirms_boundary(case, row["openclaw"])):
                return False
        return True
    except (KeyError, TypeError):
        return False


def _wire_digest(path):
    import stat

    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size < 64 * 1024 * 1024:
        raise ValueError("Missing or invalid interrupted-turn capture")
    return sha256(path.read_bytes()).hexdigest()


def _review(case, directory, *, checkout, node, runtime):
    from equivalence import interrupted_turn_native, interrupted_turn_sdk

    native_directory = directory / "native"
    sdk_directory = directory / "sdk"
    if any(path.resolve(strict=True) != path for path in (native_directory, sdk_directory)):
        raise ValueError("Missing physical interrupted-turn attempt directory")
    native = interrupted_turn_native.review_case(case, native_directory, checkout=checkout, node=node, runtime=runtime)
    sdk = interrupted_turn_sdk.review_case(case, sdk_directory)
    evidence = {"id": case["id"], "publicMatch": canonical(native) == canonical(sdk),
                "nativeSha256": _wire_digest(native_directory / "capture.json"),
                "sdkSha256": _wire_digest(sdk_directory / "capture.json"), "directory": directory.name}
    return native, sdk, evidence


def run_case(case, evidence_root, *, checkout, node, runtime):
    """Run two original process pairs and verify the retained material independently."""
    from tempfile import mkdtemp
    from equivalence import interrupted_turn_native, interrupted_turn_sdk

    evidence_root.mkdir(parents=True, exist_ok=True)
    if evidence_root.resolve(strict=True) != evidence_root:
        raise ValueError("Interrupted turns require an owned retention root")
    directory = Path(mkdtemp(prefix=case["id"] + "-", dir=evidence_root))
    (directory / "native").mkdir()
    (directory / "sdk").mkdir()
    native_live = interrupted_turn_native.run_case(case, directory / "native", checkout=checkout, node=node, runtime=runtime)
    sdk_live = interrupted_turn_sdk.run_case(case, directory / "sdk")
    native, sdk, evidence = _review(case, directory, checkout=checkout, node=node, runtime=runtime)
    if canonical([native, sdk]) != canonical([native_live, sdk_live]):
        raise ValueError("Reopened interruption observations differ from the live comparison")
    return {**case, "openclaw": native, "python": sdk,
            "status": "matched" if evidence["publicMatch"] else "mismatched",
            "referenceMode": "authenticated-official-release", "runtimeEvidenceValidated": True,
            "interruptedTurnEvidence": evidence}


def run_batch(cases, evidence_root, *, checkout, node, runtime):
    if not cases:
        return {}
    from equivalence.interrupted_turn_native import authenticate_native

    def blocked(case, error):
        return {**case, "status": "blocked", "code": "interrupted-turn-evidence-invalid",
                "evidenceError": {"name": type(error).__name__, "message": str(error)}}

    validate_registration(cases)
    try:
        verified = authenticate_native(checkout, node, runtime)
    except Exception as error:
        return {case["id"]: blocked(case, error) for case in cases}
    results = {}
    for case in cases:
        try:
            row = run_case(case, evidence_root, checkout=checkout, node=node, runtime=verified)
        except Exception as error:
            row = blocked(case, error)
        results[case["id"]] = row
    return results


def replay(case, row, evidence_root, *, checkout, node, runtime):
    """Load the same original raw material again during the full-report assessment."""
    evidence = row["interruptedTurnEvidence"]
    name = evidence["directory"]
    if (not _valid_receipt(case, evidence)
            or canonical({key: row[key] for key in case}) != canonical(case)):
        raise ValueError("Interrupted-turn replay refers to a different definition or capture")
    root = Path(evidence_root).resolve(strict=True)
    native, sdk, reviewed = _review(case, root / name, checkout=checkout, node=node, runtime=runtime)
    if (canonical(evidence) != canonical(reviewed) or row["runtimeEvidenceValidated"] is not True
            or row["referenceMode"] != "authenticated-official-release"
            or row["status"] != ("matched" if reviewed["publicMatch"] else "mismatched")
            or canonical([native, sdk]) != canonical([row["openclaw"], row["python"]])):
        raise ValueError("Original interrupted-turn capture differs from the complete report")
    return reviewed
