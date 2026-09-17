import assert from "node:assert/strict";
import { after, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const server = await createServer({ server: { middlewareMode: true }, appType: "custom" });
after(() => server.close());
const { default: ParkingMap, displayPosition } = await server.ssrLoadModule("/src/ParkingMap.jsx");
const vehicle = { id: "V1", plate_number: "TEST-01", status: "PARKED" };
const map = { filename: "parkinglot_map.jpg", url: "/admin/media/maps/map/parkinglot_map.jpg" };
const render = (props = {}) => renderToStaticMarkup(React.createElement(ParkingMap, {
  parkingMap: null, vehicles: [], api: "http://localhost:8000/api", token: "test", ...props,
}));

test("first render works before map and layout arrive", () => {
  assert.match(render(), /parking-panel/);
});

test("vehicles without coordinates render when map and layout are missing", () => {
  assert.match(render({ vehicles: [vehicle] }), /TEST-01/);
});

test("missing map does not access null vehicle coordinates", () => {
  assert.match(render({ layout: { map_id: map.filename, zones: [] }, vehicles: [{ ...vehicle, map_position: null }] }), /TEST-01/);
});

test("map can render while layout is missing or its zones are not yet available", () => {
  assert.match(render({ parkingMap: map, vehicles: [vehicle] }), /parking-canvas/);
  assert.match(render({ parkingMap: map, layout: { map_id: map.filename }, vehicles: [vehicle] }), /parking-canvas/);
});

test("loaded layout renders zone controls", () => {
  const layout = { map_id: map.filename, zones: [{ id: "P1", name: "ZONE-1", color: "#38bdf8", label: [50, 50], polygon: [[0, 0], [100, 0], [100, 100]] }] };
  assert.match(render({ parkingMap: map, layout, vehicles: [vehicle] }), /ZONE-1/);
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

test("zone-only vehicle is identified by plate and shown as approximate", () => {
  const html = render({ parkingMap: map, layout: { map_id: map.filename, zones: [{ id: "P1", name: "P1", label: [59, 22] }] }, vehicles: [{ ...vehicle, current_zone_id: "P1" }] });
  assert.match(html, /TEST-01/);
  assert.match(html, /P1 · 구역 기준/);
});
