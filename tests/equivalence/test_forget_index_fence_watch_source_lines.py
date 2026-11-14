"""Pure source-boundary admission tests; no original watcher is executed."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from equivalence import forget_index_fence_evidence as guard
from equivalence.forget_index_fence_native_watch_evidence import _opaque_native_reconciliation_return


VALUE = "const valueRecord=value=>{try{return{v8Hex:serialize(value).toString('hex')};}catch(error){return{serializationError:errorValue(error)};}};"
WRAPPED = "return deliveries.run(delivery,()=>{try{const result=Reflect.apply(listener,this,values);"
RETURNED = "emit('original-watch-delivery-return',{deliveryId:delivery.deliveryId,return:valueRecord(result),returnRef:ref(result),atNs:now()});return result;"


def _helper(padding):
    # Positions are explicit fixture inputs, independent of the guard's search.
    return "// unit observer\n" + VALUE + "\n" + "\n" * padding + "\n".join([
        "const wrapped=function(...values){const delivery={deliveryId:`${process.pid}:${threadId}:watch-delivery-${++nextDelivery}`,",
        "kind:'native',handleRef:registration.handleRef,registration,arguments:valueRecord(values),atNs:now()};",
        "emit('original-watch-delivery-enter',delivery);",
        WRAPPED,
        RETURNED,
        "}catch(error){throw error;}});",
        "};",
    ]) + "\n"


@pytest.fixture
def opaque_boundary(tmp_path, monkeypatch):
    historical, current = tmp_path / "historical", tmp_path / "current"
    for root, padding in ((historical, 0), (current, 33)):
        (root / "equivalence").mkdir(parents=True)
        (root / "equivalence/forget-index-fence-source-clock.mjs").write_text(_helper(padding))
    monkeypatch.setattr(guard, "ROOT", current)
    recorded = tmp_path / "recorded/equivalence/forget-index-fence-source-clock.mjs"
    runtime = tmp_path / "release/node_modules/openclaw"
    compiled = runtime / "dist/file-watcher-DSOr6bb7.mjs"
    compiled.parent.mkdir(parents=True)
    listener = "(eventType, filename) => this.enqueueReconciliation('unit', () => Promise.resolve())"
    compiled.write_text(listener + "\n\tenqueueReconciliation(key, run) {\n"
                        "if (this.closed) return Promise.resolve();\n"
                        "this.reconciling = pending;\n\t\t}\n\t\treturn this.reconciling;\n")
    context = {"runtime": {"runtimeRoot": str(runtime)}, "allowedLocal": [
        {"path": str(recorded), "sha256": hashlib.sha256(_helper(0).encode()).hexdigest()}]}
    delivery = {"kind": "native", "registration": {"sourceOwner": {"path": "dist/file-watcher-DSOr6bb7.mjs"},
        "originalStack": f"Error: original registration\n    at register ({compiled}:552:8)",
        "listenerSource": listener, "handleRef": "101:0:process-ref-1", "listenerRef": "101:0:process-ref-2",
        "wrapperRef": "101:0:process-ref-3"}}
    stack = ("Error: #<Promise> could not be cloned.\n    at serialize (node:v8:456:7)\n"
             f"    at valueRecord ({recorded.as_uri()}:2:44)\n"
             f"    at {recorded.as_uri()}:7:82\n"
             "    at AsyncLocalStorage.run (node:internal/async_local_storage/async_context_frame:63:14)\n"
             f"    at FSWatcher.wrapped ({recorded.as_uri()}:6:22)")
    returned = {"return": {"serializationError": {"name": "Error", "message": "#<Promise> could not be cloned.",
                                                  "stack": stack}}, "returnRef": "101:0:process-ref-4"}
    return {"historical": historical, "current": current, "recorded": recorded, "context": context,
            "delivery": delivery, "returned": returned}


def _check(value, *, selected=True):
    _opaque_native_reconciliation_return(value["returned"], value["delivery"], value["context"], 101,
        **({"approved_adapter_root": value["historical"]} if selected else {}))


def test_selected_historical_helper_uses_original_recorded_stack_uri(opaque_boundary):
    before = deepcopy(opaque_boundary["returned"])
    assert not opaque_boundary["recorded"].exists()
    _check(opaque_boundary)
    assert opaque_boundary["returned"] == before
    with pytest.raises(ValueError, match="independently selected source"):
        _check(opaque_boundary, selected=False)


def test_default_current_helper_derives_shifted_exact_lines(opaque_boundary):
    value = opaque_boundary
    value["context"]["allowedLocal"][0]["sha256"] = hashlib.sha256(_helper(33).encode()).hexdigest()
    stack = value["returned"]["return"]["serializationError"]["stack"]
    # New source has 33 extra lines after the serializer, before the wrapper.
    stack = stack.replace(":7:82", ":40:82").replace(":6:22", ":39:22")
    value["returned"]["return"]["serializationError"]["stack"] = stack
    _check(value, selected=False)


def test_selected_helper_also_derives_the_serializer_function_line(opaque_boundary):
    value = opaque_boundary
    source = value["historical"] / "equivalence/forget-index-fence-source-clock.mjs"
    text = "// earlier authenticated helper declaration\n" + source.read_text()
    source.write_text(text)
    value["context"]["allowedLocal"][0]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    error = value["returned"]["return"]["serializationError"]
    error["stack"] = error["stack"].replace(":2:44", ":3:44").replace(":7:82", ":8:82").replace(":6:22", ":7:22")
    _check(value)


@pytest.mark.parametrize("attack", ["missing-source", "missing-file", "duplicate-source", "wrong-hash",
    "wrong-location", "wrong-selected-root", "selected-uri", "old-value-line", "old-wrapper-line",
    "old-return-line", "missing-return-frame", "wrong-function", "changed-source", "duplicate-value-call",
    "duplicate-wrapper-call", "missing-wrapper-call", "detached-return-call", "wrong-wrapper-owner",
    "non-promise-error", "different-return-object", "colliding-return-object", "cloneable-carrier",
    "changed-listener", "changed-compiled-source", "changed-original-registration"])
def test_source_boundary_refuses_changed_or_ambiguous_observer_proof(opaque_boundary, attack):
    value = opaque_boundary
    context, returned, delivery = value["context"], value["returned"], value["delivery"]
    error = returned["return"]["serializationError"]
    source = value["historical"] / "equivalence/forget-index-fence-source-clock.mjs"
    if attack == "missing-source":
        context["allowedLocal"] = []
    elif attack == "missing-file":
        source.unlink()
    elif attack == "duplicate-source":
        context["allowedLocal"].append(deepcopy(context["allowedLocal"][0]))
    elif attack == "wrong-hash":
        context["allowedLocal"][0]["sha256"] = "0" * 64
    elif attack == "wrong-location":
        context["allowedLocal"][0]["path"] = str(value["recorded"].parent.parent / "callbacks" / source.name)
    elif attack == "wrong-selected-root":
        value["historical"] = value["current"]
    elif attack == "selected-uri":
        error["stack"] = error["stack"].replace(value["recorded"].as_uri(), source.as_uri())
    elif attack == "old-value-line":
        error["stack"] = error["stack"].replace(":2:44", ":16:44")
    elif attack == "old-wrapper-line":
        error["stack"] = error["stack"].replace(":6:22", ":231:22")
    elif attack == "old-return-line":
        error["stack"] = error["stack"].replace(":7:82", ":232:82")
    elif attack == "missing-return-frame":
        error["stack"] = "\n".join(line for line in error["stack"].splitlines() if not line.endswith(":7:82"))
    elif attack == "wrong-function":
        error["stack"] = error["stack"].replace("FSWatcher.wrapped", "FSWatcher.fabricated")
    elif attack in {"changed-source", "duplicate-value-call", "duplicate-wrapper-call", "missing-wrapper-call",
                    "detached-return-call", "wrong-wrapper-owner"}:
        text = source.read_text()
        if attack == "changed-source":
            text += "// changed but not authenticated\n"
        elif attack == "duplicate-value-call":
            text += VALUE + "\n"
        elif attack == "duplicate-wrapper-call":
            text += WRAPPED + "\n" + RETURNED + "\n"
        elif attack == "missing-wrapper-call":
            text = text.replace(WRAPPED, "return aDifferentContinuation();")
        elif attack == "detached-return-call":
            text = text.replace(WRAPPED + "\n", WRAPPED + "\n// a different frame\n")
        else:
            text = text.replace("const wrapped=function", "const other=function")
        source.write_text(text)
        if attack != "changed-source":
            # Even a coherently selected byte/hash pair must have one exact
            # original serializer call and the adjacent native wrapper return.
            context["allowedLocal"][0]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    elif attack == "non-promise-error":
        error["message"] = "#<Function> could not be cloned."
    elif attack == "different-return-object":
        returned["returnRef"] = "102:0:process-ref-4"
    elif attack == "colliding-return-object":
        returned["returnRef"] = delivery["registration"]["listenerRef"]
    elif attack == "cloneable-carrier":
        returned["return"]["v8Hex"] = "ff0f5f"
    elif attack == "changed-listener":
        delivery["registration"]["listenerSource"] = "(eventType, filename) => Promise.resolve()"
    elif attack == "changed-compiled-source":
        (Path(context["runtime"]["runtimeRoot"]) / "dist/file-watcher-DSOr6bb7.mjs").write_text("replacement")
    else:
        delivery["registration"]["originalStack"] = "Error: fabricated registration"
    with pytest.raises((ValueError, OSError)):
        _check(value)
