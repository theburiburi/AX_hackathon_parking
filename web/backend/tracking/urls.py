from django.urls import path
from . import views, schedules, replay_views
urlpatterns = [
    path("replay/manifest/", replay_views.manifest),
    path("replay/vehicle-state/", replay_views.vehicle_state),
    path("replay/demo-state/", replay_views.demo_state),
    path("replay/frames/", replay_views.frames),
    path("replay/paths/", replay_views.paths),
    path("replay/video/", replay_views.video),
    path("replay/map/", replay_views.map_image),
    path("vehicle-schedules/", schedules.collection),
    path("vehicle-schedules/<str:schedule_id>/", schedules.detail),
    path("auth/login/", views.login), path("auth/me/", views.me),
    path("vehicles/", views.vehicles), path("vehicles/<str:vehicle_id>/", views.vehicle_detail),
    path("admin/vehicles/", views.create_vehicle), path("parking-zones/", views.parking_zones),
    path("tracking-logs/", views.tracking_logs), path("tracking-events/", views.tracking_event),
    path("parking-map/", views.parking_map),
    path("parking-map/image/", views.parking_map_image),
]
