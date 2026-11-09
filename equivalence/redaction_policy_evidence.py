"""Exact source identity and complete ordinary source-policy transport guards."""
from __future__ import annotations

from pathlib import Path

from equivalence.reference_bindings import _git
from equivalence.search_contract import _same_json
from equivalence.session_admission_runtime_bindings import _named_link, _owners


REFERENCE_COMMIT = "bcfc88812a35243893585dbeca87ca41b48272ca"
SOURCE_HASHES = {'src/logging/redact.ts': 'ecdfdb1e0f4b0f2aa3eb54aad574bb5375ae8da78539ad937b34ba02dd170e7b',
 'src/logging/redact-internal-state.ts': '31d768d62ac50efd1d443fd27cec301b95363070be564ed5caa3616608d67def',
 'src/logging/redact-internal.ts': '94cd7ce5f4ed88d2fcdbc3530e4dd7b291095feff65d76a33cc5de3f73a97e1e',
 'src/logging/secret-redaction-registry.ts': '217d789ec4e6b3896dc7c647d33a8a2eed2df4b754fa0abf93a577296863f689',
 'src/logging/logger.ts': '8c7832f365fbb826bf338a5488b8136483fcf515dfe202a25b71e2f38d972b9e',
 'src/logging/config.ts': '6f69e236903267ccb1b1ab038f7d0a4ed6340015e51ad6fc170c86e9f62d18a4',
 'src/logging/state.ts': 'ad8e330d6f8ad4fa02bfcca7d7a27dc33375753a3c0fa2392b6e55cc2bc1ab98',
 'src/agents/transcript-redact.ts': 'd7ff59f554d3ef940b20b4276cc58c7d0ab68ba818a289a1d80970fed42ba95c',
 'src/agents/transcript-redact-text.ts': '0346abdc593ce0dce13dc4919143e6a92ab6ef7855c4ae72ed8f78ef356e8d78',
 'src/security/config-regex.ts': '438a598fcaebefc20d5e612c52f189bc2a32b83a492399917407e63128d8a1b5',
 'src/security/safe-regex.ts': '0067759e19538ca8ffe3f95f3669a519d400243bfd0798bb5384ac84713342e5',
 'src/logging/redact-pattern-runtime.ts': 'dfa74d867c6c9b16f6f63cf541841e14d324031ab6034b8c4d856c86f402936c',
 'src/logging/redact-bounded.ts': '3ef375cc5143424f04d4afdf70ed2ff9075a3820701b3c97e7734079d512150b'}
SOURCE_ANCHORS = {'src/logging/redact.ts': ('export function redactSensitiveText(',
                           'export function redactToolPayloadText(',
                           'export function redactModelVisibleSecrets<T>('),
 'src/logging/redact-internal-state.ts': ('export const fullContextToolPayloadRedactionState = {',
                                          'export function captureModelVisibleRedactionPolicy('),
 'src/logging/redact-internal.ts': ('export function isFullContextToolPayloadRedaction(',),
 'src/logging/secret-redaction-registry.ts': ('export function captureSecretRedactionRegistrySnapshot()',
                                              'export function registerSecretValueForRedaction('),
 'src/logging/logger.ts': ('export function applyLoggingConfig(', 'export function resetLogger()'),
 'src/logging/config.ts': ('export function readLoggingConfig()',),
 'src/logging/state.ts': ('export const loggingState =',),
 'src/agents/transcript-redact.ts': ('export function redactTranscriptMessage(',),
 'src/agents/transcript-redact-text.ts': ('export function resolveTranscriptLoggingConfig(',
                                          'export function redactTranscriptText('),
 'src/security/config-regex.ts': ('export function compileConfigRegex(',),
 'src/security/safe-regex.ts': ('export function compileSafeRegexDetailed(',),
 'src/logging/redact-pattern-runtime.ts': ('export function parseRedactPatternSource(',
                                           'export function* iterateRedactMatches('),
 'src/logging/redact-bounded.ts': ('export function replacePatternBounded(',)}


class RedactionPolicyEvidenceError(ValueError):
    """A source-policy observation could not prove its original owners."""


def prepare_redaction_policy_source_bindings(checkout: Path) -> dict:
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise RedactionPolicyEvidenceError("The source redaction profile needs the exact pinned commit")
    sources, evidence = _owners(checkout, SOURCE_HASHES, SOURCE_ANCHORS, committed=True)
    imports = [
        ("src/logging/redact.ts", "./redact-internal-state.js", ("modelVisibleToolTextRedactionState",)),
        ("src/logging/redact.ts", "./redact-internal.js", ("isFullContextToolPayloadRedaction",)),
        ("src/logging/redact-internal.ts", "./redact-internal-state.js", ("fullContextToolPayloadRedactionState",)),
        ("src/logging/redact-internal-state.ts", "./secret-redaction-registry.js", ("getSecretRedactionRegistryRevision",)),
        ("src/logging/redact.ts", "./secret-redaction-registry.js", ("captureSecretRedactionRegistrySnapshot", "createSecretValueRedactor", "redactRegisteredSecretValues")),
        ("src/logging/redact.ts", "./config.js", ("readLoggingConfig",)),
        ("src/logging/config.ts", "./state.js", ("APPLIED_LOGGING_CONFIG_UNOWNED", "loggingState")),
        ("src/logging/logger.ts", "./state.js", ("APPLIED_LOGGING_CONFIG_UNOWNED", "loggingState")),
        ("src/agents/transcript-redact.ts", "./transcript-redact-text.js", ("redactTranscriptText", "redactTranscriptStructuredFieldValue", "resolveTranscriptLoggingConfig")),
        ("src/agents/transcript-redact-text.ts", "../logging/redact.js", ("redactModelVisibleToolPayloadTextWithConfig", "redactToolPayloadTextWithConfig")),
        ("src/logging/redact.ts", "../security/config-regex.js", ("compileConfigRegex",)),
        ("src/security/config-regex.ts", "./safe-regex.js", ("compileSafeRegexDetailed",)),
    ]
    return {"kind": "explicit-authenticated-all-source-redaction-policy", "referenceCommit": REFERENCE_COMMIT,
            "compiledModulesAllowed": False, "sourceFallbackAllowed": False, "sameModuleGraphRequired": True,
            "freshOrdinaryProcessRequired": True, "testRegistryResetAllowed": False,
            "sourceBindings": evidence,
            "sourceImportLinks": [_named_link(sources, module, specifier, names, kind="import")
                                  for module, specifier, names in imports], "covers": []}


_CALLS = {
    "explicitSensitiveText": "redactSensitiveText", "toolText": "redactToolPayloadText",
    "modelText": "redactModelVisibleToolPayloadText", "structuredTool": "redactSecrets",
    "structuredModel": "redactModelVisibleSecrets", "transcript": "redactTranscriptMessage",
    "policy": "captureModelVisibleRedactionPolicy", "directCompiler": "compileConfigRegex",
}


def _fail(message: str) -> None:
    raise RedactionPolicyEvidenceError(message)


def validate_redaction_policy_source_execution(
    response: dict, case: dict, *, node_authority: dict, process_pid: int,
    coordinator_pid: int, fixture_root: Path,
) -> None:
    """Bind complete public outputs to genuine source calls and actual process.

    Transitive committed-source/dependency verification remains the common
    source oracle's responsibility. This guard adds the required private-state
    owners, exact ordinary process and complete original return observations.
    """
    if case.get("operation") != "redaction-policy-source" or case.get("input", {}).get("kind") != "source-policy":
        _fail("The source policy case has a different operation")
    execution = response.get("sourceExecution")
    fields = {"profile", "pid", "ppid", "execPath", "nodeVersion", "icuVersion", "unicodeVersion", "nodeSha256",
              "requestCase", "compiledFallbackAllowed", "ordinaryProcess", "observations"}
    if not isinstance(execution, dict) or set(execution) != fields:
        _fail("The source policy requires one complete execution channel")
    if (execution["profile"] != "redaction-policy-source" or execution["pid"] != process_pid
            or execution["ppid"] != coordinator_pid or execution["compiledFallbackAllowed"] is not False
            or execution["ordinaryProcess"] is not True or not _same_json(execution["requestCase"], case)):
        _fail("The source policy process or original instructions changed")
    expected_runtime = {key: node_authority[key] for key in ("execPath", "nodeVersion", "icuVersion", "unicodeVersion")}
    actual_runtime = {key: execution[key] for key in expected_runtime}
    if actual_runtime != expected_runtime or execution["nodeSha256"] != node_authority["sha256"]:
        _fail("The source policy used an unapproved executable or Unicode runtime")
    sources = response.get("sources")
    if not isinstance(sources, list):
        _fail("The source policy has no original source graph")
    seen = {}
    for source in sources:
        name = source.get("path") if isinstance(source, dict) else None
        if (not isinstance(source, dict) or set(source) != {"path", "sha256"}
                or not isinstance(name, str) or name in seen or Path(name).is_absolute()
                or ".." in Path(name).parts or "dist" in Path(name).parts):
            _fail("The source policy graph mixes compiled or duplicate modules")
        seen[name] = source.get("sha256")
    if any(seen.get(name) != digest for name, digest in SOURCE_HASHES.items()):
        _fail("The source policy omitted an original private-state or policy owner")
    rows = response.get("results")
    frames = execution["observations"]
    if (not isinstance(rows, list) or len(rows) != 1 or rows[0].get("id") != case["id"]
            or rows[0].get("ok") is not True or not isinstance(frames, list) or len(frames) != 1):
        _fail("The source policy requires one successful complete original return")
    frame, value = frames[0], case["input"]
    if not isinstance(frame, dict) or set(frame) != {"input", "registry", "calls", "output", "logging"}:
        _fail("The source policy original calls are incomplete")
    public = rows[0].get("result")
    if (not isinstance(public, dict) or set(public) != {"provider", "result", "registry"}
            or public["provider"] != "none" or not _same_json(frame["input"], value)
            or not _same_json(frame["output"], public) or not _same_json(frame["registry"], public["registry"])):
        _fail("The source policy lost a complete original output")
    registry = public["registry"]
    if (not isinstance(registry, dict) or set(registry) != {"before", "after"}
            or not _same_json(registry["before"], {"revision": 0, "values": []})):
        _fail("The source policy registry was not fresh and ordinary")
    after = registry["after"]
    allowed = value.get("declaredRegistryValues")
    if (not isinstance(after, dict) or set(after) != {"revision", "values"}
            or not isinstance(after["revision"], int) or isinstance(after["revision"], bool) or after["revision"] < 0
            or not isinstance(after["values"], list) or not isinstance(allowed, list)
            or any(not isinstance(item, str) or item not in allowed for item in after["values"])
            or len(after["values"]) != len(set(after["values"]))):
        _fail("The source policy registry contains undeclared fixture state")
    result, calls = public["result"], frame["calls"]
    keys = list(_CALLS) if value.get("directRegex") else list(_CALLS)[:-1]
    if (not isinstance(result, dict) or set(result) != set(keys) or not isinstance(calls, list)
            or len(calls) != len(keys)):
        _fail("The source policy dropped a full original owner return")
    for name, observed in zip(keys, calls, strict=True):
        if (not isinstance(observed, dict) or set(observed) != {"name", "result"}
                or observed["name"] != _CALLS[name] or not _same_json(observed["result"], result[name])):
            _fail("The source policy output differs from its actual owner observation")
    policy = result["policy"]
    if (not isinstance(policy, dict) or set(policy) != {"patterns", "fullContext", "registryRevision"}
            or not _same_json(policy["patterns"], value.get("patterns", []))
            or policy["fullContext"] is not value["fullContext"]
            or not isinstance(policy["registryRevision"], int) or isinstance(policy["registryRevision"], bool)
            or policy["registryRevision"] != after["revision"]):
        _fail("The source policy private marker or registry revision changed")
    logging = frame["logging"]
    expected_logging = {"level": "silent", "consoleLevel": "silent", "file": str(Path(fixture_root) / "native.log"),
                        **({"redactPatterns": value["patterns"]} if "patterns" in value else {})}
    if (not isinstance(logging, dict) or set(logging) != {"json", "marked"}
            or not _same_json(logging["json"], expected_logging) or logging["marked"] is not value["fullContext"]):
        _fail("The source policy host configuration or actual private marker changed")
