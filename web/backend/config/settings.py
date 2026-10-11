from pathlib import Path
import os
import secrets
BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR.parent
PROJECT_DIR = WEB_DIR.parent
secret_file = WEB_DIR / ".secret-key"
if not secret_file.exists():
    secret_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
SECRET_KEY = os.environ.get("WEB_SECRET_KEY") or secret_file.read_text(encoding="utf-8").strip()
DEBUG = os.environ.get("WEB_DEBUG") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.environ.get(
    "WEB_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver"
).split(",") if host.strip()]
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.staticfiles", "rest_framework", "tracking"]
MIDDLEWARE = ["config.compression.JsonCompressionMiddleware", "django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = []
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "UNAUTHENTICATED_TOKEN": None,
}
