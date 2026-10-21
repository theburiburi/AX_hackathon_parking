import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./vehicleSchedule.css";
import { watchScheduleState, scheduleDisplayDate } from "./scheduleSync";

const START_MINUTE = 7 * 60 + 30, END_MINUTE = 18 * 60;
const WINDOW_MINUTES = END_MINUTE - START_MINUTE;
const BOOKING_START_MINUTE = 6 * 60, BOOKING_END_MINUTE = 20 * 60;
const TIME_SLOTS = Array.from({ length: (BOOKING_END_MINUTE - BOOKING_START_MINUTE) / 30 + 1 }, (_, index) => {
  const minute = BOOKING_START_MINUTE + index * 30;
  return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
});
const TEAMS = {
  SECTION_DIGITAL_COMMUNICATION: "광양디지털통신기술섹션",
  SECTION_COLD_DX: "냉간 DX 섹션",
  SECTION_STEELMAKING_CASTING: "제강연주섹션",
};
const colorFor = (team) => team === "SECTION_COLD_DX" ? "teal" : team === "SECTION_STEELMAKING_CASTING" ? "violet" : "blue";
export const minuteOfDay = (time) => { const [h, m] = time.split(":").map(Number); return h * 60 + m; };
const DISPLAY_SLOTS = TIME_SLOTS.filter(time => minuteOfDay(time) >= START_MINUTE && minuteOfDay(time) <= END_MINUTE);
const today = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(new Date());
export function moveDay(day, direction) {
  const value = new Date(`${day}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + direction);
  return value.toISOString().slice(0, 10);
}
export function repeatLimit(day) {
  const start = new Date(`${day}T12:00:00Z`);
  const anchor = new Date(start);
  anchor.setUTCDate(1);
  anchor.setUTCMonth(anchor.getUTCMonth() + 1);
  const lastDay = new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth() + 1, 0)).getUTCDate();
  anchor.setUTCDate(Math.min(start.getUTCDate(), lastDay));
  anchor.setUTCDate(anchor.getUTCDate() - 1);
  return anchor.toISOString().slice(0, 10);
}

export function ScheduleDateNav({ date, onChange }) {
  return <div className="schedule-date-nav">
    <button aria-label="이전 날짜" onClick={() => onChange(moveDay(date, -1))}>‹</button>
    <label><span className="schedule-sr-only">조회 날짜</span><input type="date" value={date} onChange={event => { if (/^\d{4}-\d{2}-\d{2}$/.test(event.target.value)) onChange(event.target.value); }} /></label>
    <button aria-label="다음 날짜" onClick={() => onChange(moveDay(date, 1))}>›</button>
    <button onClick={() => onChange(today())}>오늘</button>
  </div>;
}

async function call(api, token, path, options = {}) {
  const response = await fetch(`${api}/vehicle-schedules/${path}`, {
    cache: "no-store", ...options, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
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
  return <div className="schedule-scroll schedule-timetable" style={{ "--schedule-slots": DISPLAY_SLOTS.length - 1 }} tabIndex="0" role="region" aria-label="차량별 하루 시간표. 시간은 왼쪽에서 오른쪽으로 표시되며 가로로 스크롤할 수 있습니다.">
    {!!rows.length && <table className="schedule-board">
      <caption className="schedule-sr-only">{date} 차량 운행 시간표 · 한국시간 07:30~18:00</caption>
      <colgroup><col className="schedule-vehicle-col" /><col /></colgroup>
      <thead><tr><th scope="col" className="schedule-vehicle">차량 / 소속 섹션</th>
        <th scope="col" className="schedule-time-heading" aria-label="시간 07:30~18:00"><div className="schedule-hours">
          {DISPLAY_SLOTS.map(time => <span key={time} style={{ left: `${(minuteOfDay(time) - START_MINUTE) / WINDOW_MINUTES * 100}%` }}>{time}</span>)}
        </div></th>
      </tr></thead>
      <tbody>{rows.map((vehicle) => {
        const items = schedules.filter((item) => item.vehicle_id === vehicle.id && minuteOfDay(item.end_time) > START_MINUTE && minuteOfDay(item.start_time) < END_MINUTE);
        return <tr key={vehicle.id}><th scope="row" className="schedule-vehicle"><strong>{vehicle.plate_number}</strong><small>{TEAMS[vehicle.team_id] || vehicle.team_id}</small></th>
          <td className="schedule-track-cell"><div className="schedule-track" role="group" aria-label={`${vehicle.plate_number} 운행 일정`}>
            {!items.length && <span className="schedule-free">표시 시간 내 운행 없음</span>}
            {items.map((item) => <button key={item.id} type="button" className={`schedule-block ${colorFor(item.team_id)} ${selectedId === item.id ? "active" : ""}`}
              style={{ left: `${(Math.max(START_MINUTE, minuteOfDay(item.start_time)) - START_MINUTE) / WINDOW_MINUTES * 100}%`, width: `${(Math.min(END_MINUTE, minuteOfDay(item.end_time)) - Math.max(START_MINUTE, minuteOfDay(item.start_time))) / WINDOW_MINUTES * 100}%` }}
              onClick={() => onSelect(item.id)} aria-pressed={selectedId === item.id}
              aria-label={`${item.plate_number} ${item.start_time}–${item.end_time} ${item.driver_name} · ${item.destination} · ${item.purpose}`}
              title={`${item.start_time}–${item.end_time} ${item.driver_name}\n${item.destination} · ${item.purpose}`}>
              <strong>{item.start_time}–{item.end_time}</strong><span>{item.driver_name} · {item.destination}</span>
            </button>)}
          </div></td></tr>;
      })}</tbody>
    </table>}
    {!rows.length && <p className="schedule-empty">등록된 차량이 없습니다. 차량이 등록되면 일정을 추가할 수 있습니다.</p>}
  </div>;
}

export function ScheduleForm({ initial, date, user, vehicles, members, busy, error, onSave, onClose }) {
  const [form, setForm] = useState(() => initial ? {
    ...initial, repeat_weekdays: !!initial.repeat_weekdays,
    repeat_until: initial.repeat_until || repeatLimit(initial.date),
  } : { date, repeat_weekdays: false, repeat_until: repeatLimit(date), vehicle_id: "", driver_id: user.role === "ADMIN" ? "" : user.id, start_time: "09:00", end_time: "10:00", destination: "", purpose: "" });
  const firstInput = useRef(null);
  useEffect(() => { firstInput.current?.focus(); }, []);
  const vehicle = vehicles.find((v) => v.id === form.vehicle_id);
  const drivers = members.filter((member) => member.team_id === vehicle?.team_id);
  const change = (key) => (event) => setForm({ ...form, [key]: event.target.value });
  const changeStartTime = event => {
    const start = event.target.value;
    const nextEnd = TIME_SLOTS[TIME_SLOTS.indexOf(start) + 1];
    setForm({ ...form, start_time: start, end_time: minuteOfDay(form.end_time) > minuteOfDay(start) ? form.end_time : nextEnd });
  };
  const changeDate = (event) => {
    const nextDate = event.target.value;
    if (!nextDate) return;
    const limit = repeatLimit(nextDate);
    setForm({ ...form, date: nextDate,
      repeat_until: form.repeat_until >= nextDate && form.repeat_until <= limit ? form.repeat_until : limit });
  };
  return <section className="schedule-editor" aria-labelledby="schedule-editor-title">
    <div className="schedule-heading"><div><h3 id="schedule-editor-title">{initial ? "운행 일정 수정" : "새 운행 일정"}</h3><p>06:00~20:00 사이에서 30분 단위로 선택하세요. 종료 시간은 시작 시간보다 늦어야 합니다.</p></div><button type="button" disabled={busy} onClick={onClose}>닫기</button></div>
    <form onSubmit={(event) => { event.preventDefault(); onSave(form); }}>
      <fieldset disabled={busy} className="schedule-form-grid">
        <label>{form.repeat_weekdays ? "반복 시작일" : "운행 날짜"}<input ref={firstInput} required type="date" value={form.date} onChange={changeDate} /></label>
        <label>차량<select required value={form.vehicle_id} onChange={(event) => setForm({ ...form, vehicle_id: event.target.value, driver_id: user.role === "ADMIN" ? "" : user.id })}>
          <option value="">차량 선택</option>{vehicles.map((v) => <option key={v.id} value={v.id}>{v.plate_number}</option>)}
        </select></label>
        <label>운전자{user.role === "ADMIN" ? <select required value={form.driver_id} onChange={change("driver_id")}><option value="">운전자 선택</option>{drivers.map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select> : <input readOnly value={user.name} />}</label>
        <label>시작 시간<select required value={form.start_time} onChange={changeStartTime}>
          {!TIME_SLOTS.slice(0, -1).includes(form.start_time) && <option value={form.start_time} disabled>{form.start_time} · 다시 선택</option>}
          {TIME_SLOTS.slice(0, -1).map(time => <option key={time} value={time}>{time}</option>)}
        </select></label>
        <label>종료 시간<select required value={form.end_time} onChange={change("end_time")}>
          {!TIME_SLOTS.slice(1).includes(form.end_time) && <option value={form.end_time} disabled>{form.end_time} · 다시 선택</option>}
          {TIME_SLOTS.slice(1).map(time => <option key={time} value={time} disabled={minuteOfDay(time) <= minuteOfDay(form.start_time)}>{time}</option>)}
        </select></label>
        <label>목적지<input required maxLength="120" placeholder="예: 제강 공장" value={form.destination} onChange={change("destination")} /></label>
        <label className="schedule-purpose">운행 목적<input required maxLength="200" placeholder="예: 설비 점검 및 현장 회의" value={form.purpose} onChange={change("purpose")} /></label>
        <label className="schedule-repeat"><input type="checkbox" checked={form.repeat_weekdays} onChange={event => setForm({ ...form, repeat_weekdays: event.target.checked })} />평일 반복 (월~금)</label>
        {form.repeat_weekdays && <>
          <label>반복 종료일<input required type="date" min={form.date} max={repeatLimit(form.date)} value={form.repeat_until} onChange={change("repeat_until")} /></label>
          <p className="schedule-repeat-help">시작일부터 최대 한 달 · 토·일 제외 · 공휴일 포함{initial && " · 변경은 반복 기간 전체에 적용됩니다."}{scheduleDisplayDate(form, form.date) !== form.date && ` · 첫 운행일: ${scheduleDisplayDate(form, form.date)}`}</p>
        </>}
        <button className="schedule-primary" type="submit">{busy ? "저장 중…" : initial ? "변경 저장" : "일정 등록"}</button>
      </fieldset>
      {error && <p role="alert" className="error">{error}</p>}
    </form>
  </section>;
}

function ScheduleDay({ date, team, user, api, token, message, onMessage, onDateChange }) {
  const [data, setData] = useState(null), [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [editor, setEditor] = useState(null), [busy, setBusy] = useState(false), [saveError, setSaveError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(null);
  const syncRef = useRef(null);
  const detailRef = useRef(null);
  const nextWeekday = scheduleDisplayDate({ date, repeat_weekdays: true, repeat_until: repeatLimit(date) }, date);
  useEffect(() => {
    const watcher = watchScheduleState({
      load: signal => call(api, token, `?date=${encodeURIComponent(date)}&team_id=${encodeURIComponent(team)}`, { signal }),
      onState: setData, onError: err => setError(err?.message || ""), events: window,
    });
    syncRef.current = watcher;
    return () => { watcher.stop(); syncRef.current = null; };
  }, [api, token, date, team]);
  const select = (id) => { setSelectedId(id); setConfirmDelete(null); detailRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); };
  const save = async (form) => {
    if (busy) return;
    setBusy(true); setSaveError(""); onMessage("");
    try {
      const saved = await call(api, token, editor?.id ? `${editor.id}/` : "", { method: editor?.id ? "PUT" : "POST", body: JSON.stringify(form) });
      setEditor(null); setSelectedId(null); setConfirmDelete(null);
      const displayDate = scheduleDisplayDate(saved, date);
      onMessage(`${form.repeat_weekdays ? `${form.date}~${form.repeat_until} 평일 반복` : form.date} ${form.start_time}–${form.end_time} 일정이 저장되었습니다.${displayDate !== date ? ` ${displayDate} 시간표를 표시합니다.` : ""}`);
      if (displayDate !== date) onDateChange(displayDate);
      else syncRef.current?.refresh();
    } catch (err) { setSaveError(err.message); }
    finally { setBusy(false); }
  };
  const remove = async (id) => {
    if (busy) return;
    setBusy(true); onMessage(""); setSaveError("");
    try {
      await call(api, token, `${id}/`, { method: "DELETE" });
      setData((value) => ({ ...value, schedules: value.schedules.filter((item) => item.id !== id) }));
      setConfirmDelete(null); setSelectedId(null); onMessage("운행 일정이 취소되었습니다."); syncRef.current?.refresh();
    } catch (err) { setSaveError(err.message); }
    finally { setBusy(false); }
  };
  if (!data) return <div className="panel" role="status">{error ? <><p className="error">{error}</p><button onClick={() => syncRef.current?.refresh()}>다시 불러오기</button></> : "스케줄을 불러오는 중입니다…"}</div>;
  const scopeName = TEAMS[team] || "전체 섹션";
  return <>
    <div className="schedule-summary">
      <div><span>조회 차량</span><strong>{data.vehicles.length}<small>대</small></strong></div>
      <div><span>운행 일정</span><strong>{data.schedules.length}<small>건</small></strong></div>
      <div><span>조회 범위</span><strong className="schedule-scope" title={scopeName}>{scopeName.endsWith("섹션") ? <><span className="schedule-section-name">{scopeName.slice(0, -2)}</span><small className="schedule-section-suffix">섹션</small></> : <span className="schedule-section-name">{scopeName}</span>}</strong></div>
    </div>
    <section className="panel schedule-panel">
      <div className="schedule-heading"><div><h2>일일 운행 시간표</h2></div>
        <button className="schedule-primary" disabled={busy || !data.vehicles.length || !!error} onClick={() => { setEditor({}); setSaveError(""); setConfirmDelete(null); }}>+ 운행 등록</button>
      </div>
      <div className="schedule-legend">{Object.entries(TEAMS).filter(([id]) => !team || team === id).map(([id, label]) => <span key={id}><i className={colorFor(id)} />{label}</span>)}</div>
      {error && <p className="error" role="alert">갱신 실패: {error} (마지막 조회 결과입니다.) <button onClick={() => syncRef.current?.refresh()}>재시도</button></p>}
      {message && <p className="success" role="status">{message}</p>}
      {editor && <ScheduleForm key={editor.id || "new"} initial={editor.id ? editor : null} date={date} user={user} vehicles={data.vehicles} members={data.members} busy={busy} error={saveError} onSave={save} onClose={() => { setEditor(null); setSaveError(""); }} />}
      <ScheduleBoard vehicles={data.vehicles} schedules={data.schedules} selectedId={selectedId} onSelect={select} date={date} />
      <p className="schedule-hint">사용자는 본인이 등록한 일정만 수정 및 취소할 수 있습니다. 반복 일정의 변경 및 취소는 반복 기간 전체에 적용됩니다.</p>
    </section>
    <section ref={detailRef} className="panel schedule-detail">
      <div className="schedule-heading"><h2>운행 상세 <span className="record-count">{data.schedules.length}건</span></h2><span>시간순 정렬</span></div>
      {!editor && saveError && <p className="error" role="alert">{saveError}</p>}
      {!data.schedules.length ? <div className="schedule-empty"><strong>이 날짜에는 운행 일정이 없습니다.</strong><p>운행 등록 버튼으로 첫 일정을 추가하세요.</p>{nextWeekday !== date && <><p>선택한 날짜는 주말입니다. 평일 반복 일정은 다음 평일 시간표에서 확인하세요.</p><button onClick={() => onDateChange(nextWeekday)}>{nextWeekday} 시간표 보기</button></>}</div> : <div className="schedule-scroll"><table className="schedule-list" role="table" aria-label="운행 상세 목록">
        <thead role="rowgroup"><tr role="row"><th role="columnheader" scope="col">시간</th><th role="columnheader" scope="col">차량 / 섹션</th><th role="columnheader" scope="col">운전자</th><th role="columnheader" scope="col">목적지</th><th role="columnheader" scope="col">운행 목적</th><th role="columnheader" scope="col">관리</th></tr></thead>
        <tbody role="rowgroup">{data.schedules.map((item) => <tr role="row" key={item.id} className={selectedId === item.id ? "schedule-selected" : ""}>
          <td role="cell" data-label="시간" className="schedule-time">{item.start_time}–{item.end_time}{item.repeat_weekdays && <small>평일 반복 · {item.date}~{item.repeat_until}</small>}</td><td role="cell" data-label="차량 / 섹션"><strong>{item.plate_number}</strong><small>{TEAMS[item.team_id] || item.team_id}</small></td><td role="cell" data-label="운전자">{item.driver_name}</td><td role="cell" data-label="목적지">{item.destination}</td><td role="cell" data-label="운행 목적">{item.purpose}</td>
          <td role="cell" data-label="관리">{item.can_edit ? <div className="schedule-actions">{confirmDelete === item.id ? <><span>{item.repeat_weekdays ? "반복 기간 전체의 일정을 취소할까요?" : "일정을 취소할까요?"}</span><button disabled={busy} className="schedule-danger" onClick={() => remove(item.id)}>취소 확정</button><button disabled={busy} onClick={() => setConfirmDelete(null)}>유지</button></> : <><button disabled={busy || !!error} aria-label={`${item.start_time} ${item.driver_name} 일정 수정`} onClick={() => { setEditor(item); setSaveError(""); setConfirmDelete(null); setSelectedId(item.id); }}>수정</button><button disabled={busy || !!error} className="schedule-danger" aria-label={`${item.start_time} ${item.driver_name} 일정 취소`} onClick={() => { setConfirmDelete(item.id); setEditor(null); setSaveError(""); }}>취소</button></>}</div> : <span className="schedule-readonly">조회 전용</span>}</td>
        </tr>)}</tbody>
      </table></div>}
    </section>
  </>;
}

export default function VehicleSchedule({ token, user, api, dateNavTarget }) {
  const [date, setDate] = useState(today), [team, setTeam] = useState(user.role === "ADMIN" ? "" : user.team_id);
  const [message, setMessage] = useState("");
  const changeDay = next => { setMessage(""); setDate(next); };
  const dateNav = <ScheduleDateNav date={date} onChange={changeDay} />;
  return <section className="vehicle-schedule">
    {dateNavTarget ? createPortal(dateNav, dateNavTarget) : <div className="schedule-toolbar">
      <div className="schedule-filters">
        {user.role === "ADMIN" && <label>섹션<select value={team} onChange={(event) => setTeam(event.target.value)}><option value="">전체 섹션</option>{Object.entries(TEAMS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>}
        {dateNav}
      </div>
    </div>}
    <ScheduleDay key={`${date}-${team}`} date={date} team={team} user={user} token={token} api={api} message={message} onMessage={setMessage} onDateChange={setDate} />
  </section>;
}
