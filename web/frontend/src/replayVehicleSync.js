import { frameForTime } from "./replayBuffer.js";

// Only the administrator's video playhead writes state. Seeks/pause wake the
// publisher immediately; pending writes finish before publishing the latest seek.
export function watchReplayVehicles({ readFrame, send, onError, interval = 250, subscribe,
  setTimer = setTimeout, clearTimer = clearTimeout }) {
  const controller = new AbortController();
  let active = true, timer, lastFrame = null, pending = false, requested = false;
  const sync = async () => {
    if (!active) return;
    clearTimer(timer);
    if (pending) { requested = true; return; }
    pending = true;
    requested = false;
    try {
      const frame = readFrame();
      if (Number.isInteger(frame) && frame !== lastFrame) {
        await send(frame, controller.signal);
        if (active) { lastFrame = frame; onError(""); }
      }
    } catch (error) {
      if (active && error.name !== "AbortError") onError(error.message);
    } finally {
      pending = false;
      if (active) {
        if (requested) sync();
        else timer = setTimer(sync, interval);
      }
    }
  };
  const unsubscribe = subscribe?.(sync);
  sync();
  return () => { active = false; unsubscribe?.(); controller.abort(); clearTimer(timer); };
}
export function watchReplayVideoState(video, { fps, frameCount, ...options }) {
  return watchReplayVehicles({ ...options,
    readFrame: () => video.readyState > 0 && !video.seeking
      ? frameForTime(video.currentTime, fps, frameCount) : null,
    subscribe: sync => {
      const events = ["loadeddata", "play", "pause", "seeked", "ended", "ratechange"];
      events.forEach(name => video.addEventListener(name, sync));
      return () => events.forEach(name => video.removeEventListener(name, sync));
    },
  });
}
