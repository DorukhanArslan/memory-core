"""Original dreaming sweeps and their separately verified diary publication family."""
from equivalence import dream_diary, dream_light, dream_rem


FAMILIES = {dream_light.OPERATION: dream_light, dream_rem.OPERATION: dream_rem, dream_diary.OPERATION: dream_diary}
PHASES = {dream_light.OPERATION: "light", dream_rem.OPERATION: "rem", dream_diary.OPERATION: "diary"}


def report_key(operation, field):
    return "dream" + PHASES[operation].capitalize() + field


def evidence_family(operation):
    return "dream-" + PHASES[operation]
