import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

import cv2
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .processor import process_frame
from .auth import require_admin
from .live import LiveDetection

live = LiveDetection()

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
jobs = {}
lock = Lock()
pool = ThreadPoolExecutor(max_workers=1)
MAX_BYTES = 500 * 1024 * 1024


@asynccontextmanager
async def lifespan(app):
    yield
    live.close()
    pool.shutdown(wait=True)


app = FastAPI(title="Video Vision Workspace", lifespan=lifespan)


def update(job_id, **fields):
    with lock:
        jobs[job_id].update(fields)


def process_video(job_id, source, folder):
    capture = cv2.VideoCapture(str(source))
    writer = None
    try:
        update(job_id, status="processing")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = 30.0
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        update(job_id, total_frames=total)
        count = 0
        with (folder / "analysis.jsonl").open("w", encoding="utf-8") as report:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if writer is None:
                    height, width = frame.shape[:2]
                    writer = cv2.VideoWriter(str(folder / "processed.avi"),
                                             cv2.VideoWriter_fourcc(*"MJPG"), fps,
                                             (width, height))
                    if not writer.isOpened():
                        raise ValueError("결과 동영상 인코더를 열 수 없습니다.")
                output, analysis = process_frame(frame, count, count / fps)
                if output.shape != frame.shape or output.dtype != frame.dtype:
                    raise ValueError("process_frame 출력 크기와 자료형은 입력과 같아야 합니다.")
                writer.write(output)
                report.write(json.dumps(analysis, ensure_ascii=False, allow_nan=False) + "\n")
                if count == 0 and not cv2.imwrite(str(folder / "preview.jpg"), output):
                    raise ValueError("미리보기 저장에 실패했습니다.")
                count += 1
                if count % 10 == 0:
                    update(job_id, processed_frames=count)
        if count == 0:
            raise ValueError("동영상 프레임을 읽을 수 없습니다. 파일 또는 코덱을 확인하세요.")
        writer.release()
        writer = None
        update(job_id, status="completed", processed_frames=count,
               result_url=f"/api/jobs/{job_id}/files/processed.avi",
               analysis_url=f"/api/jobs/{job_id}/files/analysis.jsonl",
               preview_url=f"/api/jobs/{job_id}/files/preview.jpg")
    except Exception as exc:
        logging.exception("Video processing failed: %s", job_id)
        update(job_id, status="failed", error=str(exc))
    finally:
        capture.release()
        if writer is not None:
            writer.release()


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/live", dependencies=[Depends(require_admin)])
def live_snapshot():
    return live.get()


@app.post("/api/live/start", dependencies=[Depends(require_admin)])
def start_live():
    return live.get(retry=True)


@app.post("/api/videos", status_code=202, dependencies=[Depends(require_admin)])
def upload_video(file: UploadFile):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}:
        file.file.close()
        raise HTTPException(400, "지원 확장자: mp4, avi, mov, mkv, webm, m4v")
    job_id = str(uuid4())
    with lock:
        if sum(j["status"] in {"uploading", "queued", "processing"} for j in jobs.values()) >= 5:
            file.file.close()
            raise HTTPException(429, "작업 대기열이 가득 찼습니다. 잠시 후 다시 시도하세요.")
        jobs[job_id] = {"id": job_id, "filename": file.filename,
                        "status": "uploading", "processed_frames": 0, "total_frames": 0}
    folder = DATA / job_id
    source = folder / ("source" + suffix)
    try:
        folder.mkdir()
        size = 0
        with source.open("wb") as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, "최대 업로드 크기는 500MB입니다.")
                target.write(chunk)
        capture = cv2.VideoCapture(str(source))
        try:
            readable, _ = capture.read()
        finally:
            capture.release()
        if not readable:
            raise HTTPException(400, "읽을 수 없는 동영상입니다. 파일 또는 코덱을 확인하세요.")
        update(job_id, status="queued")
        pool.submit(process_video, job_id, source, folder)
        return {"id": job_id, "status_url": f"/api/jobs/{job_id}"}
    except Exception:
        source.unlink(missing_ok=True)
        if folder.exists():
            folder.rmdir()
        with lock:
            jobs.pop(job_id, None)
        raise
    finally:
        file.file.close()


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_admin)])
def get_job(job_id: UUID):
    with lock:
        job = jobs.get(str(job_id))
        if job is None:
            raise HTTPException(404, "작업을 찾을 수 없습니다. 서버 재시작 시 작업 목록은 초기화됩니다.")
        return dict(job)


@app.get("/api/jobs/{job_id}/files/{filename}", dependencies=[Depends(require_admin)])
def download(job_id: UUID, filename: str):
    if filename not in {"processed.avi", "analysis.jsonl", "preview.jpg"}:
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    job = get_job(job_id)
    if job["status"] != "completed":
        raise HTTPException(409, "처리가 아직 완료되지 않았습니다.")
    path = DATA / str(job_id) / filename
    if filename == "preview.jpg":
        return FileResponse(path, media_type="image/jpeg")
    return FileResponse(path, filename=filename)
