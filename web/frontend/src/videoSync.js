// Times are elapsed seconds from each recording's beginning.
export class VideoSync {
  constructor(videos, report = () => {}, now = () => performance.now(), offsets = []) {
    this.videos = videos;
    this.offsets = videos.map((_, i) => Number(offsets[i] || 0));
    this.initialized = false;
    this.report = report;
    this.now = now;
    this.wanted = true;
    this.loop = true;
    this.rate = 1;
    this.time = 0;
    this.blocked = true;
    this.leader = null;
    this.pending = new Set();
    this.lastSeek = new Map();
    this.lastReport = -Infinity;
    this.lastStatus = "";
    this.disposed = false;
    this.error = "";
  }
  get duration() {
    return this.videos.length && this.videos.every(v => Number.isFinite(v.duration) && v.duration > 0)
      ? Math.max(0, Math.min(...this.videos.map((v, i) => v.duration - this.offsets[i])) - this.start) : 0;
  }
  get start() { return Math.max(0, ...this.offsets.map(offset => -offset)); }
  globalTime(video) { return video.currentTime - this.start - this.offsets[this.videos.indexOf(video)]; }
  localTime(video, time) { return time + this.start + this.offsets[this.videos.indexOf(video)]; }
  pauseAll() { this.videos.forEach(v => { if (!v.paused) v.pause(); }); }
  seek(value) {
    if (!this.duration) return;
    this.time = Math.max(0, Math.min(value, this.duration));
    this.initialized = true;
    this.blocked = true;
    this.leader = null;
    this.pauseAll();
    this.videos.forEach(v => { v.currentTime = this.localTime(v, this.time); this.lastSeek.set(v, this.now()); });
  }
  toggle() {
    this.wanted = !this.wanted;
    this.error = "";
    if (!this.wanted) {
      if (this.leader && !this.blocked) this.time = this.globalTime(this.leader);
      this.pauseAll();
    } else if (this.duration && this.time >= this.duration - .05) this.seek(0);
    this.tick();
  }
  tick() {
    if (this.disposed) return;
    const duration = this.duration;
    const now = this.now();
    const available = this.videos.filter(v => !v.error && v.readyState >= 3 && !v.seeking);
    const ready = duration > 0 && available.length === this.videos.length;
    if (ready && !this.initialized) {
      if (this.offsets.some(offset => offset !== 0)) this.seek(0);
      else this.initialized = true;
    }
    const failed = this.videos.some(v => v.error);
    const wasBlocked = this.blocked;
    // A group barrier is needed only for initial load and explicit seeks.
    if (this.blocked && !ready) {
      this.pauseAll();
    } else if (duration > 0) {
      this.blocked = false;
      if (this.wanted) {
        if (!available.includes(this.leader)) {
          this.leader = [...available].sort((a, b) => Math.abs(this.globalTime(a) - this.time) - Math.abs(this.globalTime(b) - this.time))[0] || null;
          if (this.leader && Math.abs(this.globalTime(this.leader) - this.time) > .25) {
            this.leader.currentTime = this.localTime(this.leader, this.time);
            this.lastSeek.set(this.leader, now);
          }
        }
        if (this.leader && !wasBlocked && !this.leader.seeking) this.time = Math.max(this.time, this.globalTime(this.leader));
      }
      if (this.wanted && this.time >= duration - .05) {
        if (this.loop) this.seek(0);
        else { this.wanted = false; this.seek(duration); }
      }
      if (!this.wanted) this.pauseAll();
      else if (!this.blocked) available.forEach(v => {
        if (v.seeking) return;
        const drift = this.time - this.globalTime(v);
        // Seek only a badly delayed channel, with a cooldown to prevent storms.
        if (v !== this.leader && Math.abs(drift) > 1.5 && now - (this.lastSeek.get(v) ?? -Infinity) >= 3000) {
          this.lastSeek.set(v, now);
          v.currentTime = this.localTime(v, this.time);
          return;
        }
        const correction = v === this.leader || Math.abs(drift) < .08 ? 0 : Math.max(-.05, Math.min(.05, drift * .1));
        const targetRate = this.rate * (1 + correction);
        if (Math.abs(v.playbackRate - targetRate) > .005) v.playbackRate = targetRate;
        this.play(v);
      });
    }
    const waiting = this.videos.length - available.length;
    const message = this.error || (this.blocked ? (failed ? "영상 오류 · 다시 시도하세요." : "영상 준비 / 시간 이동 대기") : !this.wanted ? "전체 일시정지" : waiting ? `동기화 재생 중 · ${waiting}채널 지연 또는 오류` : "동기화 재생 중");
    const status = JSON.stringify([duration, this.wanted, this.blocked, failed, message]);
    if (status !== this.lastStatus || now - this.lastReport >= 250) {
      this.lastStatus = status;
      this.lastReport = now;
      this.report({ time: this.time, duration, wanted: this.wanted, ready, failed, message });
    }
  }
  play(v) {
    if (!v.paused || this.pending.has(v)) return;
    this.pending.add(v);
    Promise.resolve(v.play()).then(() => {
      if (this.disposed || !this.wanted || this.blocked) v.pause();
    }).catch(error => {
      if (this.disposed || error.name === "AbortError") return;
      this.wanted = false;
      this.error = "자동 재생이 제한되었습니다. 전체 재생을 눌러 주세요.";
      this.pauseAll();
    }).finally(() => this.pending.delete(v));
  }
  dispose() { this.disposed = true; this.pauseAll(); }
}
