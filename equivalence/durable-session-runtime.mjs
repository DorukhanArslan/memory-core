// OS-process coordinator only. No transcript or context algorithm is supplied.
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";
import { mapDurableSessionIdentities } from "./durable-session-codec.mjs";

export async function runDurableSessionRuntime(input, runtimeConfig) {
  if (input.kind !== "durable" || !Array.isArray(input.phases) ||
      JSON.stringify(input.phases.map((phase) => phase.label)) !== '["write","continue","verify"]') {
    throw Error("Durability requires three ordered fresh processes: write, continue, verify");
  }
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-durable-session-"));
  const raw = { fixtureBase: directory, kind: "durable", coordinatorPid: process.pid, phases: [] };
  const phases = [];
  // Do not pass the phases array, prior snapshots, transcript bodies or recalled
  // messages as shared state. A phase sees only its own literal instructions.
  const { phases: ignoredPhases, ...identity } = input;
  try {
    for (const phase of input.phases) {
      const request = { input: identity, phase, directory, runtimeRoot: runtimeConfig.runtimeRoot };
      const requestBytes = Buffer.from(JSON.stringify(request));
      const child = spawn(process.execPath, [fileURLToPath(new URL("./durable-session-phase-cli.mjs", import.meta.url))], {
        env: { ...process.env }, stdio: ["pipe", "pipe", "pipe"] });
      const record = { label: phase.label, pid: child.pid, request,
        requestJson: requestBytes.toString("utf8"),
        requestSha256: createHash("sha256").update(requestBytes).digest("hex"),
        startedAtNs: process.hrtime.bigint().toString() };
      let stdout = "", stderr = "";
      child.stdout.on("data", (chunk) => { stdout += chunk; });
      child.stderr.on("data", (chunk) => { stderr += chunk; });
      child.stdin.end(requestBytes);
      const exit = await new Promise((resolve, reject) => {
        child.once("error", reject); child.once("close", (code, signal) => resolve({ code, signal }));
      });
      Object.assign(record, { exit, finishedAtNs: process.hrtime.bigint().toString(), stdout, stderr });
      raw.phases.push(record);
      if (!stdout.trim()) throw Error(`Durable ${phase.label} process returned no result: ${JSON.stringify({ exit, stderr })}`);
      const output = JSON.parse(stdout);
      if (exit.code !== 0 || output.fatal) throw Error(`Durable ${phase.label} process failed: ${JSON.stringify(output)}`);
      record.raw = output.raw; phases.push(output.result);
    }
    return { provider: "none", phases: mapDurableSessionIdentities(phases,
      raw.phases.map((phase) => mapGetFixturePaths(phase.raw.storePaths.databasePath, directory))) };
  } finally {
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    await fs.rm(directory, { recursive: true, force: true });
  }
}
