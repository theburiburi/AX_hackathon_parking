import assert from "node:assert/strict";
import { test } from "node:test";
import { VideoSync } from "../src/videoSync.js";

function videos() {
  return Array.from({ length: 7 }, (_, i) => ({
    duration: 100 + i, currentTime: 0, readyState: 4, seeking: false,
    paused: true, ended: false, playbackRate: 1, error: null,
    pause() { this.paused = true; },
    play() { this.paused = false; return Promise.resolve(); },
  }));
}
test("all seven wait for the slowest loader then start together", async () => {
  const group = videos(), sync = new VideoSync(group);
  group[6].readyState = 1;
  sync.tick();
  assert.ok(group.every(v => v.paused));
  group[6].readyState = 4;
  sync.tick();
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(group.every(v => !v.paused));
  sync.toggle();
  assert.ok(group.every(v => v.paused));
});
test("seek, rate and drift correction apply to every camera", () => {
  let now = 0;
  const group = videos(), sync = new VideoSync(group, () => {}, () => now);
  sync.seek(40);
  sync.rate = 2;
  sync.tick();
  assert.ok(group.every(v => v.currentTime === 40 && v.playbackRate === 2));
  group[0].currentTime = 42;
  group[6].currentTime = 38;
  now = 4000;
  sync.tick();
  assert.ok(group.every(v => v.currentTime === 42));
  sync.toggle();
  sync.seek(500);
  assert.equal(sync.time, 100);
  assert.ok(group.every(v => v.paused));
});
test("buffering leaves healthy cameras playing and only seeks the recovered channel", () => {
  let now = 0;
  const group = videos(), sync = new VideoSync(group, () => {}, () => now);
  sync.seek(20);
  sync.tick();
  group[6].readyState = 2;
  sync.tick();
  assert.ok(group.slice(0, 6).every(v => !v.paused));
  group[6].readyState = 4;
  group[6].currentTime = 18;
  now = 4000;
  sync.tick();
  assert.ok(group.every(v => v.currentTime === 20));
});
test("shortest duration controls collective loop and stop", () => {
  const group = videos(), sync = new VideoSync(group);
  sync.seek(100);
  sync.tick();
  assert.ok(group.every(v => v.currentTime === 0));
  sync.loop = false;
  sync.seek(100);
  sync.tick();
  assert.equal(sync.wanted, false);
  assert.ok(group.every(v => v.paused && v.currentTime === 100));
});
test("autoplay rejection pauses the group until user interaction", async () => {
  const group = videos(), sync = new VideoSync(group);
  group[6].play = () => Promise.reject(Object.assign(new Error("blocked"), { name: "NotAllowedError" }));
  sync.tick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sync.wanted, false);
  assert.ok(group.every(v => v.paused));
});
test("pending play cannot restart videos after unmount", async () => {
  const group = videos(), sync = new VideoSync(group);
  let resolvePlay;
  group[0].play = () => new Promise(resolve => { resolvePlay = resolve; });
  sync.tick();
  sync.dispose();
  group[0].paused = false;
  resolvePlay();
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(group.every(v => v.paused));
});

test("small drift adjusts speed without seeking or pausing any channel", () => {
  const group = videos(), sync = new VideoSync(group);
  sync.tick();
  group.forEach(v => { v.currentTime = 10; });
  group[5].currentTime = 9.6;
  group[6].currentTime = 10.4;
  sync.tick();
  assert.equal(group[5].currentTime, 9.6);
  assert.equal(group[6].currentTime, 10.4);
  assert.ok(group[5].playbackRate > 1 && group[5].playbackRate <= 1.05);
  assert.ok(group[6].playbackRate < 1 && group[6].playbackRate >= .95);
  assert.ok(group.every(v => !v.paused));
  group[5].currentTime = 10;
  sync.tick();
  assert.equal(group[5].playbackRate, 1);
});

test("automatic seeks have a per-channel cooldown", () => {
  let now = 0;
  const group = videos(), sync = new VideoSync(group, () => {}, () => now);
  sync.tick();
  group.forEach(v => { v.currentTime = 10; });
  group[6].currentTime = 1;
  sync.tick();
  assert.equal(group[6].currentTime, 10);
  group[6].currentTime = 1;
  now = 1000;
  sync.tick();
  assert.equal(group[6].currentTime, 1);
  assert.ok(group.slice(0, 6).every(v => !v.paused));
  now = 3001;
  sync.tick();
  assert.equal(group[6].currentTime, 10);
});

test("a stalled leader is replaced without freezing healthy cameras", () => {
  const group = videos(), sync = new VideoSync(group);
  sync.tick();
  group.forEach(v => { v.currentTime = 10; });
  sync.tick();
  group[0].readyState = 2;
  group[1].currentTime = 10.1;
  sync.tick();
  assert.notEqual(sync.leader, group[0]);
  sync.leader.currentTime = 11;
  sync.tick();
  assert.equal(sync.time, 11);
  assert.ok(group.slice(1).every(v => !v.paused));
});

test("a runtime file failure does not stop healthy cameras", () => {
  const group = videos(), sync = new VideoSync(group);
  sync.tick();
  group[6].error = { code: 3 };
  sync.tick();
  assert.ok(group.slice(0, 6).every(v => !v.paused));
  sync.toggle();
  assert.ok(group.every(v => v.paused));
});

test("all-channel stalls freeze the clock and UI reports are throttled", () => {
  let now = 0, reports = 0;
  const group = videos(), sync = new VideoSync(group, () => reports++, () => now);
  sync.tick();
  for (let i = 0; i < 10; i++) { now += 10; sync.tick(); }
  assert.equal(reports, 1);
  group.forEach(v => { v.readyState = 2; });
  sync.tick();
  assert.equal(reports, 2);
  now = 5000;
  sync.tick();
  assert.equal(sync.time, 0);
  assert.equal(sync.leader, null);
});
