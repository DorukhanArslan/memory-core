"""The fresh error child rejects ambient registry state before introspection."""
import pytest

from equivalence.tool_error_profile import build_tool_error_cases
from equivalence.tool_error_profile_phase import run_phase


@pytest.mark.parametrize("extra", ["registry", "envelopes", "messages", "formatter", "config"])
def test_error_child_has_no_forwarded_result_or_registry_capability(extra, tmp_path):
    request = {"input": build_tool_error_cases()[0]["input"], "directory": str(tmp_path / "fixture"), extra: {}}
    with pytest.raises(ValueError, match="accepts only literal input"):
        run_phase(request)
    assert not list(tmp_path.iterdir())


def test_error_child_rejects_nonzero_revision_before_snapshot_or_reset(monkeypatch, tmp_path):
    from memory_core import secret_registry

    def forbidden():
        raise AssertionError("An ambient registry must never be inspected or reset")

    monkeypatch.setattr(secret_registry, "get_secret_redaction_registry_revision", lambda: 1)
    monkeypatch.setattr(secret_registry, "capture_secret_redaction_registry_snapshot", forbidden)
    monkeypatch.setattr(secret_registry, "reset_secret_redaction_registry", forbidden)
    with pytest.raises(RuntimeError, match="fresh synthetic-only registry at revision zero"):
        run_phase({"input": build_tool_error_cases()[0]["input"], "directory": str(tmp_path / "fixture")})
    assert not list(tmp_path.iterdir())


def test_error_child_rejects_nonempty_registry_before_snapshot(monkeypatch, tmp_path):
    from memory_core import secret_registry

    def forbidden():
        raise AssertionError("An ambient registry must never be introspected")

    monkeypatch.setattr(secret_registry, "get_secret_redaction_registry_revision", lambda: 0)
    monkeypatch.setattr(secret_registry, "has_registered_secret_values_for_redaction", lambda: True)
    monkeypatch.setattr(secret_registry, "capture_secret_redaction_registry_snapshot", forbidden)
    with pytest.raises(RuntimeError, match="fresh synthetic-only registry at revision zero"):
        run_phase({"input": build_tool_error_cases()[0]["input"], "directory": str(tmp_path / "fixture")})
    assert not list(tmp_path.iterdir())
