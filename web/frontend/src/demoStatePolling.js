// A single ordered read keeps the clock, vehicle list and zone totals together.
// Keep the last good view on network failures; never overlap requests.
export function watchDemoState({ load, onState, onError, interval = 250,
  setTimer = setTimeout, clearTimer = clearTimeout }) {
  const controller = new AbortController();
  let active = true, timer, previous;
  const refresh = async () => {
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
      if (active) timer = setTimer(refresh, interval);
    }
  };
  refresh();
  return () => { active = false; controller.abort(); clearTimer(timer); };
}
