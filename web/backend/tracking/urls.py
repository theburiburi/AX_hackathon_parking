from django.urls import path
from . import views
urlpatterns = [
    path("auth/login/", views.login), path("auth/me/", views.me),
    path("vehicles/", views.vehicles), path("vehicles/<str:vehicle_id>/", views.vehicle_detail),
    path("admin/vehicles/", views.create_vehicle), path("parking-zones/", views.parking_zones),
    path("vehicle-requests/", views.vehicle_requests),
    path("admin/vehicle-requests/<str:request_id>/decision/", views.decide_vehicle_request),
    path("tracking-logs/", views.tracking_logs), path("tracking-events/", views.tracking_event),
    path("admin/media/", views.media_manifest),
    path("parking-map/", views.parking_map),
    path("parking-map/image/", views.parking_map_image),
    path("admin/media/<str:category>/<str:item_id>/<str:filename>", views.media_file),
]
