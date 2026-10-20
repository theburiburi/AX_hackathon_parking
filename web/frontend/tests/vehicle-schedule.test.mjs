import assert from "node:assert/strict";
import { after, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom" });
after(() => server.close());
const { default: VehicleSchedule, ScheduleBoard, ScheduleForm, minuteOfDay, moveDay, repeatLimit } = await server.ssrLoadModule("/src/VehicleSchedule.jsx");
const vehicle = { id: "V1", name: "공용 차량", plate_number: "TEST-01", team_id: "SECTION_DIGITAL_COMMUNICATION" };
const booking = { id: "S1", vehicle_id: "V1", vehicle_name: "공용 차량", plate_number: "TEST-01", team_id: vehicle.team_id, start_time: "09:30", end_time: "10:00", driver_name: "운전자", destination: "공장", purpose: "점검" };
const render = (props = {}) => renderToStaticMarkup(React.createElement(ScheduleBoard, { vehicles: [vehicle], schedules: [], selectedId: null, onSelect: () => {}, date: "2026-09-26", ...props }));

test("day navigation crosses month, year, and leap day boundaries", () => {
  assert.equal(moveDay("2026-12-31", 1), "2027-01-01");
  assert.equal(moveDay("2024-03-01", -1), "2024-02-29");
  assert.equal(minuteOfDay("24:00"), 1440);
});
test("empty day keeps vehicles and only the 07:30 to 18:00 display window visible", () => {
  const html = render();
  assert.match(html, /표시 시간 내 운행 없음/);
  assert.match(html, /TEST-01/);
  for (let hour = 0; hour < 24; hour++) {
    assert.equal(html.includes(`>${String(hour).padStart(2, "0")}:00</span>`), hour >= 8 && hour <= 18);
    assert.equal(html.includes(`>${String(hour).padStart(2, "0")}:30</span>`), hour >= 7 && hour < 18);
  }
  assert.match(html, /07:30~18:00/);
  assert.match(html, /--schedule-slots:21/);
  assert.match(html, /scope="row" class="schedule-vehicle"><strong>TEST-01/);
  assert.match(html, /시간은 왼쪽에서 오른쪽으로/);
  assert.match(html, /가로로 스크롤/);
  assert.doesNotMatch(html, /세로로 스크롤/);
});
test("minute precision positions blocks without rounding to hours", () => {
  const html = render({ schedules: [booking], selectedId: "S1" });
  assert.match(html, /left:19\.0476/);
  assert.match(html, /width:4\.7619/);
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /운전자 · 공장 · 점검/);
});
test("boundary bookings fill the operating window and deleted vehicles keep their row", () => {
  const html = render({ vehicles: [], schedules: [{ ...booking, start_time: "06:00", end_time: "20:00" }] });
  assert.match(html, /TEST-01/);
  assert.match(html, /06:00–20:00/);
  assert.match(html, /left:0%;width:100%/);
});
test("historical out-of-hours bookings are clipped without overflowing the time grid", () => {
  const html = render({ schedules: [{ ...booking, start_time: "05:00", end_time: "21:00" }, { ...booking, id: "late", start_time: "23:00", end_time: "24:00" }] });
  assert.match(html, /left:0%;width:100%/);
  assert.doesNotMatch(html, /23:00–24:00/);
  assert.match(html, /05:00–21:00/);
});

test("display clips crossing bookings and excludes bookings touching the outside boundaries", () => {
  const html = render({ schedules: [
    { ...booking, id: "early", start_time: "06:00", end_time: "07:30" },
    { ...booking, id: "morning", start_time: "07:00", end_time: "08:00" },
    { ...booking, id: "evening", start_time: "17:30", end_time: "19:00" },
    { ...booking, id: "late", start_time: "18:00", end_time: "20:00" },
  ] });
  assert.equal((html.match(/<button/g) || []).length, 2);
  assert.match(html, /left:0%;width:4\.7619/);
  assert.match(html, /left:95\.2380[^;]*;width:4\.7619/);
  assert.doesNotMatch(html, /06:00–07:30|18:00–20:00/);
});
test("booking form offers only half-hour times within the operating window", () => {
  const html = renderToStaticMarkup(React.createElement(ScheduleForm, {
    date: "2026-10-10", user: { id: "digital", name: "권혁돈", role: "USER" }, vehicles: [vehicle], members: [], busy: false,
    onSave() {}, onClose() {},
  }));
  const options = label => [...html.match(new RegExp(`<label>${label}<select[^>]*>(.*?)</select>`, "s"))[1].matchAll(/<option value="([^"]+)"/g)].map(match => match[1]);
  const slots = Array.from({ length: 29 }, (_, i) => `${String(6 + Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);
  assert.deepEqual(options("시작 시간"), slots.slice(0, -1));
  assert.deepEqual(options("종료 시간"), slots.slice(1));
  assert.doesNotMatch(html, /type="time"/);
  assert.match(html, /30분 단위/);
  assert.doesNotMatch(html, /24:00/);
  assert.doesNotMatch(html, /type="checkbox" checked/);
  assert.match(html, /평일 반복 \(월~금\)/);
  assert.doesNotMatch(html, /매일 고정|모든 날짜|반복 종료일/);
});
test("editing a dated booking preserves its non-recurring setting", () => {
  const html = renderToStaticMarkup(React.createElement(ScheduleForm, {
    initial: { ...booking, date: "2026-10-10", driver_id: "digital" },
    date: "2026-10-10", user: { id: "digital", name: "권혁돈", role: "USER" },
    vehicles: [vehicle], members: [], busy: false, onSave() {}, onClose() {},
  }));
  assert.match(html, /type="checkbox"/);
  assert.doesNotMatch(html, /type="checkbox" checked/);
});
test("editing an occurrence preserves the series anchor and bounds its end date", () => {
  const html = renderToStaticMarkup(React.createElement(ScheduleForm, {
    initial: { ...booking, date: "2026-10-12", driver_id: "digital", repeat_weekdays: true, repeat_until: "2026-11-11" },
    date: "2026-10-20", user: { id: "digital", name: "권혁돈", role: "USER" },
    vehicles: [vehicle], members: [], busy: false, onSave() {}, onClose() {},
  }));
  assert.match(html, /type="date" value="2026-10-12"/);
  assert.match(html, /type="date" min="2026-10-12" max="2026-11-11" value="2026-11-11"/);
  assert.match(html, /반복 시작일/);
  assert.match(html, /토·일 제외 · 공휴일 포함/);
  assert.match(html, /변경은 반복 기간 전체에 적용됩니다/);
  assert.match(html, /type="checkbox" checked=""/);
});
test("repeat limit clamps calendar months consistently across year and leap boundaries", () => {
  for (const [start, end] of [["2026-10-12", "2026-11-11"], ["2026-12-15", "2027-01-14"], ["2027-01-31", "2027-02-27"], ["2024-01-31", "2024-02-28"], ["2024-02-29", "2024-03-28"]]) {
    assert.equal(repeatLimit(start), end);
  }
});
test("only administrators get the section filter", () => {
  const renderUser = (role) => renderToStaticMarkup(React.createElement(VehicleSchedule, { user: { role, id: "digital", name: "권혁돈", team_id: vehicle.team_id }, api: "/api", token: "test" }));
  assert.doesNotMatch(renderUser("USER"), /전체 섹션/);
  assert.match(renderUser("ADMIN"), /전체 섹션/);
});
