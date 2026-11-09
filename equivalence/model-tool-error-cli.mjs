import fs from "node:fs";
import { runModelToolErrorPhase } from "./model-tool-error-phase.mjs";
import { modelError } from "./model-runtime-observation.mjs";
try {
  const result = await runModelToolErrorPhase(JSON.parse(fs.readFileSync(0, "utf8")));
  fs.writeFileSync(1, JSON.stringify(result) + "\n");
} catch (error) {
  fs.writeFileSync(1, JSON.stringify({ fatal: modelError(error), pid: process.pid, ppid: process.ppid }) + "\n");
  process.exitCode = 1;
}
