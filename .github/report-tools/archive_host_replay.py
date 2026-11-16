def replay_hosts(data, cases, args):
    """Replay archived business custody; retain original live V4 environment proof.

    ZIP transport assigns new inode/device identities. This reader never claims
    that the restored filesystem is the original execution host and never
    fabricates or rewrites its captured identities.
    """
    from equivalence.host_turn_barrier_v4 import CASE_HASHES, business_case, validate_case
    from equivalence.host_turn_barrier_evidence import validate_pair as validate_business_pair

    require([case['id'] for case in cases] == list(CASE_HASHES), 'Archived Host proof needs all four exact cases')
    family = (ROOT / '.equivalence-results/host-turn-barrier-v4').resolve(strict=True)
    rows = {row['id']: row for row in data['cases']}
    results = []
    for case in cases:
        validate_case(case, registered=True)
        cid, directories, raws, files = case['id'], {}, {}, []
        require(rows[cid]['status'] == 'matched' and rows[cid].get('runtimeEvidenceValidated') is True,
                'Original live V4 comparison was not affirmatively validated')
        for side in ('native', 'python'):
            diagnostic = data['hostDiagnostics'][cid + '--' + side]
            directory = Path(diagnostic['evidenceDirectory'])
            require(directory.is_absolute() and directory.resolve(strict=True) == directory
                    and directory.is_relative_to(family), 'Archived Host capture escaped its exact family')
            path = directory / ('evidence/native-raw.json' if side == 'native' else 'python-raw.json')
            payload = load(path)
            require(diagnostic['validationStatus'] == 'verified' and digest(path) == diagnostic['sha256']
                    and hashlib.sha256(canonical(payload)).hexdigest() == diagnostic['rawSnapshotsSha256']
                    and isinstance(payload, list) and len(payload) == 1,
                    'Archived raw differs from the original live-validated full-report capture')
            directories[side], raws[side] = directory, payload[0]
            files.append((path, digest(path)))
        native_path, sdk_path = directories['native'] / 'stdout.json', directories['python'] / 'sdk-output.json'
        native_result, sdk_result = load(native_path)['result'], load(sdk_path)
        files.extend((path, digest(path)) for path in (native_path, sdk_path))
        require(validate_business_pair(business_case(case), raws['native'], raws['python'],
                                       native_result, sdk_result) is True,
                'Archived complete Host business custody did not validate')
        pair = data['hostPairs'][cid]
        require(_same_json(native_result, pair['openclaw']) and _same_json(sdk_result, pair['python'])
                and all(digest(path) == sha for path, sha in files),
                'Archived whole public values or original raw bytes changed')
        results.append({'id': cid, 'validated': True,
                        'validationMode': 'original-live-v4-custody-and-archived-business-replay',
                        'originalLiveEnvironmentValidation': True, 'restoredLiveInodesReplayed': False,
                        'publicMatch': _same_json(native_result, sdk_result)})
    return results
