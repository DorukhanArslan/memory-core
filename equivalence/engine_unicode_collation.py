"""Whole ordered hybrid hits, original concept tags and UTF-16 cuts for both Unicode points."""

from __future__ import annotations

import hashlib
import json
from random import Random

REQUIREMENT = "engine.unicode-collation"
OPERATION = "engine-unicode-collation"
POINTS = (REQUIREMENT + ".outcomes", REQUIREMENT + ".boundaries")
DIAGNOSTIC = "hybrid-unicode-path-collation-diagnostic"
OWNERS = sorted((
    "extensions/memory-core/src/concept-vocabulary.ts",
    "extensions/memory-core/src/memory/hybrid.ts",
    "packages/normalization-core/src/string-coerce.ts",
    "packages/normalization-core/src/utf16-slice.ts",
))
PROFILE = (
    "Actual pinned hybrid candidate merger with identical scores and ranges, concept vocabulary, "
    "optional-string lowercasing, word-like boundaries and original UTF-16 slicing and truncation. "
    "Return entire ordered hits and complete outputs for fixed named and generated samples. "
    "The pinned English default locale, ICU 78.3 and Unicode 17.0 are required. UTF-16 unit "
    "limits can split combining or emoji clusters; only valid surrogate pairs receive edge protection."
)
PRIOR_NATIVE_F01_SHA256 = "5557cac38760fa4dfada60946a7009a3c9c021ba550297aaa6ba0677b2c00471"
MEASURED_SDK_F01_SHA256 = "1cee3224f3ab57e567fb26b7e0c553800fcea3634ca23087569f39a231f1044f"
DEFINITION_SHA256 = "49735cb2f505fbc0a09adafd9b953cc3998b2bc61ec0f88f5e3a1bd928d16113"


def _wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()


def _case(name, texts, paths):
    vector = [{"id": f"unicode-{i}", "path": f"memory/{value}.md", "startLine": 2, "endLine": 4,
               "source": "memory", "snippet": f"same score, source {i}", "vectorScore": 0.8}
              for i, value in enumerate(paths)]
    merge = {"kind": "merge", "vectorWeight": 0.7, "textWeight": 0.3, "vector": vector, "keyword": []}
    return {"id": "unicode-collation-" + name, "requirement": REQUIREMENT, "operation": OPERATION,
            "covers": list(POINTS), "driverScope": PROFILE, "normalizationPolicy": "Exact whole return, preserving order.",
            "input": {"merge": merge, "texts": texts, "ranges": [[0, 0], [0, 1], [0, 2], [1, 2], [1, 5],
                          [-5, -1], [2, 0], [3, 17], [8, 32], [0, 99]], "limits": [-1, 0, 1, 2, 3, 4, 7, 16, 32]}}


def _definitions():
    alphabet = ("a", "A", "ä", "a\u0308", "ß", "ss", "ø", "İ", "ς", "ﬃ", "Ꜳ", "é", "𐐀",
                "𐐨", "𖺠", "𰀀", "日本", "ไทย", "৪", "ـ", "👩🏽‍💻", "🇹🇷", "́", "_", "\0", "\ud800", "\udfff")
    rng = Random(170009)
    generated = ["".join(rng.choices(alphabet, k=rng.randrange(1, 8))) for _ in range(36)]
    named = ["", "a", "A", "ß", "ss", "Straße", "STRASSE", "t", "ẞ", "e\u0301", "é", "İ", "I", "ı", "i",
             "ΟΣ", "ΟΣΑ", "ς", "æ", "œ", "a-b", "a_b", "００９", "01", "a\0b", "𐐀", "𖺠"]
    cases = [_case("named-order", ["Straße STRASSE ẞ ss t", " İSTANBUL I ı i ", "ΟΣ ΟΣΑ Σ",
                              "CAFÉ cafe\u0301 Kelvin ﬃ ①", "𐐀ABC 𖺠𖺠"], named),
             _case("words-and-cuts", ["", "\ud800", "\udfff", "A\ud800B\udfffC", "A😀B", "x̣́",
                              "👩🏽‍💻🇹🇷1️⃣", "क्‍ष क्षमा", "日本語を学ぶ。東京都", "ประเทศไทยภาษาไทย",
                              "𰀀 𰀀𰀀 abc𰀀", "한글 게이트웨이", "a.b 7.15 26.md can't café",
                              "ﬃ" * 11, "𐐀" * 16, "𐐀" * 17, "\u200d🐈‍⬛\0"], list(reversed(alphabet))),
             _case("generated", generated, generated)]
    return cases


def build_cases():
    rows = _definitions()
    if hashlib.sha256(_wire(rows)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("The frozen Unicode comparisons changed")
    return rows


def validate_registration(cases):
    rows = [c for c in cases if c.get("operation") == OPERATION or set(c.get("covers", ())).intersection(POINTS)]
    if rows:
        from equivalence.hybrid_scoring import build_hybrid_scoring_cases

        original = next(row for row in build_hybrid_scoring_cases() if row["id"] == DIAGNOSTIC)
        if [case for case in cases if case.get("id") == DIAGNOSTIC] != [original]:
            raise ValueError("The previous real hybrid tie diagnostic must be present unchanged")
    if rows and _wire(rows) != _wire(build_cases()):
        raise ValueError("Both Unicode conditions require all named and generated batches in order")


def run_sdk(arguments):
    from memory_core._icu import word_tokens
    from memory_core.bootstrap._js import slice_utf16_safe, truncate_utf16_safe, utf16_len
    from memory_core.consolidation.concepts import _normalize_lowercase_string, derive_concept_tags
    from equivalence.hybrid_scoring import run_hybrid_scoring

    rows = []
    for text in arguments["texts"]:
        encoded = text.encode("utf-16-le", "surrogatepass")
        rows.append({"input": text, "units": [int.from_bytes(encoded[i:i+2], "little") for i in range(0, len(encoded), 2)],
                     "length": utf16_len(text), "lower": _normalize_lowercase_string(text), "wordLike": word_tokens(text),
                     "tags": derive_concept_tags("", text, limit=64),
                     "slices": [slice_utf16_safe(text, start, end) for start, end in arguments["ranges"]],
                     "truncated": [truncate_utf16_safe(text, limit) for limit in arguments["limits"]]})
    return {"merge": run_hybrid_scoring(arguments["merge"]), "texts": rows}


def sdk_unicode_identity():
    """Verify the active binding's installed libraries against its wheel RECORD."""
    import base64
    from importlib.metadata import distribution
    from pathlib import Path

    from icu4py import icu_version
    from memory_core._icu import _icu

    owner = _icu()
    package = distribution("icu4py")
    if package.version != "1.2.0" or icu_version != "78.3":
        raise ValueError("Unexpected ICU binding or runtime version")
    checked = {}
    for label, library in (("i18n", owner.i18n_library), ("common", owner.common_library), ("data", owner.data_library)):
        path = Path(library._name).resolve(strict=True)
        files = [entry for entry in package.files or () if Path(package.locate_file(entry)).resolve() == path]
        if len(files) != 1 or files[0].hash is None or files[0].hash.mode != "sha256":
            raise ValueError("The ICU dynamic library is missing from the binding's wheel RECORD")
        data = path.read_bytes()
        digest = hashlib.sha256(data)
        if base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode() != files[0].hash.value:
            raise ValueError("The active ICU dynamic library differs from its installed wheel")
        checked[label] = {"name": path.name, "bytes": len(data), "sha256": digest.hexdigest()}
    return {"distribution": package.metadata["Name"], "version": package.version, "icu": icu_version,
            "unicode": ".".join(map(str, owner.unicode_version[:2])), "libraries": checked}


def validate_source_pair(case, source_imports, sources, runtime, native, sdk):
    if source_imports != OWNERS or not set(OWNERS) <= {item["path"] for item in sources}:
        raise ValueError("The per-case original Unicode owner imports changed")
    if runtime != {"icu": "78.3", "unicode": "17.0", "locale": "en-US"}:
        raise ValueError("Unicode comparison used a different Node collation profile")
    arguments = case["input"]
    for result in (native, sdk):
        if len(result["merge"]["merged"]) != len(arguments["merge"]["vector"]):
            raise ValueError("Tied candidate merger did not retain every complete hit")
        if [row["input"] for row in result["texts"]] != arguments["texts"]:
            raise ValueError("A Unicode text probe was omitted or changed")
        for row in result["texts"]:
            if row["length"] != len(row["units"]) or len(row["slices"]) != len(arguments["ranges"]) or len(row["truncated"]) != len(arguments["limits"]):
                raise ValueError("Unicode unit inventory or truncation probes are incomplete")


def family_complete(rows):
    from equivalence.search_contract import _same_json

    frozen = build_cases()
    family = [row for row in rows if row.get("operation") == OPERATION]
    f01 = [row for row in rows if row["id"] == DIAGNOSTIC]
    if len(f01) != 1 or f01[0]["status"] != "matched" or len(family) != len(frozen):
        return False
    previous = f01[0]
    if "openclaw" in previous and "python" in previous:
        receipts = {side: hashlib.sha256(_wire(previous[side])).hexdigest() for side in ("openclaw", "python")}
        if not _same_json(previous["openclaw"], previous["python"]):
            return False
    else:
        # The streaming EOF assessor already verified equality of the full
        # numeric JSON values, then retained each side's original JSON hash.
        receipts = previous.get("publicValueSha256")
    if receipts != {"openclaw": PRIOR_NATIVE_F01_SHA256, "python": MEASURED_SDK_F01_SHA256}:
        return False
    return all(row.get("status") == "matched" and row.get("unicodeEvidenceValidated") is True
               and _wire({k: row.get(k) for k in given}) == _wire(given)
               for row, given in zip(family, frozen, strict=True))
