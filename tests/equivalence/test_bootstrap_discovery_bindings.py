"""Static authority guards; labelled declarations never prove Native execution."""
from copy import deepcopy
import hashlib
import pytest

from equivalence import bootstrap_discovery_bindings as bindings


# Independent frozen original edges. The labelled fixture below is deliberately
# non-executing and tests the authority parser, not bootstrap business behavior.
_EXPECTED_LINKS = (('src/agents/workspace.ts',
  './workspace-bootstrap-publish.js',
  ('publishAgentInstructions', 'publishBootstrapFile'),
  'import'),
 ('src/agents/workspace.ts',
  './workspace-bootstrap-policy.js',
  ('WORKSPACE_BOOTSTRAP_FILENAMES', 'resolveWorkspaceBootstrapPath'),
  'import'),
 ('src/agents/workspace.ts',
  './workspace-file-read.js',
  ('readWorkspaceFileWithGuards', 'setWorkspaceFileSourceIdentity'),
  'import'),
 ('src/agents/workspace.ts',
  './workspace-state-store.js',
  ('readWorkspaceStateSnapshot', 'mergeWorkspaceSetupState', 'replaceWorkspaceAttestation'),
  'import'),
 ('src/agents/workspace.ts',
  './workspace-templates.js',
  ('resolveWorkspaceTemplateSearchDirs',),
  'import'),
 ('src/agents/workspace.ts',
  '../routing/session-key.js',
  ('isCronSessionKey', 'isSubagentSessionKey'),
  'import'),
 ('src/agents/workspace.ts',
  '../sessions/session-chat-type-shared.js',
  ('deriveSessionChatTypeFromKey',),
  'import'),
 ('src/agents/workspace.ts',
  '../../packages/markdown-core/src/frontmatter.js',
  ('extractFrontmatterBlock',),
  'import'),
 ('src/agents/workspace-file-read.ts',
  './workspace-bootstrap-read.js',
  ('readWorkspaceBootstrapFile', 'MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES'),
  'import'),
 ('src/agents/workspace-file-read.ts',
  './workspace-file-cache.js',
  ('readWorkspaceFileCache', 'writeWorkspaceFileCache'),
  'import'),
 ('src/agents/workspace-file-read.ts',
  '../infra/boundary-file-read.js',
  ('openRootFile',),
  'import'),
 ('src/agents/workspace-bootstrap-read.ts',
  '../infra/boundary-file-read.js',
  ('readFileDescriptorBounded',),
  'import'),
 ('src/agents/workspace-templates.ts',
  '../infra/openclaw-root.js',
  ('resolveOpenClawPackageRoot',),
  'import'),
 ('src/agents/workspace-state-store.ts',
  './workspace-state-store.kernel.js',
  ('readWorkspaceStateSnapshotFromDatabase', 'resolveWorkspaceIdentityFromDatabase'),
  'import'),
 ('src/agents/workspace-state-store.ts',
  '../state/openclaw-state-db.js',
  ('openOpenClawStateDatabase', 'runOpenClawStateWriteTransaction'),
  'import'),
 ('src/agents/bootstrap-files.ts',
  './workspace.js',
  ('loadWorkspaceBootstrapFiles',
   'filterBootstrapFilesForSession',
   'isWorkspaceSetupCompleted',
   'workspaceFilesShareSourceIdentity'),
  'import'),
 ('src/agents/bootstrap-files.ts', './bootstrap-cache.js', ('getOrLoadBootstrapFiles',), 'import'),
 ('src/agents/bootstrap-files.ts',
  './bootstrap-hooks.js',
  ('applyBootstrapHookOverrides',),
  'import'),
 ('src/agents/bootstrap-files.ts',
  './workspace-personal-bootstrap.js',
  ('loadPersonalUserBootstrapFile',),
  'import'),
 ('src/agents/bootstrap-files.ts',
  '../plugins/memory-runtime.js',
  ('classifyActiveMemoryWorkspacePaths',),
  'import'),
 ('src/agents/bootstrap-hooks.ts',
  '../hooks/internal-hooks.js',
  ('createInternalHookEvent', 'triggerInternalHook'),
  'import'),
 ('src/agents/bootstrap-cache.ts',
  './workspace.js',
  ('loadWorkspaceBootstrapFiles', 'workspaceFileSourceIdentitiesMatch'),
  'import'),
 ('src/agents/bootstrap-files.ts', '../memory-host-sdk/host/types.js', ('isMemoryOriginEligibleForAutomaticInjection',), 'import'),
 ('extensions/memory-core/src/workspace-path-classifier.ts', './memory/memory-path-provenance.js', ('resolveMemoryPathClassification',), 'import'),
 ('extensions/memory-core/src/memory/memory-path-provenance.ts', 'openclaw/plugin-sdk/memory-core-host-runtime-core', ('readMemoryArtifactProvenance',), 'import'),
 ('src/plugin-sdk/memory-core-host-runtime-core.ts', '../memory/memory-artifact-provenance.js', ('readMemoryArtifactProvenance', 'listMemoryArtifactProvenance'), 'export'),
 ('src/memory/memory-artifact-provenance.ts', '../plugin-state/plugin-state-store.js', ('createCorePluginStateKeyedStore',), 'import'),
 ('src/plugins/memory-runtime.ts', './config-state.js', ('normalizePluginsConfig',), 'import'),
 ('src/plugins/config-state.ts', './config-normalization-shared.js', ('normalizePluginsConfigWithResolverCore',), 'import'),
 ('src/plugins/config-normalization-shared.ts', './slots.js', ('normalizeSlotValue', 'resolveSlotSelection'), 'import'))


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def owner_trees(tmp_path, monkeypatch):
    source, runtime = tmp_path / "source", tmp_path / "runtime"
    source.mkdir()
    runtime.mkdir()
    source_bytes, compiled_bytes = {}, {}
    for relative, anchors in bindings.SOURCE_ANCHORS.items():
        declarations = [f"{kind} {{ {', '.join(names)} }} from {specifier!r};"
                        for module, specifier, names, kind in _EXPECTED_LINKS if module == relative]
        raw = ("// Labelled non-executing declaration fixture.\n" + "\n".join([*declarations, *anchors]) + "\n").encode()
        source_bytes[relative] = raw
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    for relative, anchors in bindings.COMPILED_ANCHORS.items():
        declarations = [declaration for module, declaration in bindings.COMPILED_LINKS if module == relative]
        raw = ("// Labelled non-executing release declaration fixture.\n" + "\n".join(dict.fromkeys([*declarations, *anchors])) + "\n").encode()
        compiled_bytes[relative] = raw
        path = runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    templates = deepcopy(bindings.TEMPLATE_ARTIFACTS)
    for name, item in templates.items():
        raw = ("Literal labelled template bytes: " + name + "\n").encode()
        for root, relative in ((runtime, item["path"]), (source, item["sourcePath"])):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        source_bytes[item["sourcePath"]] = raw
        item.update(bytes=len(raw), sha256=_sha(raw), sourceSha256=_sha(raw))
    monkeypatch.setattr(bindings, "SOURCE_HASHES", {name: _sha(raw) for name, raw in source_bytes.items()
                                                   if name in bindings.SOURCE_ANCHORS})
    monkeypatch.setattr(bindings, "COMPILED_HASHES", {name: _sha(raw) for name, raw in compiled_bytes.items()})
    monkeypatch.setattr(bindings, "TEMPLATE_ARTIFACTS", templates)
    state = {"commit": bindings.REFERENCE_COMMIT, "dirty": False, "committed": dict(source_bytes), "top": source}

    def git(checkout, *args):
        assert checkout == source
        if args == ("rev-parse", "HEAD"):
            return (state["commit"] + "\n").encode()
        if args == ("rev-parse", "--show-toplevel"):
            return (str(state["top"]) + "\n").encode()
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return b" M changed.ts\n" if state["dirty"] else b""
        if len(args) == 2 and args[0] == "show" and args[1].startswith("HEAD:"):
            return state["committed"][args[1][5:]]
        raise AssertionError(args)

    monkeypatch.setattr(bindings, "_git", git)
    return source, runtime, state


def _prepare(trees):
    source, runtime, _ = trees
    return bindings.prepare_bootstrap_discovery_bindings(source, runtime)


def test_reviewed_graph_and_three_original_exports_remain_explicit():
    assert (len(bindings.SOURCE_HASHES), len(bindings.COMPILED_HASHES), len(bindings.SOURCE_LINKS),
            len(bindings.COMPILED_LINKS)) == (40, 30, 30, 19)
    assert bindings.SOURCE_LINKS == _EXPECTED_LINKS
    assert bindings.CANONICAL_BOOTSTRAP_FILES == ("AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "BOOTSTRAP.md", "MEMORY.md")
    assert "src/agents/workspace-bootstrap-publish.ts" in bindings.SOURCE_HASHES
    assert "src/agents/workspace-file-read.ts" in bindings.SOURCE_HASHES
    assert "src/state/openclaw-state-db-cache.ts" in bindings.SOURCE_HASHES
    assert set(bindings.TEMPLATE_ARTIFACTS) == {"AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "BOOTSTRAP.md"}


def test_binding_retains_complete_owners_and_templates_without_claiming_execution(owner_trees):
    result = _prepare(owner_trees)
    assert (len(result["sourceBindings"]), len(result["compiledBindings"])) == (40, 30)
    assert result["sourceBuildReproduced"] is False and result["sourceFallbackAllowed"] is False
    assert result["covers"] == [] and result["fullWorkspaceLifecycleEquivalenceClaimed"] is False
    assert result["entrypoints"] == {
        "ensure": {"path": "dist/workspace-C0LMBmap.mjs", "export": "t", "sourceExport": "ensureAgentWorkspace"},
        "load": {"path": "dist/workspace-C0LMBmap.mjs", "export": "s", "sourceExport": "loadWorkspaceBootstrapFiles"},
        "resolve": {"path": "dist/bootstrap-files-CgqY-7GK.mjs", "export": "c", "sourceExport": "resolveBootstrapFilesForRun"},
    }
    assert result["stateEntrypoints"]["close"] == {"path": "dist/openclaw-state-db-cache-IdIaBoUp.mjs", "export": "a"}
    assert result["conditionalCompiledArtifacts"] == {
        "configuredAutomaticMemoryClassification": ["dist/memory-runtime-BzdCLKPx.mjs",
            "dist/extensions/memory-core/index.js", "dist/workspace-path-classifier-nZNRErpg.mjs",
            "dist/workspace-path-classifier-279hOw9K.mjs", "dist/memory-path-provenance-C84vBRrO.mjs",
            "dist/memory-artifact-provenance-DhnyWiV1.mjs", "dist/plugin-state-store-BPUaLoVD.mjs"]}
    assert "dist/memory-runtime-BzdCLKPx.mjs" not in result["requiredCompiledArtifacts"]
    for template in result["templateArtifacts"].values():
        assert set(template) == {"path", "bytes", "sha256", "sourcePath", "sourceSha256"}
        assert template["sha256"] == template["sourceSha256"]
    assert {"thirdPartyRegisteredMemoryRuntime", "remoteWorkspaceAccess"} <= set(result["branchCoverageNotClaimed"])
    assert "dist/plugin-sdk/memory-core-host-runtime-core.js" not in result["requiredCompiledArtifacts"]
    assert "dist/plugin-sdk/memory-core-host-runtime-core.js" not in result["conditionalCompiledArtifacts"]["configuredAutomaticMemoryClassification"]


@pytest.mark.parametrize("failure", ("pin", "dirty", "root"))
def test_wrong_pin_dirty_source_or_wrong_root_never_gets_authority(owner_trees, failure):
    source, _, state = owner_trees
    if failure == "pin":
        state["commit"] = "0" * 40
    elif failure == "dirty":
        state["dirty"] = True
    else:
        state["top"] = source.parent
    with pytest.raises(bindings.BootstrapDiscoveryBindingError, match="unchanged pinned"):
        _prepare(owner_trees)


@pytest.mark.parametrize("relative", tuple(bindings.SOURCE_HASHES))
def test_every_source_owner_rejects_changed_working_bytes(owner_trees, relative):
    source, _, _ = owner_trees
    path = source / relative
    path.write_bytes(path.read_bytes() + b"// unreviewed source change\n")
    with pytest.raises(bindings.BootstrapDiscoveryBindingError, match="pinned bytes"):
        _prepare(owner_trees)


@pytest.mark.parametrize("relative", tuple(bindings.COMPILED_HASHES))
def test_every_release_owner_rejects_changed_compiled_bytes(owner_trees, relative):
    _, runtime, _ = owner_trees
    path = runtime / relative
    path.write_bytes(path.read_bytes() + b"// unreviewed compiled change\n")
    with pytest.raises(bindings.BootstrapDiscoveryBindingError, match="pinned bytes"):
        _prepare(owner_trees)


def test_committed_source_bytes_are_verified_independently(owner_trees):
    _, _, state = owner_trees
    state["committed"]["src/agents/workspace.ts"] += b"// other Git version\n"
    with pytest.raises(bindings.BootstrapDiscoveryBindingError, match="pinned bytes"):
        _prepare(owner_trees)


@pytest.mark.parametrize("edge", _EXPECTED_LINKS)
def test_each_real_source_edge_is_required_even_when_hashes_match(owner_trees, monkeypatch, edge):
    source, _, state = owner_trees
    module, specifier, names, kind = edge
    declaration = f"{kind} {{ {', '.join(names)} }} from {specifier!r};"
    path = source / module
    raw = path.read_bytes().replace(declaration.encode(), b"// removed named owner edge")
    path.write_bytes(raw)
    state["committed"][module] = raw
    monkeypatch.setitem(bindings.SOURCE_HASHES, module, _sha(raw))
    with pytest.raises(bindings.BootstrapDiscoveryBindingError):
        _prepare(owner_trees)


@pytest.mark.parametrize("edge", bindings.COMPILED_LINKS)
def test_each_real_compiled_edge_is_required_even_when_hashes_match(owner_trees, monkeypatch, edge):
    _, runtime, _ = owner_trees
    module, declaration = edge
    path = runtime / module
    raw = path.read_bytes().replace(declaration.encode(), b"// removed compiled owner edge")
    path.write_bytes(raw)
    monkeypatch.setitem(bindings.COMPILED_HASHES, module, _sha(raw))
    with pytest.raises(bindings.BootstrapDiscoveryBindingError, match="compiled bootstrap import"):
        _prepare(owner_trees)


@pytest.mark.parametrize("side", ("source", "runtime"))
@pytest.mark.parametrize("name", ("AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "BOOTSTRAP.md"))
def test_each_literal_template_is_authenticated_on_both_sides(owner_trees, name, side):
    source, runtime, _ = owner_trees
    expected = bindings.TEMPLATE_ARTIFACTS[name]
    path = (source if side == "source" else runtime) / expected["sourcePath" if side == "source" else "path"]
    path.write_bytes(path.read_bytes() + b"changed literal bytes")
    with pytest.raises(bindings.BootstrapDiscoveryBindingError, match="pinned bytes"):
        _prepare(owner_trees)


def test_template_source_commit_is_checked_too(owner_trees):
    _, _, state = owner_trees
    state["committed"][bindings.TEMPLATE_ARTIFACTS["USER.md"]["sourcePath"]] += b"different source template"
    with pytest.raises(bindings.BootstrapDiscoveryBindingError, match="pinned bytes"):
        _prepare(owner_trees)


def test_matching_separate_hashes_do_not_make_different_template_bytes_equal(owner_trees, monkeypatch):
    source, _, state = owner_trees
    expected = bindings.TEMPLATE_ARTIFACTS["BOOTSTRAP.md"]
    raw = (source / expected["sourcePath"]).read_bytes().replace(b"Literal", b"Mutant")
    (source / expected["sourcePath"]).write_bytes(raw)
    state["committed"][expected["sourcePath"]] = raw
    monkeypatch.setitem(expected, "sourceSha256", _sha(raw))
    with pytest.raises(bindings.BootstrapDiscoveryBindingError, match="packaged literal"):
        _prepare(owner_trees)


def test_owner_symlinks_cannot_borrow_reviewed_bytes(owner_trees):
    source, _, _ = owner_trees
    path = source / "src/agents/workspace.ts"
    target = source / "other-owner.ts"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(bindings.BootstrapDiscoveryBindingError, match="escaped"):
        _prepare(owner_trees)


def test_duplicate_reviewed_anchor_is_rejected_after_hash_validation(owner_trees, monkeypatch):
    source, _, state = owner_trees
    relative = "src/agents/workspace.ts"
    path = source / relative
    raw = path.read_bytes() + bindings.SOURCE_ANCHORS[relative][0].encode() + b"\n"
    path.write_bytes(raw)
    state["committed"][relative] = raw
    monkeypatch.setitem(bindings.SOURCE_HASHES, relative, _sha(raw))
    with pytest.raises(bindings.BootstrapDiscoveryBindingError, match="unique reviewed"):
        _prepare(owner_trees)
