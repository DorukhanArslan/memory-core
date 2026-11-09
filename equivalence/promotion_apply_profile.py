"""One independent compiled apply capability for the reviewed before diagnostic."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority


PROMOTION_APPLY_OPERATION = "promotion-apply-reconcile-runtime"
PROMOTION_APPLY_INPUT_KIND = "promotion-apply-reconcile"
PROMOTION_APPLY_CASE_ID = "promotion-apply-zero-rehydrated-directory-memory"
PROMOTION_APPLY_CASE_WIRE_SHA256 = "2c2bcfc960b729ae64acd3878f1f5a3dcd847fe9dabf8dd4b7e12bc277f8379a"


def promotion_apply_case_wire(value):
    return json.dumps({"id": PROMOTION_APPLY_CASE_ID, "operation": PROMOTION_APPLY_OPERATION, "input": value},
                      ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def validate_promotion_apply_input(value):
    if (type(value) is not dict or value.get("kind") != PROMOTION_APPLY_INPUT_KIND
            or hashlib.sha256(promotion_apply_case_wire(value)).hexdigest() != PROMOTION_APPLY_CASE_WIRE_SHA256):
        raise ValueError("The apply capability permits only its reviewed literal before diagnostic")
    return deepcopy(value)


def validate_promotion_apply_profile(value):
    if (type(value) is not dict or set(value) != {"kind", "operation", "inputKind", "nodeRuntime", "caseWireSha256"}
            or value["kind"] != "approved-promotion-apply-profile"
            or value["operation"] != PROMOTION_APPLY_OPERATION or value["inputKind"] != PROMOTION_APPLY_INPUT_KIND
            or value["caseWireSha256"] != PROMOTION_APPLY_CASE_WIRE_SHA256):
        raise ValueError("Promotion apply requires its separate exact compiled capability")
    validate_model_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_promotion_apply_profile(node: Path):
    return validate_promotion_apply_profile({"kind": "approved-promotion-apply-profile",
        "operation": PROMOTION_APPLY_OPERATION, "inputKind": PROMOTION_APPLY_INPUT_KIND,
        "nodeRuntime": prepare_model_node_authority(node), "caseWireSha256": PROMOTION_APPLY_CASE_WIRE_SHA256})
