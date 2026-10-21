import React, { useEffect, useMemo, useRef, useState } from "react";
import { ReplayBuffer, gateEventsForTime, replayTracks, replayZoneCountsFromTracks, watchReplayMedia, watchReplayKeyboard } from "./replayBuffer";
import { drawCameraLabel, drawDetection, drawBevTracking } from "../../viewer-rendering.js";
import { collapseBevItems, globalVehicleLabel, pathUntil } from "../../bev_items.js";
import { watchReplayVideoState } from "./replayVehicleSync";
import { createReplayCanvas } from "./replayCanvas";
import { useDemoState } from "./DemoSync";
import "./cached-replay.css";

const COLORS = ["#2563eb", "#0891b2", "#7c3aed", "#ea580c", "#059669", "#db2777", "#4f46e5"];
const PATH_COLORS = ["#ff5d5d", "#38bdf8", "#facc15", "#a78bfa", "#34d399", "#fb923c", "#f472b6", "#22d3ee", "#a3e635", "#e879f9"];
const clock = n => `${Math.floor(n / 60).toString().padStart(2, "0")}:${Math.floor(n % 60).toString().padStart(2, "0")}`;
const gatePlate = value => {
  const plate = typeof value === "string" ? value.trim() : "";
  const parts = plate.replace(/\s+/g, "").match(/^(\d{2,3})([가-힣])(\d{4})$/);
  return parts ? `${parts[1]} ${parts[2]} ${parts[3]}` : plate || "번호판 미확인";
};

export function ReplayGateLog({ gateLog, time, fps, frameCount, onSeek }) {
  const events = gateEventsForTime(gateLog, time, fps, frameCount);
  return <section className="ops-panel replay-gate-panel"><div className="panel-heading"><h2>차단기 기록</h2></div>
    <div className="replay-gate-list">{events.map(event => <button key={`${event.frame}:${event.type}:${event.camera_id || gateLog?.gate?.camera_id || ""}:${event.track_id ?? ""}`} onClick={() => onSeek(event.frame / fps)}><strong>[{event.type === "IN" ? "입차" : event.type === "OUT" ? "출차" : event.label || "통과"}] {gatePlate(event.plate)}</strong></button>)}
    </div>
  </section>;
}

export function ReplayTrackOverlay({ frame, map, camera, enabled, observations }) {
  const canvasRef = useRef(null);
  const painterRef = useRef(null);
  const visible = Boolean(enabled && frame);
  const tracks = useMemo(() => observations ?? replayTracks(frame, map, camera),
    [observations, frame, map, camera]);
  const drawingRef = useRef(null);
  drawingRef.current = { tracks, mapWidth: map.width };
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !visible) return;
    const painter = createReplayCanvas(canvas, (ctx, width) => {
      const current = drawingRef.current;
      drawBevTracking(ctx, { offsetX: 0, offsetY: 0, scale: width / current.mapWidth }, { bev: current.tracks });
    });
    painterRef.current = painter;
    return () => { painter.close(); painterRef.current = null; };
  }, [visible]);
  useEffect(() => { painterRef.current?.paint(); }, [visible, tracks, map.width, map.height]);
  return visible ? <canvas ref={canvasRef} className="replay-track-overlay" aria-label="현재 차량 위치" /> : null;
}

// Path mode: each Global ID's BEV route up to the current frame. Solid where a
// camera saw the car, dashed straight links across stretches no camera saw.
export function ReplayPathLayer({ map, paths, frameIndex }) {
  const drawn = useMemo(() => Object.entries(paths?.paths || {})
    .map(([id, points]) => ({ id: Number(id), ...pathUntil(points, frameIndex, paths.gap_frames) }))
    .filter(path => path.last), [paths, frameIndex]);
  const line = points => points.map(([x, y]) => `${x},${y}`).join(" ");
  return <svg className="replay-path-layer" viewBox={`0 0 ${map.width} ${map.height}`} aria-label="차량별 이동 경로">
    {drawn.map(path => {
      const color = PATH_COLORS[(path.id - 1) % PATH_COLORS.length];
      return <g key={path.id} stroke={color} fill="none">
        {path.gaps.map((gap, index) => <polyline key={`gap${index}`} points={line(gap)} className="gap" />)}
        {path.runs.map((run, index) => <polyline key={`run${index}`} points={line(run)} />)}
        <circle cx={path.last[0]} cy={path.last[1]} r={7} fill={color} />
        <text x={path.last[0] + 10} y={path.last[1] - 10} fill={color}>{globalVehicleLabel(path.id)}</text>
      </g>;
    })}
  </svg>;
}

export function ReplayMap({ manifest, frame, imageUrl, camera, tracking = false, occupancy = [], showZones = true, paths = null, pathStatus = "", frameIndex = 0 }) {
  const [hover, setHover] = useState(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => { setReady(false); setFailed(false); }, [imageUrl]);
  useEffect(() => { if (!showZones) setHover(null); }, [showZones]);
  const observations = useMemo(() => replayTracks(frame, manifest.map, camera), [frame, manifest.map, camera]);
  const movingCounts = useMemo(() => replayZoneCountsFromTracks(observations, manifest.map), [observations, manifest.map]);
  const zones = useMemo(() => movingCounts.map(zone => {
    const current = occupancy?.find(area => area.id === zone.id);
    return { ...zone, parkingLabel: current ? `${current.parked_count}대 / ${current.capacity ?? "—"}대` : "—대 / —대" };
  }), [movingCounts, occupancy]);
  const tracks = useMemo(() => tracking ? collapseBevItems(observations) : [], [tracking, observations]);
  const selected = zones.find(zone => zone.id === hover);
  return <section className="ops-panel replay-map"><div className="panel-heading"><div><h2>{tracking ? "차량 위치 추적" : "구역별 차량 현황"}</h2></div></div>
    <div className="replay-map-stage" style={{ aspectRatio: `${manifest.map.width}/${manifest.map.height}` }}>
      <img src={imageUrl} alt="주차장 BEV 지도" onLoad={() => setReady(true)} onError={() => setFailed(true)} />
      {ready && !failed && showZones && <svg viewBox={`0 0 ${manifest.map.width} ${manifest.map.height}`} aria-label="구역별 주차 대수">
        {zones.map((zone, index) => {
          const b = zone.bndbox;
          // L and M share a top edge and M is too narrow for its label, so M's
          // label drops below L's box instead of overlapping L's label.
          const below = zone.id === "M" ? zones.find(area => area.id === "L")?.bndbox : null;
          const labelY = (below ? Math.max(b.ymin, below.ymax) : b.ymin) + 19;
          return <g key={zone.id}><rect x={b.xmin} y={b.ymin} width={b.xmax - b.xmin} height={b.ymax - b.ymin}
            fill={hover === zone.id ? COLORS[index % COLORS.length] : "transparent"} fillOpacity={.18} stroke={COLORS[index % COLORS.length]}
            tabIndex={0} role="button" aria-pressed={hover === zone.id} aria-label={`${zone.id} 구역: ${zone.parkingLabel}`}
            onClick={() => setHover(zone.id)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setHover(zone.id); } }}
            onMouseEnter={() => setHover(zone.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(zone.id)} onBlur={() => setHover(null)}>
            <title>{zone.id} 구역: {zone.parkingLabel}</title></rect>
            <text x={b.xmin + 5} y={labelY}>{zone.id} · {zone.parkingLabel}</text></g>;
        })}
      </svg>}
      {ready && !failed && paths && <ReplayPathLayer map={manifest.map} paths={paths} frameIndex={frameIndex} />}
      {ready && !failed && <ReplayTrackOverlay frame={frame} map={manifest.map} camera={camera} enabled={tracking} observations={observations} />}
      {showZones && selected && <output className="replay-zone-tooltip" role="status">{selected.id} 구역 · {selected.parkingLabel}{tracking && frame && ` · 이동 ${selected.count}대`}</output>}
    </div>
    {tracking && <div className="replay-track-legend"><span><i className="active" />이동 차량</span>
      <span><i className="stopped" />정차 차량</span><span><i className="parked" />주차 차량</span>
      <span>{!frame ? "현재 프레임의 위치를 불러오는 중입니다." : !tracks.length ? "현재 프레임에서 추적 중인 차량이 없습니다." : ""}</span></div>}
    {pathStatus && <p className={pathStatus.startsWith("이동 경로를 불러오지") ? "error" : "form-note"}>{pathStatus}</p>}
    {failed && <p className="error">지도를 불러오지 못했습니다. 로그인 상태와 파일을 확인하세요.</p>}
  </section>;
}

const MemoizedReplayMap = React.memo(ReplayMap);

export default function CachedReplay({ token, api = "/api" }) {
  const occupancy = useDemoState(api, token);
  const [manifest, setManifest] = useState(null), [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0), [frame, setFrame] = useState(null);
  const [time, setTime] = useState(0), [paused, setPaused] = useState(true);
  const [camera, setCamera] = useState(""), [boxes, setBoxes] = useState(true), [loop, setLoop] = useState(true), [rate, setRate] = useState(1);
  const [tracking, setTracking] = useState(false);
  const [showZones, setShowZones] = useState(true);
  const [showPaths, setShowPaths] = useState(false);
  const [paths, setPaths] = useState(null), [pathStatus, setPathStatus] = useState("");
  const [syncError, setSyncError] = useState("");
  const videoRef = useRef(null), canvasRef = useRef(null), presentRef = useRef(null);
  const options = useRef({ camera, boxes });
  const keyboardActions = useRef(null);
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
    let active = true, desired = -1, lastPainted = null;
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
    const show = result => {
      if (result === lastPainted) return;
      draw(result); setFrame(result);
    };
    const present = n => {
      if (!active) return;
      if (n === desired && buffer.get(n)) { show(buffer.get(n)); return; }
      if (Math.abs(n - desired) > 120) buffer.cancelPendingExcept(n);
      desired = n;
      setTime(n / manifest.fps);
      const cached = buffer.get(n);
      show(cached);
      buffer.ensure(n).then(() => {
        // The playhead can advance within this batch while its request is in
        // flight. Publish the current frame as soon as that batch is ready.
        if (active && buffer.get(desired)) { show(buffer.get(desired)); setError(""); }
      }).catch(err => { if (active && err.name !== "AbortError") setError(err.message); });
      if (cached && n % buffer.chunk >= buffer.chunk - 20 && n + buffer.chunk < manifest.frame_count) {
        buffer.ensure(Math.floor(n / buffer.chunk) * buffer.chunk + buffer.chunk).catch(err => {
          if (active && err.name !== "AbortError") setError(err.message);
        });
      }
    };
    presentRef.current = () => draw(lastPainted);
    const seeking = target => {
      desired = -1;
      setTime(target / manifest.fps);
      buffer.cancelPendingExcept(target);
      show(null);
    };
    const stopMedia = watchReplayMedia(video, { fps: manifest.fps, frameCount: manifest.frame_count, present, seeking });
    return () => {
      active = false; buffer.close(); video.pause(); presentRef.current = null;
      stopMedia();
    };
  }, [manifest, api, token]);
  useEffect(() => { presentRef.current?.(); }, [camera, boxes]);
  useEffect(() => {
    if (!manifest) return;
    const video = videoRef.current;
    return watchReplayVideoState(video, {
      fps: manifest.fps, frameCount: manifest.frame_count,
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
  }, [manifest, api, token]);

  useEffect(() => {
    if (!manifest || !showPaths || paths?.cache_id === manifest.cache_id) return;
    const controller = new AbortController();
    setPathStatus("이동 경로를 계산하는 중입니다.");
    (async () => {
      const response = await fetch(`${api}/replay/paths/?cache_id=${manifest.cache_id}`, {
        headers: { Authorization: `Bearer ${token}` }, signal: controller.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "응답 오류");
      if (!controller.signal.aborted) { setPaths(data); setPathStatus(""); }
    })().catch(err => { if (err.name !== "AbortError" && !controller.signal.aborted) setPathStatus(`이동 경로를 불러오지 못했습니다: ${err.message}`); });
    return () => controller.abort();
  }, [manifest, showPaths, paths, api, token]);

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
  keyboardActions.current = { time, seek, step, toggle };
  useEffect(() => {
    if (!manifest) return;
    return watchReplayKeyboard(window, () => keyboardActions.current);
  }, [manifest]);
  return <section className="cached-replay" aria-label="실시간 분석">
    <div className="panel-heading replay-heading"><h2>실시간 분석</h2>
      <div className="replay-mode-toggles">
        <button type="button" className="replay-tracking-toggle" aria-pressed={tracking} disabled={!manifest} onClick={toggleTracking}>
          <span className="tracking-indicator" aria-hidden="true" />실시간 추적 모드 <strong>{tracking ? "ON" : "OFF"}</strong>
        </button>
        <button type="button" className="replay-tracking-toggle" aria-pressed={showPaths} disabled={!manifest} onClick={() => setShowPaths(value => !value)}>
          <span className="tracking-indicator" aria-hidden="true" />이동 경로 모드 <strong>{showPaths ? "ON" : "OFF"}</strong>
        </button>
      </div>
    </div>
    {syncError && <p className="error" role="alert">주차 현황·차량 목록 연동 실패: {syncError}</p>}
    {error && <div className="panel" role="alert"><p className="error">{error}</p><button onClick={() => setAttempt(n => n + 1)}>다시 불러오기</button></div>}
    {!manifest && !error && <p className="form-note">재생 정보를 불러오는 중입니다.</p>}
    {manifest && <>
      <div className="replay-workspace"><section className="ops-panel replay-video-panel">
        <div className="replay-video-stage" style={{ aspectRatio: `${manifest.scene.width}/${manifest.scene.height}` }}>
          <video ref={videoRef} src={mediaUrl(manifest.scene.video_url)} preload="metadata" playsInline muted loop={loop}
            onPlay={() => setPaused(false)} onPause={() => setPaused(true)} onEnded={() => setPaused(true)}
            onError={() => setError("영상을 불러오지 못했습니다. 파일·로그인 상태·브라우저 코덱 지원을 확인하세요.")} />
          <canvas ref={canvasRef} aria-label="프레임별 검출 박스" />
        </div>
      </section><aside className="replay-sidebar" aria-label="차량 지도와 차단기 기록">
        <MemoizedReplayMap manifest={manifest} frame={frame} imageUrl={mediaUrl(manifest.map.url)} camera={camera} tracking={tracking} occupancy={occupancy.zones} showZones={showZones}
          paths={showPaths && paths?.cache_id === manifest.cache_id ? paths : null} pathStatus={showPaths ? pathStatus : ""}
          frameIndex={frame?.frame_index ?? Math.round(time * manifest.fps)} />
        <ReplayGateLog gateLog={manifest.gate_log} time={time} fps={manifest.fps} frameCount={manifest.frame_count} onSeek={seek} />
      </aside></div>
    </>}
    {manifest && <section className="ops-panel"><div className="replay-controls">
        <button className="replay-play" onClick={toggle}>{paused ? "재생" : "일시정지"}</button>
        <button onClick={() => seek(time - 5)}>−5초</button><button onClick={() => seek(time + 5)}>+5초</button>
        <label>배속<select value={rate} onChange={event => { const n = Number(event.target.value); setRate(n); videoRef.current.playbackRate = n; }}>{[.5, 1, 1.5, 2].map(n => <option key={n} value={n}>{n}×</option>)}</select></label>
      </div><details className="replay-settings"><summary>재생 설정</summary><div className="replay-controls">
        <button onClick={() => step(-1)}>이전 프레임</button><button onClick={() => step(1)}>다음 프레임</button>
        <button onClick={() => seek(0)}>처음으로</button>
        <label><input type="checkbox" checked={loop} onChange={event => setLoop(event.target.checked)} />반복</label>
        <label><input type="checkbox" checked={boxes} onChange={event => setBoxes(event.target.checked)} />검출 박스</label>
        <label><input type="checkbox" checked={showZones} onChange={event => setShowZones(event.target.checked)} />주차장 구역 표시</label>
        <label>카메라<select value={camera} onChange={event => setCamera(event.target.value)}><option value="">전체</option>{manifest.scene.cameras.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label>
      </div></details><div className="sync-timeline"><input aria-label="영상 재생 위치" type="range" min="0" max={manifest.duration - 1 / manifest.fps} step={1 / manifest.fps} value={time} onChange={event => seek(Number(event.target.value))} /><output>{clock(time)} / {clock(manifest.duration)}</output></div></section>}
  </section>;
}
