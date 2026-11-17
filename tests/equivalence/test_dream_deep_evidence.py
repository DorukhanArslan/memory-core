import pytest

from equivalence.dream_deep import build_cases
from equivalence.dream_deep_evidence import _boundaries


def test_blocks_diary_published_before_cron_returns():
    case = next(c for c in build_cases() if c["id"].endswith("cron-pending-narrative"))
    text = case["input"]["provider"][-1]["text"]
    observation = {"diaryAtReturn": None, "documents": {"DREAMS.md": text},
                   "summaries": ["memory-core: dreaming promotion complete (narrativesPending=1)."]}
    _boundaries(case, [observation], [])
    observation["diaryAtReturn"] = text
    with pytest.raises(ValueError, match="Detached diary timing"):
        _boundaries(case, [observation], [])


def test_rejects_publication_failure_that_erased_prior_promotion():
    case = next(c for c in build_cases() if c["id"].endswith("report-publication-failure"))
    initial = {"workspace/DREAMS.md/keep.txt": b"Existing directory"}
    after = {**initial, "workspace/MEMORY.md": b"promoted fact"}
    result = {"events": [{"type": "memory.dream.completed", "phase": "deep", "outcome": "failed",
                          "error": "Refusing to write non-file DREAMS.md"}]}
    _boundaries(case, [result], [initial, after])
    del after["workspace/MEMORY.md"]
    with pytest.raises(ValueError, match="prior promotion"):
        _boundaries(case, [result], [initial, after])
