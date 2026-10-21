// Keep both CCTV boxes, but show one BEV marker for a shared Global ID.
export function globalVehicleLabel(globalId) {
    return globalId == null ? null : `G${String(globalId).padStart(3, "0")}`;
}

// A confirmed Global ID is shown in every state (a parked car keeps its
// number). Before confirmation, a provisional candidate is shown with "?",
// falling back to the unverified best candidate (display only).
export function detectionLabel(detection) {
    const label = globalVehicleLabel(detection.global_id);
    if (label !== null) return { text: label, provisional: false };
    const candidate = globalVehicleLabel(
        detection.provisional_global_id ?? detection.candidate_global_id);
    return candidate === null ? null : { text: `${candidate}?`, provisional: true };
}

// PARKED boxes and markers disappear 15 s after parking. The tracker turns a
// STOPPED car PARKED after parked_after_sec (config/tracking.yaml, 5 s) and
// stopped_seconds keeps counting from the stop, so the cut-off is 5 + 15 s.
export const PARKED_HIDE_AFTER_STOPPED_SEC = 5 + 15;

export function isExpiredParked(item) {
    return item.state === "PARKED"
        && Number(item.stopped_seconds) >= PARKED_HIDE_AFTER_STOPPED_SEC;
}

const BEV_STATE_PRIORITY ={ ACTIVE: 3, STOPPED: 2, PARKED: 1 };

export function collapseBevItems(items) {
    const grouped = new Map();
    for (const item of items) {
        const key = item.global_id == null
            ? `local:${item.camera_id}:${item.local_id}`
            : `global:${item.global_id}`;
        const existing = grouped.get(key);
        if (existing) {
            existing.count += 1;
            existing.item.x += (item.x - existing.item.x) / existing.count;
            existing.item.y += (item.y - existing.item.y) / existing.count;
            if ((BEV_STATE_PRIORITY[item.state] || 0)
                    > (BEV_STATE_PRIORITY[existing.item.state] || 0)) {
                existing.item.state = item.state;
            }
        } else {
            grouped.set(key, { item: { ...item }, count: 1 });
        }
    }
    return [...grouped.values()].map(group => group.item);
}
