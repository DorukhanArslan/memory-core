// Coordinator only. Each host owns a distinct OS process; the restarted host
// receives locations and its own fact-free phase, never the producer payload.
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";

export async function runHostRestartRuntime(input, runtimeConfig) {
  if (input?.kind !== "host-restart-recall" || !Number.isFinite(input.nowMs) ||
      input.phases?.length !== 2 || input.phases[0].label !== "produce" ||
      input.phases[1].label !== "restart" ||
      ![runtimeConfig?.runtimeRoot, runtimeConfig?.evidenceDirectory].every(value =>
        typeof value === "string" && path.isAbsolute(value))) {
    throw Error("The host restart profile requires two declared phases and authenticated absolute paths");
  }
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-host-restart-"));
  const workspace = path.join(directory, "workspace");
  const isolatedWorkspace = path.join(directory, "isolated-workspace");
  await Promise.all([workspace, isolatedWorkspace, path.join(directory, "state")].map(value => fs.mkdir(value)));
  const { agentId, isolatedAgentId } = input.identity;
  const config = {
    agents: { ownership: "explicit", defaults: { workspace }, entries: {
      [agentId]: { workspace }, [isolatedAgentId]: { workspace: isolatedWorkspace },
    } },
    logging: { level: "silent", consoleLevel: "silent", file: path.join(directory, "native.log") },
    session: { maintenance: { mode: "warn" } },
    tools: { profile: "coding", loopDetection: { enabled: false }, fs: { workspaceOnly: true } },
    memory: { citations: "off", search: {
      enabled: true, provider: "none", fallback: "none", sources: ["memory"],
      store: { vector: { enabled: false } },
      sync: { onSessionStart: false, onSearch: false, watch: false },
      query: { maxResults: 5, minScore: 0, hybrid: { temporalDecay: { enabled: false } } },
    } },
  };
  await fs.writeFile(path.join(directory, "openclaw.json"), JSON.stringify(config));
  const raw = { kind: input.kind, input, fixtureBase: directory, config,
    coordinatorPid: process.pid, coordinatorPpid: process.ppid, children: [] };
  const phases = [];
  try {
    for (const phase of input.phases) {
      const request = { directory, runtimeRoot: runtimeConfig.runtimeRoot,
        nowMs: input.nowMs, identity: input.identity, phase,
        sourcePath: input.phases[0].write.path };
      const stdin = JSON.stringify(request);
      const argv = [fileURLToPath(new URL("./host-restart-phase-cli.mjs", import.meta.url))];
      const startedAtNs = process.hrtime.bigint().toString();
      const child = spawn(process.execPath, argv, { env: { ...process.env }, stdio: ["pipe", "pipe", "pipe"] });
      const observation = { label: phase.label, pid: child.pid, ppid: process.pid,
        executable: process.execPath, argv, request, stdin, startedAtNs,
        stdinSha256: createHash("sha256").update(stdin).digest("hex"), stdout: "", stderr: "" };
      raw.children.push(observation);
      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", chunk => { observation.stdout += chunk; });
      child.stderr.on("data", chunk => { observation.stderr += chunk; });
      child.stdin.end(stdin);
      observation.exit = await new Promise((resolve, reject) => {
        child.once("error", reject);
        child.once("close", (code, signal) => {
          observation.finishedAtNs = process.hrtime.bigint().toString();
          resolve({ code, signal });
        });
      });
      if (observation.exit.code !== 0 || !observation.stdout) {
        throw Error(`The ${phase.label} host process failed; original streams are retained`);
      }
      const output = JSON.parse(observation.stdout);
      observation.output = output;
      if (output.fatal || !output.result || !output.raw) throw Error(`The ${phase.label} host returned no complete observation`);
      phases.push(output.result);
    }
    raw.result = { provider: "none", phases };
    return raw.result;
  } finally {
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
  }
}
