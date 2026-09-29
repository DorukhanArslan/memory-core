import math
from pathlib import Path

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.supplements import StaticMemoryCorpusSupplement
from memory_core.tools.common import (
    MemoryToolInputError,
    read_corpus_param,
    read_finite_number_param,
    read_positive_integer_param,
    read_string_param,
    resolve_snake_case_param_key,
    to_tool_error,
)
from memory_core.tools.memory_search import (
    MemorySearchParams,
    execute_memory_search_tool,
    memory_search,
    read_memory_search_params,
)
from memory_core.workspace import MemoryWorkspace


def test_reads_numeric_strings_with_the_strict_token_regex():
    assert read_positive_integer_param({"maxResults": "5"}, "maxResults") == 5
    assert read_positive_integer_param({"maxResults": " +5 "}, "maxResults") == 5
    assert read_positive_integer_param({"maxResults": "5.0"}, "maxResults") == 5
    assert read_positive_integer_param({"maxResults": "1E1"}, "maxResults") == 10
    assert read_finite_number_param({"minScore": "0.3"}, "minScore") == 0.3
    assert read_finite_number_param({"minScore": ".5"}, "minScore") == 0.5
    assert read_finite_number_param({"minScore": "-2e-1"}, "minScore") == -0.2


@pytest.mark.parametrize(
    "raw",
    [
        "0x10",
        "1_000",
        "５",  # JavaScript \d is ASCII-only
        "\x1c5",  # Python str.strip() would remove it; ECMAScript trim does not
        "5 5",
        True,
        False,
        [5],
        {"n": 5},
        0,
        -1,
        2.5,
        2**53,
        math.nan,
        math.inf,
    ],
)
def test_rejects_non_positive_integer_max_results(raw):
    with pytest.raises(MemoryToolInputError) as raised:
        read_positive_integer_param({"maxResults": raw}, "maxResults")

    assert str(raised.value) == "maxResults must be a positive integer"
    assert raised.value.status == 400


def test_trims_numeric_strings_with_the_ecmascript_whitespace_set():
    assert read_positive_integer_param({"maxResults": "﻿5\n"}, "maxResults") == 5


@pytest.mark.parametrize("raw", ["abc", "1e400", True, math.nan, -math.inf, 10**400, [0.5]])
def test_rejects_non_finite_min_score(raw):
    with pytest.raises(MemoryToolInputError, match="^minScore must be a finite number$"):
        read_finite_number_param({"minScore": raw}, "minScore")


def test_missing_and_null_numbers_read_as_omitted():
    assert read_positive_integer_param({}, "maxResults") is None
    assert read_positive_integer_param({"maxResults": None}, "maxResults") is None
    assert read_finite_number_param({"minScore": None}, "minScore") is None


@pytest.mark.parametrize("raw", ["", "   ", "\ufeff\n", "\u3000"])
def test_blank_numeric_strings_read_as_omitted(raw):
    # common.ts isBlankParamValue (b22c36f1125, aaf5ab910cb): a blank string is no value; the
    # ECMAScript trim set decides what is blank.
    assert read_positive_integer_param({"maxResults": raw}, "maxResults") is None
    assert read_positive_integer_param({"max_results": raw}, "maxResults") is None
    assert read_finite_number_param({"minScore": raw}, "minScore") is None


def test_a_control_separator_is_not_blank():
    with pytest.raises(MemoryToolInputError, match="^maxResults must be a positive integer$"):
        read_positive_integer_param({"maxResults": "\x1c"}, "maxResults")
    with pytest.raises(MemoryToolInputError, match="^minScore must be a finite number$"):
        read_finite_number_param({"minScore": "\x1c"}, "minScore")


def test_read_corpus_param_checks_the_closed_enum():
    allowed = ("memory", "wiki", "all")
    assert read_corpus_param({"corpus": " wiki "}, allowed) == "wiki"
    assert read_corpus_param({"corpus": "  "}, allowed) is None
    assert read_corpus_param({"corpus": 5}, allowed) is None
    assert read_corpus_param({}, allowed) is None
    for raw in ("MEMORY", "sessions", "memory,wiki"):
        with pytest.raises(MemoryToolInputError) as raised:
            read_corpus_param({"corpus": raw}, allowed)
        assert str(raised.value) == "corpus must be one of: memory, wiki, all"


def test_snake_case_alias_applies_only_when_the_camel_key_is_absent():
    assert resolve_snake_case_param_key({"max_results": 1}, "maxResults") == "max_results"
    assert resolve_snake_case_param_key({"maxResults": None, "max_results": 1}, "maxResults") == (
        "maxResults"
    )
    assert read_positive_integer_param({"maxResults": None, "max_results": 1}, "maxResults") is None
    with pytest.raises(MemoryToolInputError, match="^maxResults must be a positive integer$"):
        read_positive_integer_param({"max_results": "x"}, "maxResults")


def test_read_string_param_trims_and_treats_blank_as_missing():
    assert read_string_param({"corpus": " memory "}, "corpus") == "memory"
    assert read_string_param({"corpus": "  "}, "corpus") is None
    assert read_string_param({"corpus": 5}, "corpus") is None
    with pytest.raises(MemoryToolInputError, match="^query required$"):
        read_string_param({"query": "　"}, "query", required=True)


def test_memory_search_params_are_read_in_upstream_order():
    assert read_memory_search_params(
        {"query": " x ", "max_results": "3", "minScore": 0, "corpus": "wiki"}
    ) == MemorySearchParams(query="x", max_results=3, min_score=0.0, corpus="wiki")
    for params, message in [
        (None, "query required"),
        ([("query", "x")], "query required"),
        ({"maxResults": 0}, "query required"),
        ({"query": "x", "maxResults": 0, "minScore": "bad"}, "maxResults must be a positive integer"),
        ({"query": "x", "minScore": "bad"}, "minScore must be a finite number"),
        ({"query": "x", "minScore": "bad", "corpus": "bogus"}, "minScore must be a finite number"),
        ({"query": "x", "corpus": "MEMORY"}, "corpus must be one of: memory, wiki, all, sessions"),
    ]:
        with pytest.raises(MemoryToolInputError) as raised:
            read_memory_search_params(params)
        assert raised.value.to_tool_error() == {
            "status": "error",
            "tool": "memory_search",
            "error": message,
        }


def test_to_tool_error_uses_the_type_name_for_blank_messages():
    assert to_tool_error(RuntimeError(""), tool="memory_search") == {
        "status": "error",
        "tool": "memory_search",
        "error": "RuntimeError",
    }


def _fts_store(tmp_path: Path) -> tuple[MemoryConfig, SQLiteMemoryStore]:
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        flags=FeatureFlags(vector_search=False),
    )
    return cfg, SQLiteMemoryStore(cfg, None)


def test_memory_search_raises_tool_input_errors_instead_of_disabled_payloads(tmp_path: Path):
    cfg, store = _fts_store(tmp_path)

    with pytest.raises(MemoryToolInputError, match="^query required$"):
        memory_search(cfg, store, query="  ")
    with pytest.raises(MemoryToolInputError, match="^maxResults must be a positive integer$"):
        memory_search(cfg, store, query="x", max_results=True)


def _write_memory_and_session(tmp_path: Path) -> MemoryWorkspace:
    (tmp_path / "MEMORY.md").write_text("- Cobalt router lives in the rack.\n", encoding="utf-8")
    sessions = tmp_path / "state" / "agents" / "main" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "s1.jsonl").write_text(
        '{"type":"message","message":{"role":"user","content":'
        '[{"type":"text","text":"The cobalt router moved."}]}}\n',
        encoding="utf-8",
    )
    (sessions / "sessions.json").write_text(
        '{"agent:main:s1":{"sessionFile":"s1.jsonl"}}\n', encoding="utf-8"
    )
    return MemoryWorkspace(tmp_path, openclaw_state_dir=tmp_path / "state")


def test_an_omitted_corpus_searches_every_source_and_an_unknown_one_raises(tmp_path: Path):
    # tools.ts readCorpusParam (4b3ee5e7eb6): an unknown corpus fails closed; an omitted or
    # blank one searches all indexed sources and never queries supplements.
    cfg, store = _fts_store(tmp_path)
    store.reindex(_write_memory_and_session(tmp_path))
    wiki = StaticMemoryCorpusSupplement(
        [{"corpus": "wiki", "path": "w.md", "score": 9, "snippet": "cobalt wiki"}]
    )

    def corpora(corpus):
        result = memory_search(cfg, store, query="cobalt", corpus=corpus, supplements=[wiki])
        return sorted(item["corpus"] for item in result["results"])

    assert corpora("memory") == ["memory"]
    assert corpora("sessions") == ["sessions"]
    assert corpora("wiki") == ["wiki"]
    assert corpora("all") == ["memory", "sessions", "wiki"]
    assert corpora(None) == ["memory", "sessions"]
    assert corpora("") == ["memory", "sessions"]
    with pytest.raises(MemoryToolInputError) as raised:
        corpora("bogus")
    assert raised.value.to_tool_error() == {
        "status": "error",
        "tool": "memory_search",
        "error": "corpus must be one of: memory, wiki, all, sessions",
    }


def test_execute_memory_search_tool_accepts_raw_model_arguments(tmp_path: Path):
    cfg, store = _fts_store(tmp_path)
    store.reindex(_write_memory_and_session(tmp_path))

    result = execute_memory_search_tool(
        cfg, store, {"query": "cobalt", "max_results": "1", "corpus": " sessions "}
    )

    assert [item["path"] for item in result["results"]] == ["sessions/main/s1.jsonl"]
