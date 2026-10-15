import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";

// Import the repository viewer's shared drawing module without DOM startup.
const source = await readFile(new URL("../../viewer-rendering.js", import.meta.url), "utf8");
const helpers = await readFile(new URL("../../bev_items.js", import.meta.url), "utf8");
const helperUrl = `data:text/javascript;base64,${Buffer.from(helpers).toString("base64")}`;
const { drawDetection, drawBevTracking, STATE_COLORS, CAMERA_COLORS } = await import(
  `data:text/javascript;base64,${Buffer.from(source.replace('"./bev_items.js"', JSON.stringify(helperUrl))).toString("base64")}`
);

function context() {
  const calls = [];
  return { calls,
    measureText: text => ({ width: text.length * 6 }),
    strokeRect(...args) { calls.push(["box", this.strokeStyle, ...args]); },
    fillRect(...args) { calls.push(["background", ...args]); },
    fillText(...args) { calls.push(["text", ...args]); calls.push(["alpha", this.globalAlpha]); },
    beginPath() {},
    arc(...args) { calls.push(["arc", ...args]); },
    fill() { calls.push(["fill", this.fillStyle]); },
  };
}

test("repository bbox renderer applies tile offset and keeps confirmed IDs in every state", () => {
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
    assert.ok(inactive.calls.some(call => call[0] === "text" && call[1] === "G003"));
  }
});

test("repository BEV renderer collapses shared IDs without mutating supplied coordinates", () => {
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

test("bbox candidates are dimmed and unassigned vehicles have no invented ID", () => {
  const layout = { offsetX: 0, offsetY: 0, scale: 1 };
  const camera = { rect: [0, 0] };
  const box = { x1: 10, y1: 20, x2: 50, y2: 80, global_id: null, local_id: 7, state: "STOPPED" };
  const provisional = context();
  provisional.globalAlpha = 1;
  drawDetection(provisional, layout, camera, { ...box, provisional_global_id: 2 });
  assert.ok(provisional.calls.some(call => call[0] === "text" && call[1] === "G002?"));
  assert.ok(provisional.calls.some(call => call[0] === "alpha" && call[1] === 0.6));
  assert.equal(provisional.globalAlpha, 1);
  const unassigned = context();
  drawDetection(unassigned, layout, camera, box);
  assert.equal(unassigned.calls.filter(call => call[0] === "text").length, 0);
});

test("BEV keeps parked and stopped markers with state colors and labels only assigned GIDs", () => {
  const ctx = context();
  drawBevTracking(ctx, { offsetX: 0, offsetY: 0, scale: 1 }, { bev: [
    { x: 100, y: 200, camera_id: "cam07", state: "PARKED", global_id: 9 },
    { x: 300, y: 400, camera_id: "cam06", state: "STOPPED", global_id: null, local_id: 8 },
  ] });
  assert.equal(ctx.calls.filter(call => call[0] === "arc").length, 4);
  assert.ok(ctx.calls.some(call => call[0] === "fill" && call[1] === STATE_COLORS.PARKED));
  assert.ok(ctx.calls.some(call => call[0] === "fill" && call[1] === STATE_COLORS.STOPPED));
  assert.deepEqual(ctx.calls.filter(call => call[0] === "text").map(call => call[1]), ["G009"]);
});
