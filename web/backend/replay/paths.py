"""Whole-video BEV path of every Global ID, for the replay path mode."""
import json
from functools import lru_cache
from pathlib import Path

# web/bev_items.js와 같은 규칙: 같은 GID를 동시에 보면 key 카메라의 위치가
# 목록의 카메라 위치를 대신한다. 나머지 겹치는 카메라는 평균.
BEV_CAMERA_OVERRIDES = {"cam07": ("cam02",)}
TRACKED_STATES = ("ACTIVE", "STOPPED", "PARKED")

# 3프레임(30fps 기준 0.1초)마다 한 점, 이전 점에서 이 거리보다 가까우면 생략.
SAMPLE_EVERY_FRAMES = 3
MIN_STEP_PX = 3.0
# 위치 흔들림을 줄이는 이동 평균 (앞뒤 점 개수). 끊긴 구간은 넘지 않는다.
SMOOTH_RADIUS = 2
# 이 간격보다 오래 보이지 않았던 구간은 화면에서 점선으로 잇는다.
GAP_FRAMES = 30


def frame_positions(bev, width, height):
    """GID별 이 프레임의 BEV 위치 (카메라 우선순위·평균 적용)."""
    by_global = {}
    for item in bev:
        global_id = item.get("global_id")
        x, y = item.get("x"), item.get("y")
        if (global_id is None or item.get("state") not in TRACKED_STATES
                or not isinstance(x, (int, float)) or not isinstance(y, (int, float))
                or not (0 <= x < width and 0 <= y < height)):
            continue
        by_global.setdefault(global_id, []).append(item)
    positions = {}
    for global_id, items in by_global.items():
        cameras = {item["camera_id"] for item in items}
        hidden = {camera for key in cameras for camera in BEV_CAMERA_OVERRIDES.get(key, ())}
        kept = [item for item in items if item["camera_id"] not in hidden] or items
        positions[global_id] = (sum(item["x"] for item in kept) / len(kept),
                                sum(item["y"] for item in kept) / len(kept))
    return positions


def _smooth(points):
    """끊기지 않은 구간 안에서만 이동 평균."""
    result = []
    for index, (frame, _, _) in enumerate(points):
        window = [points[index]]
        for step in (-1, 1):
            cursor = index
            for _ in range(SMOOTH_RADIUS):
                neighbor = cursor + step
                if not 0 <= neighbor < len(points):
                    break
                if abs(points[neighbor][0] - points[cursor][0]) > GAP_FRAMES:
                    break
                window.append(points[neighbor])
                cursor = neighbor
        result.append([frame, round(sum(p[1] for p in window) / len(window), 1),
                       round(sum(p[2] for p in window) / len(window), 1)])
    return result


def build_paths(frames, width, height):
    """frames: 프레임 순서대로 (frame_index, bev 목록)."""
    raw = {}
    for frame_index, bev in frames:
        if frame_index % SAMPLE_EVERY_FRAMES:
            continue
        for global_id, (x, y) in frame_positions(bev, width, height).items():
            raw.setdefault(global_id, []).append((frame_index, x, y))
    paths = {}
    for global_id, points in raw.items():
        kept = []
        for point in _smooth(points):
            if kept and point[0] - kept[-1][0] <= GAP_FRAMES and (
                    (point[1] - kept[-1][1]) ** 2 + (point[2] - kept[-1][2]) ** 2
                    < MIN_STEP_PX ** 2):
                continue
            kept.append(point)
        # 마지막으로 보인 위치는 항상 남긴다.
        last = _smooth(points)[-1]
        if kept[-1][0] != last[0]:
            kept.append(last)
        paths[str(global_id)] = kept
    return paths


@lru_cache(maxsize=4)
def _cached_paths(frames_path, size, mtime_ns, width, height):
    def frames():
        with Path(frames_path).open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    frame = json.loads(line)
                    yield frame["frame_index"], frame.get("bev") or []
    return build_paths(frames(), width, height)


def vehicle_paths(store):
    stat = store.frames_path.stat()
    map_info = store.manifest["map"]
    return {
        "cache_id": store.manifest["cache_id"],
        "gap_frames": GAP_FRAMES,
        "paths": _cached_paths(str(store.frames_path), stat.st_size, stat.st_mtime_ns,
                               map_info["width"], map_info["height"]),
    }
