"""Authenticate the published managed hook, its registrations and durable owners."""
from pathlib import Path

from equivalence.dream_light_bindings import COMPILED, SOURCE
from equivalence.reference_bindings import _git
from equivalence.session_admission_runtime_bindings import REFERENCE_COMMIT, _owners


EXTRA_SOURCE = {'extensions/memory-core/index.ts': ('407649ff3005ec692a1c3d15e7e599692e693bf3e6ccbdc7e4aa18755deddd89', ('  register(api) {',)),
 'extensions/memory-core/src/dreaming.ts': ('b6a6bc5351f4d54db3a7d313c9a5bd8ec0219c7badad755d1c416c935b9e6523',
                                            ('function runShortTermDreamingPromotion(',
                                             'function registerShortTermPromotionDreaming(')),
 'extensions/memory-core/src/memory-entry-origins.ts': ('d84877d05b1621d554260c23b3d4678eb184ffce9ad7fd0255abee67ac3ad0d7',
                                                        ('function listMemoryEntryOrigins(',
                                                         'function recordMemoryEntryOrigins(')),
 'src/plugins/runtime/system-events.ts': ('8e2ff1746191d061429c363a2ec63eae8de80cc7a82244e70525bc6fc951b148',
                                          ('export const enqueueSystemEventFromSdk = (',)),
 'extensions/memory-core/src/dreaming-consolidation.ts': ('fd6639fac416d17d0dc96464bb4abdfd023e81d65a861a2264fbfdc41b107a8b',
                                                          ('function consolidateMemory(',)),
 'extensions/memory-core/src/short-term-promotion-apply.ts': ('914fb4c452d358540e138a09681b262d1932e6c5f8c2303ab3de9b0e992f522a',
                                                              ('function applyShortTermPromotions(',))}

EXTRA_COMPILED = {'dist/extensions/memory-core/index.js': ('ead9aeb06b76504ba8ab9cb50a03c1425d18cbb936285c47f5ae7cf25e2877f8',
                                          ('register(api) {',
                                           'function runShortTermDreamingPromotion(',
                                           'function registerShortTermPromotionDreaming(')),
 'dist/memory-entry-origins-BCQSIB3X.mjs': ('35506e30b05eb6ebc688b90688b449d06c2a01ffabb0348c1eaa1b1f9d0fd37d',
                                            ('function listMemoryEntryOrigins(', 'function recordMemoryEntryOrigins(')),
 'dist/system-events-aMYQfkLb.mjs': ('140e8a1fe3b117240dd6cedfa34a19d531e371de8b2da0501853649973e38c02',
                                     ('const enqueueSystemEventFromSdk = (',)),
 'dist/short-term-promotion-MX1vHJuE.mjs': ('be3114e9aa8c448bdeedbd750b41b25ac06bc00ad8a728edb70db376aa3bc1da',
                                            ('function consolidateMemory(', 'function applyShortTermPromotions(')),
 'dist/dreaming-narrative-B8Hp3Mc_.mjs': ('db2106633d04a70616bb0b9596d9c35f506d984312325f57e6a32fbfbf46ed79',
                                          ('function generateAndAppendDreamNarrative(',))}

OWNERS = {'register': ('dist/extensions/memory-core/index.js',
              'default.register',
              '345e63a1e93658ce908d1d6548ec5817f75ae43afc525daa5b2be4dedf8e1b25'),
 'createPluginStateKeyedStore': ('dist/plugin-state-store-BPUaLoVD.mjs',
                                 'r',
                                 '3c4f0e6163afd4d4f9462fe11b1c18410332764b5ea591361ed6c66034d0c203'),
 'closePluginStateDatabaseAsync': ('dist/plugin-state-store-BPUaLoVD.mjs',
                                   'u',
                                   'c648b6b2311377ff1d43593a21ce37b67b4d8b9bce744aae495049043b99da92'),
 'readStore': ('dist/short-term-promotion-store-B6T388Bo.mjs',
               'a',
               '263f66124da587c26023e24360703445ae5cf3ed9d1dca87d91df5591f0f4ae9'),
 'readPhaseSignalStore': ('dist/short-term-promotion-store-B6T388Bo.mjs',
                          'r',
                          '5f389e8532f7870d6e511e502f09d72a2c6723e3f1dba1f23366552157edbfb2'),
 'readShortTermStore': ('dist/short-term-promotion-store-B6T388Bo.mjs',
                        'i',
                        '4c9ea7bd8a2d4bb40f607296fce8c0332eb6b0f255b1f578fa2c56bf39285c84'),
 'readMemoryHostEventRecords': ('dist/plugin-sdk/memory-host-events.js',
                                'readMemoryHostEventRecords',
                                '60d1b7c8011d88df7ab3d057a30c2983a4614e9a327dbc91fb1ddcb748b7c4d9'),
 'listMemoryEntryOrigins': ('dist/memory-entry-origins-BCQSIB3X.mjs',
                            'n',
                            'b882bddcfcc9a57a514529a215c629c0c7394342c8eb1dce4f7657be89dd3f18'),
 'readMemoryCoreWorkspaceEntries': ('dist/dreaming-state-VYUvbU-n.mjs',
                                    'y',
                                    'a4c7221642a0dd48ac944f6708d9375e3065423fd6749270cf4bb744a5fe461f'),
 'enqueueSystemEventFromSdk': ('dist/system-events-aMYQfkLb.mjs',
                               'o',
                               'd58ce42ebf67da54d3d7027680e7796feefb86877eaf481d690f82c09d3afa06'),
 'writeStore': ('dist/short-term-promotion-store-B6T388Bo.mjs',
                'l',
                'e1ebaa231556530f68fdf65c1cc227ba1140aef0b875be10c621ea3dbfecdb0e'),
 'recordMemoryEntryOrigins': ('dist/memory-entry-origins-BCQSIB3X.mjs',
                              'a',
                              '37f5fef0ba36e38d8e2d08ad059ed6acb7ef5d74e4aa5700bee35a4b8b3bb1cd'),
 'writePhaseSignalStore': ('dist/short-term-promotion-store-B6T388Bo.mjs',
                           'c',
                           'b8a8e4c14df57c38af559a55767cc37843184927a8df5d9d8c8acd502ad46135')}

REGISTRATIONS = [{'name': 'gateway_start', 'sourceSha256': '10d250c1cd0a4679ce9c4a2106903499824921b7b04c4fb511a0156e0d4f474c'},
 {'name': 'before_agent_reply',
  'opts': {'eligibleTriggers': ['heartbeat', 'cron']},
  'sourceSha256': 'c7cff6aa18bc094b163b03b9717c7061e543a6f50fe9f2e820de5558b69538c9'},
 {'name': 'before_prompt_build', 'sourceSha256': 'dc27fe046967d4c48f42c7415f390ae4ce79bfb89c0ae059b2cbcb2d8e3a8708'},
 {'name': 'before_agent_reply',
  'opts': {'eligibleTriggers': ['heartbeat', 'cron']},
  'sourceSha256': '9ec461173b796f9a69eccfd452d934e5c1c3297d927a587c4c89dd92bba5eb6e'}]
HOOK = REGISTRATIONS[1]["sourceSha256"]
PHASE_MODULE = "dist/dreaming-phases-rmgXNBLP.mjs"
APPLY_MODULE = "dist/short-term-promotion-MX1vHJuE.mjs"
NARRATIVE_MODULE = "dist/dreaming-narrative-B8Hp3Mc_.mjs"
MODULES = {**COMPILED, **EXTRA_COMPILED}


def required_modules(case):
    opts = case["input"]["options"]
    paths = {entry[0] for entry in OWNERS.values()}
    paths.update(p for p in COMPILED if "worker" in p or p.endswith("memory-host-events-C8-U38f1.mjs"))
    if opts["enabled"] and opts["limit"] > 0:
        paths.add(APPLY_MODULE)
        if opts["light"] or opts["rem"]:
            paths.add(PHASE_MODULE)
        if case["input"]["provider"]:
            paths.add(NARRATIVE_MODULE)
    return paths


def prepare_deep_bindings(checkout, runtime_root):
    checkout, runtime_root = Path(checkout).resolve(), Path(runtime_root).resolve()
    if _git(checkout, "rev-parse", "HEAD").decode().strip() != REFERENCE_COMMIT:
        raise ValueError("Managed deep dreaming requires the pinned OpenClaw commit")
    def verified(root, table, committed):
        return _owners(root, {p: v[0] for p, v in table.items()},
                       {p: v[1] for p, v in table.items()}, committed=committed)[1]
    return {"kind": "official-managed-deep-hook", "referenceCommit": REFERENCE_COMMIT,
            "sourceBindings": verified(checkout, {**SOURCE, **EXTRA_SOURCE}, True),
            "compiledBindings": verified(runtime_root, MODULES, False),
            "entryPoint": {"artifact": "dist/extensions/memory-core/index.js", "export": "default.register",
                           "event": "before_agent_reply", "hookSha256": HOOK},
            "sourceBuildReproduced": False, "sourceFallbackAllowed": False}
