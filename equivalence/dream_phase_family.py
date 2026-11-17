"""Verified case families for the managed dreaming phases and diary publication."""
from equivalence import dream_deep, dream_diary, dream_light, dream_rem

FAMILIES = {phase.OPERATION: phase for phase in (dream_light, dream_rem, dream_diary, dream_deep)}
PHASES = {dream_light.OPERATION: "light", dream_rem.OPERATION: "rem",
          dream_diary.OPERATION: "diary", dream_deep.OPERATION: "deep"}


def report_key(operation, field):
    return "dream" + PHASES[operation].capitalize() + field


def evidence_family(operation):
    return "dream-" + PHASES[operation]
