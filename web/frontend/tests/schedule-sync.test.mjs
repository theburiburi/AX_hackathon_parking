import assert from "node:assert/strict";
import { test } from "node:test";
import { watchScheduleState, scheduleDisplayDate } from "../src/scheduleSync.js";

const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

test("two users receive creation, edits and cancellation without reloading or duplicate redraws", async () => {
  let bookings = [];
  const viewers = [0, 1].map(() => {
    const states = [];
    let timer;
    const watcher = watchScheduleState({
      load: async () => ({ schedules: structuredClone(bookings) }),
      onState: state => states.push(state), onError() {},
      setTimer: (callback, delay) => { assert.equal(delay, 1000); timer = callback; }, clearTimer() {},
    });
    return { watcher, states, tick: () => timer() };
  });
  await flush();
  bookings = [{ id: "S1", purpose: "Inspection" }];
  for (const viewer of viewers) await viewer.tick();
  bookings[0].purpose = "Meeting";
  for (const viewer of viewers) await viewer.tick();
  for (const viewer of viewers) await viewer.tick();
  bookings = [];
  for (const { watcher, states, tick } of viewers) {
    await tick();
    assert.deepEqual(states.map(state => state.schedules[0]?.purpose), [undefined, "Inspection", "Meeting", undefined]);
    watcher.stop();
  }
});

test("save and focus during a slow read queue one fresh read; stopping aborts and removes listeners", async () => {
  const events = new EventTarget();
  let resolve, timer, calls = 0, signal;
  const states = [];
  const watcher = watchScheduleState({
    events, load: abort => { calls++; signal = abort; return new Promise(r => { resolve = r; }); },
    onState: state => states.push(state), onError() {},
    setTimer: callback => { timer = callback; }, clearTimer() {},
  });
  watcher.refresh(); events.dispatchEvent(new Event("focus"));
  assert.equal(calls, 1);
  assert.equal(timer, undefined);
  resolve({ schedules: [] }); await flush();
  assert.equal(calls, 2);
  resolve({ schedules: [{ id: "new" }] }); await flush();
  assert.equal(states.at(-1).schedules[0].id, "new");
  watcher.stop();
  assert.equal(signal.aborted, true);
  events.dispatchEvent(new Event("focus")); await timer();
  assert.equal(calls, 2);
});

test("failed refresh preserves the last schedules and recovers", async () => {
  let timer, fail = false;
  const states = [], errors = [];
  const watcher = watchScheduleState({
    load: async () => { if (fail) throw new Error("offline"); return { schedules: [{ id: "S1" }] }; },
    onState: state => states.push(state), onError: error => errors.push(error?.message),
    setTimer: callback => { timer = callback; }, clearTimer() {},
  });
  await flush(); fail = true; await timer();
  assert.equal(states.length, 1); assert.equal(errors.at(-1), "offline");
  fail = false; await timer();
  assert.equal(errors.at(-1), undefined); assert.equal(states.length, 1);
  watcher.stop();
});

test("saved bookings open on an actual occurrence, including weekend and cross-year starts", () => {
  const series = { date: "2026-10-18", repeat_weekdays: true, repeat_until: "2026-11-17" };
  assert.equal(scheduleDisplayDate(series, "2026-10-18"), "2026-10-19");
  assert.equal(scheduleDisplayDate(series, "2026-10-20"), "2026-10-20");
  assert.equal(scheduleDisplayDate(series, "2026-10-25"), "2026-10-19");
  assert.equal(scheduleDisplayDate(series, "2026-11-18"), "2026-10-19");
  assert.equal(scheduleDisplayDate({ ...series, date: "2028-12-30", repeat_until: "2029-01-29" }, "2028-12-30"), "2029-01-01");
  assert.equal(scheduleDisplayDate({ date: "2026-10-18", repeat_weekdays: false }, "2026-10-19"), "2026-10-18");
});
