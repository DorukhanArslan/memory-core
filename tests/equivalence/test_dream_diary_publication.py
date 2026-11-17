import json

import pytest

from equivalence.dream_diary import build_cases
from equivalence.dream_diary_evidence import validate_sdk
from equivalence.dream_diary_sdk import run_sdk


def test_rejected_stale_quote_preserves_unchanged_file_identity(tmp_path):
    case = next(row for row in build_cases() if row["id"].endswith("missing-quoted-context"))
    public = run_sdk(case, tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_bytes())
    validate_sdk(case, public, raw, tmp_path)
    raw[0]["rows"][-1]["files"]["DREAMS.md"]["ino"] += 1
    with pytest.raises(ValueError, match="suppressed publication"):
        validate_sdk(case, public, raw, tmp_path)


def test_same_document_bytes_require_original_lease_contention(tmp_path):
    case = next(row for row in build_cases() if row["id"].endswith("competing-diary-writers"))
    public = run_sdk(case, tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_bytes())
    validate_sdk(case, public, raw, tmp_path)
    raw[0]["race"][2]["pending"] = False
    with pytest.raises(ValueError, match="did not wait"):
        validate_sdk(case, public, raw, tmp_path)
