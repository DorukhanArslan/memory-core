"""Independent literal families for the original managed dreaming phases."""
from equivalence import dream_deep, dream_light, dream_rem


FAMILIES = {dream_light.OPERATION: dream_light, dream_rem.OPERATION: dream_rem, dream_deep.OPERATION: dream_deep}
PHASES = {dream_light.OPERATION: "light", dream_rem.OPERATION: "rem", dream_deep.OPERATION: "deep"}


def report_key(operation, field):
    return "dream" + PHASES[operation].capitalize() + field


def evidence_family(operation):
    return "dream-" + PHASES[operation]
