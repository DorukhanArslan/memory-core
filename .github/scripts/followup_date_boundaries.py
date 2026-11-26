"""Replay the original public parsers and separately authenticate the uncredited V8 discrepancy."""
from hashlib import sha256
import json
from pathlib import Path

from equivalence.datetime_boundary_cases import CORPUS, DIAGNOSTIC, IDS, POINT, ZONE, build_cases
from equivalence.datetime_boundary_evidence import CORPUS_OWNERS, family_complete, observe
from equivalence.datetime_regex_family import run_clock, wire
from equivalence.datetime_regex_evidence import same
from equivalence.dependencies import prepare_dependencies
from equivalence.harness import ROOT, _committed_digest, _oracle, _reference_bindings, _same_json
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.redaction_policy_evidence import prepare_redaction_policy_source_bindings, validate_redaction_policy_source_execution
from equivalence.session_projection import run_session_projection
from followup_datetime import SOURCE_OWNERS


def replay_passed(cases, receipts):
    rows = [{**case, "status": "matched" if capture["publicMatch"] else "mismatched",
             "datetimeBoundaryEvidence": capture["classification"], "publicValueSha256": capture["publicValueSha256"]}
            for case, capture in zip(cases, receipts, strict=True)]
    return family_complete(rows)


def replay(data, cases, args, runtime):
    same(cases, build_cases())
    source = {r['path']: r for r in data['datetimeSources'] + data['heartbeatSources']}
    owners = set(CORPUS_OWNERS) | SOURCE_OWNERS
    for owner in owners:
        digest = sha256((args.reference / owner).read_bytes()).hexdigest()
        same(source[owner]['sha256'], digest)
        same(_committed_digest(args.reference, owner), digest)
    node = prepare_model_node_authority(args.node)
    same(data['modelNodeAuthority'], node)
    same(data['redactionPolicySourceBindings'], prepare_redaction_policy_source_bindings(args.reference))
    ordinary = [c for c in cases if c['id'] in (CORPUS, DIAGNOSTIC, ZONE)]
    deps = prepare_dependencies(args.reference, args.release_runtime.parent / 'npm')
    bindings = _reference_bindings(args.reference, cache=False, publication=False, reuse_operations=frozenset({'session-projection'}))
    source_run = _oracle(args.node, ROOT / 'equivalence/oracle.mjs', args.reference, ordinary, 60,
                         dependencies=deps, bindings=bindings)
    original = {r['id']: r['result'] for r in source_run['results'] if r['ok']}
    same(list(original), [c['id'] for c in ordinary])
    receipts = []
    for case in cases:
        cid = case['id']
        packet = data['followupRows'][cid]
        row = packet['case']
        native, sdk = row['openclaw'], row['python']
        same({k: row[k] for k in case}, case)
        paths = [source[k] for k in sorted(owners)]
        report = {'sources': paths, 'datetimeSourceImports': data['datetimeSourceImports']}
        if cid in original:
            same(source_run['datetimeSourceImports'][cid], data['datetimeSourceImports'][cid])
            same(native, original[cid])
            rebuilt = run_clock(case['input']) if cid == ZONE else run_session_projection(case['input'])
            if not _same_json(rebuilt, sdk):
                raise ValueError('The independent SDK reader differs from the recorded complete output')
        else:
            policy = packet['sourcePolicy']['sourceExecution']
            frame = policy['observations'][0]
            base = Path(frame['logging']['json']['file']).parent
            response = {'sources': paths, 'sourceExecution': policy, 'results': [{'id': cid, 'ok': True, 'result': native}]}
            validate_redaction_policy_source_execution(response, case, node_authority=node,
                process_pid=policy['pid'], coordinator_pid=policy['ppid'], fixture_root=base)
            raw = packet['python']
            encoded = (json.dumps(raw['rawSnapshots'], ensure_ascii=True, indent=2, allow_nan=False) + '\n').encode()
            same([raw['id'], raw['side'], raw['sha256']], [cid, 'python', sha256(encoded).hexdigest()])
            report.update(sourcePolicyDiagnostics=[packet['sourcePolicy']], runtimeDiagnostics=[raw])
        measured = observe(case, report, native, sdk)
        same(row['datetimeBoundaryEvidence'], measured)
        digests = {side: sha256(wire(row[side])).hexdigest() for side in ('openclaw','python')}
        receipts.append({'id': cid, 'publicMatch': _same_json(native, sdk), 'publicValueSha256': digests,
                         'classification': measured, 'coverage': case['covers']})
    return receipts
