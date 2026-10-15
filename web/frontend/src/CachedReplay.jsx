import React, { useEffect, useRef, useState } from "react";
import { ReplayBuffer, frameForTime, replayTracks, replayZoneCounts } from "./replayBuffer";
import { drawCameraLabel, drawDetection, drawBevTracking } from "../../viewer-rendering.js";
import { collapseBevItems } from "../../bev_items.js";
import { watchReplayVehicles } from "./replayVehicleSync";
import { useParkingOccupancy, ParkingOccupancySummary } from "./ParkingOccupancy";
import "./cached-replay.css";

const COLORS = ["#2563eb", "#0891b2", "#7c3aed", "#ea580c", "#059669", "#db2777", "#4f46e5"];
const clock = n => `${Math.floor(n / 60).toString().padStart(2, "0")}:${Math.floor(n % 60).toString().padStart(2, "0")}`;
const gatePlate = value => {
  const plate = typeof value === "string" ? value.trim() : "";
  const parts = plate.replace(/\s+/g, "").match(/^(\d{2,3})([가-힣])(\d{4})$/);
  return parts ? `${parts[1]} ${parts[2]} ${parts[3]}` : plate || "번호판 미확인";
};

export function ReplayTrackOverlay({ frame, map, camera, enabled }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !enabled || !frame) return;
    const ctx = canvas.getContext("2d");
    const draw = () => {
      const width = canvas.clientWidth, height = canvas.clientHeight;
      if (!width || !height) return;
      const density = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * density);
      canvas.height = Math.round(height * density);
      ctx.setTransform(density, 0, 0, density, 0, 0);
      ctx.clearRect(0, 0, width, height);
      drawBevTracking(ctx, { offsetX: 0, offsetY: 0, scale: width / map.width },
        { bev: replayTracks(frame, map, camera) });
    };
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    draw();
    return () => { observer.disconnect(); ctx.clearRect(0, 0, canvas.width, canvas.height); };
  }, [frame, map.width, map.height, camera, enabled]);
  return enabled && frame ? <canvas ref={canvasRef} className="replay-track-overlay" aria-label="현재 차량 위치" /> : null;
}

export function ReplayMap({ manifest, frame, imageUrl, camera, tracking = false, occupancy = [] }) {
  const [hover, setHover] = useState(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => { setReady(false); setFailed(false); }, [imageUrl]);
  const zones = replayZoneCounts(frame, manifest.map, camera).map(zone => {
    const current = occupancy?.find(area => area.id === zone.id);
    return { ...zone, parkingLabel: current ? `${current.parked_count}대 / ${current.capacity ?? "—"}대` : "—대 / —대" };
  });
  const tracks = tracking ? collapseBevItems(replayTracks(frame, manifest.map, camera)) : [];
  const selected = zones.find(zone => zone.id === hover);
  return <section className="ops-panel replay-map"><div className="panel-heading"><div><h2>{tracking ? "차량 위치 추적" : "구역별 차량 현황"}</h2><p>구역별 현재 주차 대수 / 최대 주차 가능 대수</p></div>{tracking && <span className="record-count" role="status">{frame ? `추적 ${tracks.length}대` : "위치 결과 대기"}</span>}</div>
    <div className="replay-map-stage" style={{ aspectRatio: `${manifest.map.width}/${manifest.map.height}` }}>
      <img src={imageUrl} alt="주차장 BEV 지도" onLoad={() => setReady(true)} onError={() => setFailed(true)} />
      {ready && !failed && <svg viewBox={`0 0 ${manifest.map.width} ${manifest.map.height}`} aria-label="구역별 주차 대수">
        {zones.map((zone, index) => {
          const b = zone.bndbox;
          return <g key={zone.id}><rect x={b.xmin} y={b.ymin} width={b.xmax - b.xmin} height={b.ymax - b.ymin}
            fill={hover === zone.id ? COLORS[index % COLORS.length] : "transparent"} fillOpacity={.18} stroke={COLORS[index % COLORS.length]}
            tabIndex={0} role="button" aria-pressed={hover === zone.id} aria-label={`${zone.id} 구역: ${zone.parkingLabel}`}
            onClick={() => setHover(zone.id)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setHover(zone.id); } }}
            onMouseEnter={() => setHover(zone.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(zone.id)} onBlur={() => setHover(null)}>
            <title>{zone.id} 구역: {zone.parkingLabel}</title></rect>
            <text x={b.xmin + 5} y={b.ymin + 19}>{zone.id} · {zone.parkingLabel}</text></g>;
        })}
      </svg>}
      {ready && !failed && <ReplayTrackOverlay frame={frame} map={manifest.map} camera={camera} enabled={tracking} />}
      {selected && <output className="replay-zone-tooltip" role="status">{selected.id} 구역 · {selected.parkingLabel}{tracking && frame && ` · 이동 ${selected.count}대`}</output>}
    </div>
    {tracking && <div className="replay-track-legend"><span><i className="active" />이동 차량</span>
      <span><i className="stopped" />정차 차량</span><span><i className="parked" />주차 차량</span>
      <span>{!frame ? "현재 프레임의 위치를 불러오는 중입니다." : !tracks.length ? "현재 프레임에서 추적 중인 차량이 없습니다." : ""}</span></div>}
    {failed && <p className="error">지도를 불러오지 못했습니다. 로그인 상태와 파일을 확인하세요.</p>}
  </section>;
}

export default function CachedReplay({ token, api = "/api" }) {
  const occupancy = useParkingOccupancy(api, token);
  const [manifest, setManifest] = useState(null), [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0), [frame, setFrame] = useState(null);
  const [time, setTime] = useState(0), [paused, setPaused] = useState(true);
  const [camera, setCamera] = useState(""), [boxes, setBoxes] = useState(true), [loop, setLoop] = useState(true), [rate, setRate] = useState(1);
  const [tracking, setTracking] = useState(false);
  const [syncError, setSyncError] = useState("");
  const frameRef = useRef(null);
  frameRef.current = frame;
  const videoRef = useRef(null), canvasRef = useRef(null), presentRef = useRef(null);
  const options = useRef({ camera, boxes });
  options.current = { camera, boxes };
  const mediaUrl = path => `${api}${path}?token=${encodeURIComponent(token)}&cache_id=${manifest.cache_id}`;

  useEffect(() => {
    const controller = new AbortController();
    setManifest(null); setFrame(null); setError(""); setTime(0); setPaused(true);
    (async () => {
      const response = await fetch(`${api}/replay/manifest/`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "재생 정보를 불러오지 못했습니다.");
      if (!controller.signal.aborted) setManifest(data);
    })().catch(err => { if (err.name !== "AbortError" && !controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [api, token, attempt]);

  useEffect(() => {
    if (!manifest) return;
    const video = videoRef.current, canvas = canvasRef.current, ctx = canvas.getContext("2d");
    let active = true, callback, desired = -1, lastPainted = null;
    const buffer = new ReplayBuffer(async (start, count, signal) => {
      const response = await fetch(`${api}/replay/frames/?start=${start}&count=${count}&cache_id=${manifest.cache_id}`, {
        headers: { Authorization: `Bearer ${token}` }, signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "프레임 결과를 읽지 못했습니다.");
      if (data.cache_id !== manifest.cache_id) throw new Error("재생 결과가 변경됐습니다. 다시 불러오세요.");
      return data.frames;
    });
    // Limit drawing resolution to the displayed size. Coordinates remain in the
    // original video's pixel system, including camera tile offsets.
    canvas.width = Math.min(1920, manifest.scene.width);
    canvas.height = Math.round(canvas.width * manifest.scene.height / manifest.scene.width);
    const scale = canvas.width / manifest.scene.width;
    const draw = result => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      lastPainted = result;
      if (!result || !options.current.boxes) return;
      const layout = { offsetX: 0, offsetY: 0, scale };
      for (const item of manifest.scene.cameras) {
        if (options.current.camera && options.current.camera !== item.id) continue;
        drawCameraLabel(ctx, layout, item);
        for (const detection of result.cameras[item.id] || []) {
          drawDetection(ctx, layout, item, detection);
        }
      }
    };
    const show = result => { draw(result); setFrame(result); };
    const present = n => {
      if (!active) return;
      if (n === desired) { draw(buffer.get(n)); return; }
      if (Math.abs(n - desired) > 120) buffer.cancelPendingExcept(n);
      desired = n;
      setTime(n / manifest.fps);
      const cached = buffer.get(n);
      show(cached);
      buffer.ensure(n).then(() => {
        if (active && desired === n) { show(buffer.get(n)); setError(""); }
      }).catch(err => { if (active && err.name !== "AbortError") setError(err.message); });
      if (cached && n % buffer.chunk >= buffer.chunk - 20 && n + buffer.chunk < manifest.frame_count) {
        buffer.ensure(Math.floor(n / buffer.chunk) * buffer.chunk + buffer.chunk).catch(err => {
          if (active && err.name !== "AbortError") setError(err.message);
        });
      }
    };
    presentRef.current = () => draw(lastPainted);
    const tick = (_, metadata) => {
      if (!video.seeking) present(frameForTime(metadata.mediaTime, manifest.fps, manifest.frame_count));
      if (active) callback = video.requestVideoFrameCallback(tick);
    };
    const fallback = () => {
      if (!video.seeking) present(frameForTime(video.currentTime, manifest.fps, manifest.frame_count));
      if (active) callback = requestAnimationFrame(fallback);
    };
    const loaded = () => present(frameForTime(video.currentTime, manifest.fps, manifest.frame_count));
    const seeking = () => {
      desired = -1;
      buffer.cancelPendingExcept(frameForTime(video.currentTime, manifest.fps, manifest.frame_count));
      show(null);
    };
    video.addEventListener("loadeddata", loaded);
    video.addEventListener("seeking", seeking);
    if (video.requestVideoFrameCallback) callback = video.requestVideoFrameCallback(tick);
    else callback = requestAnimationFrame(fallback);
    if (video.readyState >= 2) loaded();
    const hide = () => { if (document.hidden) video.pause(); };
    document.addEventListener("visibilitychange", hide);
    return () => {
      active = false; buffer.close(); video.pause(); presentRef.current = null;
      if (video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(callback); else cancelAnimationFrame(callback);
      video.removeEventListener("loadeddata", loaded); video.removeEventListener("seeking", seeking);
      document.removeEventListener("visibilitychange", hide);
    };
  }, [manifest, api, token]);
  useEffect(() => { presentRef.current?.(); }, [camera, boxes]);
  useEffect(() => {
    if (!manifest || !tracking) return;
    return watchReplayVehicles({
      readFrame: () => frameRef.current?.frame_index,
      onError: setSyncError,
      send: async (n, signal) => {
        const response = await fetch(`${api}/replay/vehicle-state/`, {
          method: "POST", signal,
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({ cache_id: manifest.cache_id, frame: n }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "차량 목록을 갱신하지 못했습니다.");
      },
    });
  }, [manifest, api, token, tracking]);

  const seek = value => { if (videoRef.current && manifest) videoRef.current.currentTime = Math.max(0, Math.min(value, manifest.duration - 1 / manifest.fps)); };
  const step = delta => { videoRef.current?.pause(); seek(time + delta / manifest.fps); };
  const toggle = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (!video.paused) video.pause();
    else { try { await video.play(); } catch { setError("영상 재생에 실패했습니다. 브라우저 코덱 지원을 확인하세요."); } }
  };
  const toggleTracking = async () => {
    const next = !tracking;
    setTracking(next);
    if (next && videoRef.current?.paused) {
      try { await videoRef.current.play(); }
      catch { setError("영상 재생에 실패했습니다. 재생 버튼을 누르거나 브라우저 코덱 지원을 확인하세요."); }
    }
  };
  useEffect(() => {
    if (!manifest) return;
    const keyboard = event => {
      if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest?.("input,select,textarea,button,[contenteditable=true]")) return;
      if (event.code === "Space") { event.preventDefault(); toggle(); }
      else if (event.code === "KeyA") seek(time - (event.shiftKey ? 30 : 5));
      else if (event.code === "KeyD") seek(time + (event.shiftKey ? 30 : 5));
      else if (event.code === "Comma") step(-1);
      else if (event.code === "Period") step(1);
      else if (event.code === "KeyR") seek(0);
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [manifest, time]);
  const gateEvents = (manifest?.gate_log.events || []).filter(event => frame && event.frame <= frame.frame_index).slice().reverse();
  return <section className="cached-replay" aria-label="실시간 분석">
    <div className="panel-heading replay-heading"><h2>실시간 분석</h2>
      <button type="button" className="replay-tracking-toggle" aria-pressed={tracking} disabled={!manifest} onClick={toggleTracking}>
        <span className="tracking-indicator" aria-hidden="true" />실시간 추적 모드 <strong>{tracking ? "ON" : "OFF"}</strong>
      </button>
    </div>
    {tracking && syncError && <p className="error" role="alert">주차 현황·차량 목록 연동 실패: {syncError}</p>}
    {error && <div className="panel" role="alert"><p className="error">{error}</p><button onClick={() => setAttempt(n => n + 1)}>다시 불러오기</button></div>}
    {!manifest && !error && <p className="form-note">재생 정보를 불러오는 중입니다.</p>}
    {manifest && <>
      <section className="ops-panel"><div className="replay-controls">
        <button className="replay-play" onClick={toggle}>{paused ? "재생" : "일시정지"}</button>
        <button onClick={() => seek(time - 5)}>−5초</button><button onClick={() => seek(time + 5)}>+5초</button>
        <label>배속<select value={rate} onChange={event => { const n = Number(event.target.value); setRate(n); videoRef.current.playbackRate = n; }}>{[.5, 1, 1.5, 2].map(n => <option key={n} value={n}>{n}×</option>)}</select></label>
      </div><details className="replay-settings"><summary>재생 설정</summary><div className="replay-controls">
        <button onClick={() => step(-1)}>이전 프레임</button><button onClick={() => step(1)}>다음 프레임</button>
        <button onClick={() => seek(0)}>처음으로</button>
        <label><input type="checkbox" checked={loop} onChange={event => setLoop(event.target.checked)} />반복</label>
        <label><input type="checkbox" checked={boxes} onChange={event => setBoxes(event.target.checked)} />검출 박스</label>
        <label>카메라<select value={camera} onChange={event => setCamera(event.target.value)}><option value="">전체</option>{manifest.scene.cameras.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label>
      </div></details><div className="sync-timeline"><input aria-label="영상 재생 위치" type="range" min="0" max={manifest.duration - 1 / manifest.fps} step={1 / manifest.fps} value={time} onChange={event => seek(Number(event.target.value))} /><output>{clock(time)} / {clock(manifest.duration)}</output></div></section>
      <div className="replay-workspace"><section className="ops-panel replay-video-panel">
        <div className="replay-video-stage" style={{ aspectRatio: `${manifest.scene.width}/${manifest.scene.height}` }}>
          <video ref={videoRef} src={mediaUrl(manifest.scene.video_url)} preload="metadata" playsInline muted loop={loop}
            onPlay={() => setPaused(false)} onPause={() => setPaused(true)} onEnded={() => setPaused(true)}
            onError={() => setError("영상을 불러오지 못했습니다. 파일·로그인 상태·브라우저 코덱 지원을 확인하세요.")} />
          <canvas ref={canvasRef} aria-label="프레임별 검출 박스" />
        </div>
      </section><aside className="replay-sidebar" aria-label="차량 지도와 차단기 기록">
        <ReplayMap manifest={manifest} frame={frame} imageUrl={mediaUrl(manifest.map.url)} camera={camera} tracking={tracking} occupancy={occupancy.zones} />
        <section className="ops-panel replay-gate-panel"><div className="panel-heading"><div><h2>차단기 기록</h2><p>현재 재생 시점까지 발생한 기록</p></div><span className="record-count">{gateEvents.length}건</span></div>
          <div className="replay-gate-list">{gateEvents.map((event, index) => <button key={`${event.frame}:${index}`} onClick={() => seek(event.frame / manifest.fps)}><strong>[{event.type === "IN" ? "입차" : event.type === "OUT" ? "출차" : event.label || "통과"}] {gatePlate(event.plate)}</strong></button>)}
          {!gateEvents.length && <p className="form-note">현재 재생 시점까지의 차단기 기록이 없습니다.</p>}</div>
        </section>
      </aside></div>
    </>}
    <ParkingOccupancySummary {...occupancy} />
  </section>;
}
