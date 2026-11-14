"""Independent custody of the closed V5 original Native watcher protocol.

This replays original source/OS receipts. It never starts a watcher, advances a
clock, invokes a timer, or treats a quiet queue as delivery evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
import re



def _opaque_native_reconciliation_return(returned, delivery, context, pid, *, approved_adapter_root=None):
    """Authenticate an actual uncloneable callback Promise without replacing it.

    Linux subtree callbacks return enqueueReconciliation's real Promise. The
    callback return is not the Promise's settlement; the watcher drain receipts
    independently prove the admitted work and original inner sync settlements.
    """
    from equivalence.forget_index_fence_evidence import ROOT, _adapter_path, _compiled_text, _digest, _sha, require

    carrier = returned["return"]
    require(isinstance(carrier, dict) and set(carrier) == {"serializationError"}
            and delivery["kind"] == "native", "Native watcher lost a cloneable callback return or claimed an opaque emitter result")
    error = carrier["serializationError"]
    require(isinstance(error, dict) and set(error) == {"name", "message", "stack"}
            and error["name"] == "Error" and error["message"] == "#<Promise> could not be cloned."
            and isinstance(error["stack"], str), "Native callback return lost its exact actual Promise clone failure")
    registration = delivery["registration"]
    filename = Path(context["runtime"]["runtimeRoot"]) / "dist/file-watcher-DSOr6bb7.mjs"
    text = _compiled_text(str(filename), _digest(filename))
    listener = registration["listenerSource"]
    require(registration["sourceOwner"]["path"] == "dist/file-watcher-DSOr6bb7.mjs"
            and f"{filename}:552:" in registration["originalStack"]
            and listener.startswith("(eventType, filename) => this.enqueueReconciliation(") and listener in text
            and text.count("\tenqueueReconciliation(key, run) {") == 1
            and "if (this.closed) return Promise.resolve();" in text
            and "this.reconciling = pending;\n\t\t}\n\t\treturn this.reconciling;" in text,
            "Native opaque callback return lacks its exact original Promise-returning listener and reconciliation source")
    helpers = [row for row in context["allowedLocal"]
               if Path(row["path"]).name == "forget-index-fence-source-clock.mjs"]
    require(len(helpers) == 1, "Native opaque callback lost its authenticated observer source")
    recorded = Path(helpers[0]["path"])
    require(recorded.is_absolute() and ".." not in recorded.parts and recorded.parent.name == "equivalence",
            "Native opaque callback borrowed another observer source location")
    selected = _adapter_path(recorded, recorded.parent.parent,
                             Path(approved_adapter_root or ROOT).resolve(strict=True))
    helper_bytes = selected.read_bytes()
    require(_sha(helper_bytes) == helpers[0]["sha256"],
            "Native opaque callback observer bytes differ from the independently selected source")
    lines = helper_bytes.decode("utf8").splitlines()
    anchors = {
        "value": "const valueRecord=value=>{try{return{v8Hex:serialize(value).toString('hex')};}catch(error){return{serializationError:errorValue(error)};}};",
        "wrapped": "return deliveries.run(delivery,()=>{try{const result=Reflect.apply(listener,this,values);",
        "returned": "emit('original-watch-delivery-return',{deliveryId:delivery.deliveryId,return:valueRecord(result),returnRef:ref(result),atNs:now()});return result;",
    }
    sites = {}
    for name, anchor in anchors.items():
        matches = [index + 1 for index, line in enumerate(lines) if line.strip() == anchor]
        require(len(matches) == 1,
                "Native opaque callback observer lacks its unique exact serialization call site")
        sites[name] = matches[0]
    require(sites["returned"] == sites["wrapped"] + 1
            and sites["wrapped"] >= 4
            and lines[sites["wrapped"] - 4].strip()
            == "const wrapped=function(...values){const delivery={deliveryId:`${process.pid}:${threadId}:watch-delivery-${++nextDelivery}`,",
            "Native opaque callback serialization escaped its actual native watcher wrapper")
    helper_uri = recorded.as_uri()
    require("at serialize (node:v8:" in error["stack"]
            and f'at valueRecord ({helper_uri}:{sites["value"]}:' in error["stack"]
            and f'at {helper_uri}:{sites["returned"]}:' in error["stack"]
            and f'at FSWatcher.wrapped ({helper_uri}:{sites["wrapped"]}:' in error["stack"]
            and isinstance(returned["returnRef"], str)
            and re.fullmatch(str(pid) + r":0:process-ref-[1-9][0-9]*", returned["returnRef"]) is not None
            and returned["returnRef"] not in {registration["handleRef"], registration["listenerRef"], registration["wrapperRef"]},
            "Native opaque Promise return lost its actual observer serialization boundary or original object identity")


def validate_native_watch_v5(case, raw, actors, commands, passive, context, imports, authority, approved_node, clock,
                             *, approved_adapter_root=None):
    from equivalence.forget_index_fence_evidence import (
        CALL_KINDS, _clock_path, _clock_stat, _compiled_text, _decode_v8, _digest, _native_clock_owner, _native_value,
        _sealed_json,
        _ns, _same, _sha, require,
    )
    from equivalence.forget_index_fence_v5 import validate_case

    validate_case(case)
    protocol = case['input']['observationPolicy']['watchEffects']['protocol']
    require(protocol == 'original-watch-effects-v5', 'Native watcher used another frozen protocol')
    workspace = Path(raw['fixtureBase']) / 'workspace'
    capacity = case['input']['observationPolicy']['watchEffects']['maxReferencesPerBarrier']
    all_rows = {pid: passive[pid, 0] for pid in actors}
    versions, receipts, waits = {}, {}, {}
    wires = set()
    def collect(value):
        if isinstance(value, dict):
            if isinstance(value.get('v8Hex'), str):
                wires.add(value['v8Hex'])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    for rows in all_rows.values():
        for row in rows:
            if row['event'].startswith('original-watch-'):
                collect(row)
    if wires:
        _decode_v8(authority, list(wires), approved_node)

    def fields(actual, expected, message):
        _same({key: actual[key] for key in expected}, expected, message)

    def source(row, pid, filename, stack_word=None):
        _native_clock_owner(row['sourceOwner'], row['originalStack'], context, imports, pid)
        require(row['sourceOwner']['path'] == filename and (stack_word is None or stack_word in row['originalStack']),
                'Native watcher substituted another original source boundary')

    def wire(value):
        return _native_value(value, authority, approved_node)

    # A completed source receipt is a projection of the already authenticated
    # original source clock boundary, not an echo of a watcher command target.
    for child, actor, command, entry in commands.values():
        if command['operation'] not in CALL_KINDS:
            require('sourceVersions' not in entry, 'Native control command manufactured a completed source receipt')
            continue
        if 'settledAtNs' not in entry:
            require('sourceVersions' not in entry, 'An interrupted Native call manufactured completed source versions')
            continue
        receipt = entry['sourceVersions']
        key = CALL_KINDS[command['operation']] + ':' + command['label']
        frame = {'commandId': command['id'], 'actor': child['actor'], 'instance': child['instance'],
                 'pid': child['pid'], 'wallClockNowMs': entry['wallClockNowMs'], 'enteredAtNs': entry['startedAtNs']}
        require(key not in receipts and receipt['callKey'] == key and receipt['actor'] == child['actor']
                and _ns(entry['settledAtNs']) <= _ns(receipt['capturedAtNs']) <= _ns(command['settledAtNs']),
                'Native source targets were recaptured after another call or borrowed another settlement')
        _same(receipt['causalFrame'], frame, 'Native source versions lost their original public entry')
        _same(command['settlement']['sourceVersions'], receipt, 'Native source versions changed across actual IPC settlement')
        boundaries = [row for row in clock['boundaries'] if row['callKey'] == key and row['actor'] == child['actor']]
        require(len(boundaries) == 1, 'Native completed source call lost its one original source clock boundary')
        _same(receipt['boundary'], boundaries[0], 'Native source targets replaced the actual completed IO boundary')
        actual_versions = receipt['versions']
        require(isinstance(actual_versions, list), 'Native source version set was omitted')
        before = {row['path']: row for row in receipt['boundary']['before']}
        after = {row['path']: row for row in receipt['boundary']['after']}
        changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
        # Stat fields can change through observation. Actual source commits,
        # rather than those incidental fields, determine successful mutations.
        owned_commits = [item for item in clock['commits'] if item['callKey'] == key]
        deletions = [row for row in all_rows[child['pid']] if row['event'] == 'source-clock-deletion' and row['callKey'] == key]
        require(len({v['path'] for v in actual_versions}) == len(actual_versions), 'Native call hid distinct source versions at one path')
        expected_paths = {item['path'] for item in owned_commits} | {item['path'] for item in deletions}
        require({v['path'] for v in actual_versions} == expected_paths, 'Native completion omitted an actual committed source mutation')
        for version in actual_versions:
            _clock_path(version['path'], workspace)
            require(version['path'] in changed and version['actor'] == child['actor'] and version['callKey'] == key
                    and _ns(entry['startedAtNs']) < _ns(version['committedAtNs']) <= _ns(receipt['capturedAtNs']),
                    'Native source version borrowed a path or a different original call lifetime')
            _same(version['causalFrame'], frame, 'Native source version changed its actual causal frame')
            body = {name: item for name, item in version.items() if name != 'versionId'}
            require(version['versionId'] == _sha(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()),
                    'Native source version changed its whole original identity seal')
            require(version['versionId'] not in versions, 'Native source version identity was duplicated')
            if version['kind'] == 'file':
                stat = _clock_stat(version['stat'], native=True)
                matches = [item for item in owned_commits if item['path'] == version['path'] and item['sha256'] == version['sha256']]
                require(matches and stat['mtimeNs'] == matches[-1]['mtimeNs'], 'Native watcher target lost its actual clocked publication')
                controls = [part for part in actor['sourceClock']['receipts'] if part['event'] == 'source-clock-control'
                            and part['controlId'] == version['controlId'] and part['callKey'] == key]
                require(len(controls) == 1 and controls[0].get('committed') is True,
                        'Native target borrowed another actual successful source publication control')
                control = controls[0]
                committed_at = (control.get('rename') or {}).get('returnedAtNs') or (control.get('close') or {}).get('finishedAtNs') or control['finishedAtNs']
                require(version['committedAtNs'] == committed_at and control['path'] == version['path'],
                        'Native retained version changed the actual original publication time or path')
                require(version['path'] in after and after[version['path']]['sha256'] == version['sha256'],
                        'Native file target differs from its original completed source boundary')
                _same(after[version['path']]['stat'], version['stat'], 'Native target stat was sampled after the actual source boundary')
            else:
                require(version['kind'] == 'deleted' and version['path'] not in after
                        and len([d for d in deletions if d['path'] == version['path']]) == 1,
                        'Native deletion target lacks its actual original successful unlink and absence')
                deletion = next(d for d in deletions if d['path'] == version['path'])
                require(version['committedAtNs'] == deletion['atNs'] and wire(deletion['return']) == {'privateType': 'undefined'},
                        'Native deletion target changed its successful original void unlink or commit time')
            versions[version['versionId']] = version
        receipts[key] = receipt

    interrupted = {}
    for stopped in raw.get('interruptedSourceCalls', []):
        require(stopped['kind'] == 'original-interrupted-source-call' and 'versions' not in stopped
                and stopped['sourceMutationState'] == 'no-original-source-write-before-held-marker'
                and stopped['callKey'] not in receipts and stopped['callKey'] not in interrupted,
                'Native interrupted call was relabelled as a completed source publication')
        child, actor, command, entry = commands[stopped['commandId']]
        gate = stopped['markerGate']
        require(child['pid'] == stopped['pid'] and child['actor'] == stopped['actor'] and child['instance'] == stopped['instance']
                and command['operation'] == 'original-forget' and stopped['callKey'] == 'forget:' + command['label']
                and 'settlement' not in command and 'settledAtNs' not in entry
                and child['exit'] == {'code': None, 'signal': 'SIGKILL'} and child['kill']['signal'] == 'SIGKILL'
                and gate['killWhileHeld'] is True and 'releasedAtNs' not in gate
                and gate['boundary'] == 'forget.marker-committed-before-purge',
                'Native negative watch target has no actual pending original call killed at the held marker')
        matches = [item for item in raw['gates'] if item['name'] == gate['name']]
        require(len(matches) == 1, 'Native interrupted call borrowed another original marker gate')
        _same(gate, matches[0], 'Native interrupted target changed its full actual marker gate')
        for name in ('kill', 'exit', 'reapedAtNs'):
            _same(stopped[name], child[name], 'Native interrupted source target changed its real process death')
        _same(stopped['termination'], command['termination'], 'Native interrupted source target borrowed another OS termination')
        _same(stopped['originalEntered'], entry['originalEntered'], 'Native interrupted target borrowed another original API entry')
        cutoff = stopped['sourceCallCutoff']
        _same(_sealed_json(stopped['sourceCallCutoffSeal']), cutoff, 'Native interrupted source IO cutoff bytes changed')
        _same(cutoff, gate['receipt']['sourceCallCutoff'], 'Native interrupted target replaced the gate-owned actual IO cutoff')
        frame = {'commandId': command['id'], 'actor': child['actor'], 'instance': child['instance'], 'pid': child['pid'],
                 'wallClockNowMs': entry['wallClockNowMs'], 'enteredAtNs': entry['startedAtNs']}
        _same(cutoff['causalFrame'], frame, 'Native interrupted cutoff lost its original pending producer frame')
        require(cutoff['kind'] == 'original-source-call-cutoff' and cutoff['completed'] is False
                and cutoff['callKey'] == stopped['callKey'] and cutoff['actor'] == child['actor']
                and not cutoff['commits'] and not cutoff['deletions'] and not cutoff['handles'] and not cutoff['failures']
                and _ns(entry['originalEntered']['atNs']) <= _ns(gate['receipt']['enteredAtNs']) <= _ns(cutoff['cutoffAtNs'])
                < _ns(child['kill']['atNs']) < _ns(child['reapedAtNs']) <= _ns(stopped['capturedAtNs'])
                and _ns(child['reapedAtNs']) < _ns(gate['receipt']['enteredAtNs']) + 30_000_000_000,
                'Native interrupted absence has mutations, uncertainty, or an expired original gate hold')
        rows = all_rows[child['pid']]
        actual = [row for row in rows if row['event'] == 'original-source-call-interrupted-cutoff' and row['gate'] == gate['name']]
        require(len(actual) == 1 and actual[0]['gateEnterSequence'] == gate['receipt']['sequence'],
                'Native interrupted source cutoff was not flushed by its original held gate')
        _same(actual[0]['cutoff'], cutoff, 'Native marker cutoff differs from its complete original passive event')
        original_io = [row for row in rows if row['event'] in {'source-clock-read', 'source-clock-read-throw',
                       'source-clock-control', 'source-clock-deletion', 'source-clock-call-boundary', 'source-clock-failure'}
                       and row.get('callKey') == stopped['callKey']]
        require(len(original_io) == len(cutoff['receipts'])
                and not any(row['event'] in {'source-clock-control', 'source-clock-deletion', 'source-clock-call-boundary',
                                            'source-clock-failure'} for row in original_io),
                'Native interrupted IO cutoff omitted an actual source write or original completion')
        for observed, retained in zip(original_io, cutoff['receipts'], strict=True):
            fields(observed, retained, 'Native interrupted cutoff dropped original pending-call source IO')
        interrupted[stopped['callKey']] = stopped

    for pid, (child, actor) in actors.items():
        rows = all_rows[pid]
        def selected(event):
            return [row for row in rows if row['event'] == event]
        installed = selected('original-watch-observer-installed')
        require(len(installed) == 1, 'Native watcher observer installation was omitted or duplicated')
        install = installed[0]
        require(install['protocol'] == protocol and install['timersInvoked'] is False and install['syncMethodsWrapped'] is False
                and install['resourceTypes'] == ['Timeout', 'PROMISE'] and install['storage'] == 'shared-per-thread-immutable-jsonl'
                and install['fsWatchOriginalRef'] != install['fsWatchObserverRef'] and install['emitOriginalRef'] != install['emitObserverRef'],
                'Native watcher replaced its sync/timer algorithm or lost original function identities')
        owner_map = {row['searchEffectsOwnerRef']: row for row in actor['ownerBindings']}
        bindings = {}
        for binding in selected('original-watch-owner-binding'):
            owner = owner_map[binding['ownerRef']]
            sync = [row for row in actor['codeOwners'] if row['name'] == 'MemoryIndexManager.sync']
            require(owner['purpose'] == 'default' and len(sync) == 1 and binding['syncSource'] == sync[0]['functionSource']
                    and binding['syncSha256'] == sync[0]['functionSourceSha256']
                    and binding['originalDirtySha256'] == _sha(binding['originalDirtySource'].encode())
                    and binding['sourceModule'] == 'dist/file-watcher-DSOr6bb7.mjs'
                    and binding['originalDirtyMethodRef'] != binding['observerDirtyMethodRef'],
                    'Native watcher owner lost its actual original sync callable and supported purpose')
            require(binding['watcherRef'] not in bindings, 'Native watcher owner was rebound')
            runtime = Path(context['runtime']['runtimeRoot'])
            dirty_file = runtime / 'dist/file-watcher-DSOr6bb7.mjs'
            manager_file = runtime / 'dist/extensions/memory-core/manager-runtime.js'
            require(binding['originalDirtySource'] in _compiled_text(str(dirty_file), _digest(dirty_file))
                    and binding['onChangeSource'] in _compiled_text(str(manager_file), _digest(manager_file)),
                    'Native watcher dirty/onChange callbacks lost their actual loaded compiled source bodies')
            bindings[binding['watcherRef']] = binding
        deliveries = {r['deliveryId']: r for r in selected('original-watch-delivery-enter')}
        delivery_returns = {r['deliveryId']: r for r in selected('original-watch-delivery-return')}
        handles = {r['handleRef']: r for r in selected('original-watch-handle-created')}
        for handle in handles.values():
            source(handle, pid, 'dist/file-watcher-DSOr6bb7.mjs')
            require(handle['originalMethodRef'] == install['fsWatchOriginalRef'] and handle['listenerRef'] != handle['wrapperRef'],
                    'Native original watcher handle lost its transparent original callback')
        for delivery in deliveries.values():
            if delivery['kind'] == 'native':
                fields(handles[delivery['handleRef']], delivery['registration'], 'Native delivered fact borrowed an unregistered OS handle')
            else:
                require(delivery['kind'] == 'chokidar' and delivery['eventName'] in {'ready', 'add', 'change', 'unlink', 'unlinkDir'}
                        and delivery['originalMethodRef'] == install['emitOriginalRef'], 'Native watcher invented another delivery kind')
                source(delivery, pid, 'index.js') if delivery['sourceOwner']['path'] == 'index.js' else source(delivery, pid, 'node_modules/chokidar/index.js')
            if delivery['deliveryId'] in delivery_returns:
                returned = delivery_returns[delivery['deliveryId']]
                require(_ns(delivery['atNs']) < _ns(returned['atNs']), 'Native delivered callback return preceded its actual invocation')
                if 'v8Hex' in returned['return']:
                    wire(returned['return'])
                else:
                    _opaque_native_reconciliation_return(returned, delivery, context, pid,
                                                          approved_adapter_root=approved_adapter_root)
        source_probes = [row for row in rows if row['event'] in {'source-clock-read', 'source-clock-read-throw'}
                         and 'snapshotPath' in row['originalStack']]
        watch_probes = selected('original-watch-version-stat-return') + selected('original-watch-version-stat-throw')
        require(len(source_probes) == len(watch_probes), 'Native watcher omitted a complete original reconciliation probe')
        for probe in watch_probes:
            matches = [row for row in source_probes if row['path'] == probe['path']
                       and row['startedAtNs'] == probe['startedAtNs'] and row['finishedAtNs'] == probe['finishedAtNs']]
            require(len(matches) == 1, 'Native watcher probe has no unique actual original source read')
            actual = matches[0]
            if probe['event'].endswith('-return'):
                _same(probe['return'], actual['return'], 'Native watcher stat replaced its whole original V8 return')
                decoded = wire(probe['return'])
                require(all(probe[name] == str(decoded[name]) for name in ('size', 'ino', 'dev'))
                        and probe['mtimeMs'] == decoded['mtimeMs'] and probe['ctimeMs'] == decoded['ctimeMs'],
                        'Native watcher stat scalars differ from the complete actual original Stats value')
            else:
                fields(probe, {key: item for key, item in actual.items()
                       if key not in {'event', 'sequence', 'atNs'}},
                       'Native watcher deletion lost its whole actual original source-read exception')

        facts = {r['factId']: r for r in selected('original-watch-fact-return')}
        fact_entries = {r['factId']: r for r in selected('original-watch-fact-enter')}
        for fact in facts.values():
            binding = bindings[fact['watcherRef']]
            fields(fact, {name: item for name, item in fact_entries[fact['factId']].items() if name not in {'event', 'sequence', 'atNs'}}, 'Native delivered dirty fact changed its actual entry arguments')
            require(fact['ownerRef'] == binding['ownerRef'] and fact['originalMethodRef'] == binding['originalDirtyMethodRef']
                    and _ns(fact['enteredAtNs']) < _ns(fact['returnedAtNs']), 'Native fact borrowed another actual owner/callback frame')
            if fact['delivery'] is not None:
                fields(deliveries[fact['delivery']['deliveryId']], fact['delivery'], 'Native fact lost its genuine delivered event ancestry')
            wire(fact['return'])
            for argument in fact['argumentValues']:
                if 'v8Hex' in argument:
                    wire(argument)
        timers = {r['resourceRef']: r for r in selected('original-watch-timer-created')}
        fires = {r['resourceRef']: r for r in selected('original-watch-timer-fire')}
        for timer in timers.values():
            source(timer, pid, 'dist/file-watcher-DSOr6bb7.mjs', 'scheduleWatchSync')
            require(':234:' in timer['originalStack'] and timer['kind'] == 'watch-timer' and timer['fired'] is False,
                    'Native watcher timer was guessed or manually invoked')
        promises = {r['promiseRef']: r for r in selected('original-watch-promise-created')}
        settlements = {r['promiseRef']: r for r in selected('original-watch-promise-settlement')}
        for promise in promises.values():
            binding = bindings[promise['watcherRef']]
            source(promise, pid, 'dist/extensions/memory-core/manager-runtime.js')
            require(':5508:' in promise['originalStack'] and ':1541:' in promise['originalStack']
                    and promise['kind'] == 'watch-sync' and promise['ownerRef'] == binding['ownerRef']
                    and promise['syncMethodRef'] == binding['syncMethodRef'] and promise['onChangeRef'] == binding['onChangeRef']
                    and promise['promiseConstructorRef'] == install['promiseClassRef']
                    and promise['promisePrototypeRef'] == install['promisePrototypeRef']
                    and any(t['asyncId'] in promise['asyncAncestry'] for t in fires.values()
                            if t.get('watcherRef') == promise['watcherRef']),
                    'Native inner sync Promise lost its exact original method/owner/timer ancestry')
        ready_owners = set()
        for command_id, (command_child, _, command, entry) in commands.items():
            if command_child['pid'] != pid or command['operation'] not in {'await-original-watch-ready', 'await-original-watch-effects'}:
                continue
            receipt = entry['watchEffects']
            kind = 'ready' if command['operation'].endswith('-ready') else 'effects'
            require(receipt['protocol'] == protocol and receipt['kind'] == kind and receipt['label'] == command['label']
                    and _ns(command['startedAtNs']) <= _ns(receipt['startedAtNs']) < _ns(receipt['finishedAtNs']) <= _ns(command['settledAtNs']),
                    'Native watch barrier lost its actual command interval')
            matches = [r for r in selected('original-watch-' + kind + '-return') if r['label'] == receipt['label']]
            require(len(matches) == 1, 'Native watcher barrier omitted its actual returned event')
            fields(matches[0], receipt, 'Native watcher command replaced the full actual original wait return')
            if kind == 'effects':
                _same(command['request']['sourceVersions'], receipt['versions'], 'Native watch wait recaptured targets instead of retaining call-completion versions')
            require(len(receipt['owners']) <= capacity, 'Native watcher barrier exceeded its declared reference capacity')
            for owner in receipt['owners']:
                bound = owner_map[owner['ownerRef']]
                if owner.get('absence') in {'original-transient-owner', 'original-no-local-file-watcher'}:
                    require(owner['purpose'] == bound['purpose'] and (bound['purpose'] != 'default' or owner['absence'] == 'original-no-local-file-watcher'),
                            'Native observer fabricated absence for an actual watcher owner')
                    continue
                binding = bindings[owner['watcherRef']]
                require(binding['ownerRef'] == owner['ownerRef'], 'Native barrier borrowed another watcher owner')
                if kind == 'ready':
                    require(owner['starting']['promiseRef'] in settlements and owner['starting']['kind'] == 'watch-starting'
                            and owner['starting']['ownerRef'] == owner['ownerRef'] and owner['starting']['watcherRef'] == owner['watcherRef']
                            and settlements[owner['starting']['promiseRef']]['settlement']['status'] == 'fulfilled',
                            'Native watcher startup never actually fulfilled')
                    fields(settlements[owner['starting']['promiseRef']], owner['starting'],
                           'Native startup Promise was replaced by another actual original resource')
                    if owner['ready'] is not None:
                        fields(deliveries[owner['ready']['deliveryId']], owner['ready'], 'Native readiness replaced its original chokidar event')
                        require(owner['ready']['eventName'] == 'ready' and owner['ready']['emitterRef'] == owner['chokidarRef'],
                                'Native readiness belongs to another original handle')
                    require(owner['ready'] is not None or owner['nativeHandles'], 'An empty Native watcher state was substituted for readiness')
                    for handle in owner['nativeHandles']:
                        fields(handles[handle['handleRef']], handle, 'Native readiness lost its actual OS watcher registration')
                    ready_owners.add(owner['watcherRef'])
                    continue
                require(owner['watcherRef'] in ready_owners, 'Native original watcher was not ready before its effects barrier')
                _same(owner['versions'], receipt['versions'], 'Native watcher owner omitted retained workspace targets')
                if not owner['versions']:
                    require(owner.get('absence') in {'no-actual-declared-source-mutations', 'original-call-interrupted-before-source-publication'},
                            'Native empty target list was claimed as positive watcher delivery')
                    continue
                require(len(owner['facts']) == len(owner['versions']) and owner['states'] and len(owner['states']) <= capacity,
                        'Native watcher target lacks genuine delivery facts and original pending-state history')
                for target, proof in zip(owner['versions'], owner['facts'], strict=True):
                    _same(target, versions[target['versionId']], 'Native watcher substituted an uncommitted source version')
                    fact = facts[proof['factId']]
                    require(proof['versionId'] == target['versionId'] and fact['path'] == target['path']
                            and fact['delivery']['deliveryId'] == proof['deliveryId']
                            and _ns(fact['returnedAtNs']) >= _ns(target['committedAtNs']),
                            'Native watcher fact preceded or borrowed another committed version')
                    probes = [r for r in rows if r['event'] in {'original-watch-version-stat-return', 'original-watch-version-stat-throw'}
                              and r['path'] == target['path'] and _ns(r['finishedAtNs']) >= _ns(fact['enteredAtNs'])]
                    for probe in probes:
                        _native_clock_owner(probe['sourceOwner'], probe['originalStack'], context, imports, pid)
                        require('snapshotPath' in probe['originalStack'], 'Native watcher version probe was not an actual original reconciliation read')
                    if target['kind'] == 'file':
                        require(any(r['event'].endswith('-return') and r['size'] == target['stat']['size'] and r['ino'] == target['stat']['ino']
                                    and r['dev'] == target['stat']['dev'] and int(target['stat']['mtimeNs']) % 1_000_000 == 0
                                    and r['mtimeMs'] == int(target['stat']['mtimeNs']) // 1_000_000 for r in probes),
                                'Native watcher never actually observed the retained file version')
                    else:
                        require(any(r['event'].endswith('-throw') and r['error'].get('code') == 'ENOENT' for r in probes),
                                'Native watcher deletion lacks a genuine original absence probe')
                require(len(owner['promises']) <= capacity and len(owner['timers']) <= capacity,
                        'Native watcher joined more original references than the declared capacity')
                for timer in owner['timers']:
                    require(timer['resourceRef'] in timers and timer.get('watcherRef') == owner['watcherRef']
                            and any(all(event.get(key) == item for key, item in timer.items()) for event in rows
                                    if event['event'].startswith('original-watch-timer-')
                                    and event.get('resourceRef') == timer['resourceRef']),
                            'Native watch wait changed an actual original timer lifecycle or successor')
                for state in owner['states']:
                    require(any(all(event.get(key) == item for key, item in state.items()) for event in rows
                                if event['event'] == 'original-watch-state-read'),
                            'Native watch wait replaced actual original pending-state reads')
                for item in owner['promises']:
                    returned = settlements[item['promiseRef']]
                    fields(returned, item, 'Native watch wait changed its complete actual Promise settlement')
                    settlement = item['settlement']
                    require(_ns(settlement['atNs']) <= _ns(owner['finishedAtNs']), 'Native watch wait returned before the original Promise settled')
                    wire(settlement['value'] if settlement['status'] == 'fulfilled' else settlement['privateError'])
                require(any(item['promiseRef'] in promises and item['kind'] == 'watch-sync' for item in owner['promises']),
                        'Native positive delivery has no actual original inner sync Promise')
                final = owner['states'][-1]
                require(final['pendingChange'] is False and final['reconcileAll'] is False and not final['timerRef']
                        and not final['reconcilingRef'] and not final['settlingRef']
                        and wire(final['pendingPaths']) == {'privateType': 'Map', 'entries': []}
                        and wire(final['pendingReconciliations']) == {'privateType': 'Map', 'entries': []},
                        'Native barrier returned while its admitted original watcher work was still pending')
            waits[command_id] = receipt

    # Every frozen actor is either contacted in its genuine live epoch or has
    # a source/lifecycle absence record; never infer absence from missing output.
    for step in raw['steps']:
        spec = step['step']
        if spec['operation'] not in {'await-original-watch-ready', 'await-original-watch-effects'}:
            continue
        active = [(child, command, entry) for child, _, command, entry in commands.values()
                  if command['operation'] == spec['operation'] and command['label'] == spec['label']]
        absence = step['watchAbsences']
        require(len({child['actor'] for child, _, _ in active}) == len(active)
                and {child['actor'] for child, _, _ in active}.isdisjoint({row['actor'] for row in absence})
                and {child['actor'] for child, _, _ in active} | {row['actor'] for row in absence} == set(spec['actors']),
                'Native watch step omitted or duplicated a declared actor lifecycle')
        for child, command, entry in active:
            require(_ns(step['startedAtNs']) <= _ns(command['startedAtNs']) < _ns(command['settledAtNs']) <= _ns(step['finishedAtNs'])
                    and command['id'] in waits, 'Native watch command escaped its declared coordinator step')
            if spec['operation'].endswith('-effects'):
                expected = [receipts[key] for key in spec['afterCalls'] if key in receipts]
                _same(command['request']['sourceVersionReceipts'], expected, 'Native watcher target receipts differ from genuine completed public calls')
                _same(command['request']['sourceVersions'], [v for receipt in expected for v in receipt['versions']],
                      'Native watcher flattened target list omitted or replaced actual source versions')
                negative = [interrupted[key] for key in spec['afterCalls'] if key in interrupted]
                _same(command['request'].get('interruptedSourceCalls', []), negative,
                      'Native watcher interruption inputs differ from genuine held-frame/OS-reap evidence')
                require(len(expected) + len(negative) == len(spec['afterCalls']),
                        'Native watcher silently omitted a completed or interrupted original call')
                if negative:
                    _same(entry['watchEffects']['interruptedSourceCalls'], negative,
                          'Native watcher wait omitted its separate actual interruption absence evidence')
        for row in absence:
            require(row['reason'] == 'actual-process-unentered-or-reaped'
                    and _ns(step['startedAtNs']) <= _ns(row['atNs']) <= _ns(step['finishedAtNs'])
                    and not any(child['actor'] == row['actor'] and _ns(child['startedAtNs']) < _ns(row['atNs']) < _ns(child['reapedAtNs'])
                                for child, _ in actors.values()), 'Native watcher absence hid a genuinely live original process')
    return {'waits': waits, 'versions': versions}
