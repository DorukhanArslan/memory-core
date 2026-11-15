"""Publication-predicate regressions using decoded doubles, not original captures.

These checks award no acceptance credit and run no Native memory engine.
The full validator still independently authenticates targets, source owners,
deliveries, later snapshot probes and original watcher settlements.
"""
from copy import deepcopy

import pytest

from equivalence.forget_index_fence_native_watch_evidence import _watch_fact_after_publication


@pytest.fixture
def publication():
    path = "/builtin/workspace/MEMORY.md"
    stats = {"dev": 7, "ino": 9, "size": 113, "mode": 0o100644, "nlink": 1,
             "mtimeMs": 1000, "ctimeMs": 2000, "gid": 1}
    target = {"kind": "file", "path": path, "committedAtNs": "400",
              "causalFrame": {"enteredAtNs": "100"},
              "stat": {key: str(stats[key]) for key in ("dev", "ino", "size", "mode", "nlink")}}
    target["stat"]["mtimeNs"] = "1000000000"
    # Labels stand for independently decoded carriers in this predicate-only double.
    decoded = {"fact": [path, deepcopy(stats)], "delivery": [path, deepcopy(stats)],
               "path": path, "stats": deepcopy(stats)}
    fact = {"path": path, "enteredAtNs": "200", "returnedAtNs": "300",
            "arguments": {"v8Hex": "fact"},
            "argumentValues": [{"v8Hex": "path"}, {"v8Hex": "stats"}],
            "delivery": {"kind": "chokidar", "eventName": "change",
                         "arguments": {"v8Hex": "delivery"}}}

    def decode(carrier):
        return deepcopy(decoded[carrier["v8Hex"]])

    return fact, target, decoded, decode


@pytest.mark.parametrize("event", ["add", "change"])
def test_final_version_can_arrive_before_writer_rename_continuation(publication, event):
    fact, target, _, decode = publication
    fact["delivery"]["eventName"] = event
    assert _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("kind", ["file", "deleted"])
@pytest.mark.parametrize("returned", ["400", "401"])
def test_existing_post_completion_path_needs_no_early_argument_decoding(kind, returned):
    def no_decode(_):
        pytest.fail("The existing post-completion path must not decode early-delivery arguments")

    assert _watch_fact_after_publication({"returnedAtNs": returned},
                                        {"kind": kind, "committedAtNs": "400"}, no_decode)


@pytest.mark.parametrize("kind,event", [("native", "change"), ("chokidar", "unlink"),
                                       ("chokidar", "ready")])
def test_early_alternative_does_not_admit_other_delivery_boundaries(publication, kind, event):
    fact, target, _, decode = publication
    fact["delivery"].update(kind=kind, eventName=event)
    assert not _watch_fact_after_publication(fact, target, decode)


def test_deletion_does_not_gain_an_early_delivery_alternative(publication):
    fact, target, _, decode = publication
    target["kind"] = "deleted"
    assert not _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("entered", [None, "", "not-a-clock", "201", "500"])
def test_notification_must_follow_its_original_command_entry(publication, entered):
    fact, target, _, decode = publication
    target["causalFrame"]["enteredAtNs"] = entered
    assert not _watch_fact_after_publication(fact, target, decode)


def test_early_delivery_requires_its_authenticated_causal_frame(publication):
    fact, target, _, decode = publication
    del target["causalFrame"]
    assert not _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("entered,returned", [("50", "60"), ("300", "300"), ("301", "300")])
def test_stale_or_invalid_original_fact_interval_is_rejected(publication, entered, returned):
    fact, target, _, decode = publication
    fact.update(enteredAtNs=entered, returnedAtNs=returned)
    assert not _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("field", ["dev", "ino", "size", "mode", "nlink", "mtimeMs"])
def test_old_delivered_identity_cannot_borrow_the_later_correct_target(publication, field):
    fact, target, decoded, decode = publication
    # All three carriers consistently describe an older delivered version.
    for stats in (decoded["fact"][1], decoded["delivery"][1], decoded["stats"]):
        stats[field] += 1
    assert not _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("carrier", ["fact", "delivery", "stats"])
def test_each_original_argument_carrier_must_agree(publication, carrier):
    fact, target, decoded, decode = publication
    stats = decoded[carrier] if carrier == "stats" else decoded[carrier][1]
    stats["ctimeMs"] += 1
    assert not _watch_fact_after_publication(fact, target, decode)


def test_full_argument_equality_does_not_confuse_booleans_with_numbers(publication):
    fact, target, decoded, decode = publication
    decoded["delivery"][1]["gid"] = True
    assert not _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("carrier", ["fact", "delivery", "path"])
def test_every_original_path_argument_identifies_the_target(publication, carrier):
    fact, target, decoded, decode = publication
    if carrier == "path":
        decoded[carrier] = "/builtin/workspace/another.md"
    else:
        decoded[carrier][0] = "/builtin/workspace/another.md"
    assert not _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("carrier", ["fact", "delivery"])
@pytest.mark.parametrize("length", [0, 1, 3])
def test_original_call_and_delivery_require_exact_two_argument_arity(publication, carrier, length):
    fact, target, decoded, decode = publication
    decoded[carrier] = (decoded[carrier] + ["extra"])[:length]
    assert not _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("length", [0, 1, 3])
def test_individual_carriers_require_exact_two_argument_arity(publication, length):
    fact, target, _, decode = publication
    fact["argumentValues"] = (fact["argumentValues"] + [{"v8Hex": "path"}])[:length]
    assert not _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("field", ["dev", "ino", "size", "mode", "nlink", "mtimeMs"])
@pytest.mark.parametrize("bad", [True, "1", 1.5, float("nan"), float("inf")])
def test_delivered_identity_requires_safe_integral_native_numbers(publication, field, bad):
    fact, target, decoded, decode = publication
    for stats in (decoded["fact"][1], decoded["delivery"][1], decoded["stats"]):
        stats[field] = bad
    assert not _watch_fact_after_publication(fact, target, decode)


def test_unsafe_native_inode_cannot_match_a_large_target_by_number_rounding(publication):
    fact, target, decoded, decode = publication
    target["stat"]["ino"] = str(2**53)
    for stats in (decoded["fact"][1], decoded["delivery"][1], decoded["stats"]):
        stats["ino"] = 2**53
    assert not _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("field,value", [("dev", "07"), ("ino", "09"), ("size", "0113"),
                                        ("mode", "033188"), ("nlink", "01")])
def test_target_integer_strings_match_native_canonical_spelling(publication, field, value):
    fact, target, _, decode = publication
    target["stat"][field] = value
    assert not _watch_fact_after_publication(fact, target, decode)


def test_negative_zero_target_string_does_not_equal_canonical_native_zero(publication):
    fact, target, decoded, decode = publication
    target["stat"]["size"] = "-0"
    for stats in (decoded["fact"][1], decoded["delivery"][1], decoded["stats"]):
        stats["size"] = 0
    assert not _watch_fact_after_publication(fact, target, decode)


def test_submillisecond_target_is_not_rounded_into_a_delivered_stat(publication):
    fact, target, _, decode = publication
    target["stat"]["mtimeNs"] = "1000000001"
    assert not _watch_fact_after_publication(fact, target, decode)


@pytest.mark.parametrize("carrier", ["fact", "delivery", "path", "stats"])
def test_missing_opaque_or_malformed_carrier_cannot_admit_an_early_fact(publication, carrier):
    fact, target, _, decode = publication
    if carrier == "fact":
        fact["arguments"] = {"serializationError": {"name": "Error"}}
    elif carrier == "delivery":
        fact["delivery"]["arguments"] = None
    elif carrier == "path":
        fact["argumentValues"][0] = {"v8Hex": None}
    else:
        fact["argumentValues"][1] = {"v8Hex": "unknown"}
    assert not _watch_fact_after_publication(fact, target, decode)


def test_failed_native_argument_decoding_is_not_positive_custody(publication):
    fact, target, _, _ = publication

    def unavailable(_):
        raise ValueError("The retained argument is not a valid original V8 carrier")

    assert not _watch_fact_after_publication(fact, target, unavailable)
