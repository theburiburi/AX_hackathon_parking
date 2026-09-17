import React, { useEffect, useRef, useState } from "react";

const BASE = import.meta.env.VITE_VISION_URL || "/vision";

export default function VisionWorkspace({ token }) {
  const [file, setFile] = useState(null);
  const [source, setSource] = useState(null);
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const abort = useRef(null);
  useEffect(() => {
    if (!file) { setSource(null); return; }
    const url = URL.createObjectURL(file);
    setSource(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => () => abort.current?.abort(), []);
  const url = path => `${BASE}${path}?token=${encodeURIComponent(token)}`;
  const run = async () => {
    const controller = new AbortController();
    abort.current = controller;
    setBusy(true); setUploading(true); setError(""); setJob(null);
    const request = async (path, options = {}) => {
      const response = await fetch(`${BASE}${path}`, { ...options, signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, ...options.headers } });
      if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("영상 분석 서버 연결을 확인하세요.");
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "요청 실패");
      return data;
    };
    try {
      const form = new FormData(); form.append("file", file);
      const task = await request("/api/videos", { method: "POST", body: form });
      setUploading(false);
      while (!controller.signal.aborted) {
        const result = await request(task.status_url);
        setJob(result);
        if (result.status === "failed") throw new Error(result.error);
        if (result.status === "completed") break;
        await new Promise(resolve => setTimeout(resolve, 800));
      }
    } catch (err) { if (err.name !== "AbortError") setError(err.message); }
    finally { if (!controller.signal.aborted) { setBusy(false); setUploading(false); } }
  };
  const names = { queued: "분석 대기", processing: "분석 중", completed: "분석 완료", failed: "분석 실패" };
  return <section className="panel vision-workspace">
    <h2>동영상 분석</h2><p>동영상을 업로드하고 분석 결과와 처리 영상을 다운로드하세요.</p>
    <label>영상 파일 · 최대 500MB<input type="file" accept=".mp4,.avi,.mov,.mkv,.webm,.m4v" disabled={busy}
      onChange={event => { setFile(event.target.files[0] || null); setJob(null); setError(""); }} /></label>
    {source && <video src={source} controls preload="metadata" />}
    <button disabled={!file || busy} onClick={run}>{busy ? "처리 중…" : "분석 시작"}</button>
    <div aria-live="polite">
      {uploading && <p>업로드 중…</p>}
      {job && <><p>{names[job.status] || job.status} · {job.processed_frames} / {job.total_frames || "?"} 프레임</p>
        <progress max={job.total_frames || 1} value={job.processed_frames} /></>}
      {error && <p className="error" role="alert">{error}</p>}
      {job?.status === "completed" && <><img src={url(job.preview_url)} alt="분석된 첫 프레임" />
        <p><a href={url(job.result_url)}>처리 영상 다운로드</a> · <a href={url(job.analysis_url)}>분석 JSONL 다운로드</a></p></>}
    </div>
  </section>;
}
