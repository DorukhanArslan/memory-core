"""HostKit.dispatch(): one tool-call entry point (docs/host_kit.md, entry point 2, Task 2)."""

from __future__ import annotations

import json
import os
import threading

import pytest

import memory_core.host.kit as kit_module
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation import record_short_term_recalls, undecorate_search_results
from memory_core.consolidation.store import recall_store_path
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState
from memory_core.tools.common import MemoryToolError, MemoryToolInputError
from memory_core.tools.memory_get import execute_memory_get_tool
from memory_core.tools.memory_search import MemorySearchToolContext, execute_memory_search_tool

NOW_MS = 1_790_375_400_000  # 2026-09-25 22:30 UTC
SESSION = SessionState.new(session_key="agent:main:main", session_id="s1")


class SpyEmbeddingProvider:
    provider_id = "spy"
    model = "spy-model"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(f"query:{text}")
        return [0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(f"documents:{len(texts)}")
        return [[0.0] for _ in texts]


def _seed(root) -> None:
    (root / "memory").mkdir(parents=True)
    (root / "MEMORY.md").write_text("# MEMORY.md\n\n- The zephyrquartz project is paused.\n")
    (root / "memory" / "2026-09-25.md").write_text("- quokkabyte shipped the importer.\n")


def _kit(root, *, embedder=None, flags=None, **options) -> HostKit:
    # No temporal decay: two calls at different instants would differ in the last digits.
    config = MemoryConfig(
        workspace_dir=root,
        flags=flags or FeatureFlags(vector_search=False, temporal_decay=False),
    )
    memory = Memory.from_workspace(
        root, embedding_provider=embedder, config=config, initialize=False
    )
    return HostKit(memory, now_ms=lambda: NOW_MS, **options)


def _files(root) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".memory-core" not in path.parts
    }


def test_dispatch_memory_search_equals_execute_memory_search_tool(tmp_path, monkeypatch):
    _seed(tmp_path)
    kit = _kit(tmp_path)
    args = {"query": "zephyrquartz", "maxResults": 3}
    context = MemorySearchToolContext(clock=lambda: NOW_MS)
    monkeypatch.setattr(
        kit_module, "execute_memory_search_tool",
        lambda *args, **kwargs: execute_memory_search_tool(*args, context=context, **kwargs),
    )

    result = kit.dispatch("memory_search", args, session=SESSION)

    assert result == execute_memory_search_tool(
        kit.memory.config, kit.memory.store, args, agent_session_key=SESSION.session_key,
        context=context,
    )
    assert [hit["path"] for hit in result["results"]] == ["MEMORY.md"]


def test_dispatch_search_prepares_aliases_without_mutating_caller(tmp_path, monkeypatch):
    kit = _kit(tmp_path)
    arguments = {"query": "cedar", "max_results": "3", "min_score": "0"}
    observed = []
    monkeypatch.setattr(
        kit_module, "execute_memory_search_tool",
        lambda _config, _store, params, **_options: observed.append(params) or {"results": []},
    )

    assert kit.dispatch("memory_search", arguments, session=SESSION) == {"results": []}
    assert observed == [{"query": "cedar", "maxResults": "3", "minScore": "0"}]
    assert arguments == {"query": "cedar", "max_results": "3", "min_score": "0"}


def test_dispatch_search_preserves_ordinary_tool_error(tmp_path, monkeypatch):
    kit = _kit(tmp_path)

    def refused(*_args, **_options):
        raise MemoryToolError("Memory is disabled for this agent.", tool="memory_search")

    monkeypatch.setattr(kit_module, "execute_memory_search_tool", refused)
    assert kit.dispatch("memory_search", {"query": "cedar"}, session=SESSION) == {
        "status": "error", "tool": "memory_search",
        "error": "Memory is disabled for this agent.",
    }


def test_dispatch_accepts_mappings_json_text_and_none(tmp_path):
    _seed(tmp_path)
    kit = _kit(tmp_path)
    args = {"path": "MEMORY.md", "from": 3, "lines": 1}

    expected = execute_memory_get_tool(kit.memory.config, args)
    assert kit.dispatch("memory_get", args, session=SESSION) == expected
    assert kit.dispatch("memory_get", json.dumps(args), session=SESSION) == expected
    with pytest.raises(MemoryToolInputError) as missing:
        execute_memory_get_tool(kit.memory.config, {})
    for empty in (None, "", "  \n"):
        assert kit.dispatch("memory_get", empty, session=SESSION) == missing.value.to_tool_error()


def test_dispatch_invalid_json_returns_an_error_payload(tmp_path):
    kit = _kit(tmp_path)

    assert kit.dispatch("memory_search", '{"query": ', session=SESSION) == {
        "status": "error",
        "tool": "memory_search",
        "error": "invalid JSON arguments: Expecting value",
    }


def test_dispatch_non_object_json_returns_an_error_payload(tmp_path):
    kit = _kit(tmp_path)

    for text in ("[]", '"zephyrquartz"', "3"):
        assert kit.dispatch("memory_search", text, session=SESSION) == {
            "status": "error",
            "tool": "memory_search",
            "error": "arguments must be a JSON object",
        }


def test_dispatch_bad_params_return_the_upstream_error_payload(tmp_path):
    kit = _kit(tmp_path)
    args = {"query": "zephyrquartz", "maxResults": "many"}
    with pytest.raises(MemoryToolInputError) as raised:
        execute_memory_search_tool(kit.memory.config, kit.memory.store, args)

    assert kit.dispatch("memory_search", args, session=SESSION) == raised.value.to_tool_error()
    assert kit.dispatch("add_memory_entry", {"section": "Decisions"}, session=SESSION) == {
        "status": "error",
        "tool": "add_memory_entry",
        "error": "text required",
    }


def test_dispatch_unoffered_tool_returns_an_error_payload(tmp_path):
    kit = _kit(tmp_path)
    off = _kit(tmp_path, flags=FeatureFlags(vector_search=False, curated_memory_writes=False))

    assert kit.dispatch("shell", {"cmd": "ls"}, session=SESSION) == {
        "status": "error",
        "tool": "shell",
        "error": "tool shell is not available",
    }
    assert off.dispatch("append_daily_note", {"text": "x"}, session=SESSION) == {
        "status": "error",
        "tool": "append_daily_note",
        "error": "tool append_daily_note is not available",
    }


def test_dispatch_curation_with_the_flag_off_writes_nothing(tmp_path, monkeypatch):
    _seed(tmp_path)
    kit = _kit(tmp_path, flags=FeatureFlags(vector_search=False, curated_memory_writes=False))
    reindexes: list[object] = []
    store = kit.memory.store
    monkeypatch.setattr(store, "reindex", lambda workspace: reindexes.append(workspace))
    before = _files(tmp_path)

    for name, args in (
        ("add_memory_entry", {"section": "Decisions", "text": "ship it"}),
        ("append_daily_note", {"text": "shipped"}),
        ("upsert_user_directive", {"text": "Always answer in Turkish."}),
    ):
        assert kit.dispatch(name, args, session=SESSION)["status"] == "error"

    assert _files(tmp_path) == before
    assert reindexes == []


def test_dispatch_curated_write_is_found_by_the_next_search(tmp_path):
    _seed(tmp_path)
    kit = _kit(tmp_path)

    written = kit.dispatch(
        "add_memory_entry", {"section": "Decisions", "text": "velvetkiwi goes live"}, session=SESSION
    )
    noted = kit.dispatch("append_daily_note", '{"text": "marbleowl call at noon"}', session=SESSION)

    assert written == {
        "status": "ok",
        "tool": "add_memory_entry",
        "path": "MEMORY.md",
        "action": "added",
        "chars": written["chars"],
    }
    assert noted["path"] == "memory/2026-09-25.md"
    search = kit.dispatch("memory_search", {"query": "velvetkiwi"}, session=SESSION)
    assert [hit["path"] for hit in search["results"]] == ["MEMORY.md"]
    search = kit.dispatch("memory_search", {"query": "marbleowl"}, session=SESSION)
    assert [hit["path"] for hit in search["results"]] == ["memory/2026-09-25.md"]


def test_dispatch_tool_exception_becomes_an_error_payload(tmp_path, monkeypatch):
    kit = _kit(tmp_path)

    def boom(config, params):
        raise RuntimeError("disk vanished")

    monkeypatch.setattr(kit_module, "execute_memory_get_tool", boom)
    assert kit.dispatch("memory_get", {"path": "MEMORY.md"}, session=SESSION) == {
        "status": "error",
        "tool": "memory_get",
        "error": "disk vanished",
    }

    def interrupted(config, params):
        raise KeyboardInterrupt

    monkeypatch.setattr(kit_module, "execute_memory_get_tool", interrupted)
    with pytest.raises(KeyboardInterrupt):
        kit.dispatch("memory_get", {"path": "MEMORY.md"}, session=SESSION)


def test_dispatch_rejects_a_non_string_name(tmp_path):
    kit = _kit(tmp_path)

    with pytest.raises(TypeError, match="name"):
        kit.dispatch(None, {}, session=SESSION)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="arguments"):
        kit.dispatch("memory_search", ["zephyrquartz"], session=SESSION)  # type: ignore[arg-type]


def test_dispatch_records_recalls_only_with_dreaming_enabled(tmp_path):
    twin = tmp_path / "twin"
    for root in (tmp_path / "off", tmp_path / "on", twin):
        _seed(root)
        # These workspaces represent identical source observations, including
        # the indexed mtime now retained in each result's provenance.
        for source in (root / "MEMORY.md", root / "memory" / "2026-09-25.md"):
            os.utime(source, (NOW_MS / 1000, NOW_MS / 1000))
    args = {"query": "quokkabyte importer"}

    _kit(tmp_path / "off").dispatch("memory_search", args, session=SESSION)
    result = _kit(tmp_path / "on", dreaming_enabled=True).dispatch(
        "memory_search", args, session=SESSION
    )
    twin_kit = _kit(twin)
    twin_result = execute_memory_search_tool(twin_kit.memory.config, twin_kit.memory.store, args)
    record_short_term_recalls(
        config=twin_kit.memory.config,
        query=args["query"],
        results=undecorate_search_results(
            [hit for hit in twin_result["results"] if hit.get("corpus") == "memory"]
        ),
        now_ms=NOW_MS,
    )

    assert result["results"]
    assert not recall_store_path(tmp_path / "off").exists()
    assert recall_store_path(tmp_path / "on").read_text() == recall_store_path(twin).read_text()


def test_dispatch_with_vector_search_off_never_calls_the_embedder(tmp_path):
    _seed(tmp_path)
    spy = SpyEmbeddingProvider()
    kit = _kit(tmp_path, embedder=spy)
    spy.calls.clear()

    kit.dispatch("memory_search", {"query": "zephyrquartz"}, session=SESSION)
    kit.dispatch("memory_get", {"path": "MEMORY.md"}, session=SESSION)
    kit.dispatch("append_daily_note", {"text": "reindex me"}, session=SESSION)

    assert spy.calls == []


def test_parallel_reindexes_leave_a_consistent_index(tmp_path):
    _seed(tmp_path)
    kit = _kit(tmp_path)
    errors: list[BaseException] = []

    def write(prefix: str) -> None:
        try:
            for index in range(8):
                result = kit.dispatch(
                    "append_daily_note", {"text": f"{prefix}token{index}"}, session=SESSION
                )
                assert result["status"] == "ok" and "afterWriteError" not in result, result
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(prefix,)) for prefix in ("alpha", "beta")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    daily = (tmp_path / "memory" / "2026-09-25.md").read_text()
    for prefix in ("alpha", "beta"):
        for index in range(8):
            assert f"{prefix}token{index}\n" in daily
    chunks = kit.memory.store.count_chunks()
    kit.memory.store.reindex(kit.memory.workspace)
    assert kit.memory.store.count_chunks() == chunks
    hits = kit.dispatch("memory_search", {"query": "betatoken7"}, session=SESSION)["results"]
    assert [hit["path"] for hit in hits] == ["memory/2026-09-25.md"]


def test_parallel_searches_record_every_recall(tmp_path):
    _seed(tmp_path)
    kit = _kit(tmp_path, dreaming_enabled=True)
    errors: list[BaseException] = []
    start = threading.Barrier(8)

    def search() -> None:
        try:
            start.wait()
            for _ in range(5):
                result = kit.dispatch("memory_search", {"query": "quokkabyte"}, session=SESSION)
                assert result["results"]
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=search) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    entries = json.loads(recall_store_path(tmp_path).read_text())["entries"]
    assert entries["memory:memory/2026-09-25.md:1:2"]["recallCount"] == 40


def test_dispatcher_equals_dispatch_with_the_session(tmp_path, monkeypatch):
    # HostKit.dispatcher (docs/host_kit.md, F24): FlushRequest.dispatch's two-argument shape.
    _seed(tmp_path)
    kit = _kit(tmp_path)
    context = MemorySearchToolContext(clock=lambda: NOW_MS)
    monkeypatch.setattr(
        kit_module, "execute_memory_search_tool",
        lambda *args, **kwargs: execute_memory_search_tool(*args, context=context, **kwargs),
    )
    run_tool = kit.dispatcher(SESSION)
    calls = [
        ("memory_search", {"query": "zephyrquartz", "maxResults": 3}),
        ("memory_get", '{"path": "MEMORY.md", "from": 3, "lines": 1}'),
        ("memory_get", None),
        ("memory_search", '{"query": '),
        ("memory_search", "[1, 2]"),
        ("memory_search", {}),
        ("web_search", {"query": "x"}),
    ]

    for name, arguments in calls:
        assert run_tool(name, arguments) == kit.dispatch(name, arguments, session=SESSION)
    assert run_tool("memory_search", {"query": "zephyrquartz"})["results"]
    with pytest.raises(TypeError):
        run_tool(3, {})


def test_dispatcher_reaches_a_replaced_dispatch(tmp_path, monkeypatch):
    kit = _kit(tmp_path)
    run_tool = kit.dispatcher(SESSION)
    seen = []

    def spy(name, arguments, *, session):
        seen.append((name, arguments, session))
        return {"status": "ok"}

    monkeypatch.setattr(kit, "dispatch", spy)

    assert run_tool("memory_get", {"path": "MEMORY.md"}) == {"status": "ok"}
    assert seen == [("memory_get", {"path": "MEMORY.md"}, SESSION)]


def test_dispatcher_rejects_a_session_that_is_not_a_session_state(tmp_path):
    kit = _kit(tmp_path)

    for session in (None, SESSION.to_json(), "agent:main:main"):
        with pytest.raises(TypeError, match="SessionState"):
            kit.dispatcher(session)
