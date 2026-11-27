"""Pin the SDK, complete candidate catalog and previous independent measurement."""
import re

from previous_review import ASSESSMENT_SHA, REVIEW_COMMIT, load_baseline


ACCEPTED, _ = load_baseline()
PREVIOUS_CASES = ACCEPTED["registeredCases"]
PREVIOUS_CATALOG_SHA = ACCEPTED["catalogSha256"]
SCOPE_SHA = "a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9"
PRODUCT = "116245150afc82ff8b79106f1b2ffb6cab45fbb1"
SDK_SHA = "485d61abe1314ae2c57ef5fdf11c105eb400fd6a8961790710df40b586f370de"
SDK_FILES = 185
CATALOG_SHA = "3f8ceb713d0da159aa2a3b6d52b46b057f6131a3213721c2b515af7c7e44162b"
REGISTERED_CASES = 1667
PREVIOUS_COMPARISON = {
    "decisionCommit": REVIEW_COMMIT, "runId": ACCEPTED["run"], "verified": ACCEPTED["verified"],
    "reportSha256": ACCEPTED["report"]["sha256"], "assessmentSha256": ASSESSMENT_SHA,
    "registeredCases": PREVIOUS_CASES, "familyGates": ACCEPTED["families"],
}


def check_seal():
    if not (re.fullmatch(r"[0-9a-f]{40}", PRODUCT)
            and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (SDK_SHA, CATALOG_SHA))
            and type(SDK_FILES) is int and SDK_FILES > 0
            and type(REGISTERED_CASES) is int and REGISTERED_CASES > PREVIOUS_CASES == 1663
            and ACCEPTED["verified"] == 122 and ACCEPTED["scopeSha256"] == SCOPE_SHA):
        raise ValueError("An approved SDK and complete candidate catalog are required for the measurement")
