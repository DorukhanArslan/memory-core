// Complete synchronous JSON transport after genuine owner cleanup.
import fs from "node:fs";
import { runModelSessionPhase } from "./model-session-phase.mjs";
import { modelError } from "./model-runtime-observation.mjs";
try {
  const output = await runModelSessionPhase(JSON.parse(fs.readFileSync(0, "utf8")));
  fs.writeFileSync(1, JSON.stringify(output) + "\n");
} catch (error) {
  fs.writeFileSync(1, JSON.stringify({ fatal: modelError(error), pid: process.pid, ppid: process.ppid }) + "\n");
  process.exitCode = 1;
}
