"""Serve the React build from the same origin as the business/replay API."""
from pathlib import Path
import mimetypes

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse


def frontend(request, asset=""):
    root = (Path(settings.WEB_DIR) / "frontend/dist").resolve()
    path = (root / ("assets/" + asset if asset else "index.html")).resolve()
    if not path.is_relative_to(root):
        raise Http404
    if not path.is_file():
        if asset:
            raise Http404
        return HttpResponse("웹 화면 빌드가 필요합니다. web/frontend에서 npm.cmd ci 후 npm.cmd run build를 실행하세요.", status=503, content_type="text/plain; charset=utf-8")
    response = FileResponse(path.open("rb"), content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    response["Cache-Control"] = "public, max-age=31536000, immutable" if asset else "no-cache"
    return response
