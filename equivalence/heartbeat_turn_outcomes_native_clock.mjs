// The delivery lease and its SQLite worker must observe the same fixture time.
import fs from "node:fs";
const clock = process.env.MEMORY_EQ_HEARTBEAT_CLOCK;
Date.now = () => {
  const now = Number(fs.readFileSync(clock, "utf8"));
  if (!Number.isSafeInteger(now) || now <= 0) throw Error("Invalid heartbeat fixture time");
  return now;
};
