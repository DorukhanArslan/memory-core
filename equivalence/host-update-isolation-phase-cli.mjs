import fs from "node:fs";
import { runHostUpdateIsolationPhase } from "./host-update-isolation-phase.mjs";

const stdin = fs.readFileSync(0, "utf8");
let output;
try {
  output = await runHostUpdateIsolationPhase(JSON.parse(stdin), stdin);
} catch (error) {
  output = { fatal: { name: error.name, message: error.message }, stack: error.stack,
    pid: process.pid, ppid: process.ppid, stdin };
  process.exitCode = 1;
}
await new Promise((resolve, reject) => process.stdout.write(JSON.stringify(output) + "\n",
  error => error ? reject(error) : resolve()));
