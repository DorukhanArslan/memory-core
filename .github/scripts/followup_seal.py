"""Pin the accepted baseline separately from the catalog of the intervening blocked run."""
import re


PREVIOUS_CASES = 1519
PREVIOUS_CATALOG_SHA = "d6a6e64b7c48efa35fe09ddd542e1e82f2329725bc5245bc138bb5b304c6024d"
SCOPE_SHA = "a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9"
PRODUCT = None
SDK_SHA = None
SDK_FILES = None
CATALOG_SHA = None
REGISTERED_CASES = None
PREVIOUS_COMPARISON = None


def check_seal():
    if not (isinstance(PRODUCT, str) and re.fullmatch("[0-9a-f]{40}", PRODUCT)
            and all(isinstance(v, str) and re.fullmatch("[0-9a-f]{64}", v) for v in (SDK_SHA, CATALOG_SHA))
            and type(SDK_FILES) is int and SDK_FILES > 0
            and type(REGISTERED_CASES) is int and REGISTERED_CASES > PREVIOUS_CASES
            and isinstance(PREVIOUS_COMPARISON, dict) and type(PREVIOUS_COMPARISON.get("runId")) is int
            and type(PREVIOUS_COMPARISON.get("verified")) is int
            and isinstance(PREVIOUS_COMPARISON.get("familyGates"), dict)
            and PREVIOUS_COMPARISON["runId"] == 44137396647
            and PREVIOUS_COMPARISON["verified"] == 84
            and PREVIOUS_COMPARISON.get("registeredCases") == 1500
            and len(PREVIOUS_COMPARISON["familyGates"]) == 14
            and all(type(v) is bool for v in PREVIOUS_COMPARISON["familyGates"].values())
            and all(isinstance(PREVIOUS_COMPARISON.get(k), str) and re.fullmatch("[0-9a-f]{64}", PREVIOUS_COMPARISON[k])
                    for k in ("reportSha256", "assessmentSha256", "warmFlushNativeSha256"))):
        raise ValueError("The approved product, catalog and preceding hosted assessment have not been frozen")
