"""Daily, section-scoped vehicle bookings for the single-process local web server."""
from datetime import date
import re
from threading import RLock
from uuid import uuid4

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from . import json_store
from .views import login_required

# Serialize conflict checking and persistence across Django request threads.
_lock = RLock()


def records():
    try:
        return json_store.read("vehicle_schedules")
    except FileNotFoundError:
        return []


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValidationError("날짜를 YYYY-MM-DD 형식으로 입력하세요.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValidationError("유효한 날짜를 입력하세요.")
    return value


def minutes(value, end=False):
    if end and value == "24:00":
        return 1440
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValidationError("시간을 HH:MM 형식으로 입력하세요. 종료는 24:00까지 가능합니다.")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def visible(user, item):
    return user["role"] == "ADMIN" or item["team_id"] == user["team_id"]


def can_edit(user, item):
    return user["role"] == "ADMIN" or item["created_by"] == user["id"]


def present(user, item):
    return {**item, "can_edit": can_edit(user, item)}


def validated(data, user, old=None):
    if not isinstance(data, dict):
        raise ValidationError("운행 정보를 JSON 객체로 입력하세요.")
    vehicle = next((v for v in json_store.read("vehicles") if v["id"] == data.get("vehicle_id")), None)
    if not vehicle or not visible(user, vehicle):
        raise ValidationError("예약 가능한 소속 차량을 선택하세요.")
    driver_id = data.get("driver_id") if user["role"] == "ADMIN" else user["id"]
    if user["role"] != "ADMIN" and data.get("driver_id", user["id"]) != user["id"]:
        raise ValidationError("일반 사용자는 본인의 운행만 등록할 수 있습니다.")
    driver = next((u for u in json_store.read("users") if u["id"] == driver_id and u["role"] == "USER" and u["team_id"] == vehicle["team_id"]), None)
    if not driver:
        raise ValidationError("차량과 같은 섹션의 운전자를 선택하세요.")
    day = valid_date(data.get("date"))
    start, end = minutes(data.get("start_time")), minutes(data.get("end_time"), end=True)
    if start >= end:
        raise ValidationError("종료 시간은 시작 시간보다 늦어야 합니다. 자정을 넘는 일정은 날짜별로 나누세요.")
    text = {}
    for key, label, maximum in (("destination", "목적지", 120), ("purpose", "운행 목적", 200)):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise ValidationError(f"{label}을 1~{maximum}자로 입력하세요.")
        text[key] = value.strip()
    return {
        "id": old["id"] if old else uuid4().hex,
        "date": day, "start_time": data["start_time"], "end_time": data["end_time"],
        "vehicle_id": vehicle["id"], "vehicle_name": vehicle["name"], "plate_number": vehicle["plate_number"],
        "team_id": vehicle["team_id"], "driver_id": driver["id"], "driver_name": driver["name"],
        "created_by": old["created_by"] if old else user["id"],
        "created_at": old["created_at"] if old else timezone.now().isoformat(),
        "updated_at": timezone.now().isoformat(), **text,
    }


def conflict(candidate, bookings):
    start = minutes(candidate["start_time"])
    end = minutes(candidate["end_time"], end=True)
    for item in bookings:
        if item["id"] == candidate["id"] or item["date"] != candidate["date"]:
            continue
        if start < minutes(item["end_time"], end=True) and minutes(item["start_time"]) < end:
            if item["vehicle_id"] == candidate["vehicle_id"]:
                return "해당 시간에 차량 운행 일정이 이미 있습니다. 다른 시간을 선택하세요."
            if item["driver_id"] == candidate["driver_id"]:
                return "해당 시간에 운전자의 다른 운행 일정이 있습니다."
    return None


@api_view(["GET", "POST"])
@login_required()
def collection(request):
    user = request.auth_user
    if request.method == "GET":
        day = valid_date(request.query_params.get("date", timezone.localdate().isoformat()))
        team = request.query_params.get("team_id") if user["role"] == "ADMIN" else user["team_id"]
        def selected(item):
            return visible(user, item) and (not team or item["team_id"] == team)
        with _lock:
            bookings = [present(user, item) for item in records() if item["date"] == day and selected(item)]
        vehicles = [v for v in json_store.read("vehicles") if selected(v)]
        members = [{k: u[k] for k in ("id", "name", "team_id")} for u in json_store.read("users") if u["role"] == "USER" and selected(u)]
        return Response({"date": day, "schedules": sorted(bookings, key=lambda item: (item["start_time"], item["plate_number"])), "vehicles": vehicles, "members": members})
    with _lock:
        candidate = validated(request.data, user)
        bookings = records()
        error = conflict(candidate, bookings)
        if error:
            return Response({"detail": error}, status=409)
        bookings.append(candidate)
        json_store.write("vehicle_schedules", bookings)
    return Response(present(user, candidate), status=201)


@api_view(["PUT", "DELETE"])
@login_required()
def detail(request, schedule_id):
    user = request.auth_user
    with _lock:
        bookings = records()
        old = next((item for item in bookings if item["id"] == schedule_id and visible(user, item)), None)
        if not old:
            return Response({"detail": "일정을 찾을 수 없습니다."}, status=404)
        if not can_edit(user, old):
            return Response({"detail": "본인이 등록한 일정만 변경할 수 있습니다."}, status=403)
        if request.method == "DELETE":
            json_store.write("vehicle_schedules", [item for item in bookings if item["id"] != schedule_id])
            return Response(status=204)
        candidate = validated(request.data, user, old)
        error = conflict(candidate, bookings)
        if error:
            return Response({"detail": error}, status=409)
        json_store.write("vehicle_schedules", [candidate if item["id"] == schedule_id else item for item in bookings])
    return Response(present(user, candidate))
