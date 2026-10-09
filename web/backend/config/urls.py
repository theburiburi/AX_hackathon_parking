from django.urls import include, path
from .frontend import frontend
urlpatterns = [path("api/", include("tracking.urls")), path("", frontend), path("assets/<path:asset>", frontend)]
