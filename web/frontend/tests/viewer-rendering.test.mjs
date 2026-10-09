import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";

// Import the repository viewer's shared drawing module without DOM startup.
const source = await readFile(new URL("../../viewer-rendering.js", import.meta.url), "utf8");
const { drawDetection, drawBevTracking, STATE_COLORS, CAMERA_COLORS } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

function context() {
  const calls = [];
  return { calls,
    measureText: text => ({ width: text.length * 6 }),
    strokeRect(...args) { calls.push(["box", this.strokeStyle, ...args]); },
    fillRect(...args) { calls.push(["background", ...args]); },
    fillText(...args) { calls.push(["text", ...args]); },
    beginPath() {},
    arc(...args) { calls.push(["arc", ...args]); },
    fill() { calls.push(["fill", this.fillStyle]); },
  };
}

test("repository bbox renderer applies tile offset and native state colors; only ACTIVE gets an ID", () => {
  const ctx = context();
  const layout = { offsetX: 3, offsetY: 5, scale: .5 };
  const camera = { id: "cam02", rect: [1280, 720, 2560, 1440] };
  const box = { x1: 10, y1: 20, x2: 50, y2: 80, global_id: 3, local_id: 7, state: "ACTIVE" };
  drawDetection(ctx, layout, camera, box);
  assert.deepEqual(ctx.calls[0], ["box", STATE_COLORS.ACTIVE, 648, 375, 20, 30]);
  assert.ok(ctx.calls.some(call => call[0] === "text" && call[1] === "G003"));
  for (const state of ["UNKNOWN", "STOPPED", "PARKED"]) {
    const inactive = context();
    drawDetection(inactive, layout, camera, { ...box, state });
    assert.equal(inactive.calls[0][1], STATE_COLORS[state]);
    assert.equal(inactive.calls.filter(call => call[0] === "text").length, 0);
  }
});

test("repository BEV renderer preserves supplied coordinates and uses camera colors for ACTIVE observations", () => {
  const ctx = context();
  const item = { x: 100.25, y: 200.75, camera_id: "cam07", state: "ACTIVE", global_id: 9 };
  const frame = { bev: [item, { ...item, state: "PARKED" }] };
  const original = structuredClone(frame);
  drawBevTracking(ctx, { offsetX: 4, offsetY: 10, scale: .5 }, frame);
  const arcs = ctx.calls.filter(call => call[0] === "arc");
  assert.equal(arcs.length, 2);
  assert.deepEqual(arcs[0].slice(1, 4), [54.125, 110.375, 6]);
  assert.ok(ctx.calls.some(call => call[0] === "fill" && call[1] === CAMERA_COLORS.cam07));
  assert.ok(ctx.calls.some(call => call[0] === "text" && call[1] === "G009"));
  assert.deepEqual(frame, original);
  const missing = context();
  drawBevTracking(missing, { scale: 1 }, null);
  assert.equal(missing.calls.length, 0);
});
