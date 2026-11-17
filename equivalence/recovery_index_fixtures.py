"""Independent, pre-observation drives for the index part of repair diagnostics."""
from copy import deepcopy


OPERATION = "recovery-index-repair-runtime"
POINTS = ("recovery.repair-diagnostics.outcomes", "recovery.repair-diagnostics.boundaries")
STAGES = ("published", "damaged", "repaired", "repeated")
SEARCHES = ("observatory", "staledomequartz", "riverbank")
FILES = {
    "MEMORY.md": "# Observatory\n\nThe observatory keeps its brass telescope in the eastern dome.\n",
    "memory/2026-01-01.md": "# Field journal\n\nA blue heron nests near the riverbank.\n",
}
DAMAGE = {
    "derived-text": {"sql": "UPDATE memory_index_chunks_fts SET text = ? WHERE path = ?",
                     "args": ["staledomequartz", "MEMORY.md"]},
    "provenance-row": {
        "sql": "UPDATE memory_index_chunk_provenance SET supersedes_key = ? WHERE chunk_id IN "
               "(SELECT id FROM memory_index_chunks WHERE path = ?)",
        "args": ["missing-origin-record", "MEMORY.md"]},
}


def recovery_index_cases():
    return [{
        "id": "recovery-index-repair-" + name, "requirement": "recovery.repair-diagnostics",
        "covers": list(POINTS), "operation": OPERATION,
        "input": {"kind": name, "files": deepcopy(FILES), "target": "MEMORY.md", "mtimeMs": 1700000000000,
                  "nowMs": 1800000000000, "stages": list(STAGES), "damage": deepcopy(damage),
                  "searches": list(SEARCHES)},
        "driverScope": "Publish two real notes with the provider-none manager and SDK. Damage one persisted "
                       "derived field, then force a full repair twice over the unchanged source files.",
        "normalizationPolicy": "Compare the complete published index, ordered real full-text matches, SQLite "
                               "integrity output and literal document contents after every stage. Physical images, "
                               "manager status, SDK reindex returns and SQL mutation receipts remain in evidence."
    } for name, damage in DAMAGE.items()]
