"""Configured patterns must agree at the source policy and through durable model sessions."""
from copy import deepcopy
from hashlib import sha256
import json

from equivalence.redaction_fixtures import model_session_fixtures, source_policy_fixtures

POINT = "trust.configured-redaction.outcomes"
IDS = ("redaction-configured-structured-captures", "redaction-configured-session-captures")
RESOLVED_IDS = (
    "redaction-policy-letter-mixed-i-engine-diagnostic",
    "redaction-policy-letter-repeated-capture-engine-diagnostic",
    "redaction-policy-unsupported-valid-general-property",
    "redaction-policy-unsupported-valid-v-direct-compiler",
    "model-session-configured-letter-mixed-i-engine-diagnostic",
    "model-session-configured-letter-capture-reset-engine-diagnostic",
)
CASE_SHA = ('c4a24dda69e129f8d3fe85c7f27cb9f33c6791a8131e16f2373845d36059ed3b', 'da471386d5a8edfdfb6309989636ae2a1d844b38ec71b12726c6b3f0cf013204')


def _digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def build_cases():
    src=deepcopy(next(c for c in source_policy_fixtures() if c["id"]=="redaction-policy-configured-replaces-sensitive-merges-tool"))
    model=deepcopy(next(c for c in model_session_fixtures() if c["id"]=="model-session-configured-letter-capture-reset-engine-diagnostic"))
    text="Ticket:AB12 and Ticket:CD34; Capsule:a1; Map:I Map:ı."
    patterns=[r"/(Ticket:)([A-Z]{2}[0-9]{2})/g",r"/Capsule:(?:(\d)|(\p{L})){2}/gu",r"/(Map:)(i)/giu"]
    src["input"].update(text=text,fullContext=True,patterns=patterns,value={"ordinary":text,"nested":[{"label":text}]})
    src["input"]["message"]["content"]=[{"type":"text","text":text}]
    src["input"]["message"]["details"]={"label":text}
    model["input"]["patterns"]=list(patterns)
    write=model["input"]["phases"][0]
    write["toolResult"]={"content":[{"type":"text","text":text}],"details":{"label":text}}
    for c,ident in zip((src,model),IDS,strict=True):
        c.update(id=ident,requirement="trust.configured-redaction",covers=[POINT])
    return [src,model]


def required_predecessors():
    return [r for r in (*source_policy_fixtures(),*model_session_fixtures()) if
            "patterns" in r["input"] or r["input"].get("directRegex") or r["input"].get("fullContext")]


def validate_registration(rows):
    selected=[r for r in rows if r["id"] in IDS or POINT in r.get("covers",())]
    if selected and [r["id"] for r in selected]!=list(IDS):
        raise ValueError("Configured redaction requires both end-to-end cases")
    for row,case,expected in zip(selected,build_cases() if selected else [],CASE_SHA if selected else [],strict=True):
        if _digest(case)!=expected or _digest({k:row.get(k) for k in case})!=expected:
            raise ValueError("The configured full-context or stored-session fixture changed")


def family_complete(rows):
    from equivalence.harness import _same_json
    try:
        validate_registration(rows)
        seen={r["id"]:r for r in rows}
        for definition in [*required_predecessors(),*build_cases()]:
            row=seen[definition["id"]]
            if row.get("status")!="matched" or _digest({k:row.get(k) for k in definition})!=_digest(definition):
                return False
            if "openclaw" in row and not _same_json(row["openclaw"],row["python"]):
                return False
        return True
    except (KeyError,TypeError,ValueError):
        return False
