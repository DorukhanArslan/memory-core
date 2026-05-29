from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs" / "parity_matrix.md"
ORACLE_TEST_PATH = ROOT / "tests" / "integration" / "test_openclaw_ts_oracle.py"


def _matrix_rows() -> list[dict[str, str]]:
    rows = []
    for line in MATRIX_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| Area ") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 8:
            continue
        rows.append(
            {
                "area": cells[0],
                "oracle": cells[3],
                "status": cells[4],
                "known_gaps": cells[5],
            }
        )
    return rows


def _oracle_operations(value: str) -> list[str]:
    if value in {"Not added", "Not planned"}:
        return []
    return [
        operation.strip().strip("`")
        for operation in value.split(",")
        if operation.strip() and operation.strip().strip("`") not in {"after added"}
    ]


def test_match_rows_have_executable_oracle_test_evidence():
    oracle_test_source = ORACLE_TEST_PATH.read_text(encoding="utf-8")
    match_rows = [row for row in _matrix_rows() if row["status"] == "`match`"]

    assert match_rows, "expected at least one parity match row"
    for row in match_rows:
        operations = _oracle_operations(row["oracle"])
        assert operations, f"{row['area']} is match but has no oracle operation"
        missing = [operation for operation in operations if f'"operation": "{operation}"' not in oracle_test_source]
        assert not missing, f"{row['area']} lacks integration oracle tests for {missing}"


def test_runtime_context_rows_are_not_marked_match_without_runtime_oracle():
    runtime_rows = [
        row
        for row in _matrix_rows()
        if "runtime" in row["area"].lower() or "transcript" in row["area"].lower()
    ]

    assert runtime_rows, "expected runtime/transcript rows in parity matrix"
    for row in runtime_rows:
        assert row["status"] != "`match`"
        assert "approximation" in row["known_gaps"] or row["oracle"] == "Not added"
