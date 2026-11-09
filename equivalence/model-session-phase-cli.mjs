// Complete JSON transport after genuine owner cleanup, including pipe pressure.
import fs from "node:fs";
import { runModelSessionPhase } from "./model-session-phase.mjs";
import { modelError, writeModelJson } from "./model-runtime-observation.mjs";
let output;
try {
  output = await runModelSessionPhase(JSON.parse(fs.readFileSync(0, "utf8")));
} catch (error) {
  output = { fatal: modelError(error), pid: process.pid, ppid: process.ppid };
  process.exitCode = 1;
}
await writeModelJson(output);
