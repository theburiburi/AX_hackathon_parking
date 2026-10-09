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
const { Dashboard } = await server.ssrLoadModule("/src/main.jsx");
const { ReplayTrackOverlay } = await server.ssrLoadModule("/src/CachedReplay.jsx");
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
  assert.doesNotMatch(html, /차량 관리 요청|내 요청 이력|요청 제출|승인 대기/);
  assert.doesNotMatch(html, /실시간 분석|영상 분석 재생|실시간 감지 모드/);
});
