import assert from "node:assert/strict";
import { test } from "node:test";
import { watchReplayVehicles, watchReplayVideoState } from "../src/replayVehicleSync.js";

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

test("video playhead publishes without tracking frames and immediately follows pause, seek and loop", async () => {
  const video = Object.assign(new EventTarget(), { readyState: 0, seeking: false, currentTime: 0 });
  const sent = [];
  let timer;
  const stop = watchReplayVideoState(video, { fps: 30, frameCount: 300,
    send: async n => sent.push(n), onError() {},
    setTimer: callback => { timer = callback; }, clearTimer() {} });
  await flush();
  assert.deepEqual(sent, []);
  video.readyState = 2;
  video.dispatchEvent(new Event("loadeddata")); await flush();
  video.currentTime = 2;
  video.dispatchEvent(new Event("pause")); await flush();
  await timer();
  assert.deepEqual(sent, [0, 60]);
  video.seeking = true; video.currentTime = 1;
  await timer();
  assert.deepEqual(sent, [0, 60]);
  video.seeking = false; video.dispatchEvent(new Event("seeked")); await flush();
  video.currentTime = 0;
  await timer();
  assert.deepEqual(sent, [0, 60, 30, 0]);
  stop();
  video.currentTime = 3; video.dispatchEvent(new Event("pause")); await flush();
  assert.deepEqual(sent, [0, 60, 30, 0]);
});

test("seeks during a slow write coalesce to the latest destination without out of order writes", async () => {
  let notify, resolve, frame = 30, pending = 0;
  const sent = [];
  const stop = watchReplayVehicles({ readFrame: () => frame,
    subscribe: callback => { notify = callback; return () => {}; },
    send: n => { assert.equal(pending++, 0); sent.push(n); return new Promise(r => { resolve = () => { pending--; r(); }; }); },
    onError() {}, setTimer() {}, clearTimer() {} });
  frame = 90; notify();
  frame = 0; notify();
  assert.deepEqual(sent, [30]);
  resolve(); await flush();
  assert.deepEqual(sent, [30, 0]);
  resolve(); await flush();
  stop();
});
