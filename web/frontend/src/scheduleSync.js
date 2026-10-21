// Refresh shared bookings without concurrent reads or resetting an open form.
export function watchScheduleState({ load, onState, onError, interval = 1000,
  events, setTimer = setTimeout, clearTimer = clearTimeout }) {
  const controller = new AbortController();
  let active = true, pending = false, queued = false, timer, previous;
  const refresh = async () => {
    if (!active) return;
    clearTimer(timer);
    if (pending) { queued = true; return; }
    pending = true;
    try {
      const state = await load(controller.signal);
      if (active) {
        const serialized = JSON.stringify(state);
        if (serialized !== previous) { previous = serialized; onState(state); }
        onError(null);
      }
    } catch (error) {
      if (active && error.name !== "AbortError") onError(error);
    } finally {
      pending = false;
      if (active) {
        if (queued) { queued = false; void refresh(); }
        else timer = setTimer(refresh, interval);
      }
    }
  };
  events?.addEventListener("focus", refresh);
  refresh();
  return { refresh, stop() {
    active = false; controller.abort(); clearTimer(timer);
    events?.removeEventListener("focus", refresh);
  } };
}

export function scheduleDisplayDate(booking, currentDate) {
  if (!booking.repeat_weekdays) return booking.date;
  const weekday = day => new Date(`${day}T12:00:00Z`).getUTCDay();
  if (currentDate >= booking.date && currentDate <= booking.repeat_until
      && weekday(currentDate) > 0 && weekday(currentDate) < 6) return currentDate;
  const first = new Date(`${booking.date}T12:00:00Z`);
  while (first.getUTCDay() === 0 || first.getUTCDay() === 6) first.setUTCDate(first.getUTCDate() + 1);
  return first.toISOString().slice(0, 10);
}
