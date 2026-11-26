"""Independently recount the 128 fixed conditions using one authenticated complete Actions projection."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import types


BASE_REVIEW = '9430a2cb23a6660f281adbeadb0fb1b926687fa4'
BASE_RUN = 45153594838
BASE_DECISION = 'f717be1b4d89f1fe3cf22cf1f81588567cf65a665d6dbe434c71a65d2ed49c39'
PREPARATION_SOURCE = 'f0aa931e0a170109094b1c7439d9e5e8e818471e49c887ac6360970f8d6ec5be'
PREVIOUS_READER = 'ad558a02524ec0b2eb12ff297984c0e9917f2f56f3417a4025efc0ec5b0cbe45'
RETRY = 'query-sync-boundaries-warm-failure-natural-retry'


def require(test, reason):
    if not test:
        raise ValueError(reason)


def immutable(root, path, expected):
    raw = subprocess.check_output(['git', '-C', str(root), 'show', path])
    require(hashlib.sha256(raw).hexdigest() == expected, f'Immutable source differs at {path}')
    return raw


def module(raw, name):
    item = types.ModuleType(name)
    exec(compile(raw, name, 'exec'), item.__dict__)
    return item


def historical(root, baseline):
    prefix = BASE_REVIEW + ':independent-review/search-retry/'
    decision = json.loads(immutable(root, prefix + f'independent-{BASE_RUN}.json', BASE_DECISION))
    prepare = module(immutable(root, prefix + 'review_search.py', PREPARATION_SOURCE), 'search_reviewer')
    previous_code = prepare.read_blob(root, 'review.py')
    require(hashlib.sha256(previous_code).hexdigest() == PREVIOUS_READER, 'Previous reviewer differs')
    legacy = module(previous_code, 'heartbeat_reviewer')
    prior, original = legacy.load_previous(root)
    require(prior.artifact(baseline, BASE_RUN, decision['measurement'], decision['archive']['sha256'])
            == decision['archive'], 'Wrong prior summary selected')
    old = prior.read(baseline / 'assessment.json')
    require(old['report'] == decision['report'] and len(old['projection']['cases']) == decision['registeredCases']
            and [r['id'] for r in old['projection']['cases'] if r['status'] == 'mismatched']
            == decision['mismatchedCaseIds'], 'Prior decisions and summary disagree')
    return legacy, prior, original, decision, old


def original_process(folder, run, audit, projection, prior):
    # Unlike the old assessor, this check accepts every genuine terminal status.
    launch, end, term = [prior.read(folder / f'{name}.json') for name in ('launch', 'os-exit', 'run-summary')]
    report = audit['report']
    require(launch['kind'] == 'single-full-comparison-launch' and launch['automaticRetry'] is False
            and type(launch['pid']) is int and launch['pid'] > 0
            and Path(launch['tmpdir']).name == f'memory-core-once-{run}'
            and launch['sourceSealSha256'] == prior.file_sha(folder / 'source-seal.json')
            and all(end[k] == v for k, v in launch.items() if k != 'pid'), 'Original single-launch metadata')
    argv = launch['argv']
    require(len(argv) == 10 and argv[1:5] == ['scripts/check_equivalence.py', '--reference', '.reference/openclaw', '--node']
            and Path(argv[5]).name == 'node'
            and argv[6:] == ['--release-runtime', '.reference/release-runtime', '--report', '.equivalence-results/full.json'],
            'Original process command')
    require(Path(report['path']) == Path(launch['cwd']) / term['report'] and term['report'] == argv[-1]
            and report['bytes'] > 0 and report['sha256'] == end['fullReportSha256'] == term['reportSha256']
            and prior.valid_hash(report['sha256']), 'Complete report size, digest, or location')
    process = {'pid': launch['pid'], 'actualReturnCode': end['actualReturnCode'],
               'stdoutSha256': prior.file_sha(folder / 'run-summary.json'),
               'stderrSha256': prior.file_sha(folder / 'comparison.stderr.log'),
               'reportBytes': report['bytes'], 'reportSha256': report['sha256']}
    require(audit['comparisonProcess'] == process and
            all(end[k] == process[k] for k in ('stdoutSha256','stderrSha256')), 'Comparison process streams')
    codes = {'passed': 0, 'mismatched': 1, 'incomplete': 1, 'blocked': 2}
    require(all(term[k] == projection[k] for k in ('mode','status','errors','summary','fullScopePassed'))
            and term['mode'] == 'full' and term['status'] in codes
            and type(end['actualReturnCode']) is int and end['actualReturnCode'] == codes[term['status']]
            and term['fullScopePassed'] is (term['status'] == 'passed') and end['elapsedSeconds'] > 0
            and datetime.fromisoformat(end['finishedAt']) >= datetime.fromisoformat(launch['startedAt']),
            'Terminal comparison observation')
    return end, term


def public_pair(cid, pair, row, prior, same_json):
    require(type(pair) == dict and set(pair) == {'openclaw','python'}, f'Whole public outputs missing for {cid}')
    hashes = {side: prior.digest(prior.canonical(value)) for side, value in pair.items()}
    require(row['publicValueSha256'] == hashes, f'Whole values differ from original row {cid}')
    require(row['status'] == ('matched' if same_json(pair['openclaw'], pair['python']) else 'mismatched'),
            f'Whole public result status disagrees for {cid}')
    return hashes


def public_changes(old_rows, new_rows, audit, decision, prior, same_json, same_run):
    before = {r['id']: r for r in old_rows}
    by_id = {r['id']: r for r in new_rows}
    require(list(before) == [r['id'] for r in new_rows[:len(before)]], 'Original ordered cases changed')
    changes = {cid: {'before': a['status'], 'after': by_id[cid]['status']} for cid, a in before.items()
               if a['status'] != by_id[cid]['status']}
    prev_diff = set(decision['mismatchedCaseIds'])
    expected_pairs = {cid for cid in prev_diff if by_id[cid]['status'] != 'blocked'}
    current = audit.get('previousMismatchPublicPairs', {})
    if not same_run:
        require(set(current) == expected_pairs, 'Incomplete historical whole public pairs')
    elif current:
        require(set(current) == expected_pairs, 'Wrong self-check pair inventory')
    values = {}
    for cid in decision['mismatchedCaseIds']:
        result = by_id[cid]
        sha = result.get('publicValueSha256')
        if cid in current:
            sha = public_pair(cid, current[cid], result, prior, same_json)
        values[cid] = {'status': result['status'], 'before': before[cid]['publicValueSha256'], 'after': sha,
                       'wholeValuesRead': cid in current}
    q = by_id[RETRY]
    public_pair(RETRY, audit['warmRetryPublicPair'], q, prior, same_json)
    require(q['referenceMode'] == 'authenticated-official-release' and q['runtimeEvidenceValidated'] is True,
            'Original retry runtime evidence')
    return changes, values


def validate_replays(prior, specialized_receipt, folder, assessment, rows, gates, sdk, independent_fif_sha):
    """Validate every historical receipt and every new registered family member on the same report."""
    read, file_sha = prior.read, prior.file_sha
    from followup_families import FAMILIES, family_key
    legacy = [("host-turn-barrier-v4-runtime", "hostReplays", 4), ("forget-lineage-runtime", "lineageReplays", 3),
              ("forget-boundaries-runtime", "boundaryReplays", 1), ("recall-signals-runtime", "recallReplays", 6),
              ("embed-cache-lifecycle-runtime", "embeddingCacheReplays", 8),
              ("session-reset-boundaries-runtime", "sessionResetBoundariesReplays", 7),
              ("prompt-runtime-context-runtime", "promptRuntimeContextReplays", 10),
              ("prompt-history-repair-runtime", "promptHistoryRepairReplays", 8),
              ("engine.numeric-boundaries", "engineNumericReplays", 4),
              ("deep-consolidation-runtime", "deepConsolidationReplays", 7)]
    by_group = {}
    for op, field, count in legacy:
        selected = [r for r in rows if r["requirement" if op == "engine.numeric-boundaries" else "operation"] == op]
        evidence = assessment[field]
        require(len(selected) == len(evidence) == count, field)
        for row, raw in zip(selected, evidence, strict=True):
            require(raw["id"] == row["id"] and raw["validated"] is True and raw["publicMatch"] is True, field)
            if "actualOperations" in raw and "operations" in row["input"]:
                require(raw["actualOperations"] == len(row["input"]["operations"]), raw["id"])
            if field in {"promptRuntimeContextReplays", "promptHistoryRepairReplays"}:
                require(raw["nativeOnDiskRawReopened"] is True and raw["nativeRawFileBytes"] > 0 and
                        raw["nativeRawFileSha256"] == raw["nativeCollectorRawSha256"], raw["id"])
            if field == "engineNumericReplays":
                if row["operation"] == "engine-numeric-boundaries":
                    require(raw["probes"] == len(row["input"]["probes"]) and raw["publicValueSha256"]
                            == row["publicValueSha256"], raw["id"])
                else:
                    require(raw["rawWireHashesReproduced"] is True and raw["candidateCounts"] == [3,2,1,0,1], raw["id"])
            if field == "deepConsolidationReplays":
                require(all(raw[k] is True for k in ("nativeOnDiskRawReopened", "sdkOnDiskRawReopened",
                                                      "physicalStateRebuilt")), raw["id"])
            for key, val in raw.items():
                if key.endswith("Sha256") and isinstance(val, str):
                    require(re.fullmatch("[a-f0-9]{64}", val), "Invalid retained raw checksum")
        by_group[op] = count
    fif = read(folder / "forget-family-replay.json")
    [fif_report] = fif["sourceReports"]
    fif_ids = [r["id"] for r in rows if r["operation"] == "forget-index-fence-v6-runtime"]
    require(fif["finalAuthenticationPassed"] is True and fif["validCompleteBaseline"] is True
            and fif["candidateFamilyMatched"] == gates["forget-index-fence-v6-runtime"] and not fif["errors"]
            and file_sha(folder / "forget-family-replay.json") == (independent_fif_sha or assessment["fifReplaySha256"])
            and fif_report["report"] == assessment["report"] and fif_report["fixedAcceptancePoints"] == 128
            and fif_report["registeredCases"] == len(rows) and fif["authority"]["sdk"]["sourceSha256"] == sdk
            and [r["id"] for r in fif["cases"]] == fif_ids and len(fif_ids) == 13, "Complete retained forget replay")
    by_group["forget-index-fence-v6-runtime"] = len(fif_ids)
    combined = set()
    require(set(FAMILIES) == set(assessment["appendedFamilyReplays"]), "Appended family inventory")
    for key, (family, field, _) in FAMILIES.items():
        measurements = assessment["appendedFamilyReplays"][key]
        selected = [r for r in rows if family_key(r) == key]
        cases = measurements["cases"]
        require(measurements["gate"] == field and measurements["passed"] is gates[key]
                and measurements["scopePoints"] == sorted({p for r in selected for p in r["covers"]}), key)
        require([r["id"] for r in selected] == [r["id"] for r in cases]
                == [r["id"] for r in family.build_cases()], key)
        for row, item in zip(selected, cases, strict=True):
            require(item["publicMatch"] is (row["status"] == "matched") and item["id"] not in combined, "Invalid appended replay " + item["id"])
            combined.add(item["id"])
            # Most families expose native/SDK raw digest pairs. The four corpus/flush controls store
            # per-source or raw-trace digests, with their own independent archived reconstruction.
            if "nativeRawSha256" in item:
                require(all(re.fullmatch("[a-f0-9]{64}", item[k]) for k in ("nativeRawSha256", "sdkRawSha256")),
                        "Raw receipt digests " + item["id"])
            elif key == "heartbeat.turn-decisions.boundaries":
                if "sourceSha256" in item:
                    require(item["opensPerSide"] == 2 and re.fullmatch("[a-f0-9]{64}", item["sourceSha256"]), item["id"])
                else:
                    require(item["drives"] == 3 and set(item["rawDigests"]) == {"native","python"}
                            and all(re.fullmatch("[a-f0-9]{64}", h) for h in item["rawDigests"].values()), item["id"])
            else:
                specialized_receipt(key, row, item)
            if "sdkOnDiskRawReopened" in item:
                require(item["sdkOnDiskRawReopened"] is True and item["nativeOnDiskRawReopened"] is True, item["id"])
            if key == "heartbeat-turn-outcomes-runtime":
                require(item["drives"] == len(row["input"]["steps"]) and item["sqliteStoresReopened"] == 2
                        and item["originalActors"] >= 7, item["id"])
        by_group[key] = len(cases)
    require({r["id"] for r in rows[1519:]} <= combined and
            combined == {r["id"] for r in rows if family_key(r) in FAMILIES},
            "Every appended definition and every previously registered new family member needs a bound replay")
    return by_group


def transcript_receipt(row, receipt, prior):
    inputs = row['input']
    raw = receipt['rawFiles']
    require(receipt['validated'] is True and row['runtimeEvidenceValidated'] is True
            and row['referenceMode'] == 'authenticated-official-release'
            and receipt['source'] == inputs['source'] and receipt['physicalReads'] == sum(s['op'] == 'read' for s in inputs['steps'])
            and receipt['mutations'] == ('initial' in inputs) + sum(s['op'] != 'read' for s in inputs['steps'])
            and set(raw) == {'native','python'} and receipt['threads'] == len(receipt['traceSha256']) > 0
            and all(prior.valid_hash(s) for s in receipt['traceSha256'].values())
            and all(re.fullmatch(r'[0-9]+-[0-9]+[.]jsonl', name) for name in receipt['traceSha256'])
            and sum(name.endswith('-0.jsonl') for name in receipt['traceSha256']) == 1,
            'Missing registered file mutations or original protected transcript capture')
    for side, directory, name in (('native','native-attempt-','native-raw.json'),
                                  ('python','sdk-attempt-','python-raw.json')):
        path = Path(raw[side])
        require(len(path.parts) == 2 and path.parent.name.startswith(directory) and path.name == name
                and prior.valid_hash(receipt['nativeSha256' if side == 'native' else 'sdkSha256']),
                'Missing physical transcript packet ' + row['id'])


def full_replay(legacy, prior, folder, audit, rows, gates, sdk):
    validate = prior.specialized_receipt
    def family_receipt(key, row, receipt):
        if key == legacy.OP:
            legacy.validate_scratch(row, receipt, prior.valid_hash)
        elif key == 'transcript-boundary-runtime':
            transcript_receipt(row, receipt, prior)
        elif key == 'engine.datetime-regex.boundaries':
            from equivalence.search_contract import _same_json
            cells = receipt['classification']
            require(receipt['publicValueSha256'] == row['publicValueSha256'] and receipt['coverage'] == row['covers']
                    and prior.canonical(cells) == prior.canonical(row['datetimeBoundaryEvidence']) and cells,
                    'Observed public/date classifications differ')
            for cell in cells:
                match = _same_json(cell['openclaw'], cell['python'])
                require(cell['comparison'] in ({'matched','uncovered'} if match else {'mismatched'}),
                        'Classified date admission disagrees with observations')
        elif key == 'engine-unicode-collation':
            from equivalence.engine_unicode_collation import DIAGNOSTIC
            from followup_unicode import MEASURED_ORIGINAL
            tie = next(r for r in rows if r['id'] == DIAGNOSTIC)
            observed = row['publicValueSha256']
            require(receipt['previousTie'] == tie['publicValueSha256'] and
                    receipt['previousTie']['openclaw'] == '5557cac38760fa4dfada60946a7009a3c9c021ba550297aaa6ba0677b2c00471'
                    and receipt['nativePublicSha256'] == MEASURED_ORIGINAL[row['id']] == observed['openclaw']
                    and receipt['sdkPublicSha256'] == observed['python'] and receipt['texts'] > 0,
                    'Unbound or different original Unicode public observation')
            if 'previousTiePublicMatch' in receipt:
                require(receipt['previousTiePublicMatch'] is (tie['status'] == 'matched'), 'Unicode tie observation')
        else:
            validate(key, row, receipt)
    return validate_replays(prior, family_receipt, folder, audit, rows, gates, sdk,
                            prior.file_sha(folder / 'forget-family-replay.json'))




def replay_inventory(folder, audit, prior):
    sections = {
        'host-turn-barrier-v4-runtime':'hostReplays', 'forget-lineage-runtime':'lineageReplays',
        'forget-boundaries-runtime':'boundaryReplays', 'recall-signals-runtime':'recallReplays',
        'embed-cache-lifecycle-runtime':'embeddingCacheReplays', 'session-reset-boundaries-runtime':'sessionResetBoundariesReplays',
        'prompt-runtime-context-runtime':'promptRuntimeContextReplays', 'prompt-history-repair-runtime':'promptHistoryRepairReplays',
        'engine.numeric-boundaries':'engineNumericReplays', 'deep-consolidation-runtime':'deepConsolidationReplays'}
    groups = {op:[r['id'] for r in audit[field]] for op,field in sections.items()}
    groups['forget-index-fence-v6-runtime'] = [r['id'] for r in prior.read(folder / 'forget-family-replay.json')['cases']]
    for key, group in audit['appendedFamilyReplays'].items():
        require(key not in groups, 'Duplicate physical evidence family ' + key)
        groups[key] = [r['id'] for r in group['cases']]
    require(all(len(members) == len(set(members)) for members in groups.values()), 'Duplicate physical case in family')
    return groups

def historical_runtime(rows, audit, prior):
    rank = 'promotion-ranking-primitive-provenance-safety-diagnostic'
    layout = 'bootstrap-discovery-memory-core-layout-extension'
    legacy = 'bootstrap-discovery-legacy-state-gate'
    cases = {r['id']: r for r in rows if r['id'] in {rank, layout, legacy}}
    packets = audit['historicalRuntimeReceipts']
    require(set(packets) == {cid for cid,r in cases.items() if r['status'] != 'blocked'},
            'Missing original ranked/selected workspace process receipts')
    receipts = {}
    for cid, receipt in packets.items():
        row = cases[cid]
        pair = audit['previousMismatchPublicPairs'][cid]
        require(receipt['id'] == cid and receipt['publicMatch'] is (row['status'] == 'matched')
                and row['referenceMode'] == 'authenticated-official-release' and receipt['rawWireHashesReproduced'] is True
                and type(receipt['nativeOnDiskRawReopened']) is bool and type(receipt['protectedWorkerThreads']) is int
                and receipt['protectedWorkerThreads'] >= (0 if cid == legacy else 1)
                and receipt['compiledOwners'] > 0 and prior.valid_hash(receipt['sdkRawSha256'])
                and prior.valid_hash(receipt['nativeCollectorRawSha256']) and receipt['rawTraceSha256']
                and all(prior.valid_hash(x) for x in receipt['rawTraceSha256']), 'Protected run receipt '+cid)
        if cid == rank:
            phases = receipt['sdkPhaseFiles']
            require(receipt['validated'] is True and receipt['sourceOwners'] > 0
                    and receipt['nativeSqlitePhases'] == ['before','after'] and set(phases) == {'before','after'},
                    'Missing ranked original SQLite or SDK file readings')
            expected_files = {'workspace/memory/.dreams/phase-signals.json','workspace/memory/.dreams/short-term-recall.json'}
            require(all(set(values) == expected_files and all(map(prior.valid_hash, values.values()))
                        for values in phases.values()) and phases['before'] == phases['after'],
                    'Missing or modified SDK source files during rank preview')
            original = pair['openclaw']
            counts = [len(q['candidates']) for q in original['queries']]
            require(counts == receipt['candidateCounts'] and len(counts) == len(row['input']['queries'])
                    and original['before'] == original['after'], 'Ranking preview updated stored records')
            observation = {'candidateCounts':{side:[len(q['candidates']) for q in value['queries']]
                                              for side,value in pair.items()}, 'sdkFilePhases':phases}
        else:
            require(all(prior.valid_hash(receipt[k]) for k in ('sdkChildStdoutSha256','sdkRequestSha256')),
                    'Bootstrap child request/stdout hashes')
            labels = [r['label'] for r in row['input']['steps']]
            phases = {side:receipt[side+'Phases'] for side in ('native','sdk')}
            for snaps in phases.values():
                require([s['label'] for s in snaps] == labels and all(isinstance(s['workspace'],list)
                        and len(s['workspace']) == len(set(s['workspace'])) and s['outside'] == [] for s in snaps),
                        'Unexpected bootstrap source/outer inventory')
            observation = {'workspaceInventories':phases, 'steps':{}}
            for side, result in pair.items():
                require([s['label'] for s in result['steps']] == labels, 'Bootstrap public steps')
                observation['steps'][side] = []
                for step, fixture in zip(result['steps'],row['input']['steps'],strict=True):
                    observed = {k:step[k] for k in ('label','ensure','bootstrapStatus','setupCompleted')}
                    observed['runs'] = [{'files':[f['name'] for f in r.get('files',[]) if not f.get('missing')],
                                         'error':r.get('error')} for r in step['runs']]
                    require(len(step['runs']) == len(fixture['runs']), 'Bootstrap file selection missing')
                    observation['steps'][side].append(observed)
                if cid == legacy and side == 'openclaw':
                    step = result['steps'][0]
                    require(all(step[k]['error']['code'] == 'gateway.maintenance_required' for k in
                                ('ensure','bootstrapStatus','setupCompleted')) and 'files' in step['runs'][0],
                            'Original migration errors or permissive selection missing')
        receipts[cid] = {'nativeRawSha256':receipt['nativeCollectorRawSha256'], 'sdkRawSha256':receipt['sdkRawSha256'],
                         'rawWireHashesReproduced':True, 'nativeOnDiskRawReopened':receipt['nativeOnDiskRawReopened'],
                         'protectedWorkerThreads':receipt['protectedWorkerThreads'], 'observed':observation}
    return receipts

def review(args):
    root, folder, baseline = (getattr(args, k).resolve() for k in ('measurement', 'summary', 'previous_summary'))
    sys.path[:0] = [str(root), str(root / '.github/scripts')]
    from equivalence.cases import build_cases
    from equivalence.catalog_migration import definition_authority
    from equivalence.harness import _same_json
    import followup_seal as pin

    legacy, prior, original, previous, old_audit = historical(root, baseline)
    archive = prior.artifact(folder, args.run, args.head, args.archive_sha256)
    audit, seal, after = [prior.read(folder / f'{k}.json') for k in ('assessment','source-seal','source-after')]
    prior.source(root, seal, after, args.head, pin)
    require(pin.PRODUCT == args.product and seal['scopeSha256'] == prior.SCOPE, 'Product and immutable scope')
    require(audit['completeReportParsed'] is True and audit['originalEnginesExecuted'] is False, 'Missing EOF assessment')
    proj = audit['projection']
    require(proj['reference'] == previous['reference'] and proj['reference']['commit'] == prior.REFERENCE
            and proj['paidProviderCalls'] == 0 and proj['providerCredentialsForwarded'] is False, 'Pinned runtime or providers')
    for key, name in (('reference','reference.json'), ('scope','scope.json'), ('sourceMap','source-map.json')):
        require(proj['manifestSha256'][key] == prior.file_sha(root / 'equivalence' / name), f'Manifest {key}')
    require(proj['casesSha256'] == prior.file_sha(root / 'equivalence/cases.py'), 'Registry source digest')
    end, terminal = original_process(folder, args.run, audit, proj, prior)
    defs = build_cases()
    existing = previous['registeredCases']
    require(len(defs) == seal['registeredCases'] and len(defs) >= existing
            and prior.digest(prior.canonical(defs)) == seal['catalogSha256'] == pin.CATALOG_SHA
            and prior.digest(prior.canonical(defs[:existing])) == previous['catalogSha256']
            and prior.digest(prior.canonical(defs[:1623])) == original['catalogSha256']
            and definition_authority(defs, fif_version='v6') == seal['definitionMigration'], 'Frozen and appended case catalog')
    rows, modes = legacy.reconstruct(root, prior, defs, proj)
    scope = prior.read(root / 'equivalence/scope.json')['requirements']
    gates, points, contracts, missing, unresolved = legacy.recount_current(prior, defs, rows, proj, scope)
    require(previous['families'].keys() <= gates.keys(), 'A prior family gate disappeared')
    states=Counter(r['status'] for r in rows)
    counts = {key: states[key] for key in ('matched','mismatched','blocked')}
    require(proj['summary'] == {**counts, 'uncoveredAcceptance': len(missing)}, 'Terminal case totals')
    for status, key in (('mismatched','mismatchedCaseIds'), ('blocked','blockedCaseIds')):
        require([r['id'] for r in rows if r['status'] == status] == terminal[key], 'Terminal row identity')
    mismatch_fields = ('id','operation','requirement','covers','publicValueSha256')
    require(audit['mismatchMetadata'] == [{k:r[k] for k in mismatch_fields} for r in rows if r['status'] == 'mismatched'],
            'Different retained mismatch identity, coverage, or public values')
    require(terminal['status'] == ('blocked' if counts['blocked'] or terminal['errors'] else 'mismatched' if counts['mismatched']
            else 'incomplete' if missing else 'passed'), 'Terminal status vs observed rows')
    metrics = {'verified': sum(points.values()), 'remaining': len(missing)+len(unresolved), 'uncovered': len(missing),
               'registeredUnresolved': len(unresolved), 'contracts': contracts, 'cases': counts,
               'families': gates, 'points': [{'id': k, 'verified': v} for k,v in points.items()]}
    for k in ('candidateAssessment','observedAssessment','observedMetrics'):
        if audit.get(k) is not None:
            require(audit[k] == metrics, f'Hosted {k} disagrees with independent score')
    physical = full_replay(legacy, prior, folder, audit, rows, gates, pin.SDK_SHA)
    previous_inventory = replay_inventory(baseline, old_audit, prior)
    inventory = replay_inventory(folder, audit, prior)
    require({k:len(v) for k,v in previous_inventory.items()} == previous['appendedPhysicalReplays']
            and physical == {k:len(v) for k,v in inventory.items()}, 'Different physical evidence counts')
    for group, members in previous_inventory.items():
        original_members = set(members)
        require([cid for cid in inventory[group] if cid in original_members] == members,
                'Lost or reordered historical physical replay ' + group)
    baseline_run = args.run == previous['run'] and args.head == previous['measurement'] and args.product == previous['product']
    changes, values = public_changes(old_audit['projection']['cases'], rows, audit, previous, prior, _same_json, baseline_run)
    historic = {} if baseline_run else historical_runtime(rows, audit, prior)
    previous_points = {r['id']: r['verified'] for r in previous['points']}
    require(set(points) == set(previous_points), 'The existing condition IDs changed')
    gained = [k for k,v in points.items() if v and not previous_points[k]]
    lost = [k for k,v in points.items() if not v and previous_points[k]]
    require(metrics['verified'] == previous['verified'] + len(gained) - len(lost), 'Individual condition change vs total')
    if baseline_run:
        require(not changes and not gained and not lost and physical == previous['appendedPhysicalReplays'] and
                all(metrics[k] == previous[k] for k in metrics), 'Prior 119 is not reproducible')
    if 'changeSince119' in audit:
        observed = audit['changeSince119']
        require(observed['delta'] == len(gained) - len(lost) and observed['gained'] == gained and observed['lost'] == lost
                and observed['originalCaseStatusChanges'] == changes and observed['previousMismatchWholeValues']
                == {k:{key: row[key] for key in ('status','before','after')} for k,row in values.items()},
                'Hosted status/public/gate deltas vs independently reconstructed evidence')
    require(prior.artifact(folder, args.run, args.head, args.archive_sha256) == archive, 'Summary changed during verification')
    return {'kind':'independent-full-scope-recount', 'run': args.run, 'measurement':args.head,'product':args.product,
            'reference':proj['reference'],'sdk':seal['productSdk'],'sdkTree':seal['sdkGitTree'],'scopeSha256':prior.SCOPE,
            'catalogSha256':seal['catalogSha256'],'archive':archive,'report':audit['report'],'conditions':len(points),
            'registeredCases':len(rows), 'unchangedPrefix':existing, **metrics,'netChange':len(gained)-len(lost),
            'gained':gained,'lost':lost,'uncoveredIds':missing,'unresolvedIds':unresolved,
            'changedOriginalCaseStatuses':changes,'previousMismatchWholeValues':values,
            'appendedCases':[{'id':r['id'],'status':r['status'],'covers':r['covers']} for r in rows[existing:]],
            'mismatchedCaseIds':terminal['mismatchedCaseIds'],'blockedCaseIds':terminal['blockedCaseIds'],
            'fullScopePassed':terminal['fullScopePassed'],'terminalStatus':terminal['status'],'engineErrors':terminal['errors'],
            'actualReturnCode':end['actualReturnCode'],'elapsedSeconds':end['elapsedSeconds'],
            'physicalReplayCounts':physical,'originalRecoveryModes':modes,'historicalRuntimeChecks':historic,'assessmentStatus':audit['status'],
            'assessmentErrors':audit['errors'],'baselineDecision':BASE_REVIEW,'reviewerSha256':prior.file_sha(Path(__file__))}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('measurement','summary','previous-summary'):
        parser.add_argument('--'+key,type=Path,required=True)
    for key in ('head','product','archive-sha256'):
        parser.add_argument('--'+key,required=True)
    parser.add_argument('--run',type=int,required=True)
    print(json.dumps(review(parser.parse_args()), indent=2, allow_nan=False))
