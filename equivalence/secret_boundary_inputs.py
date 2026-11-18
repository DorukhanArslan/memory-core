"""Caller inputs for comparing bounded secret redaction and complete failure reports."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from equivalence.redaction_fixtures import model_session_fixtures

REQUIREMENT = "trust.secret-redaction"
POINTS = (REQUIREMENT + ".boundaries",)
WHOLE_ID = "secret-boundary-whole-utf16"
CHUNKED_ID = "secret-boundary-chunked-utf16"
SESSION_ID = "secret-boundary-session-reopen"
ERROR_ID = "secret-boundary-failed-tools"
ERROR_INPUT_SHA256 = "f2d2068951f109c0f7cd23ca8ae0b20788869d75ab191a8155d2d1cb620b786f"
DEFINITION_SHA256 = "7969049b80e2706edf99739fa86cae0faacd3420b7bd6d1805a473b51d695425"


def _case(identifier, operation, arguments, scope):
    return {"id": identifier, "requirement": REQUIREMENT, "operation": operation,
            "covers": list(POINTS), "input": arguments, "driverScope": scope,
            "normalizationPolicy": "Compare complete ordinary public returns and observable side effects "
            "from synthetic inputs. Keep raw observations, nested errors, original caller objects and "
            "public result identities under their original contracts. No output normalization."}


def _bounded(identifier, length):
    # The first harmless marker crosses the original 16384-code-unit boundary.
    # The exact secret is a separate field so masking cannot move this boundary.
    prefix = "🌿" + " " * 16378 + "BOUNDARY-1234 then BOUNDARY-9876"
    text = prefix + " " * (length - len(prefix.encode("utf-16-le")) // 2)
    return _case(identifier, "redaction-policy-source", {
        "kind": "source-policy", "mode": "tools", "fullContext": False,
        "text": text, "patterns": [r"/BOUNDARY-[0-9]+/g"], "registeredSecrets": ["registered-fixture"],
        "declaredRegistryValues": ["registered-fixture"],
        "value": {"calendar": text, "note": "sample registered-fixture"},
        "message": {"role": "toolResult", "toolCallId": "lookup-1", "toolName": "lookup",
                    "content": [{"type": "text", "text": text}], "timestamp": 1000}},
        "Original tracked redaction policy and ordinary SDK policy: whole and bounded token scanning, "
        "registered synthetic literals, structured text, transcript, model and tool returns.")


def _session():
    # Reuse the existing genuine three-process host protocol and response script.
    seed = next(case for case in model_session_fixtures()
                if case["id"] == "model-session-invalid-patterns-and-late-registration")
    arguments = deepcopy(seed["input"])
    arguments.pop("patterns")
    arguments["registeredSecrets"] = ["registered-fixture"]
    write = arguments["phases"][0]
    prefix = "before registered-fixture, later-fixture-secret | "
    text = prefix + "a" * (7999 - len(prefix)) + "🌿 END clearly synthetic"
    write["toolResult"] = {"content": [{"type": "text", "text": text}],
                           "details": {"note": "later-fixture-secret", "credentials": {"password": "sample-only"}}}
    return _case(SESSION_ID, "model-session-runtime", arguments,
        "One real tool return, public live listener registration, guarded persistence, a fresh continuation "
        "and an independent third-process read. The previous helper raw-input identity probes retain their "
        "own unchanged comparisons; the complete session result here includes its normal provider/SQLite outputs.")


def _failed_tools():
    return _case(ERROR_ID, "model-tool-error-runtime", {
        "registeredSecrets": ["demo-supplement-credential"],
        "patterns": ["[", r"SAMPLE-[0-9]+"],
        "error": {"message": "orchard service demo-supplement-credential reference SAMPLE-1269",
                  "cause": {"message": "orchard transport demo-supplement-credential sample SAMPLE-9845",
                            "code": "EPIPE"}}},
        "Real recursive formatter and complete memory_get and memory_search after a genuine registered "
        "supplement throws. An invalid configured rule coexists with a valid one. All values are synthetic.")


def _definitions():
    return [_bounded(WHOLE_ID, 32768), _bounded(CHUNKED_ID, 32769), _session(), _failed_tools()]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def build_cases():
    rows = _definitions()
    if hashlib.sha256(canonical(rows)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("The frozen secret boundary caller inputs or assigned condition changed")
    return rows
