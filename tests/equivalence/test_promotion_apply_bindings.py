"""Static owner/alias guard challenges; labelled files are never native evidence."""
import hashlib

import pytest

from equivalence import promotion_apply_bindings as bindings
from equivalence import promotion_ranking_bindings as ranking
from equivalence import session_admission_runtime_bindings as owner_guards


@pytest.fixture
def owners(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    runtime = tmp_path / "installation/node_modules/openclaw"
    checkout.mkdir()
    runtime.mkdir(parents=True)
    declarations = {}
    for module, specifier, names, kind in bindings.SOURCE_LINKS:
        declarations.setdefault(module, []).append(
            kind + " {\n  " + ",\n  ".join(names) + '\n} from "' + specifier + '";')

    def populate(root, anchors, links=None):
        hashes = {}
        for relative, needles in anchors.items():
            parts = ["// Labelled static guard fixture; never executed.",
                     *(links or {}).get(relative, ())]
            for needle in sorted(needles, key=len, reverse=True):
                if needle not in "\n".join(parts):
                    parts.append(needle)
            filename = root / relative
            filename.parent.mkdir(parents=True, exist_ok=True)
            raw = ("\n".join(parts) + "\n").encode()
            filename.write_bytes(raw)
            hashes[relative] = hashlib.sha256(raw).hexdigest()
        return hashes

    source_hashes = populate(checkout, bindings.SOURCE_ANCHORS, declarations)
    compiled_hashes = populate(runtime, bindings.COMPILED_ANCHORS)
    monkeypatch.setattr(bindings, "SOURCE_HASHES", source_hashes)
    monkeypatch.setattr(bindings, "COMPILED_HASHES", compiled_hashes)
    native_hashes = {}
    for package, relative in bindings.NATIVE_ARTIFACTS:
        filename = runtime.parent.parent / package / relative
        filename.parent.mkdir(parents=True, exist_ok=True)
        raw = b"Labelled nonexecutable native-artifact guard fixture.\n"
        filename.write_bytes(raw)
        native_hashes[package, relative] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(bindings, "NATIVE_ARTIFACTS", native_hashes)

    def git(root, *args):
        if args == ("rev-parse", "HEAD"):
            return bindings.REFERENCE_COMMIT.encode()
        assert args[0] == "show" and args[1].startswith("HEAD:")
        return (root / args[1][5:]).read_bytes()

    monkeypatch.setattr(bindings, "_git", git)
    monkeypatch.setattr(owner_guards, "_git", git)
    return checkout, runtime


def test_manifest_keeps_real_aliases_and_exact_existing_worker_route(owners):
    result = bindings.prepare_promotion_apply_bindings(*owners)
    assert bindings.PROMOTION_APPLY_OPERATION == "promotion-apply-reconcile-runtime"
    assert result["applyEntrypoint"] == {
        "path": "dist/short-term-promotion-MX1vHJuE.mjs", "export": "a"}
    assert result["storeEntrypoints"] == {
        "path": "dist/short-term-promotion-store-B6T388Bo.mjs", "readRecall": "a", "writeRecall": "l"}
    factory = result["factoryEntrypoints"]
    assert factory["configure"]["export"] == "p" and factory["keyed"]["export"] == "r"
    assert factory["close"]["export"] == "u" and factory["provenanceKeyed"]["export"] == "t"
    assert result["eventReadEntrypoint"] == {
        "path": "dist/memory-host-events-C8-U38f1.mjs", "export": "n"}
    assert result["databasePathEntrypoint"] == {
        "path": "dist/openclaw-state-db.paths-rJI64Ab5.mjs", "export": "s"}
    assert result["requiredWorkerRoute"] == list(ranking.PROMOTION_WORKER_ROUTE)
    assert bindings.REQUIRED_WORKER_ARTIFACTS == ranking.PROMOTION_WORKER_ROUTE
    assert result["workerImportsRequired"] is True
    assert result["workspaceLeaseEntrypoint"]["namespace"] == "short-term-locks"
    assert result["workspaceLeaseEntrypoint"]["initialReadRequired"] is True
    assert result["promotionFileLockEntrypoint"]["reachedAfterZeroRehydratedReturn"] is False
    assert result["sourceAliasLink"]["declaration"] == bindings.SOURCE_ALIAS_DECLARATION
    assert result["sourceAliasLink"]["line"] > 0
    assert result["clock"] == {"owner": "node:test", "apis": ["Date"], "schedulerReplaced": False}
    assert result["covers"] == [] and result["acceptancePointsAwarded"] == 0
    for key in ("sourceBuildReproduced", "sourceFallbackAllowed", "providerConstructed",
                "managerConstructed", "lockEquivalenceClaimed", "publicationOrderingClaimed"):
        assert result[key] is False


def test_authenticated_public_barrel_does_not_claim_execution(owners):
    result = bindings.prepare_promotion_apply_bindings(*owners)
    public = result["factoryEntrypoints"]["publicKeyed"]
    assert public["export"] == "createPluginStateKeyedStore"
    assert public["executionRequired"] is False
    assert public["path"] in {row["path"] for row in result["compiledBindings"]}
    assert public["path"] not in result["requiredLoadedArtifacts"]
    assert set(bindings.PROMOTION_WORKER_ROUTE) <= set(result["requiredLoadedArtifacts"])
    result["requiredWorkerRoute"].append("unreviewed-worker")
    result["factoryEntrypoints"]["keyed"]["export"] = "changed"
    again = bindings.prepare_promotion_apply_bindings(*owners)
    assert again["requiredWorkerRoute"] == list(ranking.PROMOTION_WORKER_ROUTE)
    assert again["factoryEntrypoints"]["keyed"]["export"] == "r"


@pytest.mark.parametrize("relative", (
    "extensions/memory-core/src/short-term-promotion-apply.ts",
    "extensions/memory-core/src/memory-workspace-lock.ts",
    "src/memory/memory-artifact-provenance.ts",
    "src/plugin-state/plugin-state-store.ts",
    "src/state/openclaw-state-worker-store.ts",
))
def test_changed_original_source_owner_is_rejected(owners, relative):
    checkout, _ = owners
    filename = checkout / relative
    filename.write_bytes(filename.read_bytes() + b"// drift\n")
    with pytest.raises(ValueError, match="reviewed bytes"):
        bindings.prepare_promotion_apply_bindings(*owners)


@pytest.mark.parametrize("relative", (
    "dist/short-term-promotion-MX1vHJuE.mjs",
    "dist/memory-artifact-provenance-DhnyWiV1.mjs",
    "dist/dreaming-dreams-file-BJzlZFlf.mjs",
    "dist/plugin-state-store-BPUaLoVD.mjs",
    "dist/plugin-sdk/plugin-state-store-runtime.js",
    *bindings.PROMOTION_WORKER_ROUTE,
))
def test_changed_published_owner_or_worker_is_rejected(owners, relative):
    _, runtime = owners
    filename = runtime / relative
    filename.write_bytes(filename.read_bytes() + b"// drift\n")
    with pytest.raises(ValueError, match="reviewed bytes"):
        bindings.prepare_promotion_apply_bindings(*owners)


@pytest.mark.parametrize("relative,old,new", (
    ("dist/short-term-promotion-MX1vHJuE.mjs", "applyShortTermPromotions as a", "applyShortTermPromotions as z"),
    ("dist/short-term-promotion-store-B6T388Bo.mjs", "readStore as a", "readStore as z"),
    ("dist/plugin-state-store-BPUaLoVD.mjs", "createCorePluginStateKeyedStore as t", "createCorePluginStateKeyedStore as z"),
    ("dist/memory-host-events-C8-U38f1.mjs", "readMemoryHostEventRecords as n", "readMemoryHostEventRecords as z"),
))
def test_changed_alias_cannot_be_approved_by_only_replacing_its_hash(owners, monkeypatch, relative, old, new):
    _, runtime = owners
    filename = runtime / relative
    filename.write_text(filename.read_text().replace(old, new))
    monkeypatch.setitem(bindings.COMPILED_HASHES, relative, hashlib.sha256(filename.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="unique reviewed linkage"):
        bindings.prepare_promotion_apply_bindings(*owners)


def test_initial_provenance_cannot_borrow_a_different_source_import(owners, monkeypatch):
    checkout, _ = owners
    relative = "src/memory/memory-artifact-provenance.ts"
    filename = checkout / relative
    filename.write_text(filename.read_text().replace('../plugin-state/plugin-state-store.js', '../unreviewed.js'))
    monkeypatch.setitem(bindings.SOURCE_HASHES, relative, hashlib.sha256(filename.read_bytes()).hexdigest())
    with pytest.raises(ValueError):
        bindings.prepare_promotion_apply_bindings(*owners)


@pytest.mark.parametrize("alias", ("source-leaf", "compiled-leaf", "parent", "hardlink", "runtime-root"))
def test_owner_path_aliases_cannot_inherit_authority(owners, tmp_path, alias):
    checkout, runtime = owners
    filename = runtime / "dist/memory-artifact-provenance-DhnyWiV1.mjs"
    if alias == "source-leaf":
        filename = checkout / "src/memory/memory-artifact-provenance.ts"
    if alias in {"source-leaf", "compiled-leaf"}:
        copied = tmp_path / "copied"
        copied.write_bytes(filename.read_bytes())
        filename.unlink()
        filename.symlink_to(copied)
    elif alias == "parent":
        original = runtime / "dist"
        moved = runtime / "moved"
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
    elif alias == "hardlink":
        (tmp_path / "alias").hardlink_to(filename)
    else:
        linked = tmp_path / "runtime-alias"
        linked.symlink_to(runtime, target_is_directory=True)
        runtime = linked
    with pytest.raises(ValueError):
        bindings.prepare_promotion_apply_bindings(checkout, runtime)


def test_wrong_reference_commit_and_changed_committed_source_are_rejected(owners, monkeypatch):
    monkeypatch.setattr(bindings, "_git", lambda *_: b"unreviewed")
    with pytest.raises(ValueError, match="pinned source commit"):
        bindings.prepare_promotion_apply_bindings(*owners)
    monkeypatch.setattr(bindings, "_git", lambda *_: bindings.REFERENCE_COMMIT.encode())
    monkeypatch.setattr(owner_guards, "_git", lambda *_: b"different committed bytes")
    with pytest.raises(ValueError, match="reviewed bytes"):
        bindings.prepare_promotion_apply_bindings(*owners)


def test_native_artifact_hash_is_checked_without_loading_it(owners):
    _, runtime = owners
    package, relative = next(iter(bindings.NATIVE_ARTIFACTS))
    filename = runtime.parent.parent / package / relative
    filename.write_bytes(b"changed nonexecutable fixture")
    with pytest.raises(ValueError, match="native artifact changed"):
        bindings.prepare_promotion_apply_bindings(*owners)
