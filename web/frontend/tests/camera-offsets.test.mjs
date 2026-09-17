import assert from "node:assert/strict";
import { test } from "node:test";
import { VideoSync } from "../src/videoSync.js";

test("positive and negative offsets define the overlapping range and local seek positions", () => {
  const videos = [2, -1].map(() => ({ duration: 10, currentTime: 0, readyState: 4, seeking: false, paused: true, playbackRate: 1,
    pause() { this.paused = true; }, play() { this.paused = false; return Promise.resolve(); } }));
  const sync = new VideoSync(videos, () => {}, () => 0, [2, -1]);
  assert.equal(sync.start, 1);
  assert.equal(sync.duration, 7);
  sync.tick();
  assert.deepEqual(videos.map(v => v.currentTime), [3, 0]);
  sync.seek(4);
  assert.deepEqual(videos.map(v => v.currentTime), [7, 4]);
  assert.deepEqual(videos.map(v => sync.globalTime(v)), [4, 4]);
});

test("recordings with no overlap cannot start", () => {
  const sync = new VideoSync([{ duration: 2 }], () => {}, () => 0, [3]);
  assert.equal(sync.duration, 0);
});
