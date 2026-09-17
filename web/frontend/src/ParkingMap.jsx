import React, { useEffect, useState } from "react";
import "./parking-map.css";
import { formatLastSeen } from "./dateTime";

const statusLabel = (status) => ({ PARKED: "주차", MOVING: "이동", UNKNOWN: "미확인", EXITED: "출차" }[status] || status);
const hasPosition = (vehicle, mapId) => Boolean(mapId && vehicle.map_position) && vehicle.status !== "EXITED" && vehicle.map_position.map_id === mapId &&
  [vehicle.map_position.x, vehicle.map_position.y].every(value => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100);
const detectedTime = (value) => formatLastSeen(value, "감지 이력 없음");

export function displayPosition(vehicle, mapId, zones) {
  if (vehicle.status === "EXITED") return null;
  if (hasPosition(vehicle, mapId)) return { ...vehicle.map_position, source: "exact" };
  const area = zones.find(item => item.id === vehicle.current_zone_id);
  if (!mapId || !area || !Array.isArray(area.label)) return null;
  return { x: area.label[0], y: area.label[1], source: "zone" };
}

export default function ParkingMap({ parkingMap, layout, vehicles, token, api, onVehiclesUpdated }) {
  const [records, setRecords] = useState(vehicles);
  const [selected, setSelected] = useState(null);
  const [zone, setZone] = useState(null);
  const [showZones, setShowZones] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [imageReady, setImageReady] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [syncError, setSyncError] = useState(false);
  useEffect(() => { setRecords(vehicles); }, [vehicles]);
  useEffect(() => { setImageReady(false); setImageError(false); }, [parkingMap?.url]);
  useEffect(() => {
    let active = true, timer;
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const response = await fetch(`${api}/vehicles/`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal });
        if (!response.ok) throw new Error("refresh failed");
        const data = await response.json();
        if (active) { setRecords(data); onVehiclesUpdated?.(data); setSyncError(false); }
      } catch (error) { if (active && error.name !== "AbortError") setSyncError(true); }
      finally { if (active) timer = setTimeout(refresh, 3000); }
    };
    timer = setTimeout(refresh, 3000);
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [api, token, onVehiclesUpdated]);
  useEffect(() => {
    if (!expanded) return;
    const close = event => { if (event.key === "Escape") setExpanded(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [expanded]);

  const matchingLayout = Boolean(parkingMap?.filename && layout?.map_id) && parkingMap.filename === layout.map_id;
  const zones = matchingLayout && Array.isArray(layout.zones) ? layout.zones : [];
  const mapped = records.map(vehicle => ({ ...vehicle, display_position: displayPosition(vehicle, parkingMap?.filename, zones) }));
  const located = mapped.filter(vehicle => vehicle.display_position);
  const unlocated = mapped.filter(vehicle => !vehicle.display_position);
  const visible = zone ? located.filter(vehicle => vehicle.current_zone_id === zone) : located;
  const current = mapped.find(vehicle => vehicle.plate_number === selected);
  const chooseVehicle = vehicle => { setSelected(vehicle.plate_number); setZone(null); };

  return <section className={`ops-panel parking-panel ${expanded ? "parking-expanded" : ""}`} aria-label="주차장 차량 위치">
    <div className="panel-heading"><div><h2>주차장 차량 위치</h2><p>{syncError ? "갱신 실패 · 마지막 조회 결과" : "3초마다 위치 갱신"}{layout?.draft && " · 구역 경계 초안"}</p></div>
      <button onClick={() => setExpanded(!expanded)}>{expanded ? "닫기" : "크게 보기"}</button></div>
    <div className="parking-toolbar"><div className="position-summary"><strong>{located.length}</strong> 위치 확인 <span>·</span> {unlocated.length} 위치 미확인</div>
      <div className="map-controls"><label><input type="checkbox" checked={showZones} onChange={event => setShowZones(event.target.checked)} />구역</label>
        <button aria-label="지도 축소" disabled={zoom === 1} onClick={() => setZoom(value => Math.max(1, value - .5))}>−</button>
        <button aria-label="지도 배율 초기화" onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button>
        <button aria-label="지도 확대" disabled={zoom === 3} onClick={() => setZoom(value => Math.min(3, value + .5))}>＋</button></div></div>
    <div className="parking-viewport">
      {!parkingMap || imageError ? <p className="map-empty">주차장 이미지를 불러올 수 없습니다.</p> : <div className="parking-canvas" style={{ width: `${zoom * 100}%` }}>
        <img src={`${api}${parkingMap.url}?token=${encodeURIComponent(token)}`} alt="주차장 항공사진" onLoad={() => setImageReady(true)} onError={() => setImageError(true)} />
        {imageReady && <>
          {showZones && <svg className="parking-boundaries" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            {zones.map(item => <polygon key={item.id} points={item.polygon.map(point => point.join(",")).join(" ")} fill={item.color} stroke={item.color} fillOpacity={zone === item.id ? .3 : .08} strokeWidth={zone === item.id ? 3 : 1.5} vectorEffect="non-scaling-stroke" />)}
          </svg>}
          {showZones && zones.map(item => <button key={item.id} className={`parking-zone-label ${zone === item.id ? "active" : ""}`} style={{ left: `${item.label[0]}%`, top: `${item.label[1]}%`, "--zone-color": item.color }} aria-pressed={zone === item.id} onClick={() => { setZone(zone === item.id ? null : item.id); setSelected(null); }}>{item.name}</button>)}
          {visible.map(vehicle => <button key={vehicle.plate_number} className={`vehicle-pin ${vehicle.display_position.source === "zone" ? "pin-zone" : ""} ${vehicle.status === "MOVING" ? "pin-moving" : ""} ${selected === vehicle.plate_number ? "pin-selected" : ""}`} style={{ left: `${vehicle.display_position.x}%`, top: `${vehicle.display_position.y}%` }} onClick={() => chooseVehicle(vehicle)} aria-label={`${vehicle.plate_number} ${statusLabel(vehicle.status)} 위치`} title={`${vehicle.plate_number} · ${vehicle.display_position.source === "zone" ? "구역 기준 위치" : "인식 좌표"} · ${detectedTime(vehicle.last_seen_at)}`}>
            <span className="pin-dot"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 8l2-4h8l2 4 2 3v8h-3v-2H7v2H4v-8l2-3zm1 0h10l-1-3H8L7 8zm0 4v2h3v-2H7zm7 0v2h3v-2h-3z" fill="currentColor" /></svg></span>
            <span className="pin-plate">{vehicle.plate_number}</span>
          </button>)}
        </>}
      </div>}
    </div>
    <div className="parking-legend"><span><i className="legend-parked" />주차</span><span><i className="legend-moving" />이동</span><span>점선 마커: 구역 기준 위치</span><span>사진 속 차량은 배경 이미지입니다.</span></div>
    <div className="parking-zone-filters"><button className={!zone ? "chosen" : ""} onClick={() => setZone(null)}>전체</button>{zones.map(item => <button key={item.id} className={zone === item.id ? "chosen" : ""} onClick={() => setZone(zone === item.id ? null : item.id)}>{item.name} · {located.filter(vehicle => vehicle.current_zone_id === item.id).length}</button>)}</div>
    {current && <div className="parking-detail"><strong>{current.plate_number} · {statusLabel(current.status)}</strong><span>{current.current_zone_id || "구역 미확인"} · {current.display_position?.source === "zone" ? "구역 기준 위치 · 정확한 주차면은 미확인" : current.display_position ? "인식 좌표" : "위치 미확인"}</span><small>최종 감지: {detectedTime(current.last_seen_at)}</small></div>}
    <div className="parking-vehicle-list">{(zone ? mapped.filter(vehicle => vehicle.current_zone_id === zone) : mapped).map(vehicle => <button key={vehicle.plate_number} onClick={() => chooseVehicle(vehicle)} className={selected === vehicle.plate_number ? "chosen" : ""}><strong>{vehicle.plate_number}</strong><span>{vehicle.display_position?.source === "zone" ? `${vehicle.current_zone_id} · 구역 기준` : vehicle.display_position ? statusLabel(vehicle.status) : "위치 미확인"}</span></button>)}</div>
    {!located.length && <p className="parking-note">차량 위치 수신 대기 · 인식된 위치가 들어오면 지도에 표시됩니다.</p>}
    {zone && !visible.length && <p className="parking-note">이 구역에 확인된 차량 좌표가 없습니다.</p>}
  </section>;
}
