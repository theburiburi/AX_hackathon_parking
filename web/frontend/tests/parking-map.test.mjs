import assert from "node:assert/strict";
import { after, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom" });
after(() => server.close());
const { default: ParkingMap, displayPosition, zoneName } = await server.ssrLoadModule("/src/ParkingMap.jsx");
const vehicle = { id: "V1", plate_number: "TEST-01", status: "PARKED" };
const map = { filename: "parkinglot_map.jpg", url: "/admin/media/maps/map/parkinglot_map.jpg" };
const render = (props = {}) => renderToStaticMarkup(React.createElement(ParkingMap, {
  parkingMap: null, vehicles: [], api: "http://localhost:8000/api", token: "test", ...props,
}));

test("first render works before map and layout arrive", () => {
  assert.match(render(), /parking-panel/);
});

test("vehicles without coordinates render when map and layout are missing", () => {
  assert.match(render({ vehicles: [vehicle] }), /1 위치 미확인/);
});

test("missing map does not access null vehicle coordinates", () => {
  assert.match(render({ layout: { map_id: map.filename, zones: [] }, vehicles: [{ ...vehicle, map_position: null }] }), /1 위치 미확인/);
});

test("map can render while layout is missing or its zones are not yet available", () => {
  assert.match(render({ parkingMap: map, vehicles: [vehicle] }), /parking-canvas/);
  assert.match(render({ parkingMap: map, layout: { map_id: map.filename }, vehicles: [vehicle] }), /parking-canvas/);
});

test("map footer does not duplicate zone filters, vehicle details or the vehicle list", () => {
  const layout = { map_id: map.filename, zones: [{ id: "A", name: "A 구역", color: "#38bdf8", label: [50, 50], polygon: [[0, 0], [100, 0], [100, 100]] }] };
  const html = render({ parkingMap: map, layout, vehicles: [vehicle] });
  assert.match(html, /parking-canvas/);
  assert.doesNotMatch(html, /parking-legend|parking-zone-filters|parking-detail|parking-vehicle-list|parking-note/);
  assert.doesNotMatch(html, /사진 속 차량|점선 마커|차량 위치 수신 대기/);
});

test("zone location works without recognition coordinates and exact coordinates take precedence", () => {
  const zones = [{ id: "P1", label: [59, 22] }];
  const parked = { ...vehicle, current_zone_id: "P1" };
  assert.deepEqual(displayPosition(parked, map.filename, zones), { x: 59, y: 22, source: "zone" });
  assert.equal(displayPosition({ ...parked, status: "EXITED" }, map.filename, zones), null);
  assert.equal(displayPosition({ ...parked, current_zone_id: null }, map.filename, zones), null);
  const coordinates = { map_id: map.filename, x: 61, y: 24 };
  assert.deepEqual(displayPosition({ ...parked, map_position: coordinates }, map.filename, zones), { ...coordinates, source: "exact" });
});

test("zone-only vehicle still contributes to the map position count", () => {
  const html = render({ parkingMap: map, layout: { map_id: map.filename, zones: [{ id: "A", name: "A 구역", label: [59, 22] }] }, vehicles: [{ ...vehicle, current_zone_id: "A" }] });
  assert.match(html, /<strong>1<\/strong> 위치 확인/);
  assert.match(html, /0 위치 미확인/);
});

test("old numbered layouts cannot show numbered regions or false approximate positions", () => {
  const layout = { map_id: map.filename, zones: [{ id: "P1", name: "1구역", label: [50, 50] }] };
  const html = render({ parkingMap: map, layout, vehicles: [{ ...vehicle, current_zone_id: "P1" }] });
  assert.doesNotMatch(html, /1구역|P1 · 구역 기준/);
  assert.match(html, /위치 미확인/);
  assert.equal(zoneName("P1"), "구역 미확인");
  assert.equal(zoneName("A"), "A 구역");
});

test("native zone IDs and labels are authoritative instead of hardcoded letters", () => {
  const zone = { id: "EXTERNAL", name: "외부 구역", label: [50, 50] };
  const layout = { map_id: map.filename, source: "native", zones: [zone] };
  const html = render({ parkingMap: map, layout, vehicles: [{ ...vehicle, current_zone_id: zone.id }] });
  assert.match(html, /<strong>1<\/strong> 위치 확인/);
  assert.deepEqual(displayPosition({ ...vehicle, current_zone_id: zone.id }, map.filename, [zone]), { x: 50, y: 50, source: "zone" });
  assert.equal(zoneName(zone.id, [zone]), "외부 구역");
});
