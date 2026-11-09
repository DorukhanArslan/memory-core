// Sequential OS-process transport; no in-memory history crosses an exit.
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { modelChildEnvironment, modelRuntimeIdentity, observeModelChildStreams } from "./model-runtime-observation.mjs";

export function modelSessionPhaseInput(input, label) {
  const identity = Object.fromEntries(["nowMs", "agentId", "sessionId", "sessionKey"].map((key) => [key, input[key]]));
  if (label === "verify") return identity;
  return { ...identity, ...Object.fromEntries(["systemPrompt", "model", "patterns", "registeredSecrets"]
    .filter((key) => Object.hasOwn(input, key)).map((key) => [key, input[key]])) };
}

export async function runModelSessionRuntime(input, runtimeConfig) {
  if (input.kind !== "model-session" || input.agentId !== "main" || !Array.isArray(input.phases) ||
      JSON.stringify(input.phases.map((phase) => phase.label)) !== '["write","continue","verify"]' ||
      JSON.stringify(Object.keys(input.phases[2])) !== '["label"]') {
    throw Error("Model sessions require ordered write/continue/identity-only verify phases");
  }
  const runtime = modelRuntimeIdentity();
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-model-session-"));
  const raw = { kind: "model-session", fixtureBase: directory, coordinatorPid: process.pid, input, runtime, phases: [] };
  const phases = [];
  try {
    for (const phase of input.phases) {
      const request = { input: modelSessionPhaseInput(input, phase.label), phase, directory, runtimeRoot: runtimeConfig.runtimeRoot };
      const requestJson = JSON.stringify(request);
      const argv = [process.execPath, fileURLToPath(new URL("./model-session-phase-cli.mjs", import.meta.url))];
      const environment = modelChildEnvironment();
      const child = spawn(argv[0], argv.slice(1), { env: environment, stdio: ["pipe", "pipe", "pipe"] });
      const record = { label: phase.label, pid: child.pid, request, requestJson,
        requestSha256: crypto.createHash("sha256").update(requestJson).digest("hex"), argv,
        environmentKeys: Object.keys(environment).sort(), startedAtNs: process.hrtime.bigint().toString() };
      const streams = observeModelChildStreams(child);
      child.stdin.end(requestJson);
      const exit = await new Promise((resolve, reject) => {
        child.once("error", reject); child.once("close", (code, signal) => resolve({ code, signal }));
      });
      const { stdout, stderr } = streams();
      Object.assign(record, { exit, finishedAtNs: process.hrtime.bigint().toString(), stdout, stderr });
      raw.phases.push(record);
      const output = JSON.parse(stdout); record.raw = output.raw;
      if (exit.code !== 0 || output.fatal) throw Error(`The actual model ${phase.label} process failed: ${JSON.stringify(output)}`);
      phases.push(output.result);
    }
    return { provider: "none", phases };
  } finally {
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    await fs.rm(directory, { recursive: true, force: true });
  }
}
