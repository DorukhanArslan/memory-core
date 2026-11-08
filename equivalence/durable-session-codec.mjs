// Only opaque append/read-anchor identities and exact producer-owned store
// paths are relational. User payloads and all raw observations stay unchanged.
export function mapDurableSessionIdentities(phases, storePaths) {
  if (!Array.isArray(phases) || phases.length !== storePaths.length) throw Error("Missing durable producer paths");
  const generations = new Map();
  return phases.map((phase, index) => {
    const result = structuredClone(phase);
    const anchors = [...result.appendResults.map((value) => value.result?.anchor), result.activeAnchor].filter(Boolean);
    for (const anchor of anchors) {
      if (!/^[0-9a-f]{32}$/.test(anchor.generation) || typeof anchor.agentId !== "string" ||
          anchor.storePath !== storePaths[index]) throw Error("An opaque anchor has no recognized producer identity");
      if (!generations.has(anchor.generation)) generations.set(anchor.generation, `$GENERATION/${generations.size + 1}`);
      anchor.generation = generations.get(anchor.generation);
      anchor.storePath = `$SESSION_STORE/${anchor.agentId}`;
    }
    return result;
  });
}
