"""Check the two hosted Doctor outcomes that exercise all three repair notices."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from equivalence import heartbeat_doctor_probe as doctor
from equivalence.heartbeat_dependency import prepare_heartbeat_dependency
from equivalence.heartbeat_scratch_outcomes import compare_doctor_outcomes
from equivalence.heartbeat_scratch_review import _check_doctor_sdk, _digest


CASES = ("doctor-ordinary", "doctor-disabled-shared-retention")


def read(path):
    return json.loads(path.read_bytes())


def run(receipt):
    reference = ROOT / ".reference/openclaw"
    runtime = ROOT / ".reference/release-runtime"
    output = ROOT / ".heartbeat-home-preflight"
    if not ROOT.is_relative_to(Path.home()) or ROOT == Path.home():
        raise ValueError("This preflight must reproduce the hosted checkout under the runner account home")
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as temp:
        private = Path(temp) / "release-runtime"
        shutil.copytree(runtime, private, symlinks=True)
        archive = ROOT / ".reference/heartbeat-dependencies/archives/croner-10.0.1.tgz"
        prepare_heartbeat_dependency(reference, private, archive, install=True)
        doctor.run(reference, private, Path(shutil.which("node")).resolve(), output, CASES, configured_state=True)
    selected = read(output / "cases.json")
    if tuple(c["id"] for c in selected) != CASES:
        raise ValueError("Missing required preflight examples")
    for case in selected:
        ident = case["id"]
        folder = output / ident
        streams = {"native": [], "sdk": []}
        raw = {"id": ident, "phases": [], "notices": []}
        receipt["cases"].append(raw)
        for number, phase in enumerate(case["phases"]):
            pair = {}
            for side in streams:
                path = folder / str(number) / (side + ".stdout.json")
                data = path.read_bytes()
                observed = json.loads(data)
                streams[side].append(observed)
                fixture = folder / (side + "-fixture")
                if side == "sdk":
                    _check_doctor_sdk(observed["raw"], phase, fixture)
                elif observed["raw"]["env"]["OPENCLAW_HOME"] != str(fixture / "home"):
                    raise ValueError("The OpenClaw probe used a different home")
                changes = [message for call in observed["raw"]["calls"] if call["operation"]["op"] == "repair"
                           for message in call["result"]["changes"]]
                raw["notices"].append({"phase": number, "side": side, "messages": changes})
                pair[side] = hashlib.sha256(data).hexdigest()
            raw["phases"].append(pair)
        public = compare_doctor_outcomes(case, streams["native"], streams["sdk"])
        raw.update(matches=public["matches"], nativeSha256=_digest(public["native"]), sdkSha256=_digest(public["sdk"]))
        if not raw["matches"] or raw["nativeSha256"] != raw["sdkSha256"]:
            raise ValueError("Preflight public outputs differ: " + ident)
        for side in streams:
            literal = str(folder / (side + "-fixture") / "workspace" / "HEARTBEAT.md")
            messages = [m for row in raw["notices"] if row["side"] == side for m in row["messages"]]
            expected = 1 if ident == "doctor-ordinary" else 3
            if len(messages) != expected or any(literal not in m for m in messages):
                raise ValueError("The hosted raw repair response did not use its literal fixture path: " + ident)
    seal = output / "authentication-before.json"
    if read(seal) != read(output / "authentication-after.json"):
        raise ValueError("Probe source or runtime changed during preflight")
    receipt["authenticationSha256"] = hashlib.sha256(seal.read_bytes()).hexdigest()
    receipt["passed"] = True


if __name__ == "__main__":
    receipt = {"passed": False, "acceptancePointsAwarded": 0, "cases": []}
    try:
        run(receipt)
    finally:
        encoded = json.dumps(receipt, ensure_ascii=True, separators=(",", ":"))
        (Path(os.environ["RUNNER_TEMP"]) / "scratch-home-preflight.json").write_text(encoded + "\n")
        print("SCRATCH_HOME_PREFLIGHT " + encoded, flush=True)
