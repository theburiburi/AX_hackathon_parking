import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import ParkingMap from "./ParkingMap";
import { formatLastSeen } from "./dateTime";
import SyncedCameras from "./SyncedCameras";

import LiveDetection from "./LiveDetection";

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

function AdminOperations({ cameras, parkingMap, layout, vehicles, logs, token }) {
  const [recentLogs, setRecentLogs] = useState(logs);
  const [logError, setLogError] = useState(false);
  useEffect(() => { setRecentLogs(logs); }, [logs]);
  useEffect(() => {
    let active = true, timer;
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const data = await request("/tracking-logs/", { signal: controller.signal }, token);
        if (active) { setRecentLogs(data); setLogError(false); }
      } catch (err) { if (active && err.name !== "AbortError") setLogError(true); }
      finally { if (active) timer = setTimeout(refresh, 3000); }
    };
    timer = setTimeout(refresh, 3000);
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [token]);
  return <div className="operations-layout">
    <SyncedCameras cameras={cameras} token={token} api={API} />
    <div className="operations-side">
      <ParkingMap parkingMap={parkingMap} layout={layout} vehicles={vehicles} token={token} api={API} />
      <section className="ops-panel log-panel"><div className="panel-heading"><div><h2>차량 입출차 내역</h2><p>{logError ? "갱신 실패 · 마지막 조회 결과" : "최근 감지 로그 · 3초마다 갱신"}</p></div><span className="record-count">{recentLogs.length}건</span></div>
        <div className="log-table-wrap"><table><thead><tr><th>시각</th><th>차량번호</th><th>카메라</th><th>구역</th><th>상태</th></tr></thead><tbody>
          {recentLogs.map((log) => <tr key={log.id}><td>{new Date(log.detected_at).toLocaleString("ko-KR")}</td><td><strong>{log.plate_number}</strong></td><td>{log.camera_id}</td><td>{log.zone_id}</td><td><span className={`log-status ${log.status.toLowerCase()}`}>{log.status === "PARKED" ? "입차" : log.status === "MOVING" ? "이동" : log.status}</span></td></tr>)}
          {!recentLogs.length && <tr><td colSpan="5" className="empty-cell">표시할 입출차 내역이 없습니다.</td></tr>}
        </tbody></table></div>
      </section>
    </div>
  </div>;
}

function VehicleList({ vehicles }) {
  return <section className="panel"><h2>차량 목록</h2><div className="vehicle-list">{vehicles.map((vehicle) => <article className="vehicle" key={vehicle.id}>
    <div><strong>{vehicle.plate_number}</strong><span>{TEAM_LABELS[vehicle.team_id] || vehicle.team_id}</span></div>
    <div className={`badge ${vehicle.status.toLowerCase()}`}>{vehicle.status}</div>
    <small>위치: {vehicle.current_zone_id || "미확인"} / 최종 감지: {formatLastSeen(vehicle.last_seen_at)}</small>
  </article>)}{!vehicles.length && <p>표시할 차량이 없습니다.</p>}</div></section>;
}

function VehicleRequestForm({ token, user, vehicles, onSubmitted }) {
  const [type, setType] = useState("CREATE");
  const [form, setForm] = useState({ name: "", plate_number: "", vehicle_id: "" });
  const [message, setMessage] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    try {
      const body = type === "CREATE"
        ? { request_type: type, vehicle: { name: form.name, plate_number: form.plate_number, team_id: user.team_id } }
        : { request_type: type, vehicle_id: form.vehicle_id };
      await request("/vehicle-requests/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, token);
      setForm({ name: "", plate_number: "", vehicle_id: "" });
      setMessage("관리자 승인 대기 요청이 등록되었습니다.");
      onSubmitted();
    } catch (err) { setMessage(err.message); }
  };
  return <section className="panel"><h2>차량 관리 요청</h2><p className="form-note">요청은 관리자 승인 후 반영됩니다.</p>
    <form className="request-form" onSubmit={submit}>
      <label>요청 유형<select value={type} onChange={(event) => setType(event.target.value)}><option value="CREATE">차량 추가</option><option value="DELETE">차량 삭제</option></select></label>
      {type === "CREATE" ? <><input required placeholder="차량 이름" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /><input required placeholder="번호판" value={form.plate_number} onChange={(event) => setForm({ ...form, plate_number: event.target.value })} /></> :
        <select required value={form.vehicle_id} onChange={(event) => setForm({ ...form, vehicle_id: event.target.value })}><option value="">삭제할 차량 선택</option>{vehicles.map((vehicle) => <option value={vehicle.id} key={vehicle.id}>{vehicle.name} · {vehicle.plate_number}</option>)}</select>}
      <button>요청 제출</button>
    </form>{message && <p className={message.includes("등록") ? "success" : "error"}>{message}</p>}
  </section>;
}

function RequestHistory({ records }) {
  return <section className="panel"><h2>내 요청 이력</h2>{!records.length ? <p>요청 이력이 없습니다.</p> : <div className="request-list">{records.map((item) => <article className="request-item" key={item.id}>
    <strong>{item.request_type === "CREATE" ? "차량 추가" : "차량 삭제"} · {item.payload.name || item.payload.vehicle_name}</strong>
    <span className={`request-status ${item.status.toLowerCase()}`}>{item.status === "PENDING" ? "승인 대기" : item.status === "APPROVED" ? "승인" : "반려"}</span>
    {item.rejection_reason && <small>반려 사유: {item.rejection_reason}</small>}
  </article>)}</div>}</section>;
}

function AdminRequests({ records, token, onUpdated }) {
  const [reasons, setReasons] = useState({});
  const [error, setError] = useState("");
  const decide = async (item, decision) => {
    try {
      setError("");
      await request(`/admin/vehicle-requests/${item.id}/decision/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, rejection_reason: reasons[item.id] || "" }) }, token);
      onUpdated();
    } catch (err) { setError(err.message); }
  };
  return <section className="panel"><h2>관리 요청</h2><p className="form-note">승인 시 차량 데이터에 즉시 반영됩니다.</p>{error && <p className="error">{error}</p>}
    {!records.length ? <p>관리 요청이 없습니다.</p> : <div className="request-list">{records.map((item) => <article className="request-item admin-request" key={item.id}>
      <div><strong>{item.request_type === "CREATE" ? "추가 요청" : "삭제 요청"} · {item.payload.name || item.payload.vehicle_name}</strong><small>{item.requester_name} · {TEAM_LABELS[item.payload.team_id] || item.payload.team_id} · {item.requested_at}</small></div>
      {item.status === "PENDING" ? <div className="decision"><input placeholder="반려 사유 (반려 시 필수)" value={reasons[item.id] || ""} onChange={(event) => setReasons({ ...reasons, [item.id]: event.target.value })} /><button className="approve" onClick={() => decide(item, "APPROVED")}>승인</button><button className="reject" onClick={() => decide(item, "REJECTED")}>반려</button></div> :
        <div><span className={`request-status ${item.status.toLowerCase()}`}>{item.status === "APPROVED" ? "승인됨" : "반려됨"}</span>{item.rejection_reason && <small>반려 사유: {item.rejection_reason}</small>}</div>}
    </article>)}</div>}
  </section>;
}

function Dashboard({ session, onLogout }) {
  const { token, user } = session;
  const [vehicles, setVehicles] = useState([]), [logs, setLogs] = useState([]), [requests, setRequests] = useState([]), [media, setMedia] = useState({ cameras: [], map: null }), [error, setError] = useState("");
  const [page, setPage] = useState("dashboard");
  const isAdmin = user.role === "ADMIN";
  const load = async () => {
    try {
      setError("");
      const [vehicleData, requestData, mediaData, logData] = await Promise.all([
        request("/vehicles/", {}, token),
        request("/vehicle-requests/", {}, token),
        request(isAdmin ? "/admin/media/" : "/parking-map/", {}, token),
        isAdmin ? request("/tracking-logs/", {}, token) : Promise.resolve([]),
      ]);
      setVehicles(vehicleData); setRequests(requestData); setLogs(logData); setMedia(mediaData);
    } catch (err) { if (err.message === "Login required.") onLogout(); else setError(err.message); }
  };
  useEffect(() => { load(); }, []);
  return <main><header><div><p className="eyebrow">CCTV VEHICLE TRACKING</p><h1>차량 주차 관리</h1></div>
    <div className="account"><span><strong>{user.name}</strong> · {isAdmin ? "관리자" : "사용자"}</span><button onClick={onLogout}>로그아웃</button></div></header>
    {isAdmin && <nav className="page-nav"><button className={page === "dashboard" ? "selected" : ""} onClick={() => setPage("dashboard")}>운영 현황</button><button className={page === "requests" ? "selected" : ""} onClick={() => setPage("requests")}>관리 요청</button><button className={page === "live" ? "selected" : ""} onClick={() => setPage("live")}>실시간 감지 모드</button></nav>}
    {!isAdmin && <p className="team-notice">조회 범위: {TEAM_LABELS[user.team_id] || user.team_id}</p>}
    {page === "live" && isAdmin ? <LiveDetection token={token} /> : error ? <p className="error">{error}</p> : page === "requests" && isAdmin ? <AdminRequests records={requests} token={token} onUpdated={load} /> : isAdmin ? <AdminOperations cameras={media.cameras} parkingMap={media.map} layout={media.layout} vehicles={vehicles} logs={logs} token={token} /> : <><div className="grid user-location-grid"><ParkingMap parkingMap={media.map} layout={media.layout} vehicles={vehicles} token={token} api={API} onVehiclesUpdated={setVehicles} /><VehicleList vehicles={vehicles} /></div>
      {!isAdmin && <><VehicleRequestForm token={token} user={user} vehicles={vehicles} onSubmitted={load} /><RequestHistory records={requests} /></>}
    </>}
  </main>;
}

function App() {
  const [session, setSession] = useState(() => { try { return JSON.parse(localStorage.getItem("ax-session")); } catch { return null; } });
  const login = (next) => { localStorage.setItem("ax-session", JSON.stringify(next)); setSession(next); };
  const logout = () => { localStorage.removeItem("ax-session"); setSession(null); };
  return session?.token && session?.user ? <Dashboard session={session} onLogout={logout} /> : <Login onLogin={login} />;
}
createRoot(document.getElementById("root")).render(<App />);
