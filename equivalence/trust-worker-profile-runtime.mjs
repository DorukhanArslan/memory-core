// Transport only: the frozen experiment owns SQLite, registry mutation and retry.
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { mapGetFixturePaths } from "./get-contract-runtime.mjs";
import { observeModelChildStreams } from "./model-runtime-observation.mjs";

const literalInputs = [
  { secret: "worker-fixture-credential", sessionKind: "interactive", mutations: 0 },
  { secret: "worker-fixture-credential", sessionKind: "interactive", mutations: 1 },
  { secret: "worker-fixture-credential", sessionKind: "interactive", mutations: 2 },
  { secret: "worker-fixture-credential", sessionKind: "interactive", mutations: 1, initiallyRegistered: true },
  { secret: "worker-fixture-credential", sessionKind: "interactive", mutations: 1, observer: true },
];
const equalInput = (left, right) => left && typeof left === "object" && !Array.isArray(left) &&
  Object.keys(left).length === Object.keys(right).length &&
  Object.entries(right).every(([key, value]) => Object.hasOwn(left, key) && left[key] === value);

export async function runTrustWorkerRuntime(input, runtimeConfig) {
  if (!literalInputs.some(value => equalInput(input, value)))
    throw Error("Only the five declared synthetic worker inputs are admitted");
  if (![runtimeConfig.runtimeRoot, runtimeConfig.evidenceDirectory].every(value =>
      typeof value === "string" && path.isAbsolute(value)))
    throw Error("Worker profiles require absolute authenticated runtime and evidence paths");
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-trust-worker-"));
  const request = { input, runtimeRoot: runtimeConfig.runtimeRoot, fixtureDirectory: path.join(directory, "fixture") };
  const requestJson = JSON.stringify(request), requestPath = path.join(directory, "request.json");
  await fs.writeFile(requestPath, requestJson);
  const owner = fileURLToPath(new URL("./trust-worker-runtime.mjs", import.meta.url));
  const argv = [owner, requestPath];
  const env = { PATH: process.env.PATH, LANG: "en_US.UTF-8", TZ: "UTC" };
  for (const name of ["NODE_OPTIONS", "MEMORY_EQ_RELEASE_CONTEXT"])
    if (process.env[name] !== undefined) env[name] = process.env[name];
  const raw = { kind: "worker-profile", fixtureBase: directory, coordinatorPid: process.pid, input,
    child: { request, requestJson, requestSha256: createHash("sha256").update(requestJson).digest("hex"),
      argv: [process.execPath, ...argv], environmentKeys: Object.keys(env).sort() } };
  try {
    const child = spawn(process.execPath, argv, { env, stdio: ["ignore", "pipe", "pipe"] });
    raw.child.pid = child.pid;
    const streams = observeModelChildStreams(child);
    const timer = setTimeout(() => child.kill("SIGKILL"), 60000);
    let exit;
    try {
      exit = await new Promise((resolve, reject) => {
        child.once("error", reject); child.once("close", (code, signal) => resolve({ code, signal }));
      });
    } finally { clearTimeout(timer); }
    const { stdout, stderr } = streams();
    Object.assign(raw.child, { exit, stdout, stderr });
    if (exit.code !== 0) throw Error("The genuine native worker experiment failed; complete streams were retained");
    const observation = JSON.parse(stdout); raw.child.observation = observation;
    return mapGetFixturePaths({ provider: "none", result: observation.result ?? null,
      error: observation.error ?? null,
      transcript: { before: observation.before, after: observation.after } }, directory);
  } finally {
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    await fs.rm(directory, { recursive: true, force: true });
  }
}
