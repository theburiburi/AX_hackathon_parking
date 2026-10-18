"""Authenticated replay reads and explicit demo state sync; no inference."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from replay.store import ReplayError, ReplayStore
from replay.frame_response import frame_response
from replay.vehicle_state import apply_snapshot, replay_snapshot
from threading import RLock
from . import json_store
from .media_stream import media_response
from .views import current_parking_zones, login_required
from .parking_state import PARKING_POLICY, vehicle_fingerprint, manual_zone_deltas

_vehicle_lock = RLock()


@api_view(["POST"])
@login_required("ADMIN")
def vehicle_state(request):
    """Explicit demo synchronization; GET and frame prefetch stay read-only."""
    data = request.data
    if not isinstance(data, dict) or type(data.get("frame")) is not int:
        return Response({"detail": "frame은 정수여야 합니다."}, status=400)
    try:
        with _vehicle_lock:
            store = open_store(request)
            if data.get("cache_id") != store.manifest["cache_id"]:
                return Response({"detail": "재생 결과가 변경됐습니다. 다시 불러오세요."}, status=409)
            n = data["frame"]
            if not 0 <= n < store.manifest["frame_count"]:
                return Response({"detail": "영상 프레임 범위를 벗어났습니다."}, status=400)
            vehicles = json_store.read("vehicles")
            updates, parking_deltas = replay_snapshot(store, n, vehicles)
            snapshot = {"cache_id": store.manifest["cache_id"], "video": store.title,
                        "fps": store.manifest["fps"],
                        "parking_policy": PARKING_POLICY,
                        "frame": n, "vehicles": updates, "parking_deltas": parking_deltas,
                        "parking_base_deltas": manual_zone_deltas(vehicles),
                        "base_states": {vehicle["id"]: vehicle_fingerprint(vehicle) for vehicle in vehicles if vehicle["id"] in updates}}
            json_store.write("vehicle_replay_state", snapshot)
        return Response({"frame": n, "updated": len(updates)})
    except (ReplayError, OSError, ValueError, KeyError, TypeError) as exc:
        return Response({"detail": str(exc)}, status=503)


@api_view(["GET"])
@login_required()
def demo_state(request):
    """Read one shared playhead snapshot for both inventory and vehicle status.

    User viewers never open the replay store or change the administrator's
    playhead. Filtering happens after applying departure/team transfers.
    """
    try:
        try:
            snapshot = json_store.read("vehicle_replay_state")
        except FileNotFoundError:
            snapshot = {}
        original = json_store.read("vehicles")
        vehicles = apply_snapshot(original, snapshot)
        if request.auth_user["role"] != "ADMIN":
            vehicles = [row for row in vehicles if row["team_id"] == request.auth_user["team_id"]]
        fps, frame = snapshot.get("fps"), snapshot.get("frame")
        playback = None
        if type(frame) is int and frame >= 0 and type(fps) in (int, float) and fps > 0:
            playback = {"video": snapshot.get("video"), "cache_id": snapshot.get("cache_id"),
                        "frame": frame, "time": frame / fps}
        return Response({"playback": playback, "vehicles": vehicles,
                         "zones": current_parking_zones(original, snapshot)},
                        headers={"Cache-Control": "no-store"})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return Response({"detail": str(exc)}, status=503)


def open_store(request):
    store = ReplayStore()
    requested = request.GET.get("cache_id")
    if requested and requested != store.manifest["cache_id"]:
        raise ReplayError("재생 결과가 변경됐습니다. 페이지를 새로고침하세요.")
    return store


@api_view(["GET"])
@login_required("ADMIN")
def manifest(request):
    try:
        store = open_store(request)
        result = store.public_manifest()
        result["scene"] = {**result["scene"], "video_url": "/replay/video/"}
        result["map"] = {**result["map"], "url": "/replay/map/"}
        return Response(result)
    except ReplayError as exc:
        return Response({"detail": str(exc)}, status=503)


@api_view(["GET"])
@login_required("ADMIN")
def frames(request):
    try:
        start = int(request.GET.get("start", "0"))
        count = int(request.GET.get("count", "60"))
        if start < 0 or not 1 <= count <= 120:
            return Response({"detail": "start는 0 이상, count는 1~120이어야 합니다."}, status=400)
    except ValueError:
        return Response({"detail": "프레임 번호는 정수여야 합니다."}, status=400)
    try:
        store = open_store(request)
        if start >= store.manifest["frame_count"]:
            return Response({"detail": "영상 프레임 범위를 벗어났습니다."}, status=400)
        return frame_response(store, start, count, request)
    except (ReplayError, OSError, ValueError) as exc:
        return Response({"detail": str(exc)}, status=503)


@api_view(["GET", "HEAD"])
@login_required("ADMIN")
def video(request):
    try:
        return media_response(request, open_store(request).video_path, "video/mp4")
    except ReplayError as exc:
        return Response({"detail": str(exc)}, status=503)


@api_view(["GET", "HEAD"])
@login_required("ADMIN")
def map_image(request):
    try:
        store = open_store(request)
        return media_response(request, store.project / "data/maps/map.png", "image/png")
    except ReplayError as exc:
        return Response({"detail": str(exc)}, status=503)
