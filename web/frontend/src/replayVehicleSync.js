// One writer per enabled viewer, at most one request in flight. Frame prefetch
// never changes shared vehicle state; only the actual displayed frame is sent.
export function watchReplayVehicles({ readFrame, send, onError, interval = 1000,
  setTimer = setTimeout, clearTimer = clearTimeout }) {
  const controller = new AbortController();
  let active = true, timer, lastFrame = null;
  const sync = async () => {
    try {
      const frame = readFrame();
      if (Number.isInteger(frame) && frame !== lastFrame) {
        await send(frame, controller.signal);
        if (active) { lastFrame = frame; onError(""); }
      }
    } catch (error) {
      if (active && error.name !== "AbortError") onError(error.message);
    } finally {
      if (active) timer = setTimer(sync, interval);
    }
  };
  sync();
  return () => { active = false; controller.abort(); clearTimer(timer); };
}
