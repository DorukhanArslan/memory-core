"""Pin the accepted baseline separately from the catalog of the intervening blocked run."""
import re


from heartbeat_119_guard import baseline

ACCEPTED = baseline()
PREVIOUS_CASES = ACCEPTED["registeredCases"]
PREVIOUS_CATALOG_SHA = ACCEPTED["catalogSha256"]
SCOPE_SHA = "a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9"
PRODUCT = 'f040ac1852a878672ff6f6ede85ebee393a8ffd6'
SDK_SHA = 'a00070f6ffd781c8372b06f7bc9b0546a5dacb59058144519e1ba7d9a174bba3'
SDK_FILES = 183
CATALOG_SHA = '1480bb7dbbbda146e7044bc265cfcc510cedcff8f8a316762e558bce2f21021e'
REGISTERED_CASES = 1662
PREVIOUS_COMPARISON = {
    "runId": ACCEPTED["runId"],
    "verified": ACCEPTED["verified"],
    "reportSha256": ACCEPTED["reportSha256"],
    "assessmentSha256": ACCEPTED["allSummaryFileHashes"]["assessment.json"],
    "registeredCases": PREVIOUS_CASES,
    "familyGates": ACCEPTED["measuredFamilyGates"],
}
EXPECTED_RESOLUTIONS = ()


def check_seal():
    if not (re.fullmatch(r"[0-9a-f]{40}", PRODUCT) and PRODUCT != ACCEPTED["productSourceCommit"]
            and all(re.fullmatch(r"[0-9a-f]{64}", s) for s in (SDK_SHA, CATALOG_SHA))
            and SDK_SHA != ACCEPTED["productSdk"]["sourceSha256"]
            and type(SDK_FILES) is int and SDK_FILES > 0
            and REGISTERED_CASES == 1662 and PREVIOUS_CASES == 1623
            and len(PREVIOUS_COMPARISON["familyGates"]) == 37):
        raise ValueError("Awaiting the frozen new SDK and complete 1662-case catalog")
