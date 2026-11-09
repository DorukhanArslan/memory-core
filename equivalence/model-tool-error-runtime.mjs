// One fresh protected child per complete original error boundary case.
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { modelChildEnvironment, modelRuntimeIdentity, observeModelChildStreams } from "./model-runtime-observation.mjs";

export async function runModelToolErrorRuntime(input, runtimeConfig) {
  if (!input || !Object.hasOwn(input, "error")) throw Error("The error profile requires its literal recursive error fixture");
  await fs.mkdir(runtimeConfig.evidenceDirectory, { recursive: true });
  const directory = await fs.mkdtemp(path.join(runtimeConfig.evidenceDirectory, "native-model-error-"));
  const request = { input, directory, runtimeRoot: runtimeConfig.runtimeRoot }, requestJson = JSON.stringify(request);
  const raw = { kind: "model-tool-error", fixtureBase: directory, coordinatorPid: process.pid, input,
    runtime: modelRuntimeIdentity(), child: null };
  try {
    const argv = [process.execPath, fileURLToPath(new URL("./model-tool-error-cli.mjs", import.meta.url))];
    const environment = modelChildEnvironment();
    const child = spawn(argv[0], argv.slice(1), { env: environment, stdio: ["pipe", "pipe", "pipe"] });
    raw.child = { pid: child.pid, request, requestJson,
      requestSha256: crypto.createHash("sha256").update(requestJson).digest("hex"), argv,
      environmentKeys: Object.keys(environment).sort(), startedAtNs: process.hrtime.bigint().toString() };
    const streams = observeModelChildStreams(child);
    child.stdin.end(requestJson);
    const exit = await new Promise((resolve, reject) => {
      child.once("error", reject); child.once("close", (code, signal) => resolve({ code, signal }));
    });
    const { stdout, stderr } = streams();
    Object.assign(raw.child, { exit, finishedAtNs: process.hrtime.bigint().toString(), stdout, stderr });
    const output = JSON.parse(stdout); raw.child.raw = output.raw;
    if (exit.code !== 0 || output.fatal) throw Error(`The original formatter/tool error caller failed: ${JSON.stringify(output)}`);
    return output.result;
  } finally {
    await fs.writeFile(path.join(runtimeConfig.evidenceDirectory, "native-raw.json"), JSON.stringify([raw]));
    await fs.rm(directory, { recursive: true, force: true });
  }
}
