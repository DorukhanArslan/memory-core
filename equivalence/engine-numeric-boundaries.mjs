// The original flush planner owns every normalized field. Binary64 literals are
// a lossless transport for values that cannot otherwise traverse JSON.
import { runFlushContract } from "./flush-contract.mjs";

function decode(value) {
  if (value === null || typeof value !== "object") return value;
  if (Object.keys(value).length !== 1 || typeof value.binary64 !== "string" ||
      !/^[0-9a-f]{16}$/.test(value.binary64)) throw Error("Expected one exact binary64 input");
  return Buffer.from(value.binary64, "hex").readDoubleBE();
}

function observe(value) {
  const json = JSON.stringify(value);
  if (typeof value !== "number") return { type: value === null ? "null" : typeof value, json };
  const bytes = Buffer.alloc(8);
  bytes.writeDoubleBE(value);
  return { type: "number", bits: bytes.toString("hex"), json };
}

export async function runEngineNumericBoundaries(input, importReference) {
  if (input.kind !== "numeric-flush") throw Error("Expected a numeric flush planner request");
  const output = [];
  for (const probe of input.probes) {
    if (!["softThresholdTokens", "forceFlushTranscriptBytes", "contextWindowTokens"].includes(probe.field)) {
      throw Error("Unknown numeric flush option");
    }
    const options = { model: "numeric-plan-model" };
    const params = { cfg: { agents: { defaults: { userTimezone: "UTC", compaction: { memoryFlush: options } } } },
      nowMs: input.nowMs };
    const target = probe.field === "contextWindowTokens" ? params : options;
    target[probe.field] = decode(probe.value);
    const returned = await runFlushContract({ kind: "plan", params, fallbackNowMs: input.nowMs }, importReference);
    const numbers = Object.fromEntries(Object.entries(returned.plan)
      .filter(([, value]) => typeof value === "number").map(([key, value]) => [key, observe(value)]));
    output.push({ label: probe.label, input: observe(target[probe.field]), returned, numbers });
  }
  return output;
}
