from memory_core.tools.citations import clamp_text, source_label


def test_source_label_uses_path_and_start_line():
    assert source_label("memory/2026-05-03.md", 7) == "Source: memory/2026-05-03.md#7"


def test_clamp_text_reports_truncation():
    result = clamp_text("abcdef", max_chars=4)
    assert result.text == "abcd"
    assert result.truncated is True
    assert result.original_chars == 6
