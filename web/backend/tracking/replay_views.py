"""Authenticated read-only replay endpoints. Never run inference or tracking."""
from rest_framework.decorators import api_view
from rest_framework.response import Response

from replay.store import ReplayError, ReplayStore
from .media_stream import media_response
from .views import login_required


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
        return Response({"cache_id": store.manifest["cache_id"], "frames": store.frames(start, count)})
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
