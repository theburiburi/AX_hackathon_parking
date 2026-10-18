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
from .parking_state import plate_key, zone_occupancy, occupancy_deltas

TOKEN_SALT = "ax-vehicle-tracking.auth"

def public_user(user):
    return {key: user[key] for key in ("id", "name", "role", "team_id", "team_name")}

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
    if not isinstance(request.data, dict):
        return Response({"detail": "Invalid ID or password."}, status=status.HTTP_401_UNAUTHORIZED)
    user_id = request.data.get("id", "")
    password = request.data.get("password", "")
    if not isinstance(user_id, str) or not isinstance(password, str) or not user_id.strip() or not password:
        return Response({"detail": "Invalid ID or password."}, status=status.HTTP_401_UNAUTHORIZED)
    user = next((item for item in read("users")
                 if item["id"] == user_id.strip() and item["password"] == password), None)
    if not user:
        return Response({"detail": "Invalid ID or password."}, status=status.HTTP_401_UNAUTHORIZED)
    token = signing.dumps({"user_id": user["id"]}, salt=TOKEN_SALT, compress=True)
    return Response({"token": token, "user": public_user(user)})

@api_view(["GET"])
@login_required()
def me(request):
    return Response(public_user(request.auth_user))

def filtered(request, records):
    team_id = request.query_params.get("team_id")
    return [v for v in records if not team_id or v["team_id"] == team_id]

def current_vehicles():
    records = read("vehicles")
    from replay.vehicle_state import apply_snapshot
    try:
        snapshot = read("vehicle_replay_state")
    except FileNotFoundError:
        return records
    return apply_snapshot(records, snapshot)

@api_view(["GET"])
@login_required()
def vehicles(request):
    records = current_vehicles()
    if request.auth_user["role"] == "USER":
        return Response([v for v in records if v["team_id"] == request.auth_user["team_id"]])
    return Response(filtered(request, records))

@api_view(["GET"])
@login_required()
def vehicle_detail(request, vehicle_id):
    vehicle = next((v for v in current_vehicles() if v["id"] == vehicle_id), None)
    if vehicle and request.auth_user["role"] == "USER" and vehicle["team_id"] != request.auth_user["team_id"]:
        vehicle = None
    return Response(vehicle) if vehicle else Response({"detail": "Vehicle not found"}, status=404)

@api_view(["POST"])
@login_required("ADMIN")
def create_vehicle(request):
    if any(not request.data.get(key) for key in ("plate_number", "name", "team_id")):
        return Response({"detail": "plate_number, name, team_id are required"}, status=400)
    records = read("vehicles")
    if any(plate_key(v["plate_number"]) == plate_key(request.data["plate_number"]) for v in records):
        return Response({"detail": "Duplicate plate number"}, status=409)
    vehicle = {"id": f"V-{uuid4().hex[:6].upper()}", "plate_number": request.data["plate_number"], "name": request.data["name"], "team_id": request.data["team_id"], "status": "UNKNOWN", "current_zone_id": None, "last_seen_at": None, "camera_id": None}
    records.append(vehicle); write("vehicles", records)
    return Response(vehicle, status=status.HTTP_201_CREATED)

@api_view(["GET"])
@login_required()
def parking_zones(request):
    try:
        return Response(current_parking_zones())
    except (OSError, ValueError) as exc:
        return Response({"detail": f"initial_parking.json: {exc}"}, status=503)


def current_parking_zones(vehicles=None, snapshot=None):
    # Geometry belongs to the model project. Keep only web-specific metadata
    # from the demo catalog; do not maintain a second set of zone coordinates.
    catalog = {zone["id"]: zone for zone in read("parking_zones")}
    zones = current_map_layout().get("zones", [])
    try:
        inventory = read("initial_parking")
    except FileNotFoundError:
        inventory = []
    # Validate the baseline before reading any derived state.
    zone_occupancy(inventory, zones)
    if vehicles is None:
        try:
            vehicles = read("vehicles")
        except FileNotFoundError:
            vehicles = []
    if snapshot is None:
        try:
            snapshot = read("vehicle_replay_state")
        except FileNotFoundError:
            snapshot = {}
    counts = zone_occupancy(inventory, zones, occupancy_deltas(vehicles, snapshot))
    return [{**catalog.get(zone["id"], {}), **counts[zone["id"]], "id": zone["id"],
             "name": zone.get("name", zone["id"]),
             "x": zone["label"][0], "y": zone["label"][1]}
            for zone in zones]

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
    vehicle = next((v for v in records if plate_key(v["plate_number"]) == plate_key(request.data["plate_number"])), None)
    if not vehicle: return Response({"detail": "Vehicle not registered"}, status=404)
    detected_at = request.data.get("detected_at") or timezone.now().isoformat()
    if "parking_baseline_zone_id" not in vehicle:
        from replay.vehicle_state import apply_snapshot
        try:
            snapshot = read("vehicle_replay_state")
        except FileNotFoundError:
            snapshot = {}
        previous = apply_snapshot([vehicle], snapshot)[0]
        origin = previous.get("current_zone_id") if previous.get("status") == "PARKED" else None
        vehicle.update(parking_baseline_zone_id=origin, parking_counted_zone_id=origin)
    event_status = request.data.get("status", "PARKED")
    if event_status == "PARKED":
        vehicle["parking_counted_zone_id"] = zone_id
    elif event_status in ("MOVING", "EXITED"):
        vehicle["parking_counted_zone_id"] = None
    # The native model reports parking state, but does not classify double parking.
    same_parking = vehicle.get("status") == "PARKED" and vehicle.get("current_zone_id") == zone_id
    parked = request.data.get("status", "PARKED") == "PARKED"
    vehicle.update(parking_type=vehicle.get("parking_type", "UNKNOWN") if parked and same_parking else "UNKNOWN" if parked else None,
                   parking_space_id=vehicle.get("parking_space_id") if parked and same_parking else None)
    vehicle.update({"current_zone_id": zone_id, "camera_id": request.data["camera_id"], "last_seen_at": detected_at, "status": request.data.get("status", "PARKED"), "map_position": position})
    write("vehicles", records)
    logs = read("tracking_logs")
    event = {"id": f"E-{uuid4().hex[:8].upper()}", "vehicle_id": vehicle["id"], "plate_number": vehicle["plate_number"], "camera_id": vehicle["camera_id"], "zone_id": vehicle["current_zone_id"], "status": vehicle["status"], "confidence": request.data.get("confidence"), "detected_at": detected_at}
    event["map_position"] = position
    logs.append(event); write("tracking_logs", logs)
    return Response(event, status=status.HTTP_201_CREATED)
