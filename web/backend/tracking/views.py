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
from .project_media import selected_map, map_layout

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

@api_view(["GET"])
@login_required()
def parking_zones(request):
    # Geometry belongs to the model project. Keep only web-specific metadata
    # from the demo catalog; do not maintain a second set of zone coordinates.
    catalog = {zone["id"]: zone for zone in read("parking_zones")}
    zones = current_map_layout().get("zones", [])
    return Response([{**catalog.get(zone["id"], {}), "id": zone["id"],
                      "name": zone.get("name", zone["id"]),
                      "capacity": zone.get("capacity"),
                      "x": zone["label"][0], "y": zone["label"][1]}
                     for zone in zones])

@api_view(["GET"])
@login_required("ADMIN")
def tracking_logs(request): return Response(read("tracking_logs")[-100:][::-1])

MEDIA_DIR = Path(settings.BASE_DIR) / "media"
MAP_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg"}

def first_media(directory, suffixes):
    if not directory.exists():
        return None
    return next((item for item in sorted(directory.iterdir()) if item.is_file() and item.suffix.lower() in suffixes), None)

def current_map_layout():
    image = selected_map(MEDIA_DIR, first_media, MAP_SUFFIXES)
    return map_layout(image, read("map_layout"))

@api_view(["GET"])
@login_required()
def parking_map(request):
    image = selected_map(MEDIA_DIR, first_media, MAP_SUFFIXES)
    return Response({
        "layout": map_layout(image, read("map_layout")),
        "map": {"filename": image.name, "url": "/parking-map/image/"} if image else None,
    })

@api_view(["GET", "HEAD"])
@login_required()
def parking_map_image(request):
    image = selected_map(MEDIA_DIR, first_media, MAP_SUFFIXES)
    if image is None:
        return Response({"detail": "Map not found"}, status=404)
    return media_response(request, image, mimetypes.guess_type(image.name)[0] or "application/octet-stream")

@api_view(["POST"])
@login_required("ADMIN")
def tracking_event(request):
    if any(not request.data.get(key) for key in ("plate_number", "camera_id", "zone_id")):
        return Response({"detail": "plate_number, camera_id, zone_id are required"}, status=400)
    zone_id = str(request.data["zone_id"])
    layout = current_map_layout()
    if zone_id not in {zone["id"] for zone in layout.get("zones", [])}:
        return Response({"detail": "zone_id must be a configured map zone."}, status=400)
    position = request.data.get("map_position")
    if position is not None:
        if (not isinstance(position, dict)
            or position.get("map_id") != layout["map_id"]
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
