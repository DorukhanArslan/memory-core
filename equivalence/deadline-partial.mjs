// Controlled host inputs for the original deadline/control/corpus owners.
// Node's own mock timers drive actual setTimeout callbacks; no deadline or
// unavailable algorithm is implemented in this transport.
import { mock } from "node:test";
import { setImmediate as nextTurn } from "node:timers/promises";

export async function flushDeadlineFixture() {
  for (let index = 0; index < 8; index++) await Promise.resolve();
  await nextTurn();
}

export async function awaitDeadlineFixture(test, label) {
  for (let index = 0; index < 2000; index++) {
    if (test()) return;
    await flushDeadlineFixture();
  }
  throw Error(`Controlled fixture did not reach its explicit barrier: ${label}`);
}

export function fixtureError(spec) {
  const value = typeof spec === "string" ? { message: spec } : spec ?? {};
  const error = new Error(value.message ?? "Fixture provider failed");
  if (value.name !== undefined) error.name = value.name;
  if (value.code !== undefined) error.code = value.code;
  return error;
}

export function fixtureAbortReason(spec) {
  return spec && typeof spec === "object" ? fixtureError(spec) : spec;
}

export function fixturePublicError(error, deadlineOwner) {
  return { name: error.name, ...(error.status === undefined ? {} : { status: error.status }),
    message: error.message, deadline: deadlineOwner.isMemorySearchDeadlineError(error),
    ...(error.code === undefined ? {} : { code: error.code }) };
}

export function enableDeadlineFixtureClock(startMs) {
  if (!Number.isFinite(startMs)) throw Error("An explicit finite clock origin is required");
  const before = { Date, setTimeout, clearTimeout };
  mock.timers.enable({ apis: ["Date", "setTimeout"], now: startMs });
  const controlledClear = globalThis.clearTimeout, clearEvents = [];
  mock.method(globalThis, "clearTimeout", (...args) => {
    const handle = args[0];
    clearEvents.push({ time: Date.now(), handleType: typeof handle,
      ...(typeof handle === "number" || typeof handle === "string" ? { handle } : {}),
      ...(handle?.constructor?.name ? { constructor: handle.constructor.name } : {}) });
    return controlledClear(...args);
  });
  mock.method(performance, "now", () => Date.now());
  return {
    clearEvents,
    evidence: { dateReplaced: Date !== before.Date, setTimeoutReplaced: setTimeout !== before.setTimeout,
      clearTimeoutReplaced: clearTimeout !== before.clearTimeout,
      initialDateNow: Date.now(), initialPerformanceNow: performance.now() },
    tick: (ms) => mock.timers.tick(ms), setTime: (ms) => mock.timers.setTime(ms),
    restore: () => { mock.restoreAll(); mock.timers.reset(); },
  };
}

export async function runDeadlinePartial(input, source) {
  // Native imports and their initialization complete before timer control.
  const deadline = await source("extensions/memory-core/src/memory/search-deadline.ts");
  if (input.kind === "provenance") {
    const owned = deadline.createMemorySearchDeadlineError(input.message);
    const ordinary = new Error(owned.message);
    const copy = Object.assign(new Error(owned.message), owned);
    const cloned = structuredClone(owned);
    return { owned: fixturePublicError(owned, deadline), ordinary: fixturePublicError(ordinary, deadline),
      copy: fixturePublicError(copy, deadline), cloned: fixturePublicError(cloned, deadline) };
  }
  if (input.kind === "control") {
    const { createMemorySearchDeadlineControl } = await source("packages/memory-host-sdk/src/host/search-deadline-control.ts");
    const control = createMemorySearchDeadlineControl();
    const listeners = new Map();
    const events = [];
    for (const action of input.actions) {
      if (action.op === "subscribe") listeners.set(action.id,
        control.subscribe((value) => events.push({ listener: action.id, action: value })));
      else if (action.op === "unsubscribe") listeners.get(action.id)?.();
      else if (action.op === "pause" || action.op === "resume") control.report(action.op);
      else throw Error(`Unsupported deadline-control action: ${action.op}`);
    }
    return { events };
  }
  if (input.kind !== "deadline") throw Error(`Unsupported deadline-partial source operation: ${input.kind}`);
  const corpus = input.owner === "search" ? null : await source("extensions/memory-core/src/memory-corpus.ts");
  const clock = enableDeadlineFixtureClock(input.startMs);
  const parent = new AbortController();
  const events = [], clockSteps = [];
  let providerSignal, control, resolveProvider, rejectProvider, completed = false;
  let outcome, outcomeError, partial = null;
  const providerPromise = new Promise((resolve, reject) => { resolveProvider = resolve; rejectProvider = reject; });
  const runProvider = async (signal) => {
    providerSignal = signal;
    events.push({ event: "provider:start", time: Date.now() });
    signal.addEventListener("abort", () => {
      const reason = signal.reason instanceof Error ? fixturePublicError(signal.reason, deadline) : signal.reason;
      events.push({ event: "provider:abort", time: Date.now(), reason });
      if (input.abortBehavior !== "ignore") rejectProvider(input.abortError ? fixtureError(input.abortError) : signal.reason);
    }, { once: true });
    try {
      const value = await providerPromise;
      events.push({ event: "provider:fulfilled", time: Date.now(), value });
      return value;
    } catch (error) {
      events.push({ event: "provider:rejected", time: Date.now(), error: fixturePublicError(error, deadline) });
      throw error;
    }
  };
  if (Object.hasOwn(input, "parentPreAbort")) parent.abort(fixtureAbortReason(input.parentPreAbort));
  try {
    const promise = input.owner === "search"
      ? deadline.runMemorySearchWithDeadline({ timeoutMs: input.timeoutMs, parentSignal: parent.signal, run: runProvider })
      : corpus.runMemoryCorpusDeadline({ operation: input.operation ?? "memory_search", parentSignal: parent.signal,
        run: (signal, channel) => {
          control = channel;
          return input.owner === "attempt" ? corpus.attemptMemoryCorpus({ corpus: input.corpus ?? "memory",
            signal, unavailableValue: input.unavailableValue ?? null, getPartialValue: () => partial,
            run: () => runProvider(signal) }) : runProvider(signal);
        } });
    promise.then((result) => { outcome = { result }; completed = true; }, (error) => {
      outcomeError = error; outcome = { error: fixturePublicError(error, deadline) }; completed = true;
    });
    await awaitDeadlineFixture(() => providerSignal || completed, "provider entry or pre-abort settlement");
    for (const action of input.actions) {
      if (action.op === "tick") clock.tick(action.ms);
      else if (action.op === "set-time") clock.setTime(action.nowMs);
      else if (action.op === "resolve") resolveProvider(action.value);
      else if (action.op === "reject") rejectProvider(fixtureError(action.error));
      else if (action.op === "partial") partial = action.value;
      else if (action.op === "abort") parent.abort(fixtureAbortReason(action.reason));
      else if (action.op === "pause" || action.op === "resume") {
        if (!control) throw Error("Only corpus owners expose a readiness control channel");
        control.report(action.op);
      } else if (action.op !== "settle" && action.op !== "flush") throw Error(`Unsupported deadline action: ${action.op}`);
      clockSteps.push({ ...action, time: Date.now() });
      await flushDeadlineFixture();
      if (action.op === "settle") await awaitDeadlineFixture(() => completed, "deadline settlement");
    }
    await awaitDeadlineFixture(() => completed, "final deadline settlement");
    const signal = providerSignal ? { aborted: providerSignal.aborted,
      ...(providerSignal.aborted ? { reason: providerSignal.reason instanceof Error
        ? fixturePublicError(providerSignal.reason, deadline) : providerSignal.reason } : {}),
      reasonIsOutcomeError: providerSignal.aborted && providerSignal.reason === outcomeError } : null;
    return { outcome, signal, events, clockSteps,
      ...(input.owner === "attempt" && outcome.result ? { metadata: corpus.composeMemoryCorpusMetadata([outcome.result]) } : {}) };
  } finally { clock.restore(); }
}
