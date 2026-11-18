"""Operation-bound local workspace profiles with complete native and SDK evidence."""
from equivalence import recovery_failure, recovery_repair
from equivalence.dream_phase_family import FAMILIES as DREAMS, PHASES, report_key as dream_report_key

FAMILIES = {**DREAMS, recovery_failure.OPERATION: recovery_failure, recovery_repair.ARTIFACT: recovery_repair, recovery_repair.INDEX: recovery_repair}
RECOVERY = {recovery_failure.OPERATION: "recovery-interruption", recovery_repair.ARTIFACT: "recovery-artifact", recovery_repair.INDEX: "recovery-index"}


def evidence_family(operation):
    return RECOVERY[operation] if operation in RECOVERY else "dream-" + PHASES[operation]


def report_key(operation, field):
    if operation == recovery_failure.OPERATION:
        return "recoveryInterruption" + field
    if operation in RECOVERY:
        if field == "FamilyComplete":
            return "recoveryRepairFamilyComplete"
        return ("recoveryArtifact" if operation == recovery_repair.ARTIFACT else "recoveryIndex") + field
    return dream_report_key(operation, field)


def prepare_bindings(checkout, runtime_root, operation):
    if operation == recovery_failure.OPERATION:
        from equivalence.forget_lineage_bindings import prepare_forget_lineage_bindings
        return prepare_forget_lineage_bindings(checkout, runtime_root)
    if operation == recovery_repair.ARTIFACT:
        from equivalence.recovery_artifact_evidence import prepare_artifact_bindings
        return prepare_artifact_bindings(checkout, runtime_root)
    if operation == recovery_repair.INDEX:
        from equivalence.recovery_index_bindings import prepare_index_repair_bindings
        return prepare_index_repair_bindings(checkout, runtime_root)
    from equivalence.dream_light_bindings import prepare_dream_light_bindings
    return prepare_dream_light_bindings(checkout, runtime_root, phase=PHASES[operation])


def native_validator(operation):
    if operation == recovery_failure.OPERATION:
        from equivalence.recovery_failure_evidence import validate_native
        return validate_native
    if operation == recovery_repair.ARTIFACT:
        from equivalence.recovery_artifact_evidence import validate_native
        return validate_native
    if operation == recovery_repair.INDEX:
        from equivalence.recovery_index_evidence import validate_native
        return validate_native
    if operation == "dream-diary-publication-runtime":
        from equivalence.dream_diary_evidence import validate_native
        return validate_native
    if operation == "dream-deep-runtime":
        from equivalence.dream_deep_evidence import validate_deep_native
        return validate_deep_native
    from equivalence.dream_light_evidence import validate_dream_light_native
    return validate_dream_light_native


def sdk_validator(operation):
    if operation == recovery_failure.OPERATION:
        from equivalence.recovery_failure_evidence import validate_sdk
    elif operation == recovery_repair.ARTIFACT:
        from equivalence.recovery_artifact_evidence import validate_sdk
    elif operation == recovery_repair.INDEX:
        from equivalence.recovery_index_evidence import validate_sdk
    elif operation == "dream-diary-publication-runtime":
        from equivalence.dream_diary_evidence import validate_sdk
    elif operation == "dream-deep-runtime":
        from equivalence.dream_deep_evidence import validate_deep_sdk as validate_sdk
    else:
        from equivalence.dream_light_sdk_evidence import validate_sdk
    return validate_sdk
