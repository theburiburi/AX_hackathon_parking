import assert from "node:assert/strict";
import { test } from "node:test";
import { watchReplayVehicles } from "../src/replayVehicleSync.js";

const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

test("sync uses displayed frames, skips missing and paused frames, and handles seeks", async () => {
  let frame, timer;
  const sent = [], errors = [];
  const stop = watchReplayVehicles({ readFrame: () => frame, send: async n => { sent.push(n); }, onError: e => errors.push(e),
    setTimer: callback => { timer = callback; return 1; }, clearTimer() {} });
  await flush();
  assert.deepEqual(sent, []);
  frame = 246; await timer();
  await timer();
  assert.deepEqual(sent, [246]);
  frame = 0; await timer();
  assert.deepEqual(sent, [246, 0]);
  assert.deepEqual(errors, ["", ""]);
  stop();
});

test("pending writes do not overlap and stopping aborts them without scheduling another", async () => {
  let resolve, signal, timers = 0;
  const errors = [];
  const stop = watchReplayVehicles({ readFrame: () => 5, send: (_, abort) => {
    signal = abort; return new Promise(r => { resolve = r; });
  }, onError: e => errors.push(e), setTimer: () => { timers++; }, clearTimer() {} });
  assert.equal(timers, 0);
  stop();
  assert.equal(signal.aborted, true);
  resolve(); await flush();
  assert.equal(timers, 0);
  assert.deepEqual(errors, []);
});

test("failed synchronization is retried for the same frame", async () => {
  let timer, count = 0;
  const errors = [];
  const stop = watchReplayVehicles({ readFrame: () => 246, send: async () => {
    if (++count === 1) throw new Error("server error");
  }, onError: e => errors.push(e), setTimer: callback => { timer = callback; }, clearTimer() {} });
  await flush();
  await timer();
  assert.equal(count, 2);
  assert.deepEqual(errors, ["server error", ""]);
  stop();
});
