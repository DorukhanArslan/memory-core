// Offline model transport only. The public dispatcher, session store, history repair,
// write tools and delivery path are the shipped OpenClaw implementations.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { mock } from 'node:test';

const [specPath, phase] = process.argv.slice(2);
const { input, runtimeRoot, root } = JSON.parse(fs.readFileSync(specPath));
const workspace = path.join(root, 'workspace');
const bridge = Symbol.for('memory-core.equivalence.host-turn-barrier-provider');
const provider = 'fixture-turn-barrier-model';
const modelId = 'scripted-turn-barrier-model';
const pluginPath = fileURLToPath(new URL('./host-turn-barrier-provider/index.mjs', import.meta.url));
const load = relative => import(pathToFileURL(path.join(runtimeRoot, 'dist', relative)).href);
const snapshot = value => JSON.parse(JSON.stringify(value));
mock.timers.enable({ apis: ['Date'], now: input.nowMs });

const cfg = {
  logging: { level: 'silent', consoleLevel: 'silent', file: path.join(root, 'native.log') },
  plugins: { allow: [provider, 'memory-core'], load: { paths: [pluginPath] },
    entries: { [provider]: { enabled: true }, 'memory-core': { enabled: true } }, slots: { memory: 'memory-core' } },
  agents: { list: [{ id: input.identity.agentId, default: true, workspace, agentDir: path.join(root, 'agent') }],
    defaults: { workspace, skipBootstrap: true, model: { primary: `${provider}/${modelId}` },
      compaction: { enabled: false, memoryFlush: { enabled: false } } } },
  session: { store: path.join(root, 'sessions.json'), maintenance: { mode: 'warn' } },
  tools: { profile: 'coding', loopDetection: { enabled: false }, fs: { workspaceOnly: true } },
  memory: { citations: 'off', search: { enabled: false } },
  models: { providers: { [provider]: { api: 'openai-completions', baseUrl: 'http://127.0.0.1:1/v1',
    apiKey: 'fixture-not-a-credential', models: [{ id: modelId, name: 'Offline recovery model', api: 'openai-completions',
      reasoning: false, input: ['text'], contextWindow: 262144, maxTokens: 4096,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] } } },
};
fs.mkdirSync(workspace, { recursive: true });
fs.mkdirSync(path.join(root, 'agent'), { recursive: true });
fs.writeFileSync(process.env.OPENCLAW_CONFIG_PATH, JSON.stringify(cfg));
const { agentId, sessionKey, sessionId } = input.identity;
const scope = { agentId, sessionKey, storePath: cfg.session.store };
const raw = { phase, input, pid: process.pid, ppid: process.ppid, node: process.execPath, scope,
  calls: [], events: [], deliveries: [], pluginEvents: [], closeReceipts: [] };
const receipt = path.join(root, `${phase}.json`);
const observedPaths = [input.original.relativePath, input.followup.write?.relativePath ?? 'memory/2026-11-27.md'];
function files() {
  return Object.fromEntries(observedPaths.map(relative => {
    const file = path.join(workspace, relative);
    try { return [relative, fs.readFileSync(file).toString('base64')]; }
    catch (error) { if (error.code !== 'ENOENT') throw error; return [relative, null]; }
  }));
}
let sessions, scheduler, unsubscribe, disposeMcp, closeManagers, closeDatabases, clearConfig;
function state() {
  return { entry: sessions.loadSessionEntry(scope),
    transcript: sessions.loadTranscriptEventsSync({ ...scope, sessionId }), files: files() };
}
function save() { fs.writeFileSync(receipt, JSON.stringify(raw), { flag: 'wx', mode: 0o600 }); }
try {
  const { x: createStream } = await load('llm-ASoRyt-k.mjs');
  globalThis[bridge] = { progress: event => raw.pluginEvents.push(event), stream(model, context) {
    const i = raw.calls.length;
    if (i > 1) throw Error('Unexpected third inference');
    const write = phase === 'cut' ? input.original : input.followup.write;
    const tool = i === 0 && write;
    const message = { role: 'assistant', content: tool
      ? [{ type: 'toolCall', id: write.callId, name: 'write', arguments: { path: write.relativePath, content: write.content } }]
      : [{ type: 'text', text: input.followup.reply }],
      api: model.api, provider: model.provider, model: model.id, stopReason: tool ? 'toolUse' : 'stop',
      timestamp: Date.now(), usage: { input: 24, output: 4, cacheRead: 0, cacheWrite: 0, totalTokens: 28,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
    raw.calls.push({ messages: snapshot(context.messages), response: snapshot(message) });
    const result = createStream();
    queueMicrotask(() => { result.push({ type: 'done', reason: message.stopReason, message }); result.end(message); });
    return result;
  } };
  const config = await load('plugin-sdk/config-runtime.js');
  config.setRuntimeConfigSnapshot(cfg); clearConfig = config.clearRuntimeConfigSnapshot;
  const { w: setRegistry } = await load('runtime-9cxii0oQ.mjs');
  const { t: emptyRegistry } = await load('registry-empty-BTjzcMW2.mjs');
  setRegistry(emptyRegistry(), 'startup-registry', 'gateway-bindable', workspace);
  const { t: GatewayScheduler } = await load('gateway-scheduler-TywODsdc.mjs');
  scheduler = new GatewayScheduler();
  const mcp = await load('agent-bundle-mcp-manager-api--Y4zt2wo.mjs');
  await mcp.p(scheduler); disposeMcp = mcp.i;
  const { o: metadataSnapshot } = await load('plugin-metadata-snapshot-DT_pRp6g.mjs');
  const { t: loadRegistry } = await load('loader-DpAS3szV.mjs');
  const metadata = metadataSnapshot({ config: cfg, workspaceDir: workspace });
  const registry = loadRegistry({ config: cfg, workspaceDir: workspace, manifestRegistry: metadata.manifestRegistry,
    discovery: metadata.discovery, onlyPluginIds: [provider, 'memory-core'],
    runtimeOptions: { allowGatewaySubagentBinding: true }, cache: false, throwOnLoadError: true });
  raw.providers = registry.providers.map(item => item.provider.id);
  sessions = await load('session-accessor-CiKKTlbe.mjs');
  const { t: createHeader } = await load('transcript-header-CP-ow2Zr.mjs');
  const { n: dispatch } = await load('dispatch-from-config-BG9rT_X3.mjs');
  const { i: createDispatcher } = await load('reply-dispatcher-XbSXLzuk.mjs');
  closeManagers = (await load('extensions/memory-core/manager-runtime.js')).closeAllMemoryIndexManagers;
  closeDatabases = (await load('openclaw-agent-db-lifecycle-B8sSLgPo.mjs')).s;
  if (phase === 'cut') {
    await sessions.replaceSessionEntry(scope, { sessionId, updatedAt: input.nowMs, compactionCount: 0 });
    await sessions.replaceTranscriptEvents({ ...scope, sessionId }, [createHeader({ sessionId, cwd: workspace })]);
  }
  raw.before = state();
  const events = await load('agent-events-CwU5G442.mjs');
  unsubscribe = events.f(event => {
    if (event.stream !== 'tool') return;
    raw.events.push(snapshot(event));
    if (phase === 'cut' && event.data?.name === 'write' && event.data.toolCallId === input.original.callId
        && event.data.phase === (input.cut === 'before-write' ? 'start' : 'result')) {
      raw.after = state(); save(); process.kill(process.pid, 'SIGKILL');
    }
  });
  const prompt = phase === 'cut' ? input.original.prompt : input.followup.prompt;
  const dispatcher = createDispatcher({ deliver: async (payload, info) => {
    raw.deliveries.push(snapshot({ payload, info })); return true;
  } });
  try {
    raw.dispatch = await dispatch({ cfg, dispatcher, ctx: { Body: prompt, RawBody: prompt, BodyForAgent: prompt,
      BodyForCommands: prompt, SessionKey: sessionKey, From: 'fixture-user', To: sessionKey,
      Provider: 'webchat', Surface: 'webchat', ChatType: 'direct', SenderId: 'fixture-user', CommandAuthorized: true,
      MessageSid: `fixture-recovery-${phase}` } });
  } finally { dispatcher.markComplete(); await dispatcher.waitForIdle(); }
  if (phase === 'cut') throw Error('The original write did not reach its specified interruption');
  raw.after = state();
} finally {
  unsubscribe?.();
  for (const [name, close] of [['memory', closeManagers], ['mcp', disposeMcp],
    ['scheduler', scheduler && (() => scheduler.stop())], ['sessions', closeDatabases]]) {
    if (close) { await close(); raw.closeReceipts.push(name); }
  }
  clearConfig?.(); delete globalThis[bridge];
}
save();
process.exit(0);
