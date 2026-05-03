from memory_core.index.chunking import chunk_markdown


def test_chunk_markdown_preserves_line_ranges():
    text = "# Title\none two three\nfour five six\n"
    chunks = chunk_markdown("MEMORY.md", text, target_tokens=3, overlap_tokens=1)
    assert chunks[0].path == "MEMORY.md"
    assert chunks[0].start_line == 1
    assert chunks[0].end_line >= 1
    assert chunks[0].text
