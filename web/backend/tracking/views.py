import hashlib
import hmac
import mimetypes
from functools import wraps
from pathlib import Path
from uuid import uuid4
from django.conf import settings
from django.core import signing
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .json_store import read, write
from .media_stream import media_response
from .project_media import selected_map, camera_media

TOKEN_SALT = "ax-vehicle-tracking.auth"

def public_user(user):
    return {key: user[key] for key in ("id", "username", "name", "role", "team_id")}

def password_matches(password, user):
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), user["password_salt"].encode("utf-8"), 390000).hex()
    return hmac.compare_digest(digest, user["password_hash"])

def current_user(request):
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else request.GET.get("token", "")
    if not token:
        return None
    try:
        payload = signing.loads(token, salt=TOKEN_SALT, max_age=60 * 60 * 8)
    except signing.BadSignature:
        return None
    return next((user for user in read("users") if user["id"] == payload.get("user_id")), None)

def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            user = current_user(request)
            if not user:
                return Response({"detail": "Login required."}, status=status.HTTP_401_UNAUTHORIZED)
            if role and user["role"] != role:
                return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
            request.auth_user = user
            return view(request, *args, **kwargs)
        return wrapped
    return decorator

@api_view(["POST"])
def login(request):
    username = str(request.data.get("username", "")).strip()
    password = str(request.data.get("password", ""))
    user = next((item for item in read("users") if item["username"] == username), None)
    if not user or not password_matches(password, user):
        return Response({"detail": "Invalid username or password."}, status=status.HTTP_401_UNAUTHORIZED)
    token = signing.dumps({"user_id": user["id"]}, salt=TOKEN_SALT, compress=True)
    return Response({"token": token, "user": public_user(user)})

@api_view(["GET"])
@login_required()
def me(request):
    return Response(public_user(request.auth_user))

def filtered(request, records):
    team_id = request.query_params.get("team_id")
    return [v for v in records if not team_id or v["team_id"] == team_id]

@api_view(["GET"])
@login_required()
def vehicles(request):
    records = read("vehicles")
    if request.auth_user["role"] == "USER":
        return Response([v for v in records if v["team_id"] == request.auth_user["team_id"]])
    return Response(filtered(request, records))

@api_view(["GET"])
@login_required()
def vehicle_detail(request, vehicle_id):
    vehicle = next((v for v in read("vehicles") if v["id"] == vehicle_id), None)
    if vehicle and request.auth_user["role"] == "USER" and vehicle["team_id"] != request.auth_user["team_id"]:
        vehicle = None
    return Response(vehicle) if vehicle else Response({"detail": "Vehicle not found"}, status=404)

@api_view(["POST"])
@login_required("ADMIN")
def create_vehicle(request):
    if any(not request.data.get(key) for key in ("plate_number", "name", "team_id")):
        return Response({"detail": "plate_number, name, team_id are required"}, status=400)
    records = read("vehicles")
    if any(v["plate_number"] == request.data["plate_number"] for v in records):
        return Response({"detail": "Duplicate plate number"}, status=409)
    vehicle = {"id": f"V-{uuid4().hex[:6].upper()}", "plate_number": request.data["plate_number"], "name": request.data["name"], "team_id": request.data["team_id"], "status": "UNKNOWN", "current_zone_id": None, "last_seen_at": None, "camera_id": None}
    records.append(vehicle); write("vehicles", records)
    return Response(vehicle, status=status.HTTP_201_CREATED)

@api_view(["GET", "POST"])
@login_required()
def vehicle_requests(request):
    if request.method == "GET":
        records = read("vehicle_requests")
        if request.auth_user["role"] != "ADMIN":
            records = [item for item in records if item["requester_id"] == request.auth_user["id"]]
        return Response(records[::-1])

    request_type = request.data.get("request_type")
    if request_type not in ("CREATE", "DELETE"):
        return Response({"detail": "request_type must be CREATE or DELETE"}, status=400)

    vehicles = read("vehicles")
    if request_type == "CREATE":
        vehicle = request.data.get("vehicle") or {}
        if any(not vehicle.get(key) for key in ("name", "plate_number", "team_id")):
            return Response({"detail": "name, plate_number, team_id are required"}, status=400)
        if request.auth_user["role"] == "USER" and vehicle["team_id"] != request.auth_user["team_id"]:
            return Response({"detail": "You can request a vehicle only for your section."}, status=403)
        if any(item["plate_number"] == vehicle["plate_number"] for item in vehicles):
            return Response({"detail": "Duplicate plate number"}, status=409)
        payload = {key: vehicle[key].strip() if isinstance(vehicle[key], str) else vehicle[key] for key in ("name", "plate_number", "team_id")}
    else:
        vehicle_id = request.data.get("vehicle_id")
        target = next((item for item in vehicles if item["id"] == vehicle_id), None)
        if not target:
            return Response({"detail": "Vehicle not found"}, status=404)
        if request.auth_user["role"] == "USER" and target["team_id"] != request.auth_user["team_id"]:
            return Response({"detail": "You can request deletion only for your section."}, status=403)
        payload = {"vehicle_id": target["id"], "vehicle_name": target["name"], "plate_number": target["plate_number"], "team_id": target["team_id"]}

    item = {
        "id": f"R-{uuid4().hex[:8].upper()}",
        "request_type": request_type,
        "status": "PENDING",
        "requester_id": request.auth_user["id"],
        "requester_name": request.auth_user["name"],
        "requested_at": timezone.now().isoformat(),
        "payload": payload,
        "decision_at": None,
        "reviewer_name": None,
        "rejection_reason": None,
    }
    records = read("vehicle_requests")
    records.append(item)
    write("vehicle_requests", records)
    return Response(item, status=status.HTTP_201_CREATED)

@api_view(["POST"])
@login_required("ADMIN")
def decide_vehicle_request(request, request_id):
    decision = request.data.get("decision")
    if decision not in ("APPROVED", "REJECTED"):
        return Response({"detail": "decision must be APPROVED or REJECTED"}, status=400)
    records = read("vehicle_requests")
    item = next((record for record in records if record["id"] == request_id), None)
    if not item:
        return Response({"detail": "Request not found"}, status=404)
    if item["status"] != "PENDING":
        return Response({"detail": "This request has already been processed."}, status=409)
    if decision == "REJECTED" and not str(request.data.get("rejection_reason", "")).strip():
        return Response({"detail": "A rejection reason is required."}, status=400)

    if decision == "APPROVED":
        vehicles = read("vehicles")
        if item["request_type"] == "CREATE":
            if any(vehicle["plate_number"] == item["payload"]["plate_number"] for vehicle in vehicles):
                return Response({"detail": "Duplicate plate number"}, status=409)
            vehicles.append({
                "id": f"V-{uuid4().hex[:6].upper()}",
                **item["payload"],
                "status": "UNKNOWN", "current_zone_id": None, "last_seen_at": None, "camera_id": None,
            })
        else:
            if not any(vehicle["id"] == item["payload"]["vehicle_id"] for vehicle in vehicles):
                return Response({"detail": "Vehicle was already deleted."}, status=409)
            vehicles = [vehicle for vehicle in vehicles if vehicle["id"] != item["payload"]["vehicle_id"]]
        write("vehicles", vehicles)

    item.update({
        "status": decision,
        "decision_at": timezone.now().isoformat(),
        "reviewer_name": request.auth_user["name"],
        "rejection_reason": str(request.data.get("rejection_reason", "")).strip() if decision == "REJECTED" else None,
    })
    write("vehicle_requests", records)
    return Response(item)

@api_view(["GET"])
@login_required()
def parking_zones(request): return Response(read("parking_zones"))

@api_view(["GET"])
@login_required("ADMIN")
def tracking_logs(request): return Response(read("tracking_logs")[-100:][::-1])

MEDIA_DIR = Path(settings.BASE_DIR) / "media"
CAMERA_IDS = ("01", "02", "03", "05", "06", "07", "08")
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v", ".avi"}
MAP_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg"}

def first_media(directory, suffixes):
    if not directory.exists():
        return None
    return next((item for item in sorted(directory.iterdir()) if item.is_file() and item.suffix.lower() in suffixes), None)

@api_view(["GET"])
@login_required()
def parking_map(request):
    image = selected_map(MEDIA_DIR, first_media, MAP_SUFFIXES)
    return Response({
        "layout": read("map_layout"),
        "map": {"filename": image.name, "url": "/parking-map/image/"} if image else None,
    })

@api_view(["GET", "HEAD"])
@login_required()
def parking_map_image(request):
    image = selected_map(MEDIA_DIR, first_media, MAP_SUFFIXES)
    if image is None:
        return Response({"detail": "Map not found"}, status=404)
    return media_response(request, image, mimetypes.guess_type(image.name)[0] or "application/octet-stream")

@api_view(["GET"])
@login_required("ADMIN")
def media_manifest(request):
    cameras = []
    for camera, video in camera_media(MEDIA_DIR, first_media, VIDEO_SUFFIXES):
        camera_id = camera.camera_id
        cameras.append({
            "id": camera_id,
            "name": f"CCTV {camera_id}",
            "fps": camera.fps,
            "offset_seconds": camera.offset_seconds,
            "filename": video.name if video else None,
            "url": f"/admin/media/cctv/{camera_id}/{video.name}" if video else None,
        })
    parking_map = selected_map(MEDIA_DIR, first_media, MAP_SUFFIXES)
    return Response({
        "cameras": cameras,
        "layout": read("map_layout"),
        "map": ({"filename": parking_map.name, "url": f"/admin/media/maps/map/{parking_map.name}"} if parking_map else None),
    })

@api_view(["GET", "HEAD"])
@login_required("ADMIN")
def media_file(request, category, item_id, filename):
    if category == "cctv":
        video = next((video for camera, video in camera_media(MEDIA_DIR, first_media, VIDEO_SUFFIXES)
                      if camera.camera_id == item_id), None)
        if video is None or filename != video.name:
            return Response({"detail": "Media not found"}, status=404)
        target = video
    elif category == "maps" and item_id == "map":
        target = selected_map(MEDIA_DIR, first_media, MAP_SUFFIXES)
        if target is None or filename != target.name:
            return Response({"detail": "Media not found"}, status=404)
    else:
        return Response({"detail": "Media not found"}, status=404)
    if not target.is_file():
        return Response({"detail": "Media not found"}, status=404)
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return media_response(request, target, content_type)

@api_view(["POST"])
@login_required("ADMIN")
def tracking_event(request):
    if any(not request.data.get(key) for key in ("plate_number", "camera_id", "zone_id")):
        return Response({"detail": "plate_number, camera_id, zone_id are required"}, status=400)
    aliases = {"A-01": "P1", "A-02": "P2", "B-01": "P3", "B-02": "P4"}
    zone_id = str(request.data["zone_id"])
    zone_id = aliases.get(zone_id, zone_id)
    if zone_id not in {f"P{number}" for number in range(1, 8)}:
        return Response({"detail": "zone_id must be P1 through P7."}, status=400)
    position = request.data.get("map_position")
    if position is not None:
        if (not isinstance(position, dict)
            or position.get("map_id") != read("map_layout")["map_id"]
            or any(type(position.get(axis)) not in (int, float) or not 0 <= position[axis] <= 100 for axis in ("x", "y"))):
            return Response({"detail": "map_position requires the configured map_id and x/y numbers between 0 and 100."}, status=400)
        position = {key: position[key] for key in ("map_id", "x", "y")}
    records = read("vehicles")
    vehicle = next((v for v in records if v["plate_number"] == request.data["plate_number"]), None)
    if not vehicle: return Response({"detail": "Vehicle not registered"}, status=404)
    detected_at = request.data.get("detected_at") or timezone.now().isoformat()
    vehicle.update({"current_zone_id": zone_id, "camera_id": request.data["camera_id"], "last_seen_at": detected_at, "status": request.data.get("status", "PARKED"), "map_position": position})
    write("vehicles", records)
    logs = read("tracking_logs")
    event = {"id": f"E-{uuid4().hex[:8].upper()}", "vehicle_id": vehicle["id"], "plate_number": vehicle["plate_number"], "camera_id": vehicle["camera_id"], "zone_id": vehicle["current_zone_id"], "status": vehicle["status"], "confidence": request.data.get("confidence"), "detected_at": detected_at}
    event["map_position"] = position
    logs.append(event); write("tracking_logs", logs)
    return Response(event, status=status.HTTP_201_CREATED)
