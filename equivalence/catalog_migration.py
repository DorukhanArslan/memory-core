"""Exact default definition migration; this module executes no memory owner."""
from copy import deepcopy
import hashlib
import json

ORIGINAL_PREFIX_SHA256 = "0fa31b6393c65303f4fa2e1663671e4ef60eb15edc563f05aba218c8c408349c"
ORIGINAL_PREFIX_CASES = 1452
HISTORICAL_REGISTERED_CASES = 1465
OUTCOME_REGISTERED_CASES = 1468
OUTCOME_CATALOG_SHA256 = "e10587f60a72f203f1c9cdfe8954bb4f9b03367ef82009f5fab6f65a62631631"
BOUNDARY_REGISTERED_CASES = 1469
BOUNDARY_CATALOG_SHA256 = "74322960d928ecb2b1ed330f18f891d3e6efb04482eacd6bddf7823e4ea309a8"
RECALL_REGISTERED_CASES = 1475
RECALL_CATALOG_SHA256 = "8c6f2adb034b7360f0ef9beeb45383d77b7df9bfe9057d2f8df98eb1ac397335"
CACHE_REGISTERED_CASES = 1483
CACHE_CATALOG_SHA256 = "33277abb724a6b89423085e735fc08b950b647b577db9879df8f2395e519a93d"
RESET_REGISTERED_CASES = 1490
RESET_CATALOG_SHA256 = "a6b6d9d2fee122e0759d421d0d170ab171fecc58e86bbb3f322dc0154742d7b8"
PROMPT_REGISTERED_CASES = 1500
PROMPT_CATALOG_SHA256 = "96bf1edb8fe29618d1b62792d1ffbf58423cd16f804eb490ba3f0a7c6c187ebb"
HISTORY_REGISTERED_CASES = 1508
HISTORY_CATALOG_SHA256 = "f40567a91042cb6e46bca64d94e83a3619fe5d2353192730c6e6838998822493"
NUMERIC_REGISTERED_CASES = 1512
NUMERIC_CATALOG_SHA256 = "e9673faf7122adb19f59b1284d779a63a6bda20620e7c210854cce1da9cc257e"
DEEP_REGISTERED_CASES = 1519
DEEP_CATALOG_SHA256 = "d6a6e64b7c48efa35fe09ddd542e1e82f2329725bc5245bc138bb5b304c6024d"
PRE_RECOVERY_CASES = 1566
PRE_RECOVERY_CATALOG_SHA256 = "031f5033d3aac48b77a39748311fe550d954451ec249fa4973caf7675bd14c4d"
PRE_FLUSH_PLAN_CASES = 1575
PRE_FLUSH_PLAN_CATALOG_SHA256 = "26e794a6eb6389f48202e6c8f85e668932a3aa3d38234cd00fd2835fdf25e582"
PRE_HEARTBEAT_OUTCOME_CASES = 1588
PRE_HEARTBEAT_OUTCOME_CATALOG_SHA256 = "f5f01be60adf70d120b77c371dd6ef61dbc27e8b09fc27d307374e730f073974"
PRE_INTERRUPTION_CASES = 1592
PRE_INTERRUPTION_CATALOG_SHA256 = "d0a2b6324abc29306c635f600a46f2105b8c02585f39d9aa88e87100fddab030"
PRE_ACTIVE_HISTORY_CASES = 1594
PRE_ACTIVE_HISTORY_CATALOG_SHA256 = "86783a5b594ff4b07e14df34015ed96b2b9648500e132460841b96c7fc115880"
PRE_DATETIME_CASES = 1597
PRE_DATETIME_CATALOG_SHA256 = "fd5f81e5f1223d6b257d4281c23aec9c816d85908133eab5e4255f7035267293"
PRE_UNICODE_CASES = 1602
PRE_UNICODE_CATALOG_SHA256 = "142f88ded5d0dd185b85e2ba6c719999a73978318b32ec4ae5f8cacd67c36912"
PRE_SECRET_CASES = 1605
PRE_SECRET_CATALOG_SHA256 = "0ffd953f5504b162d6879a2e4e6d7916b2b985441d98f8a7cdcd85be96cf846b"
PRE_CONFIGURED_CASES = 1609
PRE_CONFIGURED_CATALOG_SHA256 = "d440b9e0828e0c0994aa4d20519a1813b54e3684ed783695b573010661dc55ed"
PRE_PROVIDER_OVERFLOW_CASES = 1611
PRE_PROVIDER_OVERFLOW_CATALOG_SHA256 = "0e2a16aa84908495a3b48d5a28f9d2855ece6d2083db8375110efe2aaca810b4"
PRE_DATE_BOUNDARY_CASES = 1618
PRE_DATE_BOUNDARY_SHA = "28eeb93559b2c65178dad1c849408f8808e95471c22583bef225ea30c4540676"
PRE_SCRATCH_CASES = 1623
PRE_SCRATCH_SHA256 = "b3defae8b4ffe4cd439ca21decadf585850835e96ad4909a47c14a0098867399"
REGISTERED_CASES = 1662

# PR22 changes these three policy texts, not the thirteen cases' business inputs,
# order, coverage or other fields. Reversing only the exact reviewed fragments
# must recover the original complete prefix hash after the existing Host mapping.
_HOME_POLICIES = (
    (("get-contract-tool-filesystem-policy", "get-contract-symlink-loop-cause-diagnostic"),
     "The same exact owned prefix in HOME-abbreviated spelling is mapped using "
     "the recorded fixtureHome, including error-escaped owned prefixes; unrelated home paths are unchanged. ", ""),
    (("storage-path-contract-root-relative-and-absolute", "storage-path-contract-traversal-and-missing",
      "storage-path-contract-encoded-literals-and-raw-boundaries", "storage-path-contract-symlink-admission",
      "storage-path-contract-symlink-loop-os-errors", "storage-path-contract-nonregular-and-hardlinks",
      "storage-path-contract-missing-workspace", "storage-path-contract-workspace-is-file",
      "storage-path-contract-plain-extra-root-authority", "storage-path-contract-patterned-extra-root-admission"),
     "prefix maps to $FIXTURE in JSON string values. Its HOME-abbreviated spelling "
     "uses only the recorded fixtureHome, including error-escaped owned prefixes; "
     "unrelated home paths are unchanged. Error wording, codes, causes, ",
     "prefix maps to $FIXTURE in JSON string values. Error wording, codes, causes, "),
    (("storage-path-read-race-owned-leaf-to-symlink",),
     "private fixture-base prefix maps to $FIXTURE, including its HOME-abbreviated "
     "spelling using recorded fixtureHome and error-escaped owned prefixes; "
     "unrelated home paths, errors, causes, codes and all fields ",
     "private fixture-base prefix maps to $FIXTURE; errors, causes, codes and all fields "),
)

# Reporting targets only. These IDs were selected from the independently retained
# 1,452-case baseline's /data/mismatchPayloads keys; no expected output is stored.
HISTORICAL_MISMATCH_REPORT_BASELINE_SHA256 = "7f858e165405d16bdf1d8973abb9fa60b8f2015531e4fc59e1735e8b8d43aaad"
HISTORICAL_MISMATCH_REPORT_IDS = (
    'hybrid-unicode-path-collation-diagnostic',
    'transcript-boundary-compressed-same-size-mtime-cache-diagnostic',
    'flush-execution-warm-index-first-recall',
    'redaction-policy-letter-mixed-i-engine-diagnostic',
    'redaction-policy-letter-repeated-capture-engine-diagnostic',
    'redaction-policy-unsupported-valid-general-property',
    'redaction-policy-unsupported-valid-v-direct-compiler',
    'model-tool-complete-tool-result',
    'model-tool-utf16-redaction-truncation-order',
    'model-session-configured-letter-mixed-i-engine-diagnostic',
    'model-session-configured-letter-capture-reset-engine-diagnostic',
    'bootstrap-discovery-memory-core-layout-extension',
    'bootstrap-discovery-legacy-state-gate',
    'promotion-ranking-primitive-provenance-safety-diagnostic',
)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _restore_reviewed_policies(prefix):
    approved = {identifier: (current, prior) for identifiers, current, prior in _HOME_POLICIES
                for identifier in identifiers}
    changes, seen = [], set()
    for index, actual in enumerate(prefix):
        if actual["id"] not in approved:
            continue
        current, prior = approved[actual["id"]]
        policy = actual.get("normalizationPolicy")
        if not isinstance(policy, str):
            raise ValueError("A reviewed HOME policy disappeared")
        if current not in policy:
            continue  # Historical unchanged catalogs retain their original authority.
        if policy.count(current) != 1 or actual["id"] in seen:
            raise ValueError("A reviewed HOME policy was duplicated or widened")
        original = deepcopy(actual)
        original["normalizationPolicy"] = policy.replace(current, prior, 1)
        prefix[index] = original
        seen.add(actual["id"])
        changes.append({"index": index, "id": actual["id"], "field": "normalizationPolicy",
                        "originalDefinitionSha256": _sha(original), "currentDefinitionSha256": _sha(actual)})
    if seen and seen != set(approved):
        raise ValueError("The thirteen reviewed HOME policy changes must migrate together")
    return changes


def definition_authority(cases, *, fif_version):
    """Authenticate all values, permitting only the reviewed exact migrations.

    V5 is a historical suite identity with the unchanged original prefix. V6
    explicitly replaces the four old Host definitions with frozen V4 wrappers
    and the thirteen V5 tail definitions with their frozen V6 successors.
    """
    from equivalence import forget_index_fence_v5, forget_index_fence_v6

    families = {"v5": forget_index_fence_v5, "v6": forget_index_fence_v6}
    if (fif_version not in families or not isinstance(cases, list)
            or len(cases) not in {HISTORICAL_REGISTERED_CASES, OUTCOME_REGISTERED_CASES,
                                  BOUNDARY_REGISTERED_CASES, RECALL_REGISTERED_CASES,
                                  CACHE_REGISTERED_CASES, RESET_REGISTERED_CASES, PROMPT_REGISTERED_CASES,
                                  HISTORY_REGISTERED_CASES, NUMERIC_REGISTERED_CASES, DEEP_REGISTERED_CASES, PRE_RECOVERY_CASES, PRE_FLUSH_PLAN_CASES,
                                  PRE_HEARTBEAT_OUTCOME_CASES, PRE_INTERRUPTION_CASES, PRE_ACTIVE_HISTORY_CASES, PRE_DATETIME_CASES, PRE_UNICODE_CASES, PRE_SECRET_CASES, PRE_CONFIGURED_CASES, PRE_PROVIDER_OVERFLOW_CASES, PRE_SCRATCH_CASES, REGISTERED_CASES}
            or fif_version == "v5" and len(cases) != HISTORICAL_REGISTERED_CASES):
        raise ValueError("Catalog migration requires one complete exact registered definition set")
    frozen = families[fif_version]
    if cases[ORIGINAL_PREFIX_CASES:HISTORICAL_REGISTERED_CASES] != frozen.build_cases():
        raise ValueError("Catalog migration changed or mixed the selected frozen FIF tail")
    lineage = cases[HISTORICAL_REGISTERED_CASES:OUTCOME_REGISTERED_CASES]
    if lineage:
        from equivalence.forget_lineage_outcomes import build_cases, validate_registration

        if lineage != build_cases():
            raise ValueError("Catalog migration changed the exact appended forget outcome family")
        validate_registration(cases)
    boundaries = cases[OUTCOME_REGISTERED_CASES:BOUNDARY_REGISTERED_CASES]
    if boundaries:
        from equivalence.forget_boundaries import build_cases, validate_registration

        if (_sha(cases[:OUTCOME_REGISTERED_CASES]) != OUTCOME_CATALOG_SHA256
                or _sha(boundaries) != _sha(build_cases())):
            raise ValueError("Catalog migration changed the frozen outcome catalog or exact boundary append")
        validate_registration(cases)
    recalls = cases[BOUNDARY_REGISTERED_CASES:RECALL_REGISTERED_CASES]
    if recalls:
        from equivalence.recall_signals import build_cases, validate_registration

        if (_sha(cases[:BOUNDARY_REGISTERED_CASES]) != BOUNDARY_CATALOG_SHA256
                or _sha(recalls) != _sha(build_cases())):
            raise ValueError("Catalog migration changed the frozen boundary catalog or exact recall append")
        validate_registration(cases)
    cache = cases[RECALL_REGISTERED_CASES:CACHE_REGISTERED_CASES]
    if cache:
        from equivalence.embedding_cache_lifecycle import build_cases, validate_registration

        if (_sha(cases[:RECALL_REGISTERED_CASES]) != RECALL_CATALOG_SHA256
                or _sha(cache) != _sha(build_cases())):
            raise ValueError("Catalog migration changed the frozen recall catalog or exact cache append")
        validate_registration(cases)
    resets = cases[CACHE_REGISTERED_CASES:RESET_REGISTERED_CASES]
    if resets:
        from equivalence.session_reset_boundaries import build_cases, validate_registration

        if (_sha(cases[:CACHE_REGISTERED_CASES]) != CACHE_CATALOG_SHA256
                or _sha(resets) != _sha(build_cases())):
            raise ValueError("Catalog migration changed the frozen cache catalog or exact reset boundary append")
        validate_registration(cases)
    prompts = cases[RESET_REGISTERED_CASES:PROMPT_REGISTERED_CASES]
    if prompts:
        from equivalence.prompt_runtime_context import build_cases, validate_registration

        if (_sha(cases[:RESET_REGISTERED_CASES]) != RESET_CATALOG_SHA256
                or _sha(prompts) != _sha(build_cases())):
            raise ValueError("Catalog migration changed the frozen reset catalog or exact prompt append")
        validate_registration(cases)
    histories = cases[PROMPT_REGISTERED_CASES:HISTORY_REGISTERED_CASES]
    if histories:
        from equivalence.prompt_history_repair import build_cases, validate_registration

        if (_sha(cases[:PROMPT_REGISTERED_CASES]) != PROMPT_CATALOG_SHA256
                or _sha(histories) != _sha(build_cases())):
            raise ValueError("Catalog migration changed the frozen prompt catalog or exact history repair append")
        validate_registration(cases)
    numbers = cases[HISTORY_REGISTERED_CASES:NUMERIC_REGISTERED_CASES]
    if numbers:
        from equivalence.engine_numeric_family import build_cases, validate_registration

        if _sha(cases[:HISTORY_REGISTERED_CASES]) != HISTORY_CATALOG_SHA256 or _sha(numbers) != _sha(build_cases()):
            raise ValueError("The numeric cases must follow the complete history repair family")
        validate_registration(cases)
    deep = cases[NUMERIC_REGISTERED_CASES:DEEP_REGISTERED_CASES]
    if deep:
        from equivalence.deep_consolidation import build_cases, validate_registration

        if _sha(cases[:NUMERIC_REGISTERED_CASES]) != NUMERIC_CATALOG_SHA256 or _sha(deep) != _sha(build_cases()):
            raise ValueError("The deep consolidation cases must follow the complete numeric family")
        validate_registration(cases)
    maintenance = cases[DEEP_REGISTERED_CASES:]
    if maintenance:
        from equivalence import automation_job_outcomes, automation_job_state, compaction_assembly, heartbeat_turn_boundaries, workspace_lock_cases
        from equivalence.dream_phase_family import FAMILIES as dream_families

        expected = [case for family in (*dream_families.values(), automation_job_state, workspace_lock_cases, automation_job_outcomes, heartbeat_turn_boundaries, compaction_assembly)
                    for case in family.build_cases()]
        if len(cases) >= PRE_RECOVERY_CASES and _sha(cases[:PRE_RECOVERY_CASES]) != PRE_RECOVERY_CATALOG_SHA256:
            raise ValueError("The first 1566 staged definitions changed")
        if len(cases) > PRE_RECOVERY_CASES:
            from equivalence.recovery_repair import build_cases as build_recovery_cases
            expected.extend(build_recovery_cases())
        if len(cases) >= PRE_FLUSH_PLAN_CASES and _sha(cases[:PRE_FLUSH_PLAN_CASES]) != PRE_FLUSH_PLAN_CATALOG_SHA256:
            raise ValueError("The first 1575 staged definitions changed")
        if len(cases) > PRE_FLUSH_PLAN_CASES:
            from equivalence.flush_plan_target import build_cases as build_flush_plan_cases
            expected.extend(build_flush_plan_cases())
        if len(cases) >= PRE_HEARTBEAT_OUTCOME_CASES and _sha(cases[:PRE_HEARTBEAT_OUTCOME_CASES]) != PRE_HEARTBEAT_OUTCOME_CATALOG_SHA256:
            raise ValueError("The 1588 definitions preceding heartbeat outcomes changed")
        if len(cases) > PRE_HEARTBEAT_OUTCOME_CASES:
            from equivalence.heartbeat_turn_outcomes import build_cases as build_heartbeat_outcome_cases
            expected.extend(build_heartbeat_outcome_cases())
        if len(cases) >= PRE_INTERRUPTION_CASES and _sha(cases[:PRE_INTERRUPTION_CASES]) != PRE_INTERRUPTION_CATALOG_SHA256:
            raise ValueError("The first 1592 registered definitions changed")
        if len(cases) > PRE_INTERRUPTION_CASES:
            from equivalence.recovery_failure import build_cases as build_interruption_cases
            expected.extend(build_interruption_cases())
        if len(cases) >= PRE_ACTIVE_HISTORY_CASES and _sha(cases[:PRE_ACTIVE_HISTORY_CASES]) != PRE_ACTIVE_HISTORY_CATALOG_SHA256:
            raise ValueError("The first 1594 registered definitions changed")
        if len(cases) > PRE_ACTIVE_HISTORY_CASES:
            from equivalence.compaction_active_history import build_cases as build_active_history
            expected.extend(build_active_history())
        if len(cases) >= PRE_DATETIME_CASES and _sha(cases[:PRE_DATETIME_CASES]) != PRE_DATETIME_CATALOG_SHA256:
            raise ValueError("The first 1597 case definitions changed")
        if len(cases) > PRE_DATETIME_CASES:
            from equivalence.datetime_regex_family import build_cases as build_date_regex_cases
            expected.extend(build_date_regex_cases())
        if len(cases) >= PRE_UNICODE_CASES and _sha(cases[:PRE_UNICODE_CASES]) != PRE_UNICODE_CATALOG_SHA256:
            raise ValueError("The first 1602 case definitions changed")
        if len(cases) > PRE_UNICODE_CASES:
            from equivalence.engine_unicode_collation import build_cases as build_unicode_cases
            expected.extend(build_unicode_cases())
        if len(cases) >= PRE_SECRET_CASES and _sha(cases[:PRE_SECRET_CASES]) != PRE_SECRET_CATALOG_SHA256:
            raise ValueError("The catalog before the four redaction boundaries changed")
        if len(cases) > PRE_SECRET_CASES:
            from equivalence.secret_boundary_inputs import build_cases as build_secret_cases
            expected.extend(build_secret_cases())
        if len(cases) >= PRE_CONFIGURED_CASES and _sha(cases[:PRE_CONFIGURED_CASES]) != PRE_CONFIGURED_CATALOG_SHA256:
            raise ValueError("The first 1609 registered definitions changed")
        if len(cases) > PRE_CONFIGURED_CASES:
            from equivalence.configured_redaction import build_cases as build_configured_cases
            expected.extend(build_configured_cases())
        if len(cases) >= PRE_PROVIDER_OVERFLOW_CASES and _sha(cases[:PRE_PROVIDER_OVERFLOW_CASES]) != PRE_PROVIDER_OVERFLOW_CATALOG_SHA256:
            raise ValueError("The first 1611 definitions preceding provider overflow changed")
        if len(cases) > PRE_PROVIDER_OVERFLOW_CASES:
            from equivalence.provider_overflow_cases import build_cases as build_provider_overflow_cases
            expected.extend(build_provider_overflow_cases())
        if len(cases) >= PRE_DATE_BOUNDARY_CASES and _sha(cases[:PRE_DATE_BOUNDARY_CASES]) != PRE_DATE_BOUNDARY_SHA:
            raise ValueError("The first 1618 ordered definitions preceding date boundary admission changed")
        if len(cases) > PRE_DATE_BOUNDARY_CASES:
            from equivalence.datetime_boundary_cases import build_cases as build_date_boundaries
            expected.extend(build_date_boundaries())
        if len(cases) >= PRE_SCRATCH_CASES and _sha(cases[:PRE_SCRATCH_CASES]) != PRE_SCRATCH_SHA256:
            raise ValueError("The 1623 definitions of the independently accepted 118 conditions changed")
        if len(cases) > PRE_SCRATCH_CASES:
            from equivalence.heartbeat_scratch_acceptance import build_cases as build_scratch_cases
            expected.extend(build_scratch_cases())
        if _sha(cases[:DEEP_REGISTERED_CASES]) != DEEP_CATALOG_SHA256 or _sha(maintenance) != _sha(expected):
            raise ValueError("Maintenance cases must follow the exact prior 1519 definitions")
    frozen.validate_registration(cases)
    prefix = deepcopy(cases[:ORIGINAL_PREFIX_CASES])
    policy_replacements = _restore_reviewed_policies(prefix)
    replacements = []
    if fif_version == "v6":
        from equivalence.host_turn_barrier import build_cases as original_hosts
        from equivalence.host_turn_barrier_v4 import build_cases as probes, business_case, registered_case

        old = original_hosts()
        new = [registered_case(probe) for probe in probes()]
        if len(old) != len(new) or len(new) != 4:
            raise ValueError("Catalog migration requires exactly four frozen Host V4 replacements")
        approved = {}
        for prior, current in zip(old, new, strict=True):
            if business_case(current) != prior or current["covers"] != prior["covers"]:
                raise ValueError("A Host wrapper changed its original business definition or point membership")
            approved[current["id"]] = prior, current
        seen = set()
        for index, actual in enumerate(prefix):
            if actual["id"] not in approved:
                continue
            prior, current = approved[actual["id"]]
            if _sha(actual) != _sha(current) or actual["id"] in seen:
                raise ValueError("A Host replacement changed, duplicated or widened its complete frozen wrapper")
            seen.add(actual["id"])
            prefix[index] = prior
            replacements.append({"index": index, "originalId": prior["id"], "currentId": current["id"],
                                 "originalDefinitionSha256": _sha(prior), "currentDefinitionSha256": _sha(current)})
        if seen != set(approved):
            raise ValueError("Catalog migration omitted an exact Host V4 replacement")
    if (_sha(prefix) != ORIGINAL_PREFIX_SHA256
            or sum("fixtureSource" in case for case in cases) != 79
            or sum("diagnosticOnly" in case for case in cases) != 1):
        raise ValueError("Catalog migration changed a definition outside its exact Host/HOME policy whitelist")
    tail = []
    if fif_version == "v6":
        for index, (prior, current) in enumerate(zip(forget_index_fence_v5.build_cases(), frozen.build_cases(), strict=True), ORIGINAL_PREFIX_CASES):
            tail.append({"index": index, "originalId": prior["id"], "currentId": current["id"],
                         "originalDefinitionSha256": _sha(prior), "currentDefinitionSha256": _sha(current)})
    result = {"kind": "explicit-default-definition-migration", "registeredCases": len(cases),
            "fifVersion": fif_version, "originalPrefixCases": ORIGINAL_PREFIX_CASES,
            "originalPrefixSha256": ORIGINAL_PREFIX_SHA256,
            "currentPrefixSha256": _sha(cases[:ORIGINAL_PREFIX_CASES]),
            "originalPrefixUnchanged": not replacements and not policy_replacements, "hostReplacements": replacements,
            "fifReplacements": tail, "policyReplacements": policy_replacements,
            "lineageAppend": [{"index": index, "id": case["id"], "definitionSha256": _sha(case)}
                              for index, case in enumerate(lineage, HISTORICAL_REGISTERED_CASES)],
            "boundaryAppend": [{"index": index, "id": case["id"], "definitionSha256": _sha(case)}
                               for index, case in enumerate(boundaries, OUTCOME_REGISTERED_CASES)]}
    if recalls:
        result["recallAppend"] = [
            {"index": index, "id": case["id"], "definitionSha256": _sha(case)}
            for index, case in enumerate(recalls, BOUNDARY_REGISTERED_CASES)]
    if cache:
        result["embeddingCacheAppend"] = [
            {"index": index, "id": case["id"], "definitionSha256": _sha(case)}
            for index, case in enumerate(cache, RECALL_REGISTERED_CASES)]
    if resets:
        result["sessionResetBoundariesAppend"] = [
            {"index": index, "id": case["id"], "definitionSha256": _sha(case)}
            for index, case in enumerate(resets, CACHE_REGISTERED_CASES)]
    if prompts:
        result["promptRuntimeContextAppend"] = [
            {"index": index, "id": case["id"], "definitionSha256": _sha(case)}
            for index, case in enumerate(prompts, RESET_REGISTERED_CASES)]
    if histories:
        result["promptHistoryRepairAppend"] = [
            {"index": index, "id": case["id"], "definitionSha256": _sha(case)}
            for index, case in enumerate(histories, PROMPT_REGISTERED_CASES)]
    if numbers:
        result["numericBoundariesAppend"] = [
            {"index": index, "id": case["id"], "definitionSha256": _sha(case)}
            for index, case in enumerate(numbers, HISTORY_REGISTERED_CASES)]
    if deep:
        result["deepConsolidationAppend"] = [
            {"index": index, "id": case["id"], "definitionSha256": _sha(case)}
            for index, case in enumerate(deep, NUMERIC_REGISTERED_CASES)]
    if maintenance:
        result["maintenanceAndLockAppend"] = [
            {"index": index, "id": case["id"], "definitionSha256": _sha(case)}
            for index, case in enumerate(maintenance, DEEP_REGISTERED_CASES)]
    return result
