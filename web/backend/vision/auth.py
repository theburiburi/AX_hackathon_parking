"""Use the parking service's signed demo session for vision administrator access."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi import HTTPException, Request

sys.dont_write_bytecode = True
backend = Path(__file__).resolve().parents[1]
if str(backend) not in sys.path:
    sys.path.insert(0, str(backend))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from tracking.views import current_user


def require_admin(request: Request):
    user = current_user(SimpleNamespace(headers=request.headers, GET=request.query_params))
    if not user:
        raise HTTPException(401, "Login required.")
    if user["role"] != "ADMIN":
        raise HTTPException(403, "Permission denied.")
    return user
