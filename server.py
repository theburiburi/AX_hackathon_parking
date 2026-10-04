from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


ROOT = Path(__file__).resolve().parent

WEB_DIR = ROOT / "web"
VIDEO_DIR = ROOT / "data" / "videos"
MAP_DIR = ROOT / "data" / "maps"
PARKING_DIR = ROOT / "data" / "parking"


app = FastAPI(
    title="AX Parking",
)


app.mount(
    "/web",
    StaticFiles(directory=WEB_DIR),
    name="web",
)

app.mount(
    "/media",
    StaticFiles(directory=VIDEO_DIR),
    name="media",
)

app.mount(
    "/map",
    StaticFiles(directory=MAP_DIR),
    name="map",
)

app.mount(
    "/parking",
    StaticFiles(directory=PARKING_DIR),
    name="parking",
)


@app.get("/")
def index():
    return FileResponse(
        WEB_DIR / "index.html"
    )


@app.get("/api/health")
def health():
    return {
        "status": "ok"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )