import React, { useEffect, useState } from "react";

const BASE = import.meta.env.VITE_VISION_URL || "/vision";

export default function LiveDetection({ token }) {
  const [enabled, setEnabled] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [snapshot, setSnapshot] = useState({ status: "starting", cameras: [] });
  const [error, setError] = useState("");
  useEffect(() => {
    if (!enabled) return;
    let active = true, timer;
    const controller = new AbortController();
    const poll = async (start = false) => {
      try {
        const response = await fetch(`${BASE}/api/live${start ? "/start" : ""}`, {
          method: start ? "POST" : "GET", headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
        });
        if (response.status === 404) throw new Error("영상 분석 서버를 재시작한 뒤 다시 시도하세요.");
        if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("영상 분석 서버를 실행하거나 재시작하세요.");
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "감지 요청 실패");
        if (!active) return;
        setSnapshot(data); setError(data.status === "error" ? data.error : "");
        if (data.status === "error") return;
        timer = setTimeout(() => poll(), 250);
      } catch (err) { if (active && err.name !== "AbortError") setError(err.message); }
    };
    setError(""); setSnapshot({ status: "starting", cameras: [] });
    poll(true);
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [token, enabled, attempt]);
  const counts = snapshot.cameras.reduce((total, camera) => {
    for (const [label, count] of Object.entries(camera.counts)) total[label] = (total[label] || 0) + count;
    return total;
  }, { 승용차: 0, 버스: 0, 트럭: 0 });
  return <section className="panel live-detection">
    <div className="panel-heading"><div><h2>실시간 감지 모드</h2>
      <p>설정된 CCTV 녹화 영상을 반복 재생하며 YOLO로 차량 종류를 계속 검출합니다.</p></div>
      <button onClick={() => setEnabled(value => !value)}>{enabled ? "화면 갱신 일시정지" : "감지 화면 재개"}</button></div>
    <div className="live-summary" aria-live="polite">
      <strong>{!enabled ? "일시정지" : error ? "감지 오류" : snapshot.status === "running" ? "감지 중" : "영상·모델 준비 중…"}</strong>
      {Object.entries(counts).map(([label, count]) => <span key={label}>{label} <b>{count}</b></span>)}
      {snapshot.status === "running" && <span>영상 {snapshot.timestamp_seconds.toFixed(1)}초 · 처리 {snapshot.processing_ms}ms · {snapshot.fps} FPS</span>}
    </div>
    {error && <div role="alert"><p className="error">{error}</p><button onClick={() => { setEnabled(true); setAttempt(value => value + 1); }}>다시 시도</button></div>}
    <div className="live-camera-grid">{snapshot.cameras.map(camera => <article className="camera-card" key={camera.id}>
      <div className="camera-title"><strong>{camera.id}</strong><span>현재 검출 {camera.detections.length}대</span></div>
      <img src={camera.image} alt={`${camera.id} 차량 분류 및 검출 상자`} />
    </article>)}</div>
    <p className="form-note">차량 수는 카메라별 관측의 합계입니다. 같은 차량이 중복 포함될 수 있으며 처리 속도는 장비 성능에 따라 달라집니다.</p>
  </section>;
}
