// The host calls this injected provider with its own complete, unmodified narrative request.
export const remHashes = new Set([
  "c6daf2b6586442356d2b99490fcd0e8e7416fa82c4413d73be8f38cbd38529d9",
  "97c158aadaed498caaaf682398cd852b4b50bacd821739881324d46ded430f21",
  "92de62ebaf0273115a4938187cc8f32e2a774d355937c06a651736b440b103b5",
  "b1af71e437230c372eb5a39f5630064fb06bd8c540df31a1b6008929402e7cc1",
  "a5d769bfcbc90c71fea52ec0843d23c08cb1c4ec963ea461bafa99c83b78b034",
  "cb4376a550e5a22916ec1fccf4fd857da126fad303a16803e46d2c48f8a99a6b",
  "8fa6e49fa4625f37a2483e242041e7216b02e53102c334e5de8fbbe53c5f79a6",
  "7d78538bd29c62047870959fdc4b04362a471587e58eb56a4da991a635cabc59",
]);

export function remPhaseConfig(options) {
  return {light: {enabled: false}, rem: {enabled: true, limit: options.limit,
    lookbackDays: options.lookbackDays, minPatternStrength: options.minPatternStrength,
    execution: {model: options.model}}};
}

export function remNarrator(options, calls, receipts, removeKey) {
  if (options.provider === null) return {};
  return {subagent: {async complete(request) {
    const reply = options.provider[calls.length];
    calls.push(structuredClone(request));
    const receipt = {request: structuredClone(request), reply: structuredClone(reply),
      callerStack: new Error("Fixture narrative callback").stack, nowMs: Date.now()};
    receipts.push(receipt);
    try {
      if (reply.removeKey) await removeKey(reply.removeKey);
      if (reply.error) throw Error(reply.error);
      receipt.returned = {text: reply.text};
      return {...receipt.returned};
    } catch (error) {
      receipt.error = {name: error.name, message: error.message, stack: error.stack};
      throw error;
    }
  }}};
}
