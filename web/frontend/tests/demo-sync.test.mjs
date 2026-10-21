import assert from "node:assert/strict";
import { test } from "node:test";
import { watchDemoState } from "../src/demoStatePolling.js";

const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

test("one snapshot updates clock, vehicles and totals together, including backward seeks", async () => {
  let timer, frame = 30;
  const states = [];
  const stop = watchDemoState({
    load: async () => ({ playback: { frame }, vehicles: [{ status: frame ? "PARKED" : "UNKNOWN" }], zones: [{ parked_count: frame ? 1 : 0 }] }),
    onState: state => states.push(state), onError() {},
    setTimer: callback => { timer = callback; }, clearTimer() {},
  });
  await flush();
  await timer();
  assert.equal(states.length, 1); // Paused snapshots do not redraw the panels.
  frame = 0; await timer();
  assert.deepEqual(states.map(s => [s.playback.frame, s.vehicles[0].status, s.zones[0].parked_count]),
    [[30, "PARKED", 1], [0, "UNKNOWN", 0]]);
  stop();
});

test("a slow or failed read preserves the last state and retries without concurrent requests", async () => {
  let resolve, signal, timer, fail = false;
  const states = [], errors = [];
  const stop = watchDemoState({ load: abort => {
    signal = abort;
    if (fail) throw new Error("offline");
    return new Promise(r => { resolve = r; });
  }, onState: s => states.push(s), onError: e => errors.push(e?.message),
  setTimer: callback => { timer = callback; }, clearTimer() {} });
  assert.equal(timer, undefined);
  resolve({ playback: { frame: 90 } }); await flush();
  fail = true; await timer();
  assert.equal(states.length, 1);
  assert.equal(errors.at(-1), "offline");
  fail = false;
  const read = timer();
  stop();
  assert.equal(signal.aborted, true);
  resolve({ playback: { frame: 0 } }); await read;
  assert.equal(states.length, 1);
});
