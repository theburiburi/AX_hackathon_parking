import assert from "node:assert/strict";
import { after, test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

// Render the dashboard without mounting the application entry into a browser.
const server = await createServer({
  server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom",
  plugins: [{
    name: "skip-browser-mount",
    enforce: "pre",
    transform(code, id) {
      if (id.endsWith("/src/main.jsx")) return code.replace(
        'createRoot(document.getElementById("root")).render(<App />);', "",
      );
    },
  }],
});
after(() => server.close());
const { Dashboard, VehicleList } = await server.ssrLoadModule("/src/main.jsx");
const { ReplayTrackOverlay, ReplayGateLog } = await server.ssrLoadModule("/src/CachedReplay.jsx");
const render = (role) => renderToStaticMarkup(React.createElement(Dashboard, {
  session: { token: "test", user: { role, team_id: "SECTION_DIGITAL_COMMUNICATION", name: "테스트 사용자" } },
  onLogout() {},
}));

test("administrator opens analysis directly without navigation or overview switches", () => {
  const html = render("ADMIN");
  assert.doesNotMatch(html, /<nav|운영 화면 전환|운영 현황|차량 운행 스케줄|차량 입출차 내역/);
  assert.match(html, /aria-label="실시간 분석"/);
  assert.match(html, /<h2>실시간 분석<\/h2>/);
  assert.doesNotMatch(html, /실시간 감지 모드|YOLO로 차량/);
  assert.doesNotMatch(html, /관리 요청|반려 사유|승인 시/);
  assert.match(html, /실시간 추적 모드/);
  assert.match(html, /aria-pressed="false" disabled=""[^>]*>.*?<strong>OFF<\/strong>/s);
  assert.doesNotMatch(html, /parking-zone-filters/);
});

test("map tracking ON mounts the shared renderer canvas; OFF and absent frames hide it", () => {
  const frame = { bev: [{ x: 100, y: 200, global_id: 3, camera_id: "cam01", state: "ACTIVE" }] };
  const renderTracks = (enabled, current = frame) => renderToStaticMarkup(React.createElement(ReplayTrackOverlay, {
    enabled, frame: current, map: { width: 1624, height: 968 }, camera: "",
  }));
  assert.equal(renderTracks(false), "");
  assert.match(renderTracks(true), /<canvas[^>]*aria-label="현재 차량 위치"/);
  assert.equal(renderTracks(true, null), "");
  assert.doesNotMatch(renderTracks(true), /<circle|<text/);
});

test("regular user sees vehicle status and schedule without requests or request history", () => {
  const html = render("USER");
  assert.match(html, /차량 현황/);
  assert.match(html, /차량 운행 스케줄/);
  assert.match(html, /주차장 차량 위치/);
  assert.match(html, /차량 목록/);
  assert.doesNotMatch(html, /관리자 영상 연동|관리자 영상 재생 대기|demo-sync-status/);
  assert.doesNotMatch(html, /3초마다/);
  assert.doesNotMatch(html, /차량 관리 요청|내 요청 이력|요청 제출|승인 대기/);
  assert.doesNotMatch(html, /실시간 분석|영상 분석 재생|실시간 감지 모드/);
});

test("gate history remains visible while tracking frames are unavailable and follows backward seeks", () => {
  const gateLog = { events: [
    { frame: 30, type: "IN", plate: "111가1111" },
    { frame: 90, type: "OUT", plate: "111가1111" },
  ] };
  // No tracking frame is supplied: this panel follows the displayed video time.
  const renderGate = time => renderToStaticMarkup(React.createElement(ReplayGateLog, {
    gateLog, time, fps: 30, frameCount: 300, onSeek() {},
  }));
  for (const time of [1, 1.5, 2, 2.5]) {
    const html = renderGate(time);
    assert.match(html, /1건/);
    assert.match(html, /입차.*111 가 1111/);
    assert.doesNotMatch(html, /출차|기록이 없습니다/);
  }
  assert.match(renderGate(3), /2건/);
  assert.match(renderGate(.5), /0건/);
  assert.match(renderGate(.5), /기록이 없습니다/);
  assert.match(renderGate(1), /1건/);
});

test("account header displays the name and section supplied by the user JSON", () => {
  const html = renderToStaticMarkup(React.createElement(Dashboard, {
    session: { token: "test", user: { role: "USER", team_id: "SECTION_DIGITAL_COMMUNICATION", team_name: "JSON 섹션", name: "JSON 사용자" } },
    onLogout() {},
  }));
  assert.match(html, /<strong>JSON 섹션<\/strong> · JSON 사용자/);
  assert.match(html, /조회 범위: JSON 섹션/);
});

test("account header falls back to the login ID when the display name is empty", () => {
  const html = renderToStaticMarkup(React.createElement(Dashboard, {
    session: { token: "test", user: { id: "digital2", role: "USER", team_id: "SECTION_DIGITAL_COMMUNICATION", name: "" } },
    onLogout() {},
  }));
  assert.match(html, /<strong>디지털통신기술섹션<\/strong> · digital2/);
});

test("vehicle list shows the zone or driving label without stale zones for moving and exited vehicles", () => {
  const renderVehicle = (status, current_zone_id) => renderToStaticMarkup(React.createElement(VehicleList, {
    vehicles: [{ id: "V1", plate_number: "12가3456", team_id: "SECTION_DIGITAL_COMMUNICATION", status, current_zone_id, last_seen_at: null }],
    zones: [{ id: "EXTERNAL", name: "외부 구역" }],
  }));
  assert.match(renderVehicle("PARKED", "A"), /class="badge parked">A 구역</);
  assert.match(renderVehicle("PARKED", "EXTERNAL"), /class="badge parked">외부 구역</);
  assert.match(renderVehicle("PARKED", "P1"), /class="badge parked">구역 미확인</);
  assert.match(renderVehicle("UNKNOWN", null), /class="badge unknown">구역 미확인</);
  const moving = renderVehicle("MOVING", "A");
  assert.match(moving, /class="badge moving">운행중</);
  assert.doesNotMatch(moving, /A 구역|>MOVING</);
  const parking = renderVehicle("PARKING", "A");
  assert.match(parking, /class="badge parking">주차중</);
  assert.doesNotMatch(parking, /A 구역|>PARKING</);
  const exited = renderVehicle("EXITED", "A");
  assert.match(exited, /class="badge exited">출차</);
  assert.doesNotMatch(exited, /A 구역|>EXITED</);
});
