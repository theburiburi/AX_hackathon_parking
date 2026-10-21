import assert from "node:assert/strict";
import { test } from "node:test";
import { watchSessionProfile } from "../src/sessionProfile.js";

const flush = () => new Promise(resolve => setImmediate(resolve));
const targets = () => ({ windowTarget: new EventTarget(), documentTarget: Object.assign(new EventTarget(), { visibilityState: "visible" }) });

test("profile reloads on opening, focus and the visible refresh interval", async context => {
  context.mock.timers.enable({ apis: ["setInterval"] });
  const events = targets(), names = [];
  let team_name = "처음 섹션";
  const stop = watchSessionProfile({ ...events, load: async () => ({ id: "digital", team_name }), onUser: user => names.push(user.team_name), onExpired() { assert.fail("valid session must remain logged in"); } });
  context.after(stop);
  await flush();
  assert.deepEqual(names, ["처음 섹션"]);
  team_name = "광양디지털통신기술섹션";
  events.windowTarget.dispatchEvent(new Event("focus"));
  await flush();
  assert.equal(names.at(-1), team_name);
  events.documentTarget.visibilityState = "hidden";
  context.mock.timers.tick(30000);
  events.documentTarget.dispatchEvent(new Event("visibilitychange"));
  await flush();
  assert.equal(names.length, 2);
  events.documentTarget.visibilityState = "visible";
  team_name = "새 섹션명";
  events.documentTarget.dispatchEvent(new Event("visibilitychange"));
  await flush();
  assert.equal(names.at(-1), "새 섹션명");
  team_name = "열린 화면에서 변경";
  context.mock.timers.tick(30000);
  await flush();
  assert.equal(names.at(-1), team_name);
});

test("logout cancels polling and ignores late responses from the previous session", async context => {
  context.mock.timers.enable({ apis: ["setInterval"] });
  const events = targets(), users = [];
  let complete, signal, calls = 0;
  const stop = watchSessionProfile({ ...events, load: abortSignal => { calls++; signal = abortSignal; return new Promise(resolve => { complete = resolve; }); }, onUser: user => users.push(user), onExpired() { assert.fail("stopped session must not change login"); } });
  events.windowTarget.dispatchEvent(new Event("focus"));
  assert.equal(calls, 1);
  stop();
  assert.equal(signal.aborted, true);
  complete({ id: "previous-user" });
  await flush();
  events.windowTarget.dispatchEvent(new Event("focus"));
  context.mock.timers.tick(60000);
  await flush();
  assert.equal(calls, 1);
  assert.deepEqual(users, []);
});

test("temporary API failures preserve login; expired credentials request logout", async context => {
  const events = targets();
  let status = 503, expired = 0;
  const stop = watchSessionProfile({ ...events, load: async () => { throw Object.assign(new Error("request failed"), { status }); }, onUser() { assert.fail("failed request must not replace the profile"); }, onExpired: () => { expired++; } });
  context.after(stop);
  await flush();
  assert.equal(expired, 0);
  status = 401;
  events.windowTarget.dispatchEvent(new Event("focus"));
  await flush();
  assert.equal(expired, 1);
});
