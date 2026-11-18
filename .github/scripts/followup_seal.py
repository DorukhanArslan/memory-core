"""Pin the accepted baseline separately from the catalog of the intervening blocked run."""
import re


PREVIOUS_CASES = 1519
PREVIOUS_CATALOG_SHA = "d6a6e64b7c48efa35fe09ddd542e1e82f2329725bc5245bc138bb5b304c6024d"
SCOPE_SHA = "a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9"
PRODUCT = '7db3a86ac9b73ed8cd728d84afb343af32847332'
SDK_SHA = '8c10212f12d6061d7d8c1fd3899f2e8be5ffafa1785ee3e7e64a861fc14eaad1'
SDK_FILES = 177
CATALOG_SHA = 'd0a2b6324abc29306c635f600a46f2105b8c02585f39d9aa88e87100fddab030'
REGISTERED_CASES = 1592
PREVIOUS_COMPARISON = {'assessmentSha256': '20af968622ab7a29339d6a11bd9cf4c363099f1bba87d3907328b64b1f9cd701',
 'familyGates': {'embed-cache-lifecycle-runtime': True,
                 'forget-boundaries-runtime': True,
                 'forget-index-fence-v6-runtime': True,
                 'forget-lineage-runtime': True,
                 'host-restart-session-runtime': True,
                 'host-turn-barrier-boundaries-runtime': True,
                 'host-turn-barrier-v4-runtime': True,
                 'host-update-isolation-runtime': True,
                 'index-identity-boundaries-runtime': True,
                 'prompt-runtime-context-runtime': True,
                 'query-sync-boundaries-runtime': True,
                 'query-sync-outcomes-runtime': True,
                 'recall-signals-runtime': True,
                 'session-reset-boundaries-runtime': True},
 'registeredCases': 1500,
 'reportSha256': '080d8a69437fcc44db824583b5a7fb3b834be1c575220a7a000a5a28455a2dd4',
 'runId': 44137396647,
 'verified': 84,
 'warmFlushNativeSha256': '4cdb2aa71ea06ed46a094e47e3739276fae9238c4480d82a6eee896d6451b569'}


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
