import fs from "node:fs";
import { runModelToolResultPhase } from "./model-tool-result-phase.mjs";
import { modelError, writeModelJson } from "./model-runtime-observation.mjs";
let output;
try {
  output = await runModelToolResultPhase(JSON.parse(fs.readFileSync(0, "utf8")));
} catch (error) {
  output = { fatal: modelError(error), pid: process.pid, ppid: process.ppid };
  process.exitCode = 1;
}
await writeModelJson(output);
