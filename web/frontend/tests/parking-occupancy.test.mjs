import assert from "node:assert/strict";
import { after, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom" });
after(() => server.close());
const { ParkingOccupancySummary } = await server.ssrLoadModule("/src/ParkingOccupancy.jsx");
const render = props => renderToStaticMarkup(React.createElement(ParkingOccupancySummary, props));

test("no inventory response shows loading or failure instead of a false zero", () => {
  const loading = render({ zones: null });
  assert.match(loading, /불러오는 중/);
  assert.doesNotMatch(loading, /총 0대/);
  const failed = render({ zones: null, error: true });
  assert.match(failed, /갱신 실패/);
  assert.doesNotMatch(failed, /총 0대/);
});

test("zone ratios show counts above capacity without overflow messages", () => {
  const html = render({ zones: [
    { id: "A", name: "A 구역", capacity: 14, parked_count: 20, overflow_count: 6 },
    { id: "B", name: "B 구역", capacity: 10, parked_count: 0, overflow_count: 0 },
  ], error: true });
  assert.match(html, /총 20대 \/ 24대/);
  assert.match(html, /현재 20대 \/ 최대 14대/);
  assert.doesNotMatch(html, /오버플로우/);
  assert.doesNotMatch(html, /이중주차|주차 유형 미확인/);
  assert.match(html, /마지막 조회 결과/);
  assert.match(html, /B 구역/);
});

test("unknown capacity is not presented as zero or full", () => {
  const html = render({ zones: [{ id: "A", name: "A 구역", capacity: null, parked_count: 20, overflow_count: null }] });
  assert.match(html, /총 20대 \/ —대/);
  assert.match(html, /현재 20대 \/ 최대 미확인대/);
  assert.doesNotMatch(html, /오버플로우/);
});
