"""Pure source-qualified job admission tests; no original engine executes."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
from textwrap import indent

import pytest

from equivalence import query_sync_outcomes_evidence as evidence


ROOT = Path(__file__).resolve().parents[2]
MODULE = Path("memory_core/host/managed_index.py")
LEGACY = '''def _submit_memory_publication(self, revision: int) -> None:
    """Admit one actual memory publisher under the pinned reader's gate."""
    needed = (self._memory_dirty or self._memory_scope_failure is not None
              or self._memory_job_error is not None or self._full_retry_required)
    if (self._memory_publication != "on-search" or not needed
            or self._memory_active or self._closing or self._closed):
        return
    if self._memory_executor is None:
        self._memory_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-publication")
    self._memory_job_count += 1
    job: dict[str, Any] = {"id": self._memory_job_count, "readRevision": revision, "state": "queued"}
    if self._last_sync_error is not None:
        job.update(wholeFailureRevision=self._whole_failure_revision,
                   fullRetry=self._full_retry_required)
    if self._full_retry_required:
        self._record_rebuild_request()
    self._memory_jobs.append(job)
    token = object()
    self._memory_worker_token = token
    self._memory_active = True
    try:
        self._memory_executor.submit(self._run_memory_publication, job, token)
    except BaseException as error:
        self._memory_worker_token = None
        self._memory_active = False
        self._memory_job_error = format_error_message(error)
        job.update(state="failed", error=self._error(error))
        self._condition.notify_all()
'''


def _modern_producer():
    tree = ast.parse((ROOT / MODULE).read_text())
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ManagedSQLiteMemoryStore")
    return ast.unparse(next(node for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == "_submit_memory_publication"))


def _source(producer, modern, *, lifecycle=None):
    if lifecycle is None:
        lifecycle = ("def lifecycle_snapshot(self):\n"
                     "    return {'memoryPublication': {'watchReadyGeneration': self._memory_watch_ready_generation}}"
                     if modern else "def lifecycle_snapshot(self):\n    return {'memoryPublication': {'jobs': []}}")
    return "class ManagedSQLiteMemoryStore:\n" + indent(producer, "    ") + "\n" + indent(lifecycle, "    ") + "\n"


@pytest.fixture
def make_job(tmp_path, monkeypatch):
    def create(modern=True):
        selected, recorded = tmp_path / "selected", tmp_path / "recorded"
        producer = _modern_producer() if modern else LEGACY
        source = _source(producer, modern)
        for root in (selected, recorded):
            (root / MODULE).parent.mkdir(parents=True, exist_ok=True)
            (root / MODULE).write_text(source)
        monkeypatch.setattr(evidence, "ROOT", selected)
        entry = {"id": 1, "readRevision": 7, "state": "queued"}
        before, own = {}, {"id": 1, "readRevision": 7, "state": "completed", "threadId": 701, "returned": 2}
        if modern:
            entry["watchGeneration"] = before["watchReadyGeneration"] = own["watchGeneration"] = 0
            own["publishedWatchGeneration"] = 1
        return {"modern": modern, "producer": producer, "source": source,
                "selected": selected, "recorded": recorded,
                "raw": {"implementationRoot": str(recorded), "implementationBindings": [{
                    "module": "memory_core.host.managed_index", "path": str(recorded / MODULE),
                    "sha256": hashlib.sha256(source.encode()).hexdigest()}]},
                "call": {"jobId": 1, "jobAtEntry": entry},
                "submit": {"readRevision": 7, "before": before}, "own": own}
    return create


def _check(value):
    return evidence._sdk_publication_job(value["raw"], value["call"], value["submit"], value["own"])


def _reseal_source(value, text):
    for root in (value["selected"], value["recorded"]):
        (root / MODULE).write_text(text)
    value["raw"]["implementationBindings"][0]["sha256"] = hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize("modern", [False, True])
def test_reviewed_actual_producer_selects_only_its_exact_schema(make_job, modern):
    value = make_job(modern)
    before = deepcopy({key: value[key] for key in ("raw", "call", "submit", "own")})
    assert value["recorded"] != value["selected"]
    assert _check(value) is None
    assert before == {key: value[key] for key in before}


def test_admission_generation_can_be_covered_by_later_original_publication(make_job):
    value = make_job()
    assert value["call"]["jobAtEntry"]["watchGeneration"] == 0
    assert value["own"]["publishedWatchGeneration"] == 1
    assert _check(value) is None
    value["call"]["jobAtEntry"]["watchGeneration"] = 5
    value["submit"]["before"]["watchReadyGeneration"] = value["own"]["watchGeneration"] = 5
    value["own"]["publishedWatchGeneration"] = 9
    assert _check(value) is None


@pytest.mark.parametrize("modern", [False, True])
def test_source_layout_changes_do_not_change_reviewed_producer_contract(make_job, modern):
    value = make_job(modern)
    _reseal_source(value, "# Independently selected source with an earlier comment.\n" + value["source"])
    assert _check(value) is None


@pytest.mark.parametrize("modern", [False, True])
def test_empty_and_absent_type_parameter_fields_have_the_same_reviewed_contract(make_job, monkeypatch, modern):
    value = make_job(modern)
    original_parse = ast.parse
    for include_empty_field in (True, False):
        def compatible_parse(*arguments, **options):
            tree = original_parse(*arguments, **options)
            producer = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                            and node.name == "_submit_memory_publication")
            if include_empty_field:
                producer.type_params = []
            elif hasattr(producer, "type_params"):
                del producer.type_params
            return tree

        monkeypatch.setattr(evidence.ast, "parse", compatible_parse)
        assert _check(value) is None


@pytest.mark.parametrize("modern", [False, True])
def test_nonempty_type_parameters_are_refused_before_schema_fingerprinting(make_job, monkeypatch, modern):
    value = make_job(modern)
    original_parse = ast.parse

    def generic_parse(*arguments, **options):
        tree = original_parse(*arguments, **options)
        producer = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                        and node.name == "_submit_memory_publication")
        producer.type_params = [ast.Name(id="T", ctx=ast.Load())]
        return tree

    monkeypatch.setattr(evidence.ast, "parse", generic_parse)
    with pytest.raises(ValueError, match="unreviewed generic parameters"):
        _check(value)


@pytest.mark.parametrize("field", ["entry", "admission", "completed"])
@pytest.mark.parametrize("replacement", [False, True, -1, 0.0, "0", None, 3])
def test_generation_requires_same_actual_nonnegative_integer(make_job, field, replacement):
    value = make_job()
    row, key = {"entry": (value["call"]["jobAtEntry"], "watchGeneration"),
                "admission": (value["submit"]["before"], "watchReadyGeneration"),
                "completed": (value["own"], "watchGeneration")}[field]
    row[key] = replacement
    with pytest.raises(ValueError):
        _check(value)


@pytest.mark.parametrize("field", ["entry", "admission", "completed"])
def test_current_source_never_falls_back_when_generation_receipt_is_missing(make_job, field):
    value = make_job()
    row, key = {"entry": (value["call"]["jobAtEntry"], "watchGeneration"),
                "admission": (value["submit"]["before"], "watchReadyGeneration"),
                "completed": (value["own"], "watchGeneration")}[field]
    del row[key]
    with pytest.raises(ValueError):
        _check(value)


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("field", ["reason", "fullRebuild", "unreviewedField"])
def test_exact_queued_schema_rejects_unknown_or_other_route_fields(make_job, modern, field):
    value = make_job(modern)
    value["call"]["jobAtEntry"][field] = "unproved"
    with pytest.raises(ValueError):
        _check(value)


@pytest.mark.parametrize("field", ["entry", "admission", "completed"])
def test_legacy_source_cannot_borrow_any_modern_watcher_state(make_job, field):
    value = make_job(False)
    row, key = {"entry": (value["call"]["jobAtEntry"], "watchGeneration"),
                "admission": (value["submit"]["before"], "watchReadyGeneration"),
                "completed": (value["own"], "watchGeneration")}[field]
    row[key] = 0
    with pytest.raises(ValueError):
        _check(value)


@pytest.mark.parametrize("field", ["id", "readRevision", "state"])
def test_existing_pinned_job_identity_and_queued_state_remain_exact(make_job, field):
    value = make_job()
    value["call"]["jobAtEntry"][field] = "changed"
    with pytest.raises(ValueError):
        _check(value)


def test_completed_job_cannot_change_its_original_admitted_revision(make_job):
    value = make_job()
    value["own"]["readRevision"] += 1
    with pytest.raises(ValueError):
        _check(value)


@pytest.mark.parametrize("attack", ["hash", "bytes", "module", "path", "root", "duplicate-binding",
    "missing-binding", "different-selected-source", "missing-source", "aliased-source"])
def test_producer_must_match_the_independently_selected_actual_source(make_job, monkeypatch, tmp_path, attack):
    value = make_job()
    binding = value["raw"]["implementationBindings"][0]
    if attack == "hash":
        binding["sha256"] = "0" * 64
    elif attack == "bytes":
        (value["selected"] / MODULE).write_text(value["source"] + "# not captured\n")
    elif attack == "module":
        binding["module"] = "memory_core.host.another_owner"
    elif attack == "path":
        binding["path"] = str(value["recorded"] / "memory_core/host/another_owner.py")
    elif attack == "root":
        value["raw"]["implementationRoot"] = str(tmp_path / "another-recorded-root")
    elif attack == "duplicate-binding":
        value["raw"]["implementationBindings"].append(deepcopy(binding))
    elif attack == "missing-binding":
        value["raw"]["implementationBindings"] = []
    elif attack == "different-selected-source":
        other = tmp_path / "other"
        (other / MODULE).parent.mkdir(parents=True)
        (other / MODULE).write_text(_source(LEGACY, False))
        monkeypatch.setattr(evidence, "ROOT", other)
    elif attack == "missing-source":
        (value["selected"] / MODULE).unlink()
    else:
        source = value["selected"] / MODULE
        target = tmp_path / "aliased-owner.py"
        source.rename(target)
        source.symlink_to(target)
    with pytest.raises(ValueError):
        _check(value)


@pytest.mark.parametrize("attack", ["conditional", "late", "duplicate-assignment", "dynamic-key", "alias",
    "missing-assignment", "different-attribute", "duplicate-class", "duplicate-producer", "missing-producer",
    "duplicate-lifecycle", "missing-lifecycle", "duplicate-lifecycle-key", "wrong-lifecycle-attribute"])
def test_changed_or_ambiguous_producer_cannot_supply_a_schema(make_job, attack):
    value = make_job()
    producer = value["producer"]
    assignment = "    job['watchGeneration'] = self._memory_watch_ready_generation"
    if attack == "conditional":
        producer = producer.replace(assignment, "    if False:\n    " + assignment)
    elif attack == "late":
        producer = producer.replace(assignment + "\n", "").replace("    self._memory_jobs.append(job)",
            "    self._memory_jobs.append(job)\n" + assignment)
    elif attack == "duplicate-assignment":
        producer = producer.replace(assignment, assignment + "\n" + assignment)
    elif attack == "dynamic-key":
        producer = producer.replace("job['watchGeneration']", "job['watch' + 'Generation']")
    elif attack == "alias":
        producer = producer.replace(assignment, "    alias = job\n    alias['watchGeneration'] = self._memory_watch_ready_generation")
    elif attack == "missing-assignment":
        producer = producer.replace(assignment + "\n", "")
    elif attack == "different-attribute":
        producer = producer.replace("self._memory_watch_ready_generation", "self._memory_watch_generation")
    text = _source(producer, True)
    if attack == "duplicate-class":
        text += text
    elif attack == "duplicate-producer":
        text += indent(value["producer"], "    ") + "\n"
    elif attack == "missing-producer":
        text = text.replace("def _submit_memory_publication", "def another_producer")
    elif attack == "duplicate-lifecycle":
        text += "    def lifecycle_snapshot(self):\n        return {}\n"
    elif attack == "missing-lifecycle":
        text = text.replace("def lifecycle_snapshot", "def another_snapshot")
    elif attack == "duplicate-lifecycle-key":
        text = text.replace("'watchReadyGeneration': self._memory_watch_ready_generation",
            "'watchReadyGeneration': self._memory_watch_ready_generation, 'watchReadyGeneration': self._memory_watch_ready_generation")
    elif attack == "wrong-lifecycle-attribute":
        text = text.replace("return {'memoryPublication': {'watchReadyGeneration': self._memory_watch_ready_generation}}",
            "return {'memoryPublication': {'watchReadyGeneration': self._memory_watch_generation}}")
    assert text != value["source"], attack
    _reseal_source(value, text)
    with pytest.raises(ValueError):
        _check(value)


def test_historical_producer_cannot_be_selected_by_a_modern_lifecycle_mapping(make_job):
    value = make_job(False)
    _reseal_source(value, _source(LEGACY, True))
    with pytest.raises(ValueError):
        _check(value)
