"""Read one exact retained artifact; measure capture transport, never run engines."""
from __future__ import annotations

import codecs
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "DorukhanArslan/memory-core"
RUN_ID = 44088814920
HEAD = "a882d3d78424ca3552fabce53355da1a6a8cdb65"
ARTIFACT_ID = 14339997707
ARTIFACT_NAME = "prompt-runtime-context-raw-evidence"
ARTIFACT_BYTES = 2477882808
ARTIFACT_SHA256 = "59e4a892bac968cda3c9133f5220be50c7660ddc27e28d8b5972f09c27351fb5"
CASE_ID = "forget-index-fence-v6-split-old-full-complete-forget"
SCENARIO = "split-old-full-complete-forget"
CASE_SHA256 = "10a26d8c9005092f786daf5840666bea7677493671d9fc807bdb96c75ee08e7a"
MANIFEST_SHA256 = "ce4ee37230a9a814d7f8440e7e9cc513ae5140ee2980aa01c45480493ef4998d"
SDK_SHA256 = "375890b10db63088c9fb1d2e6ce7ddafed363acfd6aa020da52dfd46de0d0517"
SDK_TREE = "c0e5c2f805931d02f3834f8b856e2cc65c8bb9a6"
WIRE_LIMIT = 512 * 1024**2
LOAD_LIMIT = 1024**3
PREFIX_LIMIT = 1024**2
RECEIPT_LIMIT = 20_000


def require(value, message):
    if not value:
        raise ValueError(message)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(_value):
    raise ValueError("non-finite JSON constant")


def finite(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float):
            require(math.isfinite(item), "non-finite JSON number")
        elif isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def strict_load(stream):
    value = json.load(stream, object_pairs_hook=pairs, parse_constant=invalid_constant)
    finite(value)
    return value


def encoded_size(value):
    digest, size = hashlib.sha256(), 0
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for text in encoder.iterencode(value):
        chunk = text.encode("utf8")
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def sdk_identity():
    digest = hashlib.sha256()
    files = sorted((ROOT / "memory_core").rglob("*.py"))
    for path in files:
        require(path.is_file() and not path.is_symlink(), "nonregular SDK source")
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    tree = subprocess.check_output(["git", "rev-parse", "HEAD:memory_core"], cwd=ROOT, text=True).strip()
    require(len(files) == 164 and digest.hexdigest() == SDK_SHA256 and tree == SDK_TREE,
            "frozen SDK source changed")
    require(not subprocess.check_output(["git", "status", "--porcelain", "--", "memory_core"],
                                       cwd=ROOT, text=True).strip(), "dirty SDK source")
    return {"sha256": digest.hexdigest(), "files": len(files), "gitTree": tree}


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        require(urllib.parse.urlsplit(new_url).scheme == "https", "non-HTTPS artifact redirect")
        redirected = super().redirect_request(request, response, code, message, headers, new_url)
        if urllib.parse.urlsplit(new_url).netloc != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected


def download_archive(path):
    token = os.environ["GH_TOKEN"]
    opener = urllib.request.build_opener(SafeRedirect())
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    url = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}"
    with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as response:
        metadata_bytes = response.read(PREFIX_LIMIT + 1)
    require(len(metadata_bytes) <= PREFIX_LIMIT, "artifact metadata bound")
    metadata = json.loads(metadata_bytes.decode("utf8"), object_pairs_hook=pairs,
                          parse_constant=invalid_constant)
    require(metadata["id"] == ARTIFACT_ID and metadata["name"] == ARTIFACT_NAME
            and metadata["size_in_bytes"] == ARTIFACT_BYTES and metadata["expired"] is False
            and metadata["digest"] == "sha256:" + ARTIFACT_SHA256
            and metadata["workflow_run"]["id"] == RUN_ID
            and metadata["workflow_run"]["head_sha"] == HEAD, "retained artifact identity changed")
    digest, size = hashlib.sha256(), 0
    with opener.open(urllib.request.Request(url + "/zip", headers=headers), timeout=60) as response, path.open("xb") as output:
        while chunk := response.read(PREFIX_LIMIT):
            size += len(chunk)
            require(size <= ARTIFACT_BYTES, "artifact exceeds its exact declared size")
            digest.update(chunk)
            output.write(chunk)
    require(size == ARTIFACT_BYTES and digest.hexdigest() == ARTIFACT_SHA256,
            "complete retained archive bytes changed")
    return {"id": ARTIFACT_ID, "runId": RUN_ID, "head": HEAD, "bytes": size,
            "sha256": digest.hexdigest(), "downloadedOnlyInsideGithubRunner": True}


def prefix_identity(payload):
    """Read only leading dispatch/input string metadata, never print the prefix."""
    text = codecs.getincrementaldecoder("utf8")().decode(payload, final=False)
    decoder, position = json.JSONDecoder(), 0

    def expect(token):
        nonlocal position
        while position < len(text) and text[position] in " \t\r\n":
            position += 1
        require(text.startswith(token, position), "unrecognized bounded capture prefix")
        position += len(token)

    def string():
        nonlocal position
        while position < len(text) and text[position] in " \t\r\n":
            position += 1
        value, position = decoder.raw_decode(text, position)
        require(isinstance(value, str), "capture prefix metadata must be a string")
        return value

    expect("[")
    expect("{")
    require(string() == "kind", "capture does not begin with its real dispatch kind")
    expect(":")
    kind = string()
    expect(",")
    require(string() == "input", "capture does not retain the leading actual input")
    expect(":")
    expect("{")
    metadata = {}
    for _ in range(8):
        key = string()
        expect(":")
        require(key in {"kind", "profile", "scenario"} and key not in metadata,
                "unrecognized leading input metadata")
        metadata[key] = string()
        if key == "scenario":
            require(kind == "forget-index-fence-v6-sdk-dispatch"
                    and metadata.get("kind") == "forget-index-fence-v6"
                    and metadata["scenario"] == SCENARIO, "oversized capture is another scenario")
            return {"dispatchKind": kind, "inputKind": metadata["kind"], "scenario": SCENARIO,
                    "prefixBytesRead": len(payload), "prefixNotEmitted": True}
        expect(",")
    raise ValueError("scenario absent from bounded leading metadata")


def selected_entry(info):
    path = PurePosixPath(info.filename)
    parts = path.parts
    return (not path.is_absolute() and ".." not in parts and len(parts) >= 4
            and any(parts[index:index + 2] == (".equivalence-results", "forget-index-fence-v6")
                    for index in range(len(parts) - 1))
            and parts[-1] == "python-raw.json" and parts[-2].startswith("sdk-attempt-"))


def extract_one(archive, info, destination):
    require(0 < info.file_size <= LOAD_LIMIT and not info.is_dir() and not info.flag_bits & 1
            and stat.S_IFMT(info.external_attr >> 16) in {0, stat.S_IFREG}, "unsafe or excessive selected capture")
    digest, without_last, count, last = hashlib.sha256(), hashlib.sha256(), 0, b""
    with archive.open(info) as source, destination.open("xb") as output:
        while chunk := source.read(PREFIX_LIMIT):
            count += len(chunk)
            require(count <= LOAD_LIMIT and count <= info.file_size, "selected capture read exceeds its bound")
            digest.update(chunk)
            output.write(chunk)
            combined = last + chunk
            without_last.update(combined[:-1])
            last = combined[-1:]
    require(count == info.file_size, "incomplete original selected capture")
    return {"bytes": count, "sha256": digest.hexdigest(), "lastByteIsLf": last == b"\n",
            "sha256WithoutFinalByte": without_last.hexdigest()}


def inspect_capture(path, identity):
    with path.open(encoding="utf8") as source:
        records = strict_load(source)
    require(isinstance(records, list) and len(records) == 1 and isinstance(records[0], dict),
            "capture is not the complete singleton dispatch")
    packet = records[0]
    require(packet.get("kind") == "forget-index-fence-v6-sdk-dispatch"
            and packet.get("input", {}).get("scenario") == SCENARIO, "selected complete capture identity changed")
    actual_wire = {"id": CASE_ID, "operation": "forget-index-fence-v6-runtime", "input": packet["input"]}
    case_sha = hashlib.sha256(json.dumps(actual_wire, sort_keys=True, ensure_ascii=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    require(case_sha == CASE_SHA256, "actual complete input differs from the frozen failed case")
    require(len(packet) <= 128, "metadata field inventory bound")
    inventory = [{"field": key, "valueType": type(value).__name__, "compactJsonUtf8Bytes": encoded_size(value)[0]}
                 for key, value in packet.items()]
    compact_bytes, compact_sha = encoded_size(records)
    encoding = packet.get("observationEncoding")
    stdout = packet.get("stdout")
    require(isinstance(stdout, str) and isinstance(encoding, dict)
            and encoding.get("kind") == "stdout-json-v1" and encoding.get("field") == "stdout",
            "selected packet lacks its existing exact stdout encoding")
    stdout_bytes = stdout.encode("utf8")
    require(len(stdout_bytes) <= LOAD_LIMIT and len(stdout_bytes) == encoding.get("utf8Bytes")
            and hashlib.sha256(stdout_bytes).hexdigest() == encoding.get("sha256"),
            "actual nested stdout differs from its retained byte seal")
    del stdout_bytes
    nested = json.loads(stdout, object_pairs_hook=pairs, parse_constant=invalid_constant)
    finite(nested)
    inner_bytes, inner_hash, escaped_inner_bytes = 0, hashlib.sha256(), 2
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for text in encoder.iterencode(nested):
        data = text.encode("utf8")
        inner_bytes += len(data)
        inner_hash.update(data)
        escaped_inner_bytes += len(json.dumps(text, ensure_ascii=False, allow_nan=False)[1:-1].encode("utf8"))
    old_stdout_size = next(item["compactJsonUtf8Bytes"] for item in inventory if item["field"] == "stdout")
    candidate_bytes = compact_bytes - old_stdout_size + escaped_inner_bytes
    refreshed_bytes = candidate_bytes + len(str(inner_bytes)) - len(str(encoding["utf8Bytes"]))
    return {"caseId": CASE_ID, "scenario": SCENARIO, "completeInputSha256": case_sha,
        "originalCapture": identity, "guardSizeLimitBytes": WIRE_LIMIT,
        "originalExceedsGuardSizeLimit": identity["bytes"] > WIRE_LIMIT,
        "compactOuterBytes": compact_bytes, "compactOuterSha256": compact_sha,
        "compactOuterFitsExistingGuard": compact_bytes <= WIRE_LIMIT,
        "originalIsExactlyCompactOuterPlusLf": identity["lastByteIsLf"]
            and compact_bytes + 1 == identity["bytes"] and compact_sha == identity["sha256WithoutFinalByte"],
        "fieldInventory": sorted(inventory, key=lambda item: item["compactJsonUtf8Bytes"], reverse=True),
        "hypotheticalNestedStdoutCompaction": {"actualStdoutUtf8Bytes": encoding["utf8Bytes"],
            "compactStdoutUtf8Bytes": inner_bytes, "compactStdoutSha256": inner_hash.hexdigest(),
            "escapedCompactStdoutJsonBytes": escaped_inner_bytes,
            "outerBytesWithOnlyStdoutChanged": candidate_bytes,
            "outerBytesWithStdoutEncodingMetadataRefreshed": refreshed_bytes,
            "fitsUnchanged512MiBGuard": refreshed_bytes + 1 <= WIRE_LIMIT,
            "includesOriginalWriterLf": True, "measuredOnSameStrictlyParsedWholeValue": True,
            "captureRewritten": False, "validForAcceptance": False,
            "semanticRoundTripIndependentlyReparsed": False},
        "originalLinkCountRecoverableFromZip": False,
        "diagnosisScope": "actual byte size is sufficient to explain this guard rejection; ZIP does not attest original hardlink count"}


def main():
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    started, stage = time.monotonic(), "source-seal"
    receipt = {"kind": "retained-fif-capture-size-diagnosis", "status": "blocked", "acceptancePointsAwarded": 0,
               "comparisonEnginesExecuted": False, "sdkBusinessCallsExecuted": False, "captureValuesEmitted": False,
               "artifactDownloadedToUserWorkspace": False, "rawCapturesRewritten": False}
    try:
        receipt["sdkBefore"] = sdk_identity()
        manifest = (ROOT / "docs/forget_index_fence_v6_literals.json").read_bytes()
        require(hashlib.sha256(manifest).hexdigest() == MANIFEST_SHA256, "frozen input manifest changed")
        stage = "download-exact-retained-archive"
        archive_path = Path(os.environ["RUNNER_TEMP"]) / "retained-prompt-raw-evidence.zip"
        receipt["artifact"] = download_archive(archive_path)
        stage = "zip-metadata-only"
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            require(len({entry.filename for entry in entries}) == len(entries), "duplicate ZIP entry names")
            captures = [entry for entry in entries if selected_entry(entry)]
            receipt["fifRawFiles"] = [{"name": item.filename, "uncompressedBytes": item.file_size,
                "compressedBytes": item.compress_size, "unixMode": oct(item.external_attr >> 16),
                "oversizedForExistingGuard": item.file_size > WIRE_LIMIT} for item in captures]
            require(len(captures) == 13, "the exact thirteen-member SDK raw inventory is absent")
            candidates = [item for item in captures if item.file_size > WIRE_LIMIT]
            require(len(candidates) == 1, "there is no unique oversized FIF capture; no payload decoded")
            candidate = candidates[0]
            require(candidate.file_size <= LOAD_LIMIT, "the unique capture exceeds the separate 1 GiB diagnostic load bound")
            stage = "bounded-prefix-scenario-confirmation"
            with archive.open(candidate) as source:
                prefix = source.read(PREFIX_LIMIT)
            receipt["prefixIdentity"] = prefix_identity(prefix)
            del prefix
            stage = "extract-one-complete-capture"
            capture_path = Path(os.environ["RUNNER_TEMP"]) / "one-retained-fif-capture.json"
            identity = extract_one(archive, candidate, capture_path)
            stage = "strict-one-capture-size-inventory"
            receipt["captureDiagnosis"] = inspect_capture(capture_path, identity)
        receipt["sdkAfter"] = sdk_identity()
        require(receipt["sdkAfter"] == receipt["sdkBefore"], "SDK source changed during metadata diagnosis")
        receipt["status"] = "diagnosed"
    except Exception as error:
        receipt["failure"] = {"stage": stage, "exceptionType": type(error).__name__,
                              "reason": str(error) if type(error) is ValueError else "bounded read-only diagnosis failed"}
    receipt["elapsedSeconds"] = round(time.monotonic() - started, 3)
    encoded = json.dumps(receipt, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    require(len(encoded) <= RECEIPT_LIMIT, "metadata receipt exceeds 20 KB; no capture values emitted")
    with output.open("xb") as destination:
        destination.write(encoded + b"\n")
    print(encoded.decode("ascii"), flush=True)
    return 0 if receipt["status"] == "diagnosed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
