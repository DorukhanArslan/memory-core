"""Run only the actual source identity function, never an original host/helper.

The OS regression opts in to the approved official /var/tmp namespace; the
standard sandbox has a synthetic Git marker and cannot qualify that platform.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from equivalence import host_turn_barrier_v4_environment as environment
from equivalence.model_runtime_authority import prepare_model_node_authority

ENTRY = environment.ROOT / "equivalence/host-turn-barrier-v4-entry.mjs"
SCRIPT = r"""
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
const request=JSON.parse(process.argv[1]);
const bytes=fs.readFileSync(request.source),source=bytes.toString('utf8');
const definition=source.match(/^function identity\(value\)\{[^\n]+\}$/m)?.[0];
if(!definition)throw Error('The exact source identity function was not found');
const fsAuthority=request.kind==='actual' ? fs : {
 lstatSync(value,options){
  if(value!=='labelled-stat-input'||options?.bigint!==true)throw Error('Changed stat call');
  return{dev:BigInt(request.stat.dev),ino:BigInt(request.stat.ino),
   mode:BigInt(request.stat.mode),uid:BigInt(request.stat.uid)};
 }
};
const identity=vm.runInNewContext(`(${definition})`,{fs:fsAuthority});
const observations=request.paths.map(path=>({path,identity:identity(path)}));
console.log(JSON.stringify({sourceSha256:crypto.createHash('sha256').update(bytes).digest('hex'),
 observations}));
"""


@pytest.fixture(scope="module")
def node():
    candidate = Path(os.environ.get("MEMORY_EQ_NODE",
        "/workspace/memory-core/work/node-v24.16.0-linux-x64/bin/node"))
    if not candidate.is_file():
        pytest.skip("Pinned Node is unavailable for the pure identity regression")
    authority = prepare_model_node_authority(candidate.resolve(strict=True))
    return Path(authority["execPath"])


def source_identity(node, request):
    request = {"source": str(ENTRY), **request}
    completed = subprocess.run([str(node), "--input-type=module", "-e", SCRIPT,
                                json.dumps(request, ensure_ascii=True, allow_nan=False)],
        cwd=environment.ROOT, env={"PATH": str(node.parent) + os.pathsep + os.defpath,
                                  "LANG": "C.UTF-8", "TZ": "UTC"},
        capture_output=True, check=True, text=True, timeout=10)
    result = json.loads(completed.stdout)
    assert result["sourceSha256"] == hashlib.sha256(ENTRY.read_bytes()).hexdigest()
    return result["observations"]


@pytest.mark.parametrize("inode", [0, 1, 2**63 - 1, -(2**63), -1, 2**63, 2**64 - 1])
def test_actual_producer_represents_each_64_bit_inode_as_unsigned_decimal(node, inode):
    observation, = source_identity(node, {"kind": "labelled", "paths": ["labelled-stat-input"],
        "stat": {"dev": "27", "ino": str(inode), "mode": str(0o40700), "uid": "65534"}})
    assert observation["identity"] == {"device": "27", "inode": str(inode % 2**64),
                                      "mode": 0o40700, "uid": 65534}


@pytest.mark.skipif(os.environ.get("MEMORY_EQ_HOST_V4_REAL_STAT") != "1",
                    reason="Requires the root-approved official /var/tmp execution view")
def test_actual_pinned_node_and_cpython_stat_identical_physical_ancestors_and_owned_roots(node, tmp_path):
    mapping = environment.allocate_execution(tmp_path, "native")
    try:
        Path(mapping["workspace"]).mkdir()
        paths = [Path("/"), Path("/var"), Path("/var/tmp"), *(Path(mapping[key]) for key in
                 ("executionRoot", "cwd", "state", "workspace", "captureRoot"))]
        expected = [{"path": str(path), "identity": environment.identity(path)} for path in paths]
        actual = source_identity(node, {"kind": "actual", "paths": [str(path) for path in paths]})
        assert actual == expected
        # UID remains the actual OS observation, including root or an unprivileged
        # execution account. It is never mapped between sandbox namespaces.
        assert actual[3]["identity"]["uid"] == os.getuid()
        before = environment.path_observation(mapping)
        for field in ("cwdAncestors", "workspaceAncestors"):
            observations = source_identity(node, {"kind": "actual",
                "paths": [row["path"] for row in before[field]]})
            for row, observation in zip(before[field], observations, strict=True):
                row["identity"] = observation["identity"]
        environment.validate_path_observation(before, mapping, before=False)
        for index, row in enumerate(before["cwdAncestors"]):
            inode = int(row["identity"]["inode"])
            if inode >= 2**63:
                signed_wire = deepcopy(before)
                signed_wire["cwdAncestors"][index]["identity"]["inode"] = str(inode - 2**64)
                with pytest.raises(ValueError, match="ancestor identity changed"):
                    environment.validate_path_observation(signed_wire, mapping, before=False)
    finally:
        shutil.rmtree(mapping["executionRoot"])
