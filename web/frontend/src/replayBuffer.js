export function frameForTime(seconds, fps, count) {
  return Math.max(0, Math.min(count - 1, Math.floor(seconds * fps + 1e-4)));
}

// Gate events are already loaded with the manifest. A missing tracking frame
// must not clear their history while the next batch is being fetched.
export function gateEventsForTime(gateLog, seconds, fps, frameCount) {
  const frameIndex = frameForTime(seconds, fps, frameCount);
  return (gateLog?.events || []).filter(event => event.frame <= frameIndex).slice().reverse();
}

// A paused seek may deliver its only video-frame callback while seeking is
// still true. The seeked event must load the destination independently.
export function watchReplayMedia(video, { fps, frameCount, present, seeking,
  requestFrame = requestAnimationFrame, cancelFrame = cancelAnimationFrame }) {
  let active = true, callback;
  const current = () => frameForTime(video.currentTime, fps, frameCount);
  const loaded = () => present(current());
  const onSeeking = () => seeking(current());
  const tick = (_, metadata) => {
    if (!active) return;
    if (!video.seeking) present(frameForTime(metadata?.mediaTime ?? video.currentTime, fps, frameCount));
    schedule();
  };
  const schedule = () => {
    callback = video.requestVideoFrameCallback ? video.requestVideoFrameCallback(tick) : requestFrame(tick);
  };
  video.addEventListener("loadeddata", loaded);
  video.addEventListener("seeking", onSeeking);
  video.addEventListener("seeked", loaded);
  loaded();
  schedule();
  return () => {
    active = false;
    if (video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(callback); else cancelFrame(callback);
    video.removeEventListener("loadeddata", loaded);
    video.removeEventListener("seeking", onSeeking);
    video.removeEventListener("seeked", loaded);
  };
}

export function watchReplayKeyboard(target, readActions) {
  const keyboard = event => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest?.("input,select,textarea,button,[contenteditable=true]")) return;
    const { time, seek, step, toggle } = readActions();
    if (event.code === "Space") { event.preventDefault(); toggle(); }
    else if (event.code === "KeyA") seek(time - (event.shiftKey ? 30 : 5));
    else if (event.code === "KeyD") seek(time + (event.shiftKey ? 30 : 5));
    else if (event.code === "Comma") step(-1);
    else if (event.code === "Period") step(1);
    else if (event.code === "KeyR") seek(0);
  };
  target.addEventListener("keydown", keyboard);
  return () => target.removeEventListener("keydown", keyboard);
}

// Bound memory and requests independently of video length. Each browser keeps
// its own playhead; the server only reads immutable frames by index.
export class ReplayBuffer {
  constructor(fetchFrames, { chunk = 60, limit = 360 } = {}) {
    this.fetchFrames = fetchFrames;
    this.chunk = chunk;
    this.limit = limit;
    this.frames = new Map();
    this.pending = new Map();
    this.closed = false;
  }
  get(frame) { return this.frames.get(frame) || null; }
  ensure(frame) {
    if (this.closed) return Promise.resolve(null);
    if (this.frames.has(frame)) return Promise.resolve(this.frames.get(frame));
    const start = Math.floor(frame / this.chunk) * this.chunk;
    if (!this.pending.has(start)) {
      const controller = new AbortController();
      const promise = this.fetchFrames(start, this.chunk, controller.signal).then(rows => {
        if (this.closed || controller.signal.aborted) return;
        for (const row of rows) this.frames.set(row.frame_index, row);
        if (this.frames.size > this.limit) {
          const distant = [...this.frames.keys()].sort((a, b) => Math.abs(b - frame) - Math.abs(a - frame));
          while (this.frames.size > this.limit) this.frames.delete(distant.shift());
        }
      }).finally(() => {
        if (this.pending.get(start)?.controller === controller) this.pending.delete(start);
      });
      this.pending.set(start, { controller, promise });
    }
    return this.pending.get(start).promise.then(() => this.get(frame));
  }
  cancelPendingExcept(frame) {
    const start = Math.floor(frame / this.chunk) * this.chunk;
    for (const [key, value] of this.pending) if (key !== start) {
      this.pending.delete(key);
      value.controller.abort();
    }
  }
  close() {
    this.closed = true;
    for (const value of this.pending.values()) value.controller.abort();
    this.frames.clear();
  }
}

export function visibleDetections(frame, camera = "") {
  return Object.entries(frame?.cameras || {}).filter(([id]) => !camera || camera === id)
    .flatMap(([id, items]) => items.map(item => ({ ...item, camera_id: id })));
}

// Display aggregation only: use positions already emitted by the native
// engine. UNKNOWN boxes do not become web-invented BEV positions.
export function replayZoneCounts(frame, map, camera = "") {
  return replayZoneCountsFromTracks(replayTracks(frame, map, camera), map);
}

export function replayZoneCountsFromTracks(tracks, map) {
  const items = tracks.filter(item => item.state === "ACTIVE");
  return map.zones.map(zone => ({ ...zone,
    count: items.filter(item => item.x >= zone.bndbox.xmin && item.x <= zone.bndbox.xmax
      && item.y >= zone.bndbox.ymin && item.y <= zone.bndbox.ymax).length,
  }));
}

// Only filter existing observations for the viewport. The shared repository
// renderer handles state colors, marker style and ID labels.
export function replayTracks(frame, map, camera = "") {
  return (frame?.bev || []).filter(item => ["ACTIVE", "STOPPED", "PARKED"].includes(item.state)
    && (!camera || item.camera_id === camera)
    && Number.isFinite(item.x) && Number.isFinite(item.y)
    && item.x >= 0 && item.y >= 0 && item.x < map.width && item.y < map.height
    && (item.global_id != null || (item.local_id != null && item.camera_id)));
}
