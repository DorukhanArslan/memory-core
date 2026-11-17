// Offline model transport and passive original tool-hook observation only.
// Prompt composition, tools and transcript owners execute unchanged.
const BRIDGE = Symbol.for("memory-core.equivalence.prompt-runtime-provider");
export default {
  id: "fixture-prompt-runtime-model",
  register(api) {
    globalThis[BRIDGE]?.progress("provider-plugin-registered");
    api.on("before_tool_call", (event, context) => {
      globalThis[BRIDGE]?.observeTool("before_tool_call", event, context);
    });
    api.on("after_tool_call", (event, context) => {
      globalThis[BRIDGE]?.observeTool("after_tool_call", event, context);
    });
    api.registerProvider({
      id: "fixture-prompt-runtime-model", label: "Prompt runtime offline transport", auth: [],
      createStreamFn() {
        const bridge = globalThis[BRIDGE];
        if (!bridge) throw Error("The owned prompt runtime model transport is unavailable");
        bridge.progress("provider-stream-created");
        return bridge.stream;
      },
    });
  },
};
