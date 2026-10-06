from memory_core.usage_normalization import has_nonzero_normalized_usage, normalize_usage


def test_cache_buckets_are_subtracted_from_provider_input_totals():
    assert normalize_usage({"input_tokens": 100, "cached_tokens": 40}) == {
        "input": 60,
        "cacheRead": 40,
    }
    assert normalize_usage(
        {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 60}}
    ) == {"input": 40, "cacheRead": 60}
    assert normalize_usage({"input": 100, "cached_input_tokens": 40}) == {
        "input": 100,
        "cacheRead": 40,
    }


def test_nested_details_count_as_usage():
    assert has_nonzero_normalized_usage({"prompt_tokens_details": {"cached_tokens": 5}})
    assert has_nonzero_normalized_usage({"output_tokens_details": {"thinking_tokens": 1}})
    assert not has_nonzero_normalized_usage({"prompt_tokens_details": {"cached_tokens": 0}})
    assert has_nonzero_normalized_usage({"contextUsage": {"state": "unavailable"}})
    assert not has_nonzero_normalized_usage({"input": "5", "output": True})
    assert not has_nonzero_normalized_usage(None)
