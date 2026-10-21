import assert from "node:assert/strict";
import { test } from "node:test";
import { createReplayCanvas } from "../src/replayCanvas.js";

function canvasFixture() {
  let width = 300, height = 150, resized, observers = 0, disconnected = 0;
  const writes = [], transforms = [], clears = [], drawings = [];
  const context = {
    setTransform(...args) { transforms.push(args); },
    clearRect(...args) { clears.push(args); },
  };
  const canvas = {
    clientWidth: 400, clientHeight: 200,
    getContext(type) { assert.equal(type, "2d"); return context; },
    get width() { return width; }, set width(value) { width = value; writes.push(["width", value]); },
    get height() { return height; }, set height(value) { height = value; writes.push(["height", value]); },
  };
  class Observer {
    constructor(callback) { observers++; resized = callback; }
    observe(element) { assert.equal(element, canvas); }
    disconnect() { disconnected++; }
  }
  let density = 2, frame = 0;
  const painter = createReplayCanvas(canvas, (ctx, w, h) => {
    assert.equal(ctx, context);
    drawings.push({ frame, width: w, height: h });
  }, { Observer, readDensity: () => density });
  return { canvas, painter, writes, transforms, clears, drawings,
    setDensity(value) { density = value; }, setFrame(value) { frame = value; },
    resize() { resized(); }, get observers() { return observers; }, get disconnected() { return disconnected; } };
}

test("successive tracking frames paint every position using one observer and one canvas allocation", () => {
  const fixture = canvasFixture();
  for (let frame = 0; frame < 300; frame++) {
    fixture.setFrame(frame);
    fixture.painter.paint();
  }
  assert.equal(fixture.observers, 1);
  assert.deepEqual(fixture.writes, [["width", 800], ["height", 400]]);
  assert.deepEqual(fixture.drawings.map(row => row.frame), Array.from({ length: 300 }, (_, n) => n));
  assert.equal(fixture.clears.length, 300);
  assert.deepEqual(fixture.transforms.at(-1), [2, 0, 0, 2, 0, 0]);
  fixture.painter.close();
  assert.equal(fixture.disconnected, 1);
  fixture.resize();
  fixture.painter.paint();
  assert.equal(fixture.drawings.length, 300);
});

test("resize and density changes redraw current positions with the correct pixel dimensions", () => {
  const fixture = canvasFixture();
  fixture.painter.paint();
  fixture.setFrame(25);
  fixture.canvas.clientWidth = 500;
  fixture.resize();
  assert.deepEqual(fixture.writes.at(-1), ["width", 1000]);
  assert.deepEqual(fixture.drawings.at(-1), { frame: 25, width: 500, height: 200 });
  fixture.setDensity(1);
  fixture.painter.paint();
  assert.deepEqual(fixture.writes.slice(-2), [["width", 500], ["height", 200]]);
  assert.deepEqual(fixture.transforms.at(-1), [1, 0, 0, 1, 0, 0]);
  fixture.canvas.clientWidth = 0;
  fixture.resize();
  assert.equal(fixture.drawings.length, 3);
  fixture.canvas.clientWidth = 500;
  fixture.resize();
  assert.equal(fixture.drawings.length, 4);
  fixture.painter.close();
});
