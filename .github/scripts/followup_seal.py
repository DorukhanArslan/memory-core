"""Pin the SDK, complete candidate catalog and previous independent measurement."""
import re

from previous_review import ASSESSMENT_SHA, REVIEW_COMMIT, load_baseline


ACCEPTED, _ = load_baseline()
PREVIOUS_CASES = ACCEPTED["registeredCases"]
PREVIOUS_CATALOG_SHA = ACCEPTED["catalogSha256"]
SCOPE_SHA = "a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9"
PRODUCT = "44b4eb2a95dfab2daacf43bd08c9c9f12dc6074c"
SDK_SHA = "a9a9c030ef3c63428e540948e2dd47a3ce2f070facab5933ecb7c73addf2cdd9"
SDK_FILES = 185
CATALOG_SHA = "468d7a01efc95c1c75cfb102e029f2b55a31c170fd41b08e42ff37f1a5ebde59"
REGISTERED_CASES = 1670
PREVIOUS_COMPARISON = {
    "decisionCommit": REVIEW_COMMIT, "runId": ACCEPTED["run"], "verified": ACCEPTED["verified"],
    "reportSha256": ACCEPTED["report"]["sha256"], "assessmentSha256": ASSESSMENT_SHA,
    "registeredCases": PREVIOUS_CASES, "familyGates": ACCEPTED["families"],
}


def check_seal():
    if not (re.fullmatch(r"[0-9a-f]{40}", PRODUCT)
            and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (SDK_SHA, CATALOG_SHA))
            and type(SDK_FILES) is int and SDK_FILES > 0
            and type(REGISTERED_CASES) is int and REGISTERED_CASES > PREVIOUS_CASES == 1667
            and ACCEPTED["verified"] == 123 and ACCEPTED["scopeSha256"] == SCOPE_SHA):
        raise ValueError("An approved SDK and complete candidate catalog are required for the measurement")
