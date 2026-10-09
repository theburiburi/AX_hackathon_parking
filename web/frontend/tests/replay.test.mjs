import assert from "node:assert/strict";
import { test } from "node:test";
import { ReplayBuffer, frameForTime, replayTracks, replayZoneCounts } from "../src/replayBuffer.js";

test("displayed media time determines the exact frame, including last frame", () => {
  assert.equal(frameForTime(1 / 30, 30, 100), 1);
  assert.equal(frameForTime(3.3333333, 30, 100), 99);
  assert.equal(frameForTime(-1, 30, 100), 0);
});

test("requests share a chunk, missing frames never substitute an old frame, memory is bounded", async () => {
  let calls = 0;
  const buffer = new ReplayBuffer(async (start, count) => {
    calls++;
    return Array.from({ length: count }, (_, n) => ({ frame_index: start + n }));
  }, { chunk: 4, limit: 8 });
  assert.equal(buffer.get(0), null);
  await Promise.all([buffer.ensure(0), buffer.ensure(1), buffer.ensure(2)]);
  assert.equal(calls, 1);
  assert.equal(buffer.get(3).frame_index, 3);
  assert.equal(buffer.get(4), null);
  await buffer.ensure(20); await buffer.ensure(40);
  assert.equal(buffer.frames.size, 8);
  assert.equal(buffer.get(40).frame_index, 40);
  buffer.close();
  assert.equal(buffer.frames.size, 0);
});

test("pending requests abort on unmount and cancelled results cannot repopulate cache", async () => {
  let resolve, signal;
  const buffer = new ReplayBuffer((_, __, abort) => {
    signal = abort;
    return new Promise(r => { resolve = r; });
  });
  const pending = buffer.ensure(0);
  buffer.close();
  assert.equal(signal.aborted, true);
  resolve([{ frame_index: 0 }]);
  await pending;
  assert.equal(buffer.get(0), null);
});

test("two viewers seek independently and retain stored IDs", async () => {
  const load = async start => [{ frame_index: start, global_id: 12 }];
  const a = new ReplayBuffer(load, { chunk: 1 }), b = new ReplayBuffer(load, { chunk: 1 });
  await a.ensure(100); await b.ensure(0);
  assert.equal(a.get(100).global_id, b.get(0).global_id);
  assert.equal(b.get(100), null);
});

test("zone counts consume native ACTIVE BEV only and never project camera boxes", () => {
  const frame = { cameras: { cam01: [{ state: "UNKNOWN", bev_position: { valid: true, zone_id: "A" } }] },
    bev: [
      { state: "ACTIVE", global_id: 1, camera_id: "cam01", x: 10, y: 15 },
      { state: "PARKED", global_id: 2, camera_id: "cam01", x: 10, y: 15 },
      { state: "ACTIVE", global_id: 3, camera_id: "cam02", x: 70, y: 75 },
    ] };
  const map = { width: 100, height: 100, zones: [
    { id: "A", bndbox: { xmin: 0, ymin: 0, xmax: 30, ymax: 30 } },
    { id: "B", bndbox: { xmin: 50, ymin: 50, xmax: 90, ymax: 90 } },
  ] };
  assert.deepEqual(replayZoneCounts(frame, map).map(x => x.count), [1, 1]);
  assert.deepEqual(replayZoneCounts(frame, map, "cam01").map(x => x.count), [1, 0]);
  assert.deepEqual(replayZoneCounts({ cameras: frame.cameras, bev: [] }, map).map(x => x.count), [0, 0]);
  assert.deepEqual(replayZoneCounts(null, map).map(x => x.count), [0, 0]);
});

test("map tracks preserve native observations and IDs without browser confidence fusion", () => {
  const point = { state: "ACTIVE", x: 10, y: 20, global_id: 7, camera_id: "cam01", local_id: 1, confidence: .8 };
  const frame = { bev: [point, { ...point, camera_id: "cam02", x: 15, confidence: .9 },
    { ...point, global_id: null }, { ...point, global_id: null, camera_id: "cam02" }] };
  const map = { width: 100, height: 100 };
  const all = replayTracks(frame, map);
  assert.equal(all.length, 4);
  assert.deepEqual(all.filter(item => item.global_id === 7).map(item => item.x), [10, 15]);
  assert.equal(all[0], point);
  const camera = replayTracks(frame, map, "cam01");
  assert.equal(camera.length, 2);
  assert.equal(camera.find(item => item.global_id === 7).x, 10);
  assert.deepEqual(replayTracks(frame, map, "cam03"), []);
});

test("unavailable or invalid map points never become phantom vehicle positions", () => {
  const point = { state: "ACTIVE", x: 0, y: 0, global_id: 1, camera_id: "cam01" };
  const invalid = [{ state: "UNKNOWN" }, { x: NaN }, { y: Infinity }, { x: -1 }, { y: -1 },
    { x: 100 }, { y: 100 }, { x: "10" }, { global_id: null }];
  const map = { width: 100, height: 100 };
  assert.equal(replayTracks({ bev: [point, ...invalid.map(change => ({ ...point, ...change }))] }, map).length, 1);
  assert.deepEqual(replayTracks(null, map), []);
  assert.deepEqual(replayTracks({ bev: [] }, map), []);
});

test("map display matches native ACTIVE policy without changing parked observations in source frames", () => {
  const point = { state: "ACTIVE", x: 10.125, y: 20.75, global_id: 9, local_id: 2, camera_id: "cam01" };
  const frame = { bev: [point, { ...point, state: "STOPPED" }, { ...point, state: "PARKED" }] };
  const before = structuredClone(frame);
  const rows = replayTracks(frame, { width: 100, height: 100 });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].x, point.x); assert.equal(rows[0].y, point.y);
  assert.deepEqual(frame, before);
});
