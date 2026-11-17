"""The two independently frozen families that execute the original dreaming sweep."""
from equivalence import dream_light, dream_rem


FAMILIES = {dream_light.OPERATION: dream_light, dream_rem.OPERATION: dream_rem}
PHASES = {dream_light.OPERATION: "light", dream_rem.OPERATION: "rem"}


def report_key(operation, field):
    return "dream" + PHASES[operation].capitalize() + field


def evidence_family(operation):
    return "dream-" + PHASES[operation]
