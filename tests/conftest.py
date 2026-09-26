import pytest

from memory_core.tools.memory_search import reset_memory_search_tool_cooldowns


@pytest.fixture(autouse=True)
def _isolated_memory_search_cooldowns():
    # memory_search cooldowns are process-wide (OpenClaw tools.ts keeps one Map
    # per process); a failure in one test must not pause search in the next.
    reset_memory_search_tool_cooldowns()
    yield
    reset_memory_search_tool_cooldowns()
