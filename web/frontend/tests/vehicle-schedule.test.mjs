import assert from "node:assert/strict";
import { after, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom" });
after(() => server.close());
const { default: VehicleSchedule, ScheduleBoard, minuteOfDay, moveDay } = await server.ssrLoadModule("/src/VehicleSchedule.jsx");
const vehicle = { id: "V1", name: "공용 차량", plate_number: "TEST-01", team_id: "SECTION_DIGITAL_COMMUNICATION" };
const booking = { id: "S1", vehicle_id: "V1", vehicle_name: "공용 차량", plate_number: "TEST-01", team_id: vehicle.team_id, start_time: "09:30", end_time: "10:00", driver_name: "운전자", destination: "공장", purpose: "점검" };
const render = (props = {}) => renderToStaticMarkup(React.createElement(ScheduleBoard, { vehicles: [vehicle], schedules: [], selectedId: null, onSelect: () => {}, date: "2026-09-26", ...props }));

test("day navigation crosses month, year, and leap day boundaries", () => {
  assert.equal(moveDay("2026-12-31", 1), "2027-01-01");
  assert.equal(moveDay("2024-03-01", -1), "2024-02-29");
  assert.equal(minuteOfDay("24:00"), 1440);
});
test("empty day keeps vehicles and all 24 hour headers visible", () => {
  const html = render();
  assert.match(html, /등록된 운행 없음/);
  assert.match(html, /TEST-01/);
  for (let hour = 0; hour < 24; hour++) assert.ok(html.includes(`>${String(hour).padStart(2, "0")}</th>`));
});
test("minute precision positions blocks without rounding to hours", () => {
  const html = render({ schedules: [booking], selectedId: "S1" });
  assert.match(html, /left:39\.5833/);
  assert.match(html, /width:2\.0833/);
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /운전자 · 공장 · 점검/);
});
test("midnight end stays within the day and deleted vehicles keep historical bookings", () => {
  const html = render({ vehicles: [], schedules: [{ ...booking, start_time: "23:00", end_time: "24:00" }] });
  assert.match(html, /TEST-01/);
  assert.match(html, /23:00–24:00/);
  assert.match(html, /left:95\.8333/);
});
test("only administrators get the section filter", () => {
  const renderUser = (role) => renderToStaticMarkup(React.createElement(VehicleSchedule, { user: { role, id: "digital", name: "권혁돈", team_id: vehicle.team_id }, api: "/api", token: "test" }));
  assert.doesNotMatch(renderUser("USER"), /전체 섹션/);
  assert.match(renderUser("ADMIN"), /전체 섹션/);
});
