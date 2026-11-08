// Dedicated process entry, with a synchronous complete stdin envelope just as
// the protected release runner uses. This file supplies no session algorithm.
import fs from "node:fs";
import { runDurableSessionPhase } from "./durable-session-phase.mjs";

try {
  const request = JSON.parse(fs.readFileSync(0, "utf8"));
  fs.writeFileSync(1, JSON.stringify(await runDurableSessionPhase(request)) + "\n");
} catch (error) {
  fs.writeFileSync(1, JSON.stringify({ fatal: { name: error.name, message: error.message },
    stack: error.stack, pid: process.pid }) + "\n");
  process.exitCode = 1;
}
