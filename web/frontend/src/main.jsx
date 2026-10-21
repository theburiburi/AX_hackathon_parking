import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./user-theme.css";
import ParkingMap, { zoneName } from "./ParkingMap";
import CachedReplay from "./CachedReplay";
import VehicleSchedule from "./VehicleSchedule";
import { watchSessionProfile } from "./sessionProfile";
import { useDemoState } from "./DemoSync";

const API = import.meta.env.VITE_API_URL || "/api";
const TEAM_LABELS = {
  SECTION_DIGITAL_COMMUNICATION: "디지털통신기술섹션",
  SECTION_COLD_DX: "냉간 DX 섹션",
  SECTION_STEELMAKING_CASTING: "제강연주섹션",
};
const request = async (path, options = {}, token) => {
  const response = await fetch(`${API}${path}`, {
    ...options, headers: { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : null;
  if (!contentType.includes("application/json")) {
    throw new Error("백엔드 API가 최신 상태가 아닙니다. Django 서버를 종료한 뒤 다시 실행하세요.");
  }
  if (!response.ok) {
    const error = new Error(data.detail || "요청을 처리하지 못했습니다.");
    error.status = response.status;
    throw error;
  }
  return data;
};

function Login({ onLogin }) {
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    try {
      setError("");
      onLogin(await request("/auth/login/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, password }) }));
    } catch (err) { setError(err.message); }
  };
  return <main className="login-page"><section className="login-card">
    <h1>차량 주차 관리</h1><p className="login-copy">계정으로 로그인하여 차량 현황을 확인하세요.</p>
    <form className="login-form" onSubmit={submit}>
      <label>아이디<input name="id" autoComplete="username" autoCapitalize="none" spellCheck={false} required value={id} onChange={(event) => setId(event.target.value)} /></label>
      <label>비밀번호<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      {error && <p className="error">{error}</p>}<button>로그인</button>
    </form>
  </section></main>;
}

export function VehicleList({ vehicles, zones = [] }) {
  return <section className="panel"><h2>차량 목록</h2><div className="vehicle-list">{vehicles.map((vehicle) => <article className="vehicle" key={vehicle.id}>
    <div><strong>{vehicle.plate_number}</strong></div>
    <div className={`badge ${vehicle.status.toLowerCase()}`}>{vehicle.status === "MOVING" ? "운행중" : vehicle.status === "PARKING" ? "주차중" : vehicle.status === "EXITED" ? "출차" : zoneName(vehicle.current_zone_id, zones)}</div>
  </article>)}{!vehicles.length && <p>표시할 차량이 없습니다.</p>}</div></section>;
}

export function Dashboard({ session, onLogout }) {
  const { token, user } = session;
  const [media, setMedia] = useState({ map: null }), [error, setError] = useState("");
  const [page, setPage] = useState("dashboard");
  const [scheduleDateTarget, setScheduleDateTarget] = useState(null);
  const isAdmin = user.role === "ADMIN";
  const demo = useDemoState(API, token, !isAdmin);
  const vehicles = demo.vehicles;
  const load = async () => {
    try {
      setError("");
      setMedia(await request("/parking-map/", {}, token));
    } catch (err) { if (err.message === "Login required.") onLogout(); else setError(err.message); }
  };
  useEffect(() => { if (!isAdmin) load(); }, [isAdmin, token]);
  return <main className={isAdmin ? "analysis-dashboard" : "user-dashboard"}><header><div><h1>차량 주차 관리</h1></div>
    <div className="account"><span>{isAdmin ? <strong>ADMIN</strong> : <><strong>{user.team_name || TEAM_LABELS[user.team_id] || user.team_id}</strong> · {user.name || user.id}</>}</span><button onClick={onLogout}>로그아웃</button></div></header>
    {!isAdmin && <div className="user-page-toolbar">
      <nav className="page-nav" aria-label="주차 관리 메뉴"><button className={page === "dashboard" ? "selected" : ""} onClick={() => setPage("dashboard")}>차량 현황</button><button className={page === "schedule" ? "selected" : ""} onClick={() => setPage("schedule")}>차량 운행 스케줄</button></nav>
      {page === "schedule" ? <div className="user-schedule-date" ref={setScheduleDateTarget} /> : <p className="team-notice">조회 범위: {user.team_name || TEAM_LABELS[user.team_id] || user.team_id}</p>}
    </div>}
    {!isAdmin && demo.error && <p className="error" role="alert">차량 현황 갱신 실패: {demo.error}</p>}
    {isAdmin ? <CachedReplay token={token} api={API} /> : page === "schedule" ? <VehicleSchedule token={token} user={user} api={API} dateNavTarget={scheduleDateTarget} /> : error ? <p className="error">{error}</p> : <div className="grid user-location-grid"><VehicleList vehicles={vehicles} zones={media.layout?.zones || []} /><ParkingMap parkingMap={media.map} layout={media.layout} vehicles={vehicles} token={token} api={API} occupancy={demo} showOccupancy={false} /></div>}
  </main>;
}

function App() {
  const [session, setSession] = useState(() => { try { return JSON.parse(localStorage.getItem("ax-session")); } catch { return null; } });
  const token = session?.token;
  useEffect(() => {
    try {
      if (session?.token && session?.user) localStorage.setItem("ax-session", JSON.stringify(session));
      else localStorage.removeItem("ax-session");
    } catch { /* Keep the current login usable when browser storage is unavailable. */ }
  }, [session]);
  useEffect(() => {
    if (!token) return;
    return watchSessionProfile({
      load: signal => request("/auth/me/", { signal, cache: "no-store" }, token),
      onUser: user => setSession(current => current?.token !== token || JSON.stringify(current.user) === JSON.stringify(user) ? current : { ...current, user }),
      onExpired: () => setSession(current => current?.token === token ? null : current),
    });
  }, [token]);
  const logout = () => setSession(null);
  return session?.token && session?.user ? <Dashboard key={`${session.user.id}:${session.user.team_id}:${session.user.role}`} session={session} onLogout={logout} /> : <Login onLogin={setSession} />;
}
createRoot(document.getElementById("root")).render(<App />);
