import React, { useEffect, useRef, useState } from "react";
import "./vehicleSchedule.css";

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const TEAMS = {
  SECTION_DIGITAL_COMMUNICATION: "디지털통신기술섹션",
  SECTION_COLD_DX: "냉간 DX 섹션",
  SECTION_STEELMAKING_CASTING: "제강연주섹션",
};
const colorFor = (team) => team === "SECTION_COLD_DX" ? "teal" : team === "SECTION_STEELMAKING_CASTING" ? "violet" : "blue";
export const minuteOfDay = (time) => { const [h, m] = time.split(":").map(Number); return h * 60 + m; };
const today = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(new Date());
export function moveDay(day, direction) {
  const value = new Date(`${day}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + direction);
  return value.toISOString().slice(0, 10);
}
const longDate = (day) => new Date(`${day}T12:00:00+09:00`).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "long", day: "numeric", weekday: "long" });

async function call(api, token, path, options = {}) {
  const response = await fetch(`${api}/vehicle-schedules/${path}`, {
    ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  });
  if (response.status === 204) return null;
  if (!(response.headers.get("content-type") || "").includes("application/json")) {
    throw new Error("스케줄 API에 연결할 수 없습니다. Django 서버를 확인하세요.");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(Array.isArray(data) ? data.join(" ") : data.detail || "일정을 처리하지 못했습니다.");
  return data;
}

export function ScheduleBoard({ vehicles, schedules, selectedId, onSelect, date }) {
  // Keep a booked vehicle visible even if it was subsequently removed from the vehicle registry.
  const rows = [...vehicles];
  for (const item of schedules) {
    if (!rows.some((vehicle) => vehicle.id === item.vehicle_id)) rows.push({ id: item.vehicle_id, name: item.vehicle_name, plate_number: item.plate_number, team_id: item.team_id });
  }
  return <div className="schedule-scroll" tabIndex="0" role="region" aria-label="차량별 하루 시간표. 가로로 스크롤할 수 있습니다.">
    <table className="schedule-board">
      <caption className="schedule-sr-only">{date} 차량 운행 시간표 · 한국시간 00:00~24:00</caption>
      <colgroup><col className="schedule-vehicle-col" />{HOURS.map((h) => <col key={h} />)}</colgroup>
      <thead>
        <tr><th rowSpan="2" scope="col" className="schedule-vehicle">차량 / 소속 섹션</th><th colSpan="6" scope="colgroup">새벽 · 00–06</th><th colSpan="6" scope="colgroup">오전 · 06–12</th><th colSpan="6" scope="colgroup">오후 · 12–18</th><th colSpan="6" scope="colgroup">저녁 · 18–24</th></tr>
        <tr>{HOURS.map((h) => <th key={h} scope="col">{String(h).padStart(2, "0")}</th>)}</tr>
      </thead>
      <tbody>{rows.map((vehicle) => {
        const items = schedules.filter((item) => item.vehicle_id === vehicle.id);
        return <tr key={vehicle.id}>
          <th scope="row" className="schedule-vehicle"><strong>{vehicle.plate_number}</strong><span>{vehicle.name}</span><small>{TEAMS[vehicle.team_id] || vehicle.team_id}</small></th>
          <td colSpan="24" className="schedule-track-cell"><div className="schedule-track">
            {!items.length && <span className="schedule-free">등록된 운행 없음</span>}
            {items.map((item) => <button key={item.id} type="button" className={`schedule-block ${colorFor(item.team_id)} ${selectedId === item.id ? "active" : ""}`}
              style={{ left: `${minuteOfDay(item.start_time) / 1440 * 100}%`, width: `${(minuteOfDay(item.end_time) - minuteOfDay(item.start_time)) / 1440 * 100}%` }}
              onClick={() => onSelect(item.id)} aria-pressed={selectedId === item.id}
              aria-label={`${item.plate_number} ${item.start_time}–${item.end_time} ${item.driver_name} · ${item.destination} · ${item.purpose}`}
              title={`${item.start_time}–${item.end_time} ${item.driver_name}\n${item.destination} · ${item.purpose}`}>
              <strong>{item.start_time}–{item.end_time}</strong><span>{item.driver_name} · {item.destination}</span>
            </button>)}
          </div></td>
        </tr>;
      })}</tbody>
    </table>
    {!rows.length && <p className="schedule-empty">등록된 차량이 없습니다. 차량이 등록되면 일정을 추가할 수 있습니다.</p>}
  </div>;
}

function ScheduleForm({ initial, date, user, vehicles, members, busy, error, onSave, onClose }) {
  const [form, setForm] = useState(initial || { date, vehicle_id: "", driver_id: user.role === "ADMIN" ? "" : user.id, start_time: "09:00", end_time: "10:00", destination: "", purpose: "" });
  const firstInput = useRef(null);
  useEffect(() => { firstInput.current?.focus(); }, []);
  const vehicle = vehicles.find((v) => v.id === form.vehicle_id);
  const drivers = members.filter((member) => member.team_id === vehicle?.team_id);
  const change = (key) => (event) => setForm({ ...form, [key]: event.target.value });
  return <section className="schedule-editor" aria-labelledby="schedule-editor-title">
    <div className="schedule-heading"><div><h3 id="schedule-editor-title">{initial ? "운행 일정 수정" : "새 운행 일정"}</h3><p>같은 날 안에서 시간을 선택하세요. 종료 시간은 24:00까지 입력할 수 있습니다.</p></div><button type="button" disabled={busy} onClick={onClose}>닫기</button></div>
    <form onSubmit={(event) => { event.preventDefault(); onSave(form); }}>
      <fieldset disabled={busy} className="schedule-form-grid">
        <label>운행 날짜<input ref={firstInput} required type="date" value={form.date} onChange={change("date")} /></label>
        <label>차량<select required value={form.vehicle_id} onChange={(event) => setForm({ ...form, vehicle_id: event.target.value, driver_id: user.role === "ADMIN" ? "" : user.id })}>
          <option value="">차량 선택</option>{vehicles.map((v) => <option key={v.id} value={v.id}>{v.plate_number} · {v.name}</option>)}
        </select></label>
        <label>운전자{user.role === "ADMIN" ? <select required value={form.driver_id} onChange={change("driver_id")}><option value="">운전자 선택</option>{drivers.map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select> : <input readOnly value={user.name} />}</label>
        <label>시작 시간<input required type="time" value={form.start_time} onChange={change("start_time")} /></label>
        <label>종료 시간<input required type="text" inputMode="numeric" pattern="([01][0-9]|2[0-3]):[0-5][0-9]|24:00" placeholder="18:00" value={form.end_time} onChange={change("end_time")} /></label>
        <label>목적지<input required maxLength="120" placeholder="예: 제강 공장" value={form.destination} onChange={change("destination")} /></label>
        <label className="schedule-purpose">운행 목적<input required maxLength="200" placeholder="예: 설비 점검 및 현장 회의" value={form.purpose} onChange={change("purpose")} /></label>
        <button className="schedule-primary" type="submit">{busy ? "저장 중…" : initial ? "변경 저장" : "일정 등록"}</button>
      </fieldset>
      {error && <p role="alert" className="error">{error}</p>}
    </form>
  </section>;
}

function ScheduleDay({ date, team, user, api, token }) {
  const [data, setData] = useState(null), [error, setError] = useState("");
  const [revision, setRevision] = useState(0), [selectedId, setSelectedId] = useState(null);
  const [editor, setEditor] = useState(null), [busy, setBusy] = useState(false), [saveError, setSaveError] = useState("");
  const [message, setMessage] = useState(""), [confirmDelete, setConfirmDelete] = useState(null);
  const detailRef = useRef(null);
  useEffect(() => {
    let active = true, timer;
    const controller = new AbortController();
    const load = async () => {
      try {
        const result = await call(api, token, `?date=${encodeURIComponent(date)}&team_id=${encodeURIComponent(team)}`, { signal: controller.signal });
        if (active) { setData(result); setError(""); }
      } catch (err) { if (active && err.name !== "AbortError") setError(err.message); }
      finally { if (active) timer = setTimeout(load, 30000); }
    };
    load();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [api, token, date, team, revision]);
  const select = (id) => { setSelectedId(id); setConfirmDelete(null); detailRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); };
  const save = async (form) => {
    if (busy) return;
    setBusy(true); setSaveError(""); setMessage("");
    try {
      await call(api, token, editor?.id ? `${editor.id}/` : "", { method: editor?.id ? "PUT" : "POST", body: JSON.stringify(form) });
      setEditor(null); setSelectedId(null); setConfirmDelete(null);
      setMessage(`${form.date} ${form.start_time}–${form.end_time} 일정이 저장되었습니다.`); setRevision((value) => value + 1);
    } catch (err) { setSaveError(err.message); }
    finally { setBusy(false); }
  };
  const remove = async (id) => {
    if (busy) return;
    setBusy(true); setMessage(""); setSaveError("");
    try {
      await call(api, token, `${id}/`, { method: "DELETE" });
      setData((value) => ({ ...value, schedules: value.schedules.filter((item) => item.id !== id) }));
      setConfirmDelete(null); setSelectedId(null); setMessage("운행 일정이 취소되었습니다."); setRevision((value) => value + 1);
    } catch (err) { setSaveError(err.message); }
    finally { setBusy(false); }
  };
  if (!data) return <div className="panel" role="status">{error ? <><p className="error">{error}</p><button onClick={() => setRevision((value) => value + 1)}>다시 불러오기</button></> : "스케줄을 불러오는 중입니다…"}</div>;
  return <>
    <div className="schedule-summary">
      <div><span>조회 차량</span><strong>{data.vehicles.length}<small>대</small></strong></div>
      <div><span>운행 일정</span><strong>{data.schedules.length}<small>건</small></strong></div>
      <div><span>운행 참여자</span><strong>{new Set(data.schedules.map((item) => item.driver_id)).size}<small>명</small></strong></div>
      <div><span>조회 범위</span><strong className="schedule-scope">{TEAMS[team] || "전체 섹션"}</strong></div>
    </div>
    <section className="panel schedule-panel">
      <div className="schedule-heading"><div><h2>일일 운행 시간표</h2><p>한국시간 00:00–24:00 · 30초마다 갱신 · 운행 블록을 누르면 상세 정보를 볼 수 있습니다.</p></div>
        <button className="schedule-primary" disabled={busy || !data.vehicles.length || !!error} onClick={() => { setEditor({}); setSaveError(""); setConfirmDelete(null); }}>+ 운행 등록</button>
      </div>
      <div className="schedule-legend">{Object.entries(TEAMS).filter(([id]) => !team || team === id).map(([id, label]) => <span key={id}><i className={colorFor(id)} />{label}</span>)}</div>
      {error && <p className="error" role="alert">갱신 실패: {error} (마지막 조회 결과입니다.) <button onClick={() => setRevision((value) => value + 1)}>재시도</button></p>}
      {message && <p className="success" role="status">{message}</p>}
      {editor && <ScheduleForm key={editor.id || "new"} initial={editor.id ? editor : null} date={date} user={user} vehicles={data.vehicles} members={data.members} busy={busy} error={saveError} onSave={save} onClose={() => { setEditor(null); setSaveError(""); }} />}
      <ScheduleBoard vehicles={data.vehicles} schedules={data.schedules} selectedId={selectedId} onSelect={select} date={date} />
      <p className="schedule-hint">짧은 일정의 전체 내용은 아래 목록에서 확인하세요. 일반 사용자는 본인이 등록한 일정만 수정·취소할 수 있습니다.</p>
    </section>
    <section ref={detailRef} className="panel schedule-detail">
      <div className="schedule-heading"><h2>운행 상세 <span className="record-count">{data.schedules.length}건</span></h2><span>시간순 정렬</span></div>
      {!editor && saveError && <p className="error" role="alert">{saveError}</p>}
      {!data.schedules.length ? <div className="schedule-empty"><strong>이 날짜에는 운행 일정이 없습니다.</strong><p>운행 등록 버튼으로 첫 일정을 추가하세요.</p></div> : <div className="schedule-scroll"><table className="schedule-list">
        <thead><tr><th scope="col">시간</th><th scope="col">차량 / 섹션</th><th scope="col">운전자</th><th scope="col">목적지</th><th scope="col">운행 목적</th><th scope="col">관리</th></tr></thead>
        <tbody>{data.schedules.map((item) => <tr key={item.id} className={selectedId === item.id ? "schedule-selected" : ""}>
          <td className="schedule-time">{item.start_time}–{item.end_time}</td><td><strong>{item.plate_number}</strong><small>{TEAMS[item.team_id] || item.team_id}</small></td><td>{item.driver_name}</td><td>{item.destination}</td><td>{item.purpose}</td>
          <td>{item.can_edit ? <div className="schedule-actions">{confirmDelete === item.id ? <><span>일정을 취소할까요?</span><button disabled={busy} className="schedule-danger" onClick={() => remove(item.id)}>취소 확정</button><button disabled={busy} onClick={() => setConfirmDelete(null)}>유지</button></> : <><button disabled={busy || !!error} aria-label={`${item.start_time} ${item.driver_name} 일정 수정`} onClick={() => { setEditor(item); setSaveError(""); setConfirmDelete(null); setSelectedId(item.id); }}>수정</button><button disabled={busy || !!error} className="schedule-danger" aria-label={`${item.start_time} ${item.driver_name} 일정 취소`} onClick={() => { setConfirmDelete(item.id); setEditor(null); setSaveError(""); }}>취소</button></>}</div> : <span className="schedule-readonly">조회 전용</span>}</td>
        </tr>)}</tbody>
      </table></div>}
    </section>
  </>;
}

export default function VehicleSchedule({ token, user, api }) {
  const [date, setDate] = useState(today), [team, setTeam] = useState(user.role === "ADMIN" ? "" : user.team_id);
  return <section className="vehicle-schedule">
    <div className="schedule-toolbar"><div><p className="eyebrow">DAILY VEHICLE SCHEDULE</p><h2>차량 운행 스케줄</h2><p>{longDate(date)}</p></div>
      <div className="schedule-filters">
        {user.role === "ADMIN" && <label>섹션<select value={team} onChange={(event) => setTeam(event.target.value)}><option value="">전체 섹션</option>{Object.entries(TEAMS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>}
        <div className="schedule-date-nav"><button aria-label="이전 날짜" onClick={() => setDate(moveDay(date, -1))}>‹</button><label><span className="schedule-sr-only">조회 날짜</span><input type="date" value={date} onChange={(event) => { if (/^\d{4}-\d{2}-\d{2}$/.test(event.target.value)) setDate(event.target.value); }} /></label><button aria-label="다음 날짜" onClick={() => setDate(moveDay(date, 1))}>›</button><button onClick={() => setDate(today())}>오늘</button></div>
      </div>
    </div>
    <ScheduleDay key={`${date}-${team}`} date={date} team={team} user={user} token={token} api={api} />
  </section>;
}
