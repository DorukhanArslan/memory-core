"""Authenticate an assessor-only artifact against the immutable measurement and its failed first assessment."""
from __future__ import annotations

from pathlib import Path
import hashlib
import re
import subprocess

from review_remainder import FILES, artifact, canonical, file_sha, read, require, require_assessed, valid_hash

ORIGINAL_RUN = 44214324963
ORIGINAL_HEAD = "8b00530188a1d6e87a02172bebf7b6e8b5c49433"
SUMMARY = {"id":14393591298, "bytes":308200, "sha256":"bca913e53324e08fa7b73a2f2bac8e31e07a2e4f784d38de327fd6c001d42a3d"}
RAW = {"id":14392639892, "bytes":2582430612, "sha256":"f74f90cb038cfe47425e9f61d7a8601dfaa85dce79f56b3642e64dd67f8b07e5"}
REPORT = {"bytes":1907529876, "sha256":"2d661807ea171e02ee8f1676ac5eb94b30e720de396141ae65572e0c9e358e7f"}
ORIGINAL_ASSESSOR = "189fb713bfb469e0c1a26a97defd8246d87ceaabe9d84f3ff5d61f9e4010d3fd"
ORIGINAL_ASSESSMENT = "2698758785ff872c0727f9462f6114786fbeebade226847fa8a7621f7b7d0745"
ORIGINAL_FIF = "cfaca8d5602af89dda9bfd2d4dfb13c37bea9eddf3a09eb2051613b7338a78bd"
F14 = "promotion-ranking-primitive-provenance-safety-diagnostic"
F14_NATIVE = "ce9199b6cadbcca42e7b2e918271317c69a6cffdd0d6ca542227ca2457c94715"
F14_SDK = ("db6ed4a22a533156005c77236fd270ba7da4a637053384a96cb6b2685988bd47",
           "3e08d8f757379a8aa03382f7c94cb14bb083eb114fbc2c422c9508cc4446331e")
FINAL_REFUSAL = [{"type":"ValueError","message":"Unexpected change to a retained difference or its complete public value"}]
SUPPLEMENT_FILES = {"assessment.json", "replay-receipt.json"}
EARLIER_REPLAYS = {"hostReplays", "lineageReplays", "boundaryReplays", "recallReplays", "embeddingCacheReplays",
                   "sessionResetBoundariesReplays", "promptRuntimeContextReplays", "promptHistoryRepairReplays"}
REVIEW_PROGRAM = ".github/scripts/assess_merged_comparison.py"
WRAPPER = ".reference/review-source/.github/scripts/review_retained_memory.py"
ADAPTERS = ["dream-light-runtime", "dream-rem-runtime", "dream-deep-runtime",
            "dream-diary-publication-runtime", "flush-plan-target-runtime"]
REVIEW_FILES = {"restore_comparison_artifact.py", "review_retained_memory.py", "retained_recovery_reference_modes.py",
                "replay_archived_dreams.py", "replay_archived_flush.py"}


def restore_recovery_modes(rows, observed):
    """Restore only fields omitted by the original compact writer, from the authenticated original case array."""
    from equivalence.recovery_failure import OTHER_PUBLISHERS, build_cases

    selected = set().union(*OTHER_PUBLISHERS.values(), {c["id"] for c in build_cases()})
    affected = [row for row in rows if row["id"] in selected and row["operation"] != "index-publication"]
    require(len(affected) == len(observed) == 9 and set(observed) == {r["id"] for r in affected},
            "Missing or extra retained recovery publication reference mode")
    for row in affected:
        actual = observed[row["id"]]
        require(actual == "authenticated-official-release" and row.get("referenceMode", actual) == actual,
                "A retained recovery publication ran under a different reference mode")
        row["referenceMode"] = actual


def verified_earlier(original, fresh, summary_folder, final_refusal=False):
    require(file_sha(summary_folder/"assessment.json") == ORIGINAL_ASSESSMENT
            and file_sha(summary_folder/"forget-family-replay.json") == ORIGINAL_FIF,
            "Archived original assessment or forget replay digest differs")
    require(original["status"] == "blocked" and original["completeReportParsed"] is True
            and original["acceptancePointsAwarded"] == 0 and original["candidateAssessment"] is None
            and original["errors"] == [{"type":"SessionAdmissionRuntimeBindingError",
                                       "message":"A session runtime owner escaped its reviewed tree."}],
            "The first failed assessment is missing or has been replaced")
    if final_refusal:
        require(fresh["status"] == "blocked" and fresh["errors"] == FINAL_REFUSAL and fresh["candidateAssessment"] is None
                and fresh["previousMismatchPublicHashReview"]["otherChangedCaseIds"] == [F14]
                and fresh["acceptancePointsAwarded"] == 0 and "fifReplaySha256" not in fresh
                and "fullScopePassed" not in fresh, "Wrong assessment stage or independent-review exception")
    else:
        require_assessed(fresh)
        require(fresh["fifReplaySha256"] == ORIGINAL_FIF and fresh["acceptancePointsAwarded"] == 0,
                "Supplement did not finish the frozen complete-report assessment")
    for key in EARLIER_REPLAYS | {"projection","report","kind","historicalVerifiedConditions","metadataOnlyAssessment",
                                  "completeRootAudit","originalEnginesExecuted","completeReportParsed"}:
        require(canonical(fresh[key]) == canonical(original[key]), "An already measured value or replay differs: " + key)
    require(fresh["report"]["bytes"] == REPORT["bytes"] and fresh["report"]["sha256"] == REPORT["sha256"],
            "The corrected assessment observed a different report")


def archive_workspaces(initial, fresh):
    """Separate names/content verified from ZIP from metadata bound to the original successful live checks."""
    from equivalence import dream_deep, dream_diary, dream_light, dream_rem
    compact = {r["id"]: r for r in initial["projection"]["cases"]}
    summary = {"sdkPhasesWithOriginalTimes":0, "diariesWithOriginalFileIdentity":0,
               "archivedDatabaseReopens":0, "archivedLinkContentsVerified":[]}
    for family in (dream_light,dream_rem,dream_deep,dream_diary):
        cases = family.build_cases()
        protected = fresh["appendedFamilyReplays"][family.OPERATION]["cases"]
        require([r["id"] for r in protected] == [c["id"] for c in cases], "Wrong restored dreaming family inventory")
        for r in protected:
            cid = r["id"]
            witness = r["archiveSdkWorkspace"]
            require(compact[cid]["runtimeEvidenceValidated"] is True and compact[cid]["status"] == "matched"
                    and r["publicMatch"] is True and r["validated"] is True
                    and witness["producerLiveEvidenceValidated"] is True
                    and valid_hash(witness["sdkRawSha256"]) and witness["sdkRawSha256"] == r["sdkRawSha256"]
                    and valid_hash(witness["contentManifestSha256"])
                    and type(witness["filesVerified"]) is int and witness["filesVerified"] > 0,
                    "Archived files do not bind to the corresponding successful original live verification")
            if family is dream_diary:
                require(valid_hash(witness["producerFilesystemMetadataSha256"])
                        and witness["metadataAuthority"] == "producer wire and live validation; ZIP inodes, modes and timestamps are not original"
                        and type(witness["capturedStages"]) is int and witness["capturedStages"] >= 2
                        and witness["archivedLinkContentsVerified"] in ([],["DREAMS.md"]),
                        "Restored diary evidence does not distinguish archived content from the original file identity")
                summary["diariesWithOriginalFileIdentity"] += 1
                if witness["archivedLinkContentsVerified"]:
                    summary["archivedLinkContentsVerified"].append(cid)
            else:
                require(witness["mtimeAuthority"] == "producer wire and live validation; ZIP times recorded separately"
                        and valid_hash(witness["producerMtimeNsSha256"]) and valid_hash(witness["archiveMtimeNsSha256"]),
                        "Recorded and archive file timestamps have no independent source identities")
                databases = witness["reopenedDatabases"]
                require(isinstance(databases,dict) and bool(databases)
                        and all(valid_hash(v["sha256"]) and bool(v["tables"]) for v in databases.values()),
                        "Missing archived dreaming SQLite contents")
                summary["sdkPhasesWithOriginalTimes"] += 1
                summary["archivedDatabaseReopens"] += len(databases)
    require(summary["sdkPhasesWithOriginalTimes"] == 22 and summary["diariesWithOriginalFileIdentity"] == 7,
            "Incomplete archived workspace review")
    return summary


def check_argv(argv, measurement_root, launch):
    require(isinstance(argv, list) and len(argv) == 16 and Path(argv[1]).name == "assess_merged_comparison.py",
            "Expected one invocation of the frozen assessor")
    script = Path(argv[1])
    require((script if script.is_absolute() else measurement_root/script) == measurement_root/REVIEW_PROGRAM,
            "Supplement ran a different assessor entrypoint")
    options = dict(zip(argv[2::2], argv[3::2], strict=True))
    expected = {"--report":measurement_root/".equivalence-results/full.json",
                "--seal":measurement_root/".equivalence-results/summary/source-seal.json",
                "--fif-replay":measurement_root/".equivalence-results/summary/forget-family-replay.json",
                "--reference":measurement_root/".reference/openclaw",
                "--node":Path(launch["argv"][5]),
                "--release-runtime":measurement_root/".reference/release-runtime"}
    require(set(options) == set(expected) | {"--output"} and
            all(Path(options[k]) == path for k,path in expected.items()),
            "The supplemental assessor did not use every original authenticated input under its canonical path")
    output = Path(options["--output"])
    require(output.is_absolute() and output.name == "assessment.json" and
            not output.is_relative_to(measurement_root/".equivalence-results"),
            "Supplement attempted to replace original measurement evidence")


def check_resume(review, original, launch, root, head):
    measurement_root = Path(launch["cwd"])
    cmd = review["argv"]
    require(review["assessorInvocation"] == "in-process" and isinstance(cmd, list) and len(cmd) == 2
            and Path(cmd[0]).parent == measurement_root/".venv/bin" and Path(cmd[0]).name in {"python","python3"}
            and measurement_root/Path(cmd[1]) == measurement_root/WRAPPER
            and review["assessorArgv"][0] == cmd[0], "Wrong wrapper or frozen assessor invocation")
    check_argv(review["assessorArgv"], measurement_root, launch)
    sources = {n: hashlib.sha256(subprocess.check_output(
        ["git", "-C", str(root), "show", f"{head}:.github/scripts/{n}"])).hexdigest() for n in sorted(REVIEW_FILES)}
    require(review["sourceSha256"] == sources and review["archiveAdapters"] == ADAPTERS,
            "Different reviewed source or archive adapters")
    groups = {k:[r["id"] for r in original[k]] for k in sorted(EARLIER_REPLAYS)}
    require(sum(map(len,groups.values())) == 47 and review["reusedOriginalStages"] == groups
            and all(r["validated"] is True and r["publicMatch"] is True for k in groups for r in original[k]),
            "Missing, reordered or unsuccessful original protected replay")
    restoration = review["restoration"]
    require(restoration["runId"] == ORIGINAL_RUN and restoration["comparisonCommit"] == ORIGINAL_HEAD
            and restoration["restorationView"] == "complete" and restoration["artifactId"] == RAW["id"]
            and restoration["archive"] == {k:RAW[k] for k in ("bytes","sha256")}
            and restoration["fullReport"] == REPORT and restoration["summaryArtifact"] == SUMMARY,
            "Restoration is not bound to the identified complete original archive and summary")
    roots = restoration["restoredRoots"]
    required = {str(measurement_root/".equivalence-results")}
    require(isinstance(roots,list) and roots == sorted(set(roots)) and required < set(roots)
            and all(re.fullmatch(r"/var/tmp/memory-host-v4-[a-z0-9_]{8}", p) for p in set(roots)-required)
            and all(type(restoration[k]) is int for k in ("restoredBytes","restoredFiles","zipEntries"))
            and restoration["zipEntries"] >= restoration["restoredFiles"] > 9 and restoration["restoredBytes"] > REPORT["bytes"],
            "Restored original physical roots, files or sizes are missing")
    return {"reusedOriginalStages":groups, "reviewedSourceSha256":sources, "archiveAdapters":ADAPTERS,
            "assessorInvocation":"in-process", "boundedFrozenAssessorReplays":True}


def archive_flush(initial, fresh):
    from equivalence import flush_plan_target
    from equivalence.flush_plan_target_evidence import seed_tree
    checked = {r["id"]: r for r in initial["projection"]["cases"]}
    rows = fresh["appendedFamilyReplays"][flush_plan_target.OPERATION]["cases"]
    definitions = flush_plan_target.build_cases()
    require([r["id"] for r in rows] == [r["id"] for r in definitions], "Restored flush case inventory")
    summary = {"verifiedCasePairs":len(rows), "archivedFileReopens":0, "emptyDirectoriesFromOriginalCapture":0,
               "emptyRootsFromOriginalCapture":0}
    for case,row in zip(definitions,rows,strict=True):
        sides = row["archivedWorkspace"]
        require(checked[row["id"]]["status"] == "matched" and checked[row["id"]]["runtimeEvidenceValidated"] is True
                and row["validated"] is True and row["publicMatch"] is True and set(sides) == {"native","python"},
                "Restored flush workspaces are not bound to the original complete protected pair")
        seed = seed_tree(case["input"])
        seeded_directories = {p for p,v in seed.items() if v == {"kind":"directory"}}
        for side,witness in sides.items():
            dirs = witness["emptyDirectoriesFromOriginalCapture"]
            original_root = witness["workspaceRootFromOriginalCapture"]
            require(valid_hash(witness["archivedTreeSha256"]) and type(witness["filesReopened"]) is int
                    and witness["filesReopened"] >= len(case["input"]["files"]) and type(original_root) is bool
                    and isinstance(dirs,list) and dirs == sorted(set(dirs))
                    and set(dirs) <= seeded_directories | ({"workspace","user"} if side == "python" else set()),
                    "Invalid original empty directories or archived flush file evidence")
            if original_root:
                require(side == "native" and witness["filesReopened"] == 0
                        and (case["input"]["flush"].get("enabled") is False or case["input"]["directories"]),
                        "A nonempty flush workspace was replaced by an inferred empty root")
            summary["archivedFileReopens"] += witness["filesReopened"]
            summary["emptyDirectoriesFromOriginalCapture"] += len(dirs)
            summary["emptyRootsFromOriginalCapture"] += original_root
    return summary


def review_changed_f14(directory, previous, current):
    require(previous == {"openclaw":F14_NATIVE, "python":F14_SDK[0]} and current == {"openclaw":F14_NATIVE, "python":F14_SDK[1]},
            "Changed control case does not match both authenticated original result pairs")
    values = []
    for label, sha in zip(("before","after"), F14_SDK, strict=True):
        path = directory/label/"single/public.json"
        v = read(path)
        require(file_sha(path) == sha and hashlib.sha256(canonical(v)).hexdigest() == sha
                and v["queries"] == [{"candidates":[], "label":"rank"}], "Whole reproduced SDK case differs")
        values.append(v)
    before, after = values
    require(before == after, "SDK JSON value differs semantically")
    leaves = []
    for key in ("before","after"):
        original = before[key]["recall"]["entries"]["malformed-trust"]["provenance"]
        changed = after[key]["recall"]["entries"]["malformed-trust"]["provenance"]
        require(type(original["observedAt"]) is int and type(changed["observedAt"]) is float
                and original["observedAt"] == changed["observedAt"] == 1775210460000,
                "Timestamp representation does not match reproduced case")
        changed["observedAt"] = original["observedAt"]
        leaves.append("/"+key+"/recall/entries/malformed-trust/provenance/observedAt")
    require(canonical(before) == canonical(after), "Changed serialized SDK value outside the two timestamps")
    return {"caseId":F14,"condition":"promotion.ranking-gates.boundaries","matched":False,"pointsAwarded":0,
            "nativeSha256":F14_NATIVE,"sdkBeforeSha256":F14_SDK[0],"sdkAfterSha256":F14_SDK[1],
            "candidateLists":[[],[]],"changedNumberSpellings":leaves,"timestamp":1775210460000,
            "entireSdkJsonNumericallyEqual":True}


def verify_supplement(args, original_folder, remote, original, root):
    require(args.run_id == ORIGINAL_RUN and args.head == ORIGINAL_HEAD and remote == SUMMARY,
            "This supplemental review is bound to the single original 1,623-case measurement")
    folder = args.supplement.resolve(strict=True)
    require(folder != original_folder and args.supplement_run_id != ORIGINAL_RUN and args.supplement_head != ORIGINAL_HEAD
            and bool(re.fullmatch("[0-9a-f]{40}", args.supplement_head)), "Supplement needs a distinct workflow run")
    later = artifact(folder, args.supplement_run_id, args.supplement_head, args.supplement_sha256,
                     artifact_name="memory-contract-remainder-reviewed-summary", files=SUPPLEMENT_FILES)
    require(later["id"] != SUMMARY["id"], "Supplement is not a separate Actions artifact")
    fresh = read(folder/"assessment.json")
    final_refusal = args.f14_reproduction is not None
    if final_refusal:
        require(args.supplement_run_id == 44232754070 and args.supplement_head == "38c686d13ef7a9a88aa9e73ee226946d9bd252f0"
                and later == {"id":14396301086,"bytes":79295,
                              "sha256":"ca5a68d2e184581b6f96840a67e22acdc8604cffece2c93f7924822333794512"}
                and file_sha(folder/"assessment.json") == "d961593a75225564e4314fede091bca759e57011b34e5a5b2d22faf66f7f814a"
                and file_sha(folder/"replay-receipt.json") == "cecb23bfb0afc6dfa153461c7603f92ba1a1a0be78bbb681645f28e6e5fe0cc8",
                "Independent F14 disposition requires the identified actual second refusal")
    verified_earlier(original, fresh, original_folder, final_refusal)
    receipt = read(folder/"replay-receipt.json")
    measured, review = receipt["original"], receipt["review"]
    require(receipt["kind"] == "retained-measurement-assessment"
            and receipt["fullComparisonExecuted"] is False and receipt["boundedFrozenAssessorReplays"] is True
            and measured["runId"] == ORIGINAL_RUN and measured["head"] == ORIGINAL_HEAD
            and measured["summaryArtifact"] == SUMMARY and measured["report"] == REPORT,
            "The supplemental receipt identifies a different measurement")
    original_hashes = {n:file_sha(original_folder/n) for n in FILES}
    require(measured["summaryFiles"] == original_hashes and measured["comparisonReturnCode"] == 1
            and measured["assessorSha256"] == file_sha(root/REVIEW_PROGRAM) == ORIGINAL_ASSESSOR,
            "Original summary, genuine process exit or actual assessor source was replaced")
    launch = read(original_folder/"launch.json")
    exit_record = read(original_folder/"os-exit.json")
    require(launch["automaticRetry"] is False and exit_record["actualReturnCode"] == 1
            and exit_record["elapsedSeconds"] == 5499.128818286999 and
            exit_record["fullReportSha256"] == REPORT["sha256"], "Original process record changed")
    require(review["runId"] == args.supplement_run_id and review["head"] == args.supplement_head
            and type(review["assessorReturnCode"]) is int and review["assessorReturnCode"] == (2 if final_refusal else 0)
            and review["assessmentSha256"] == file_sha(folder/"assessment.json"),
            "Supplement assessor exit or result bytes differ")
    resume = check_resume(review, original, launch, root, args.supplement_head)
    archived = archive_workspaces(original, fresh)
    flush = archive_flush(original, fresh)
    raw = measured["rawArtifact"]
    require(raw == RAW, "Original retained raw archive ID, exact bytes or digest differ")
    extra = {}
    if final_refusal:
        difference = fresh["previousMismatchPublicHashChanges"][F14]
        extra = {"independentFinalDisposition":review_changed_f14(args.f14_reproduction, difference["before"], difference["after"]),
                 "supplementalAssessmentStatus":"blocked","supplementalAssessorReturnCode":2,
                 "supplementalAssessmentErrors":FINAL_REFUSAL, "supplementalCandidateScore":None,
                 "originalAndSupplementalHostedPointsAwarded":[0,0],
                 "supplementalMeasurementSourceAtStartChecked":True,"supplementalFinalTrackedSourceCheckReached":False,
                 "originalReportAndNineFilesCheckedAtSupplementEnd":True}
    return fresh, {**resume,**extra,"runId":args.supplement_run_id,"head":args.supplement_head,"remoteSummary":later,
                   "assessmentSha256":review["assessmentSha256"],"receiptSha256":file_sha(folder/"replay-receipt.json"),
                   "localAttachmentValidatorSha256":file_sha(Path(__file__)),
                   "originalAssessmentStatus":"blocked","originalAssessmentSha256":ORIGINAL_ASSESSMENT,
                   "rawArtifact":raw,"originalProgramSha256":ORIGINAL_ASSESSOR,
                   "recoveryReferenceModes":review["recoveryReferenceModes"],
                   "archiveWorkspaceEvidence":archived,"archiveFlushEvidence":flush,"restoration":review["restoration"],"sourceOriginalSummarySha256":SUMMARY["sha256"],
                   "fullComparisonExecuted":False}
