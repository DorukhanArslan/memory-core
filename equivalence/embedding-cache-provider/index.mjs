// The original plugin loader registers this deterministic offline transport.
// Chunking, cache lookup/publication, retries and lifecycle stay with Native.
const BRIDGE = Symbol.for("memory-core.equivalence.embedding-cache-provider");
const bridge = () => {
  const value = globalThis[BRIDGE];
  if (!value) throw Error("The owned embedding cache transport is unavailable");
  return value;
};

export default {
  id: "fixture-embedding-cache",
  register(api) {
    // The ollama namespace selects Native's original sequential index policy;
    // this plugin is the sole active owner and makes no service calls.
    for (const id of ["ollama", "fixture-cache-a", "fixture-cache-b"])
      api.registerEmbeddingProvider({
        id,
        transport: "remote",
        normalizeModel: options => bridge().normalizeModel(id, options),
        resolveIndexIdentity: options => bridge().resolveIndexIdentity(id, options),
        create: options => bridge().create(id, options),
      });
    bridge().registered();
  },
};
