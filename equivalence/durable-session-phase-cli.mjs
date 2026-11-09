// Dedicated process entry, with a synchronous complete stdin envelope just as
// the protected release runner uses. This file supplies no session algorithm.
import fs from "node:fs";
import { runDurableSessionPhase } from "./durable-session-phase.mjs";

let output;
try {
  const request = JSON.parse(fs.readFileSync(0, "utf8"));
  output = await runDurableSessionPhase(request);
} catch (error) {
  output = { fatal: { name: error.name, message: error.message },
    stack: error.stack, pid: process.pid };
  process.exitCode = 1;
}
await new Promise((resolve, reject) => process.stdout.write(JSON.stringify(output) + "\n",
  (error) => error ? reject(error) : resolve()));
