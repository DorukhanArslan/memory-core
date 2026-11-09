"""Literal independently reviewed #38 cases; expected outcomes remain source-owned."""
from copy import deepcopy


MEMORY_BUDGET_ACCEPTANCE = (
    "compaction.memory-budget.outcomes",
    "compaction.memory-budget.boundaries",
)

# Every family is required together for either original condition. These are
# registration guards, not expected outputs or authority for historical reports.
MEMORY_BUDGET_REQUIRED_CASE_IDS = (
    "memory-budget-mixed-sections-and-limits",
    "memory-budget-sdk-marker-extension-diagnostic",
    "memory-budget-fit",
    "memory-budget-compact",
    "memory-budget-defer",
    "memory-budget-reconcile",
    "memory-budget-marker-preservation-boundaries",
    "memory-budget-foreign-marker-reconcile",
    "memory-budget-non-js-space-prefix-reconcile",
    "memory-budget-non-js-space-key-reconcile",
    "memory-budget-js-bom-space-prefix-reconcile",
    "memory-budget-js-bom-space-key-reconcile",
    "memory-budget-literal-line-endings-fit",
)

NOW_MS = 1779811200000
DAY = "2026-05-26T16:00:00.000Z"
PATH = "memory/2026-05-08.md"
KEY = f"memory:{PATH}:3:3"
SNIPPET = "- A durable bright kumquat tea preference."


def _section(day, key, body):
    return f"## Promoted From Short-Term Memory ({day})\n<!-- openclaw-memory-promotion:{key} -->\n- {body}\n"


def _units(text):
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _candidate():
    return {"key": KEY, "path": PATH, "startLine": 3, "endLine": 3, "source": "memory", "snippet": SNIPPET,
        "recallCount": 4, "dailyCount": 0, "groundedCount": 0, "signalCount": 4, "avgScore": 0.9,
        "maxScore": 1, "uniqueQueries": 3, "firstRecalledAt": "2026-05-20T16:00:00.000Z",
        "lastRecalledAt": "2026-05-25T16:00:00.000Z", "ageDays": 1, "score": 0.875,
        "recallDays": ["2026-05-21", "2026-05-22", "2026-05-23"], "conceptTags": [],
        "components": {"frequency": 0.5, "relevance": 0.9, "diversity": 0.6, "recency": 0.9,
            "consolidation": 0.5, "conceptual": 0},
        "provenance": {"originClass": "agent", "sessionKind": "unknown", "observedAt": 1}}


def _recall():
    candidate = _candidate()
    return {"version": 1, "updatedAt": DAY, "entries": {KEY: {
        **{key: candidate[key] for key in ("key", "path", "startLine", "endLine", "source", "snippet",
            "recallCount", "dailyCount", "groundedCount", "maxScore", "firstRecalledAt", "lastRecalledAt",
            "recallDays", "conceptTags", "provenance")},
        "totalScore": 3.6, "queryHashes": ["a1", "a2", "a3"], "userQueryHashes": ["a1", "a2", "a3"]}}}


def build_memory_budget_cases():
    generated = _section("2026-05-01", "old-a", "An older generated fact.")
    newer = _section("2026-05-20", "old-b", "A more recent generated fact.")
    mixed = "# Personal notes\nNever remove the user's exact text.\n\n" + generated + "\n" + newer
    new = "\n" + _section("2026-05-26", "next", "New context.")
    pure = []

    def add(label, existing, addition, budget, loss=None):
        pure.append({"id": label, "params": {"existingMemory": existing, "newSection": addition,
            "budgetChars": budget, **({"maxPriorEntryLossFraction": loss} if loss is not None else {})}})

    add("empty", "", "", 100)
    add("disabled-zero", mixed, new, 0)
    add("disabled-negative", mixed, new, -1)
    add("fits-exact-reserve", mixed, new, _units(mixed + new) + 21)
    add("one-unit-over-reserve", mixed, new, _units(mixed + new) + 20)
    add("no-generated-preserve", "# Notes\nOnly user content.\n", new, 1)
    for loss in (0, 0.24999999999999997, 0.25, 0.5, 0.9999999999999999, 1, -1, 2):
        add(f"entry-loss-{loss}", mixed, new, _units(mixed), loss)
    add("reverse-input-dates", newer + "\n" + generated, new, _units(newer + new) + 21)
    add("equal-date-stable-order", generated + "\n" + generated.replace("old-a", "old-c"), new, _units(generated + new) + 21)
    add("mixed-user-line-preserved", generated + "A user's unowned continuation.\n", new, 1)
    add("marker-without-bullet-preserved", generated.replace("- An", "An"), new, 1)
    add("project-subsection", generated.replace("\n<!--", "\n### Project: example.test/repo\n\n<!--"), new, 1)
    add("setext-user-heading", generated + "\nUser Heading\n---\nKeep this body.\n", new, 1)
    add("atx-user-heading", generated + "\n   #### User heading\nKeep this body.\n", new, 1)
    add("crlf-source-bytes", mixed.replace("\n", "\r\n"), new, _units(mixed))
    add("unicode-units", generated.replace("An older generated fact.", "\U0001f600\u6f22\u5b57" * 12), new, 170)
    add("lone-surrogate-units", generated.replace("An older generated fact.", "\ud800A\udc00"), new, 140)
    foreign = generated.replace("openclaw-memory-promotion:", "memory-core-memory-promotion:")
    old_blocks = "\n".join(_section(f"2026-05-{day:02}", f"old-{day}", "Longer generated evidence. " * 4)
        for day in (1, 2, 3, 4))
    profiles = [
        ("fit", "# Personal notes\nA prior fact remains.\n", 10_000, 0.25),
        ("compact", "# Personal notes\nKeep this exact user fact.\n\n" + old_blocks, 1000, 0.5),
        ("defer", "# Personal notes\n" + "Preserved user bytes. " * 80, 300, 0.25),
        ("reconcile", "# Personal notes\nKeep the prior fact.\n\n" + _section("2026-05-20", KEY, "Already recorded."), 10_000, 0.25),
    ]
    values = [("mixed-sections-and-limits", "memory-budget-runtime", {"kind": "memory-budget", "nowMs": NOW_MS, "cases": pure}),
        ("sdk-marker-extension-diagnostic", "memory-budget-runtime", {"kind": "memory-budget", "nowMs": NOW_MS,
            "cases": [{"id": "foreign-marker-under-user-heading", "params": {
                "existingMemory": foreign, "newSection": new, "budgetChars": 1}}]})]
    for name, memory, budget, loss in profiles:
        values.append((name, "memory-budget-apply-runtime", {"kind": "memory-budget-apply", "nowMs": NOW_MS,
            "files": {"MEMORY.md": memory, PATH: "# Source facts\n\n" + SNIPPET + "\n"},
            "recall": _recall(), "candidates": [_candidate()], "options": {
                "timezone": "UTC", "memoryFileMaxChars": budget, "maxPriorEntryLossFraction": loss,
                "minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0, "limit": 5}}))
    marked = _section("2026-05-01", "k", "An owner-authored block.")
    preservation = [
        {"id": "ascii-marker", "params": {"existingMemory": marked, "newSection": "", "budgetChars": 1}},
        {"id": "uppercase-marker", "params": {"existingMemory": marked.replace("openclaw-memory-promotion:", "OPENCLAW-MEMORY-PROMOTION:"),
            "newSection": "", "budgetChars": 1}},
    ]
    for label, letter in (("dotted-i", "\u0130"), ("dotless-i", "\u0131")):
        preservation.append({"id": label, "params": {"existingMemory": marked.replace("promotion:", f"promot{letter}on:"),
            "newSection": "", "budgetChars": 1}})
    for label, separator in (("bare-cr", "\r"), ("line-separator", "\u2028"), ("paragraph-separator", "\u2029")):
        preservation.append({"id": "key-" + label, "params": {
            "existingMemory": marked.replace("promotion:k", "promotion:k" + separator + "user"), "newSection": "", "budgetChars": 1}})
        preservation.append({"id": "project-" + label, "params": {
            "existingMemory": marked.replace("\n<!--", "\n### Project: owner" + separator + "user\n<!--"), "newSection": "", "budgetChars": 1}})
    values.append(("marker-preservation-boundaries", "memory-budget-runtime", {
        "kind": "memory-budget", "nowMs": NOW_MS, "cases": preservation}))
    foreign_reconcile = deepcopy(values[5][2])
    foreign_reconcile["files"]["MEMORY.md"] = foreign_reconcile["files"]["MEMORY.md"].replace(
        "openclaw-memory-promotion:", "memory-core-memory-promotion:")
    values.append(("foreign-marker-reconcile", "memory-budget-apply-runtime", foreign_reconcile))
    for label, token in (("non-js-space", "\u0085"), ("js-bom-space", "\ufeff")):
        for location in ("prefix", "key"):
            spaced = deepcopy(values[5][2])
            text = spaced["files"]["MEMORY.md"]
            spaced["files"]["MEMORY.md"] = (text.replace("<!-- openclaw", "<!--" + token + "openclaw") if location == "prefix"
                else text.replace("promotion:" + KEY, "promotion:" + token + KEY))
            values.append((f"{label}-{location}-reconcile", "memory-budget-apply-runtime", spaced))
    line_endings = deepcopy(values[2][2])
    line_endings["files"]["MEMORY.md"] = "# Personal notes\r\nKeep this exact user text.\rA separate literal CR and \U0001f600.\r\n"
    values.append(("literal-line-endings-fit", "memory-budget-apply-runtime", line_endings))
    return [{"id": "memory-budget-" + name, "requirement": "compaction.memory-budget", "covers": list(MEMORY_BUDGET_ACCEPTANCE),
        "operation": operation, "input": deepcopy(value),
        "driverScope": "Ordinary JSON with explicit ISO dates: original compact helper and genuine OpenClaw-compatible apply owner "
            "over literal persisted source/recall inputs. All thirteen case families jointly support either original condition. "
            "Complete original return, document bytes, recall state and promotion events; both own raw APIs/SQL/FS retained. "
            "No provider, configuration-resolver, ranking, general promotion or lock-equivalence claim.",
        "normalizationPolicy": "Only exact owned fixture-root prefixes map to $FIXTURE. "
            "SDK dataclass fields map mechanically to the complete original apply schema; tuples become JSON arrays. "
            "Every additional own SDK/native return field stays raw. No result sorting, score tolerance, identity/hash repair or marker replacement."}
        for name, operation, value in values]
