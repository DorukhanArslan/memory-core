"""Closed real-manager family for the original index identity boundary condition.

Independent inputs are frozen before paired execution. All actual pre-query
identity diagnostics, first-query results and source bytes retain their fields.
Standalone probes and inventory checks award no acceptance conditions.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "index-identity-boundaries-runtime"
REQUIREMENT = "indexing.identity"
POINTS = ("indexing.identity.boundaries",)
OUTCOME_OPERATION = "index-identity"
CASE_HASHES = {'index-identity-boundaries-matching': '05498bb4b7f614baaa8c26aa6ee41ee5d168f847fd1e05d852d19911baeaf8fd',
 'index-identity-boundaries-missing-metadata': 'f3a4e74f0d1a72fd89fd697a02bdef50222ab9c30a2209773829b8e7033938f2',
 'index-identity-boundaries-malformed-metadata': '603fff54ff3d6eac7a728f0f604bb39817a980207e7c44d92d2c844d5aacf94a',
 'index-identity-boundaries-older-provenance': '7c67bdd74ff31a22d01c03e5620b4dd91a29500b5b8525b4aae87cfb9a3dc04c',
 'index-identity-boundaries-older-chunker-only': '73ddd55444e799b016e5dde588685964a551de57d3297c86257f9ec9259078ec',
 'index-identity-boundaries-newer-provenance-older-chunker': 'ff614f006a7befc1f01c912d5c83eb31d3660106252e9a0d5505c4a77185a1a7',
 'index-identity-boundaries-newer-chunker-older-provenance': 'f4f67768ee188f9ab0936ac525dc8ef139e0b442992fcba1914e842a010df1ce',
 'index-identity-boundaries-provider-key-only': 'f850dc2426885f6b2c3977eb3da50e243af3dd6123d1b829fe2749e29cee9753',
 'index-identity-boundaries-model-only': '48723ca0cdcb8de719288f792a3833486bd253d51f277afc8198762d2ac7bb17',
 'index-identity-boundaries-provider-only': '8c12fc66a405085de36a7729be46d88a7378771beaee2732d95ab461926eaa83',
 'index-identity-boundaries-sources-only': 'c8f3acec301946d34ae2534fb48aa9c7c649aee7198711dfea160897b7327377',
 'index-identity-boundaries-scope-only': '7dd0d5dd9329b26d7550cdedf46a76fcf4530fa14732499fe7dd757a14428321',
 'index-identity-boundaries-chunk-tokens-only': '32cc40a04bd3f7cba6267df6c916eb517bcf0c42662f795e812bc1b0c3640101',
 'index-identity-boundaries-chunk-overlap-only': '5a31baccf4c598658ae03a41330344ea394aeb8121dc82f1b7d1abd193baa788',
 'index-identity-boundaries-tokenizer-only': '399f8c4d532bbae72982c9ac982af7bbfe41be1fca256e34781a9c94f161a3a2',
 'index-identity-boundaries-older-chunker-scope-incompatible': 'b92cf95556dcd40a9f49382690dcdd5904527dffa6b272cba22fcfec436d701a'}
MANIFEST = Path(__file__).resolve().parents[1] / "docs/index_identity_boundaries_literals.json"


def case_wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def validate_case(case):
    if (not isinstance(case, dict)
            or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION or case.get("requirement") != REQUIREMENT
            or case.get("covers") != list(POINTS) or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Index identity boundaries require an exact independently frozen sixteen-case literal")
    return deepcopy(case)


def build_cases(path=MANIFEST):
    manifest = json.loads(Path(path).read_text(encoding="utf8"))
    if (not isinstance(manifest, dict)
            or set(manifest) != {"kind", "acceptancePointsAwarded", "cases"}
            or manifest["kind"] != "index-identity-boundaries-acceptance-literals"
            or type(manifest["acceptancePointsAwarded"]) is not int
            or manifest["acceptancePointsAwarded"] != 0
            or not isinstance(manifest["cases"], list)
            or any(not isinstance(case, dict) for case in manifest["cases"])
            or [case.get("id") for case in manifest["cases"]] != list(CASE_HASHES)):
        raise ValueError("The original identity boundary condition requires all sixteen independently frozen literals")
    return [validate_case(case) for case in manifest["cases"]]


def family_members(cases):
    return [case for case in cases if case.get("operation") == OPERATION
            or case.get("requirement") == REQUIREMENT and case.get("operation") != OUTCOME_OPERATION
            or str(case.get("id", "")).startswith("index-identity-boundaries-")
            or set(case.get("covers", ())) & set(POINTS)]


def validate_registration(cases):
    family = family_members(cases)
    if not family:
        return
    if len(family) != len(CASE_HASHES) or [case.get("id") for case in family] != list(CASE_HASHES):
        raise ValueError("The original identity boundary requires the complete sixteen-case family atomically")
    for case in family:
        validate_case(case)
