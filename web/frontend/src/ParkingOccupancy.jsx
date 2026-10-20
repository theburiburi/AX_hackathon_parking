import React, { useEffect, useState } from "react";
import "./parking-occupancy.css";

export function useParkingOccupancy(api, token, enabled = true) {
  const [state, setState] = useState({ zones: null, error: false });
  useEffect(() => {
    if (!enabled) return;
    let active = true, timer;
    const controller = new AbortController();
    setState({ zones: null, error: false });
    const refresh = async () => {
      try {
        const response = await fetch(`${api}/parking-zones/`, {
          headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
        });
        if (!response.ok) throw new Error("Occupancy refresh failed");
        const zones = await response.json();
        if (!Array.isArray(zones)) throw new Error("Invalid occupancy response");
        if (active) setState({ zones, error: false });
      } catch (error) {
        if (active && error.name !== "AbortError") setState(previous => ({ ...previous, error: true }));
      } finally {
        if (active) timer = setTimeout(refresh, 3000);
      }
    };
    refresh();
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [api, token, enabled]);
  return state;
}

export function ParkingOccupancySummary({ zones, error = false }) {
  const total = zones?.reduce((sum, zone) => sum + zone.parked_count, 0);
  const capacity = zones?.every(zone => Number.isInteger(zone.capacity) && zone.capacity >= 0)
    ? zones.reduce((sum, zone) => sum + zone.capacity, 0) : "—";
  return <section className="parking-occupancy" aria-label="전체 주차장 구역별 주차 대수">
    <div className="occupancy-heading"><div><h3>구역별 현재 주차</h3></div>
      {zones && <strong>총 {total}대 / {capacity}대</strong>}
    </div>
    {error && <p className="error" role="alert">주차 현황 갱신 실패{zones ? " · 마지막 조회 결과입니다." : " · 잠시 후 다시 조회합니다."}</p>}
    {!zones && !error && <p className="form-note">주차 현황을 불러오는 중입니다.</p>}
    {zones && (zones.length ? <div className="occupancy-grid">{zones.map(zone => <article key={zone.id} className="occupancy-zone">
      <div><strong>{zone.name}</strong></div>
      <p className="occupancy-count" aria-label={`현재 ${zone.parked_count}대 / 최대 ${zone.capacity ?? "미확인"}대`}><strong>{zone.parked_count}대</strong> / {zone.capacity ?? "—"}대</p>
    </article>)}</div> : <p className="form-note">설정된 주차 구역이 없습니다.</p>)}
  </section>;
}

export default function ParkingOccupancy({ api, token }) {
  return <ParkingOccupancySummary {...useParkingOccupancy(api, token)} />;
}
