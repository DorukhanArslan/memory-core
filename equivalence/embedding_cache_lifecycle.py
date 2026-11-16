"""Frozen input facts for both original managed embedding-cache conditions.

The deterministic provider is fixture transport. Cache selection, source
preparation, retry/split dispatch, persistence and publication use real owners.
"""
from copy import deepcopy
import hashlib
import json

OPERATION = "embed-cache-lifecycle-runtime"
REQUIREMENT = "indexing.embedding-cache"
POINTS = ("indexing.embedding-cache.outcomes", "indexing.embedding-cache.boundaries")
NOW = 1_794_787_200_000
CASE_HASHES = {
    "embedding-cache-lifecycle-reuse-query-reopen": "7201b833a172005ded3e31228b54a9767adb3224ff44a1fbc9a6c89f9976ac42",
    "embedding-cache-lifecycle-changed-renamed-removed": "897d87666eb0c1cf43c7abb203a990664e84e0d1a188b56c63ccee9f682d8bd2",
    "embedding-cache-lifecycle-provider-identities": "fd8682b858e274c16057b57b37fcac966eaca4c5c74e4e38eb8f5a3eff0f409a",
    "embedding-cache-lifecycle-disabled-and-reenabled": "91738a9b2ed5e93d04161cea6a2a260948ad14bc8b79542ad772bbe973703260",
    "embedding-cache-lifecycle-batch-split-retention": "76fb2b30a1f61b49b62018ca8e7d53164423c2f86441a1c9a904b4736350da94",
    "embedding-cache-lifecycle-malformed-and-dimensions": "ab425bc9b23e495e7639a53fc5b197d9746a8b903e7331924447d87cc651e82f",
    "embedding-cache-lifecycle-source-freshness": "2745aba290bdb2282c2e3feeb1e0cb57357cf6ebfc04f81c2eaa091ecb00b461",
    "embedding-cache-lifecycle-publication-failure-recovery": "14ffc1c472bbc41cad5e6c785e2802f1c03fcc27104c2ae7703ef1236d37b4da",
}
POLICY = (
    "Compare the complete cache's seven SQL columns, decoded vector and exact "
    "embedding BLOB bytes, effective configured/used provider identity, and ALL "
    "ordered actual query/document request, vector-return and fixture-domain "
    "error receipts. Query requests are not treated as cached. Every fixture "
    "operation retains its complete state. Native sync/search and SDK reindex/"
    "search returns, exceptions and completion remain unchanged in raw evidence; "
    "their generic wrapper completion is not a common cache-protocol field. "
    "Whole index/source/SQL/identity observations bind each side's cache commit "
    "and index-publication causality. No request, cache row or vector is dropped "
    "or sorted to conceal a difference. Exact JSON numeric values compare with "
    "booleans distinct, without tolerance or raw-byte rewriting."
)
DRIVER_SCOPE = (
    "Actual original memory manager, registered deterministic fixture embedding "
    "adapter, cache/provider/source/retry owners and actual SDK store/provider "
    "counterparts. The fixture adapter uses the genuine ollama ID registration "
    "to exercise the original sequential inline branch; it is not a real Ollama "
    "service. Other provider IDs use one source. CLI manager purpose and public "
    "search-bootstrap sync requests avoid watcher/dirty-field substitutions. "
    "Chunking 400/80 and cache capacity 50000 remain original defaults. Real "
    "provider-callback file mutations and SQLite publication aborts are input "
    "faults. Full physical index/search/SQL/source and language returns/errors "
    "remain retained. No queued remote batch API, multimodal, full search-ranking "
    "or universal sync/session/provider lifecycle equivalence is claimed."
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf8")


def case_wire(case):
    return canonical({key: case[key] for key in ("id", "operation", "input")})


def _profile(identifier="ollama", model="fixture-model-a", endpoint="fixture://a", dimensions=2):
    return {"id": identifier, "model": model, "dimensions": dimensions,
            "cacheKeyData": {"provider": identifier, "model": model,
                             "endpoint": endpoint, "dimensions": dimensions},
            "indexIdentityAliases": []}


def _providers():
    base = _profile()
    alias = _profile(model="fixture-compatible-alias")
    alias["indexIdentityAliases"] = [{"model": base["model"],
                                      "cacheKeyData": deepcopy(base["cacheKeyData"])}]
    return {"base": base, "alias": alias, "model": _profile(model="fixture-model-b"),
            "endpoint": _profile(model="fixture-model-b", endpoint="fixture://b"),
            "provider-a": _profile(identifier="fixture-cache-a"),
            "provider-b": _profile(identifier="fixture-cache-b"),
            "dimensions": _profile(dimensions=3)}


def _op(operation, **options):
    return {"op": operation, **options}


def _sync(**options):
    return _op("sync", force=False, **options)


def _reopen(**options):
    return _op("reopen", **options)


def _force(**options):
    return _op("sync", force=True, **options)


def _base(files, operations, **options):
    driven = [{**deepcopy(operation), "nowMs": NOW + index * 1000}
              for index, operation in enumerate(operations)]
    return {"kind": "embedding-cache-lifecycle", "nowMs": NOW, "files": files,
            "providers": _providers(), "provider": "base", "cacheEnabled": True,
            "operations": driven, **options}


def _reuse():
    text = "Cedar forest maintenance is scheduled every Tuesday.\n"
    return _base({"memory/a.md": text, "memory/b.md": text}, [
        _sync(), _op("query", query="forest"), _op("query", query="forest"),
        _sync(), _force(), _reopen(), _sync(),
        _op("query", query="forest", providerControl={"queryFailures": 1}),
    ])


def _changes():
    rows = [f"entry-{index:03}: cedar forest maintenance keeps the archive consistent. "
            "Every source line remains visible to its real chunk preparer."
            for index in range(60)]
    before = "\n".join(rows) + "\n"
    rows[-1] = "entry-059: the final source line now records a revised retention decision."
    after = "\n".join(rows) + "\n"
    return _base({"memory/a.md": before}, [
        _sync(), _op("write", path="memory/a.md", text=after), _reopen(), _sync(),
        _op("rename", path="memory/a.md", to="memory/renamed.md"), _reopen(), _sync(),
        _op("remove", path="memory/renamed.md"), _reopen(), _sync(),
    ])


def _identities():
    return _base({"memory/a.md": "A provider-scoped cedar forest document.\n"}, [
        _sync(), _reopen(provider="alias"), _sync(), _force(),
        _reopen(provider="model"), _force(), _reopen(provider="endpoint"), _force(),
        _reopen(provider="provider-a"), _force(), _reopen(provider="provider-b"), _force(),
        _reopen(provider="dimensions"), _force(), _reopen(provider="base"), _force(),
    ])


def _disabled():
    return _base({"memory/a.md": "Cache policy retains a reusable forest vector.\n"}, [
        _sync(), _force(), _reopen(cacheEnabled=True), _force(),
        _reopen(cacheEnabled=False), _force(), _reopen(cacheEnabled=True), _force(),
    ], cacheEnabled=False)


def _batches():
    text = "".join(
        f"row{index:03}: forest cedar maple " + "leaf " * 18 + "\n"
        for index in range(160)
    )
    return _base({"memory/forest.md": text}, [
        _sync(providerControl={"maxItems": 1, "failText": "row080:", "documentFailures": 1}),
        _reopen(), _sync(), _force(),
    ])


def _malformed():
    prefix = "".join(
        f"stable-{index:03}: forest cedar archive facts keep their source ranges and reusable vectors. "
        "The unchanged prefix is retained across tail revisions.\n"
        for index in range(70)
    )
    return _base({"memory/a.md": prefix + "The initial tail has a valid cached vector.\n"}, [
        _sync(), _op("write", path="memory/a.md", text=prefix + "A changed tail awaits a valid vector.\n"),
        _reopen(), _sync(providerControl={"response": "empty"}), _reopen(), _sync(),
        _op("write", path="memory/a.md", text=prefix + "The later tail tests dimensional disagreement.\n"),
        _reopen(), _sync(providerControl={"response": "dimensions-3"}), _reopen(), _force(),
    ])


def _sources():
    return _base({"memory/a.md": "The initial source A remains authoritative.\n",
                  "memory/b.md": "The initial independent source B remains authoritative.\n"}, [
        _sync(), _op("write", path="memory/a.md", text="Source A is staged for a stale response.\n"),
        _reopen(), _sync(providerControl={"mutateOnDocumentCall": {
            "call": 1, "files": {"memory/a.md": "Source A changed while its provider was running.\n"}}}),
        _reopen(), _sync(),
        _op("write", path="memory/a.md", text="Valid source A is staged for an independent change.\n"),
        _op("write", path="memory/b.md", text="Source B is staged before its next revision.\n"),
        _reopen(), _sync(providerControl={"mutateOnDocumentCall": {
            "call": 1, "files": {"memory/b.md": "Independent source B changed while valid A returned.\n"}}}),
        _reopen(), _sync(),
    ])


def _publication():
    return _base({"memory/a.md": "The published source precedes the failed replacement.\n"}, [
        _sync(), _op("write", path="memory/a.md", text="A valid generated replacement survives publication failure.\n"),
        _reopen(), _sync(publicationFailure=True), _reopen(), _sync(),
        _op("query", query="replacement"),
    ])


def _definitions():
    values = (("reuse-query-reopen", _reuse()), ("changed-renamed-removed", _changes()),
              ("provider-identities", _identities()), ("disabled-and-reenabled", _disabled()),
              ("batch-split-retention", _batches()), ("malformed-and-dimensions", _malformed()),
              ("source-freshness", _sources()), ("publication-failure-recovery", _publication()))
    return [{"id": "embedding-cache-lifecycle-" + name, "operation": OPERATION,
             "requirement": REQUIREMENT, "covers": list(POINTS), "input": value,
             "normalizationPolicy": POLICY, "driverScope": DRIVER_SCOPE}
            for name, value in values]


def build_cases():
    cases = _definitions()
    actual = {case["id"]: hashlib.sha256(case_wire(case)).hexdigest() for case in cases}
    if actual != CASE_HASHES:
        raise ValueError("The complete embedding-cache lifecycle inputs changed")
    return cases


def validate_case(case):
    expected = next((value for value in build_cases() if value["id"] == case.get("id")), None)
    if expected is None or canonical(case) != canonical(expected):
        raise ValueError("Embedding-cache lifecycle requires its exact complete frozen definition")
    return deepcopy(case)


def validate_input(value):
    if not any(canonical(value) == canonical(case["input"]) for case in build_cases()):
        raise ValueError("Embedding-cache lifecycle requires an exact frozen common input")


def family_members(cases):
    return [case for case in cases if case.get("operation") == OPERATION
            or str(case.get("id", "")).startswith("embedding-cache-lifecycle-")
            or set(case.get("covers", ())) & set(POINTS)]


def validate_registration(cases):
    family = family_members(cases)
    if not family:
        return
    expected = build_cases()
    if [case.get("id") for case in family] != [case["id"] for case in expected]:
        raise ValueError("Embedding-cache lifecycle requires all eight cases once in frozen order")
    for case in family:
        validate_case(case)


def family_complete(rows):
    family = family_members(rows)
    expected = build_cases()
    if [row.get("id") for row in family] != [case["id"] for case in expected]:
        return False
    try:
        for row in family:
            validate_case({key: row[key] for key in (
                "id", "operation", "requirement", "covers", "input", "normalizationPolicy", "driverScope")})
            if row.get("status") != "matched" or row.get("runtimeEvidenceValidated") is not True:
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False
