"""Register the complete plan and stored ranking matrix for both numeric conditions."""
import hashlib
import json

from equivalence.engine_numeric_boundaries import build_numeric_flush_cases
from equivalence.engine_numeric_rank import build_rank_cases

REQUIREMENT = "engine.numeric-boundaries"
POINTS = (REQUIREMENT + ".outcomes", REQUIREMENT + ".boundaries")
SOURCE_OPERATION = "engine-numeric-boundaries"
SOURCE_OWNERS = ("extensions/memory-core/src/flush-plan.ts", "src/agents/date-time.ts")
DEFINITION_SHA256 = "7899d8bd5d862e4ffd57ee0e11b406c5da3c74c58c9afc2738008644041d57df"


def _wire(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def build_cases():
    rows = [*build_numeric_flush_cases(), *build_rank_cases()]
    if hashlib.sha256(_wire(rows)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("The fixed numeric matrix changed")
    return rows


def _family(cases):
    return [case for case in cases if case.get("requirement") == REQUIREMENT
            or case.get("operation") == SOURCE_OPERATION or set(case.get("covers", ())).intersection(POINTS)]


def validate_registration(cases):
    rows = _family(cases)
    if rows and _wire(rows) != _wire(build_cases()):
        raise ValueError("Numeric conditions require all four complete cases in order")


def validate_source_pair(case, imports, sources, native, sdk):
    from equivalence.engine_numeric_boundaries import validate_numeric_flush

    if imports != list(SOURCE_OWNERS) or not set(SOURCE_OWNERS) <= {source["path"] for source in sources}:
        raise ValueError("The original flush planner and time-format owner must be loaded for this case")
    validate_numeric_flush(case, native)
    validate_numeric_flush(case, sdk)


def family_complete(rows):
    family = _family(rows)
    if not family or any(row.get("status") != "matched" or row.get("numericEvidenceValidated") is not True
                         for row in family):
        return False
    try:
        definitions = build_cases()
        return len(family) == len(definitions) and all(
            _wire({key: row[key] for key in definition}) == _wire(definition)
            for row, definition in zip(family, definitions, strict=True))
    except (KeyError, ValueError, TypeError):
        return False
