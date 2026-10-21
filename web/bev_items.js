// Keep both CCTV boxes, but show one BEV marker for a shared Global ID.
export function globalVehicleLabel(globalId) {
    return globalId == null ? null : `G${String(globalId).padStart(3, "0")}`;
}

// One color per Global ID, shared by the BEV marker and its path, so a car
// keeps its color while it moves between cameras.
export const GLOBAL_ID_COLORS = ["#ff5d5d", "#38bdf8", "#facc15", "#a78bfa", "#34d399",
    "#fb923c", "#f472b6", "#22d3ee", "#a3e635", "#e879f9"];

export function globalVehicleColor(globalId) {
    if (globalId == null) return null;
    const index = (Number(globalId) - 1) % GLOBAL_ID_COLORS.length;
    return GLOBAL_ID_COLORS[(index + GLOBAL_ID_COLORS.length) % GLOBAL_ID_COLORS.length];
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

// When cameras overlap, the key camera's BEV position replaces the listed
// ones for a shared Global ID: cam07 wins over cam02 while both see the car,
// so the marker does not jump between the two projections. Other overlapping
// cameras are averaged.
export const BEV_CAMERA_OVERRIDES = { cam07: ["cam02"] };

function groupKey(item) {
    return item.global_id == null
        ? `local:${item.camera_id}:${item.local_id}`
        : `global:${item.global_id}`;
}

export function collapseBevItems(items) {
    const cameras = new Map();
    for (const item of items) {
        const key = groupKey(item);
        if (!cameras.has(key)) cameras.set(key, new Set());
        cameras.get(key).add(item.camera_id);
    }

    const grouped = new Map();
    for (const item of items) {
        const key = groupKey(item);
        const overridden = [...cameras.get(key)].some(camera =>
            (BEV_CAMERA_OVERRIDES[camera] || []).includes(item.camera_id));
        const existing = grouped.get(key);
        if (!existing) {
            grouped.set(key, { item: { ...item }, count: overridden ? 0 : 1 });
            continue;
        }
        if (!overridden) {
            existing.count += 1;
            if (existing.count === 1) {
                existing.item.camera_id = item.camera_id;
                existing.item.x = item.x;
                existing.item.y = item.y;
            } else {
                existing.item.x += (item.x - existing.item.x) / existing.count;
                existing.item.y += (item.y - existing.item.y) / existing.count;
            }
        }
        if ((BEV_STATE_PRIORITY[item.state] || 0)
                > (BEV_STATE_PRIORITY[existing.item.state] || 0)) {
            existing.item.state = item.state;
        }
    }
    return [...grouped.values()].map(group => group.item);
}

// Path mode: points are [frame, x, y] in frame order (server replay/paths.py).
// Up to the current frame, observed stretches become solid runs and stretches
// where the car was out of every camera for more than gapFrames become
// straight gap links between the last and next visible points.
export function pathUntil(points, frameIndex, gapFrames) {
    const runs = [], gaps = [];
    let run = [], previous = null;
    for (const [frame, x, y] of points) {
        if (frame > frameIndex) break;
        if (previous && frame - previous[0] > gapFrames) {
            if (run.length > 1) runs.push(run);
            gaps.push([[previous[1], previous[2]], [x, y]]);
            run = [];
        }
        run.push([x, y]);
        previous = [frame, x, y];
    }
    if (run.length > 1) runs.push(run);
    return { runs, gaps, last: previous && [previous[1], previous[2]] };
}
