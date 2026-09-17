import React, { useEffect, useRef, useState } from "react";
import { VideoSync } from "./videoSync";

const clock = seconds => {
  const value = Math.max(0, Math.floor(seconds || 0));
  return `${String(Math.floor(value / 3600)).padStart(2, "0")}:${String(Math.floor(value / 60) % 60).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
};

export default function SyncedCameras({ cameras, token, api }) {
  const elements = useRef(new Map());
  const controller = useRef(null);
  const [state, setState] = useState({ time: 0, duration: 0, wanted: true, message: "영상 준비 중" });
  const [rate, setRate] = useState(1);
  const [loop, setLoop] = useState(true);
  const [retry, setRetry] = useState(0);
  const [seekPreview, setSeekPreview] = useState(null);
  const seekTimer = useRef(null);
  const scheduleSeek = value => {
    setSeekPreview(value);
    clearTimeout(seekTimer.current);
    seekTimer.current = setTimeout(() => {
      controller.current?.seek(value);
      controller.current?.tick();
      setSeekPreview(null);
    }, 250);
  };
  const sources = JSON.stringify(cameras.map(c => [c.id, c.url, c.offset_seconds]));
  const missing = !cameras.length || cameras.some(c => !c.url);
  useEffect(() => {
    if (missing) return;
    const sync = new VideoSync(cameras.map(c => elements.current.get(c.id)), setState, () => performance.now(), cameras.map(c => c.offset_seconds));
    controller.current = sync;
    const tick = () => sync.tick();
    const events = ["waiting", "seeking", "canplay", "loadedmetadata", "ended", "error"];
    sync.videos.forEach(video => events.forEach(event => video.addEventListener(event, tick)));
    const timer = setInterval(tick, 250);
    tick();
    return () => {
      clearInterval(timer);
      clearTimeout(seekTimer.current);
      sync.videos.forEach(video => events.forEach(event => video.removeEventListener(event, tick)));
      sync.dispose();
      controller.current = null;
    };
  }, [sources, token, missing, retry]);
  useEffect(() => { if (controller.current) controller.current.rate = rate; }, [rate, sources, token, retry]);
  useEffect(() => { if (controller.current) controller.current.loop = loop; }, [loop, sources, token, retry]);

  return <section className="ops-panel cctv-panel">
    <div className="panel-heading"><div><h2>CCTV 동기화 재생</h2><p>카메라별 시간차를 적용한 공통 구간을 재생합니다.</p></div><span className="record-count">{cameras.length}채널</span></div>
    <div className="sync-controls">
      <button disabled={missing} onClick={() => controller.current?.toggle()}>{state.wanted ? "전체 일시정지" : "전체 재생"}</button>
      <button disabled={!state.duration} onClick={() => { clearTimeout(seekTimer.current); setSeekPreview(null); controller.current?.seek(0); controller.current?.tick(); }}>처음으로</button>
      <label>배속 <select value={rate} onChange={e => setRate(Number(e.target.value))}>{[.5, 1, 1.5, 2].map(value => <option key={value} value={value}>{value}×</option>)}</select></label>
      <label><input type="checkbox" checked={loop} onChange={e => setLoop(e.target.checked)} />전체 반복</label>
      <button onClick={() => { clearTimeout(seekTimer.current); setSeekPreview(null); controller.current?.dispose(); elements.current.forEach(video => video.load()); setRetry(value => value + 1); }}>다시 시도</button>
    </div>
    <div className="sync-timeline"><input aria-label="전체 CCTV 재생 위치" type="range" min="0" max={state.duration || 0} step="0.1" value={seekPreview ?? state.time} disabled={!state.duration || missing} onChange={e => scheduleSeek(Number(e.target.value))} /><output>{clock(seekPreview ?? state.time)} / {clock(state.duration)}</output></div>
    <p className="sync-note">{missing ? "모든 채널의 영상 파일이 필요합니다." : state.message} · 공통 재생 구간 기준</p>
    <div className="cctv-grid">{cameras.map(camera => <article className="camera-card" key={camera.id}>
      <div className="camera-title"><strong>{camera.name}</strong><span>{camera.filename || "영상 없음"}</span></div>
      {camera.url ? <video ref={element => { if (element) elements.current.set(camera.id, element); else elements.current.delete(camera.id); }} src={`${api}${camera.url}?token=${encodeURIComponent(token)}`} muted playsInline preload="auto" aria-label={`${camera.name} 동기화 영상`} /> : <div className="media-empty">영상 파일이 없습니다.</div>}
    </article>)}</div>
  </section>;
}
