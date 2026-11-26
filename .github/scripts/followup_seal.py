"""Pin the SDK, complete candidate catalog and previous independent measurement."""
import re

from previous_review import ASSESSMENT_SHA, REVIEW_COMMIT, load_baseline


ACCEPTED, _ = load_baseline()
PREVIOUS_CASES = ACCEPTED["registeredCases"]
PREVIOUS_CATALOG_SHA = ACCEPTED["catalogSha256"]
SCOPE_SHA = "a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9"
PRODUCT = "bb40b5c532ae4dabf5504806922fba4fa414adf4"
SDK_SHA = "da7eea7d8aa960f5e86018fe2bafe47ddce8a22ec7c6df60945d8216dec8356d"
SDK_FILES = 184
CATALOG_SHA = "f95caff97657df1f3365228fa7353589ce9b025bc78aadf5e7790200e4247a59"
REGISTERED_CASES = 1663
PREVIOUS_COMPARISON = {
    "decisionCommit": REVIEW_COMMIT, "runId": ACCEPTED["run"], "verified": ACCEPTED["verified"],
    "reportSha256": ACCEPTED["report"]["sha256"], "assessmentSha256": ASSESSMENT_SHA,
    "registeredCases": PREVIOUS_CASES, "familyGates": ACCEPTED["families"],
}


def check_seal():
    if not (re.fullmatch(r"[0-9a-f]{40}", PRODUCT)
            and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (SDK_SHA, CATALOG_SHA))
            and type(SDK_FILES) is int and SDK_FILES > 0
            and type(REGISTERED_CASES) is int and REGISTERED_CASES >= PREVIOUS_CASES == 1662
            and ACCEPTED["verified"] == 119 and ACCEPTED["scopeSha256"] == SCOPE_SHA):
        raise ValueError("An approved SDK and complete candidate catalog are required for the measurement")
