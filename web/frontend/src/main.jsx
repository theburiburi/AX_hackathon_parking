import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import ParkingMap, { zoneName } from "./ParkingMap";
import { formatLastSeen } from "./dateTime";
import CachedReplay from "./CachedReplay";
import VehicleSchedule from "./VehicleSchedule";

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
  if (!response.ok) throw new Error(data.detail || "요청을 처리하지 못했습니다.");
  return data;
};

function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    try {
      setError("");
      onLogin(await request("/auth/login/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) }));
    } catch (err) { setError(err.message); }
  };
  return <main className="login-page"><section className="login-card">
    <p className="eyebrow">CCTV VEHICLE TRACKING</p><h1>차량 주차 관리</h1><p className="login-copy">계정으로 로그인하여 차량 현황을 확인하세요.</p>
    <form className="login-form" onSubmit={submit}>
      <label>아이디<input autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} /></label>
      <label>비밀번호<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      {error && <p className="error">{error}</p>}<button>로그인</button>
    </form>
  </section></main>;
}

function VehicleList({ vehicles, zones = [] }) {
  return <section className="panel"><h2>차량 목록</h2><div className="vehicle-list">{vehicles.map((vehicle) => <article className="vehicle" key={vehicle.id}>
    <div><strong>{vehicle.plate_number}</strong><span>{TEAM_LABELS[vehicle.team_id] || vehicle.team_id}</span></div>
    <div className={`badge ${vehicle.status.toLowerCase()}`}>{vehicle.status}</div>
    <small>위치: {zoneName(vehicle.current_zone_id, zones)} / 최종 감지: {formatLastSeen(vehicle.last_seen_at)}</small>
  </article>)}{!vehicles.length && <p>표시할 차량이 없습니다.</p>}</div></section>;
}

export function Dashboard({ session, onLogout }) {
  const { token, user } = session;
  const [vehicles, setVehicles] = useState([]), [media, setMedia] = useState({ map: null }), [error, setError] = useState("");
  const [page, setPage] = useState("dashboard");
  const isAdmin = user.role === "ADMIN";
  const load = async () => {
    try {
      setError("");
      const [vehicleData, mediaData] = await Promise.all([
        request("/vehicles/", {}, token),
        request("/parking-map/", {}, token),
      ]);
      setVehicles(vehicleData); setMedia(mediaData);
    } catch (err) { if (err.message === "Login required.") onLogout(); else setError(err.message); }
  };
  useEffect(() => { if (!isAdmin) load(); }, [isAdmin, token]);
  return <main className={isAdmin ? "analysis-dashboard" : undefined}><header><div><p className="eyebrow">CCTV VEHICLE TRACKING</p><h1>차량 주차 관리</h1></div>
    <div className="account"><span>{isAdmin ? <strong>관리자</strong> : <><strong>{TEAM_LABELS[user.team_id] || user.team_id}</strong> · {user.name || user.username}</>}</span><button onClick={onLogout}>로그아웃</button></div></header>
    {!isAdmin && <nav className="page-nav" aria-label="주차 관리 메뉴"><button className={page === "dashboard" ? "selected" : ""} onClick={() => setPage("dashboard")}>차량 현황</button><button className={page === "schedule" ? "selected" : ""} onClick={() => setPage("schedule")}>차량 운행 스케줄</button></nav>}
    {!isAdmin && <p className="team-notice">조회 범위: {TEAM_LABELS[user.team_id] || user.team_id}</p>}
    {isAdmin ? <CachedReplay token={token} api={API} /> : page === "schedule" ? <VehicleSchedule token={token} user={user} api={API} /> : error ? <p className="error">{error}</p> : <div className="grid user-location-grid"><ParkingMap parkingMap={media.map} layout={media.layout} vehicles={vehicles} token={token} api={API} onVehiclesUpdated={setVehicles} /><VehicleList vehicles={vehicles} zones={media.layout?.zones || []} /></div>}
  </main>;
}

function App() {
  const [session, setSession] = useState(() => { try { return JSON.parse(localStorage.getItem("ax-session")); } catch { return null; } });
  const login = (next) => { localStorage.setItem("ax-session", JSON.stringify(next)); setSession(next); };
  const logout = () => { localStorage.removeItem("ax-session"); setSession(null); };
  return session?.token && session?.user ? <Dashboard session={session} onLogout={logout} /> : <Login onLogin={login} />;
}
createRoot(document.getElementById("root")).render(<App />);
