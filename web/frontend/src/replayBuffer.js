export function frameForTime(seconds, fps, count) {
  return Math.max(0, Math.min(count - 1, Math.floor(seconds * fps + 1e-4)));
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
      }).finally(() => this.pending.delete(start));
      this.pending.set(start, { controller, promise });
    }
    return this.pending.get(start).promise.then(() => this.get(frame));
  }
  cancelPendingExcept(frame) {
    const start = Math.floor(frame / this.chunk) * this.chunk;
    for (const [key, value] of this.pending) if (key !== start) value.controller.abort();
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
  const items = replayTracks(frame, map, camera);
  return map.zones.map(zone => ({ ...zone,
    count: items.filter(item => item.x >= zone.bndbox.xmin && item.x <= zone.bndbox.xmax
      && item.y >= zone.bndbox.ymin && item.y <= zone.bndbox.ymax).length,
  }));
}

// Only filter existing observations for the viewport. The shared repository
// renderer handles state colors, marker style and ID labels.
export function replayTracks(frame, map, camera = "") {
  return (frame?.bev || []).filter(item => item.state === "ACTIVE"
    && (!camera || item.camera_id === camera)
    && Number.isFinite(item.x) && Number.isFinite(item.y)
    && item.x >= 0 && item.y >= 0 && item.x < map.width && item.y < map.height
    && (item.global_id != null || (item.local_id != null && item.camera_id)));
}
