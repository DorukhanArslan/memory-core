// Literal delivery-only model and files for the automatic production flush runner.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import { closeSync, constants, fstatSync, lstatSync, openSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { observeFlushSelection } from "./flush-plan-selection.mjs";
import { runFlushExecution } from "./flush-execution.mjs";

const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === "object"
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
const approved = new Set([
  "2e3c16ba3abb807631e33f03bd54ebbd302274f72fb40d686dd0c1c9f9c0aa8a",
  "62500080bab5d20d760e338183dc52d0dee1367e0e8b3e85348e571574bad06c",
  "deedc4eadeca362d9bbc940635396bec2eea3e2a5e3846856b7e67805f308c84",
  "acd78811c14108ec726ac8e44c5ad4c3eb0ef96712abd8501c043a438d230158",
  "72f0788ca475507cc888b1fb30c9468b05180a7b91c11b688948a33f1bedf0cf",
  "0240a18b30c8daf3f5a987254af5e766126872b4603831c28cd54e0481bd5235",
  "1ed1fa25df1fb46a747e5bee6a3efb484e5603aa744c55d2078e3f0db2ea1e73",
  "7f56322d4048af230c479558aa68c13c119624094641223d664a0d1cbb59111b",
  "da2ad3e8c0e9c05bb142da75829fae7bd8b5dd01b89ecc39321039bebc6eb522",
  "7d62e05a04ffb40f263e980c6c917906e780042a930e44f4c0af8d8cf63b24ab",
  "55a1af4b61fcf1c73dc79879daba02b0e32753914ea0f082554620add890e046",
  "0000099ff54f7abd0d7ef80047844bdb503667ba252ebdd9bc081b3bf8b05ed1",
  "4f309babd19d21467c85bf1917a7093e06f07ed784e65bc8ea714ddaeec35b1b"
]);
const boundaries = new Set([
  "c18ee0c441206ccc5283171bd96cbe21b2079e1762cf61c3ea0edd30dc328e94",
  "e4256f085c00122aea01d8662f76c4b97c60c6754251276b55d360fcb789c7fd",
  "67a374e9bca404d3f3b034da119e2df5eeeffd3d90d45b0a11e23502c2068679",
]);

export async function runFlushPlanTarget(input, runtime) {
  const inputHash = createHash("sha256").update(JSON.stringify(stable(input))).digest("hex");
  if (!approved.has(inputHash) && !boundaries.has(inputHash)) {
    throw Error("Memory flush requires an exact bound input before filesystem setup");
  }
  const evidence = runtime.evidenceDirectory;
  if (!path.isAbsolute(evidence)) throw Error("Missing owned evidence directory");
  await fs.mkdir(evidence, {recursive: true});
  const state = {kind: "native-flush-plan-target", input, plans: [], modelStarts: [],
    process: {pid: process.pid, ppid: process.ppid, executable: process.execPath, version: process.version,
      sha256: createHash("sha256").update(await fs.readFile(process.execPath)).digest("hex")}};
  const pair = input.readOnlyAlias;
  const names = pair ? Object.values(pair).sort() : [];
  if (pair) state.aliasWitnesses = [];
  function filesystem(workspace) {
    const tree = {};
    const witness = {};
    function visit(target) {
      const relative = path.relative(workspace, target);
      const info = lstatSync(target);
      if (info.isDirectory()) {
        if (relative) tree[relative] = {kind: "directory"};
        for (const name of readdirSync(target).sort()) visit(path.join(target, name));
      } else if (names.includes(relative)) {
        const fd = openSync(target, constants.O_RDONLY | constants.O_NOFOLLOW);
        try {
          const stat = fstatSync(fd, {bigint: true});
          if (!stat.isFile() || stat.nlink !== 2n || stat.size > 4n * 1024n * 1024n) {
            throw Error("Missing read-only note pair");
          }
          witness[relative === pair.target ? "target" : "alias"] = {
            dev: stat.dev.toString(), ino: stat.ino.toString(), nlink: Number(stat.nlink),
          };
          tree[relative] = {kind: "file", base64: readFileSync(fd).toString("base64"), linkedAs: names};
        } finally { closeSync(fd); }
      } else if (info.isFile() && info.size <= 4 * 1024 * 1024 && info.nlink === 1) {
        tree[relative] = {kind: "file", base64: readFileSync(target).toString("base64")};
      } else {
        throw Error("Unreviewed fixture file");
      }
    }
    visit(workspace);
    if (pair) {
      if (!witness.target || !witness.alias || witness.target.ino !== witness.alias.ino || witness.target.dev !== witness.alias.dev) {
        throw Error("The two read-only paths no longer refer to the original file");
      }
      state.aliasWitnesses.push(witness);
    }
    return tree;
  }
  const observe = {
    captureReplies: boundaries.has(inputHash),
    snapshot: filesystem,
    setup: async (workspace, cfg, provider) => {
      state.workspace = workspace;
      cfg.agents.defaults.userTimezone = input.timezone;
      cfg.agents.defaults.contextTokens = input.contextWindowTokens;
      cfg.agents.defaults.compaction.memoryFlush = input.flush;
      cfg.agents.defaults.model.fallbacks = input.fallbacks.map(id => provider + "/" + id);
      const models = cfg.models.providers[provider].models;
      models[0].contextWindow = input.contextWindowTokens;
      for (const id of new Set([...input.fallbacks, ...Object.keys(input.responses)])) {
        if (id !== models[0].id) models.push({...models[0], id, name: id});
      }
      for (const relative of input.directories) await fs.mkdir(path.join(workspace, relative), {recursive: true});
      for (const [relative, text] of Object.entries(input.files)) {
        await fs.mkdir(path.dirname(path.join(workspace, relative)), {recursive: true});
        await fs.writeFile(path.join(workspace, relative), text, {flag: "wx"});
      }
      if (pair) await fs.link(path.join(workspace, pair.target), path.join(workspace, pair.alias));
      state.cfg = structuredClone(cfg);
      state.initial = await filesystem(workspace);
    },
    plan: (args, result, nativePlan) => state.plans.push({owner: {name: nativePlan.name,
      sha256: createHash("sha256").update(Function.prototype.toString.call(nativePlan)).digest("hex")}, args: {nowMs: args.nowMs, contextWindowTokens: args.contextWindowTokens},
                                              result: structuredClone(result)}),
    reply: model => {
      const answer = input.responses[model.id];
      if (answer === "NO_REPLY") return {text: answer};
      if (answer === "unavailable") return {error: "429 rate limit for selected fixture model"};
      throw Error("Unexpected model selection in bound fixture");
    },
    finish: async ({workspace, result, before, modelCalls, toolEvents, progress, pluginRegistryProof, visibleErrors, persisted, source}) => {
      Object.assign(state, {visibleErrors, persisted, source});
      state.before = before;
      state.modelStarts = structuredClone(modelCalls);
      if (boundaries.has(inputHash)) state.toolResults = structuredClone(toolEvents);
      state.result = structuredClone(result);
      state.final = filesystem(workspace);
      const retained = path.join(evidence, "workspace");
      if (pair) await fs.rename(workspace, retained);
      else await fs.cp(workspace, retained, {recursive: true, errorOnExist: true, force: false});
      state.progress = structuredClone(progress);
      state.pluginRegistryProof = pluginRegistryProof;
    },
  };
  const routing = await observeFlushSelection(runtime.runtimeRoot);
  state.routing = routing.evidence;
  try {
    await runFlushExecution({nowMs: input.nowMs, sourceMessages: [{role: "user", content: "Remember my field note."}],
      steps: [{label: "prepare daily note", replies: []}]}, runtime, observe);
    const receipts = state.routing.receipts;
    if (state.routing.errors.length) throw Error("The native flush model selection could not be observed");
    const selection = receipts.filter(r => r.site === "selection");
    if (selection.length > 1) throw Error("Unexpected repeated native model selection");
    return {provider: "none", plans: state.plans.map(p => p.result), selection: selection[0]?.values ?? null,
      candidates: receipts.filter(r => r.site === "candidate").map(r => r.values),
      ...(boundaries.has(inputHash) && {replies: state.modelStarts.flatMap(call =>
        call.emittedAssistant.content.filter(block => block.type === "text").map(block => block.text))}),
      outcome: state.result.outcome, stamp: state.result.sessionEntry.memoryFlush ?? null, files: state.final};
  } catch (error) {
    state.error = {name: error.name, message: error.message, stack: error.stack};
    throw error;
  } finally {
    routing.close();
    await fs.writeFile(path.join(evidence, "native-raw.json"), JSON.stringify([state]));
  }
}
