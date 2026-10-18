import React, { useEffect, useState } from "react";
import "./parking-map.css";
import { useParkingOccupancy, ParkingOccupancySummary } from "./ParkingOccupancy";

const hasPosition = (vehicle, mapId) => Boolean(mapId && vehicle.map_position) && vehicle.status !== "EXITED" && vehicle.map_position.map_id === mapId &&
  [vehicle.map_position.x, vehicle.map_position.y].every(value => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100);
export const zoneName = (id, zones = []) => zones.find(zone => zone.id === id)?.name || (/^[A-N]$/.test(id || "") ? `${id} 구역` : "구역 미확인");

export function displayPosition(vehicle, mapId, zones) {
  if (vehicle.status === "EXITED") return null;
  if (hasPosition(vehicle, mapId)) return { ...vehicle.map_position, source: "exact" };
  const area = zones.find(item => item.id === vehicle.current_zone_id);
  if (!mapId || !area || !Array.isArray(area.label)) return null;
  return { x: area.label[0], y: area.label[1], source: "zone" };
}

export default function ParkingMap({ parkingMap, layout, vehicles, token, api, onVehiclesUpdated, occupancy: sharedOccupancy, showOccupancy = true }) {
  const fallbackOccupancy = useParkingOccupancy(api, token, !sharedOccupancy);
  const occupancy = sharedOccupancy || fallbackOccupancy;
  const [records, setRecords] = useState(vehicles);
  const [zone, setZone] = useState(null);
  const [showZones, setShowZones] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [imageReady, setImageReady] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [syncError, setSyncError] = useState(false);
  useEffect(() => { if (!sharedOccupancy) setRecords(vehicles); }, [vehicles, Boolean(sharedOccupancy)]);
  useEffect(() => { setImageReady(false); setImageError(false); }, [parkingMap?.url]);
  useEffect(() => {
    if (sharedOccupancy) return;
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
  }, [api, token, onVehiclesUpdated, Boolean(sharedOccupancy)]);
  useEffect(() => {
    if (!expanded) return;
    const close = event => { if (event.key === "Escape") setExpanded(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [expanded]);

  const matchingLayout = Boolean(parkingMap?.filename && layout?.map_id) && parkingMap.filename === layout.map_id;
  const zones = matchingLayout && Array.isArray(layout.zones) ? layout.zones.filter(item => layout.source === "native" || /^[A-N]$/.test(item.id)) : [];
  const mapped = (sharedOccupancy ? vehicles : records).map(vehicle => ({ ...vehicle, display_position: displayPosition(vehicle, parkingMap?.filename, zones) }));
  const located = mapped.filter(vehicle => vehicle.display_position);
  const unlocated = mapped.filter(vehicle => !vehicle.display_position);

  return <section className={`ops-panel parking-panel ${expanded ? "parking-expanded" : ""}`} aria-label="주차장 차량 위치">
    <div className="panel-heading"><div><h2>주차장 차량 위치</h2><p>{syncError || occupancy.error ? "갱신 실패 · 마지막 조회 결과" : sharedOccupancy ? "관리자 영상 시점에 맞춰 위치 갱신" : "3초마다 위치 갱신"}{layout?.draft && " · 구역 경계 초안"}</p></div>
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
          {showZones && zones.map(item => {
            const area = occupancy.zones?.find(area => area.id === item.id);
            return <button key={item.id} className={`parking-zone-label ${zone === item.id ? "active" : ""}`} style={{ left: `${item.label[0]}%`, top: `${item.label[1]}%`, "--zone-color": item.color }} aria-pressed={zone === item.id} onClick={() => { setZone(zone === item.id ? null : item.id); }}>{item.name}{area && ` · ${area.parked_count}대 / ${area.capacity ?? "—"}대`}</button>;
          })}
        </>}
      </div>}
    </div>
    {showOccupancy && <ParkingOccupancySummary {...occupancy} synchronized={Boolean(sharedOccupancy)} />}
  </section>;
}
