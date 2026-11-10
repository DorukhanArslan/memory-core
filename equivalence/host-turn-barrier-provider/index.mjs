// This plugin owns only deterministic offline model transport. All admission,
// scheduling, tools, filesystem mutation and publication are pristine Native.
const BRIDGE = Symbol.for('memory-core.equivalence.host-turn-barrier-provider');
export default {
  id: 'fixture-turn-barrier-model',
  register(api) {
    globalThis[BRIDGE]?.progress('provider-plugin-registered');
    api.registerProvider({
      id: 'fixture-turn-barrier-model', label: 'Host turn barrier offline transport', auth: [],
      createStreamFn() {
        const bridge = globalThis[BRIDGE];
        if (!bridge) throw Error('The owned turn-barrier model transport is unavailable');
        bridge.progress('provider-stream-created');
        return bridge.stream;
      },
    });
  },
};
