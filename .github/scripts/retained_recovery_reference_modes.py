"""Read the nine original release modes omitted from the 1,623-case compact artifact."""
from pathlib import Path

from equivalence.recovery_failure import OTHER_PUBLISHERS, build_cases
from equivalence.strict_report_reader import Reader


def read_recovery_reference_modes(report_path: Path, compact_cases: list[dict]) -> dict[str, str]:
    """Caller verifies the original full report SHA independently. Stop after its complete case array."""
    if len(compact_cases) != 1623 or len({r['id'] for r in compact_cases}) != 1623:
        raise ValueError("Incomplete or duplicate original case count")
    wanted = set().union(*OTHER_PUBLISHERS.values(), {r['id'] for r in build_cases()})
    found, modes = [], {}

    class CompleteCaseArray(Exception):
        pass

    def capture(key, value, status):
        if key != 'cases':
            return
        if status == 'array-done':
            raise CompleteCaseArray
        if status is not True or len(found) >= len(compact_cases):
            raise ValueError("Invalid original case array")
        expected = compact_cases[len(found)]
        case = value['id']
        if case != expected['id'] or value['status'] != expected['status']:
            raise ValueError("Original case IDs, order or status differ from the authentic compact projection")
        found.append(case)
        if case in wanted and value['operation'] != 'index-publication':
            if value.get('referenceMode') != 'authenticated-official-release' or case in modes:
                raise ValueError("A required original publisher has an unapproved or missing reference mode")
            modes[case] = value['referenceMode']

    try:
        Reader(Path(report_path)).top(capture)
    except CompleteCaseArray:
        if found == [r['id'] for r in compact_cases] and len(modes) == 9:
            return modes
    raise ValueError("Original report omitted part of the expected complete case array or release modes")
