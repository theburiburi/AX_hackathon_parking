from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml

from src.mosaic import MosaicLayout, load_layout


ROOT = Path(__file__).resolve().parents[1]

# YOLO 설정 + 기본 영상 제목 (video)
DETECTION_CONFIG_PATH = ROOT / "config" / "detection.yaml"

DATA_ROOT = ROOT / "data"

# 원본 모자이크: data/raw_video/<title>.mp4 (파일 = 영상)
RAW_VIDEO_DIR = DATA_ROOT / "raw_video"

# BEV 지도, 주차 구역 (모든 영상 공통)
MAP_DIR = DATA_ROOT / "maps"

# 카메라 위치는 영상과 무관하므로 calibration은 모든 원본 영상이 공유한다.
#   config/calibration/<camera_id>.json
CALIBRATION_ROOT = ROOT / "config" / "calibration"

# 모든 영상은 30 fps로 다룬다 (프레임 번호 <-> 시각, tracker 시간 기준).
VIDEO_FPS = 30.0

VIDEO_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
)


"""
영상 1개와 그 데이터 경로.

data/raw_video/<title>.mp4   모자이크 원본

data/<title>/                스크립트가 만드는 결과
  mosaic.mp4         칸 좌우 여백을 없애고 늘린 모자이크 (웹 재생용, 00_prepare_video.py)
  cams/<camera>.mp4  여백을 없앤 분리 영상 (00_prepare_video.py)
  content.jsonl      프레임별 원래 화면 가로 범위 (00_prepare_video.py)
  detections.jsonl   YOLO 결과 (01_detect_vehicles.py)
  metadata.json      전처리 / 검출 조건
  gate_log.json      차단기 입출차 기록 (선택)

- 칸 배치    : config/mosaic.yaml (src/mosaic.py)
- calibration: config/calibration/<camera_id>.json (공통)
- fps        : 30 고정 (VIDEO_FPS)
"""


@dataclass
class MosaicVideo:
    """
    원본 모자이크 영상 1개 (제목 = 파일 이름에서 확장자를 뺀 것).
    """

    name: str
    video_path: Path
    layout: MosaicLayout

    @property
    def rows(
        self,
    ) -> int:

        return self.layout.rows

    @property
    def cols(
        self,
    ) -> int:

        return self.layout.cols

    @property
    def camera_ids(
        self,
    ) -> list[str]:

        return self.layout.camera_ids

    def crop_rects(
        self,
        width: int,
        height: int,
    ) -> dict[str, tuple[int, int, int, int]]:

        return self.layout.crop_rects(
            width,
            height,
        )

    @property
    def data_dir(
        self,
    ) -> Path:

        return DATA_ROOT / self.name

    @property
    def split_dir(
        self,
    ) -> Path:

        return self.data_dir / "cams"

    @property
    def detections_dir(
        self,
    ) -> Path:

        # detections.jsonl, metadata.json
        return self.data_dir

    @cached_property
    def video_size(
        self,
    ) -> tuple[int, int]:
        """
        원본 모자이크 (가로, 세로).
        """

        import cv2

        capture = cv2.VideoCapture(
            str(self.video_path)
        )

        size = (
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

        capture.release()

        if size[0] <= 0 or size[1] <= 0:
            raise RuntimeError(
                f"Failed to read video size: {self.video_path}"
            )

        return size

    @property
    def cell_rects(
        self,
    ) -> dict[str, tuple[int, int, int, int]]:
        """
        카메라별 칸 영역 {camera_id: (x1, y1, x2, y2)} (모자이크 픽셀 좌표).
        원본과 mosaic.mp4 는 같은 해상도다.
        """

        return self.crop_rects(
            *self.video_size
        )

    @property
    def calibration_dir(
        self,
    ) -> Path:
        """
        calibration 폴더 (config/calibration/, 모든 영상 공통).
        """

        return CALIBRATION_ROOT

    @property
    def gate_log_path(
        self,
    ) -> Path:

        return self.data_dir / "gate_log.json"

    @property
    def mosaic_path(
        self,
    ) -> Path:
        """
        칸 좌우 여백을 없애고 늘린 모자이크 (웹 재생, 확인용 이미지 배경).
        """

        return self.data_dir / "mosaic.mp4"

    @property
    def content_path(
        self,
    ) -> Path:

        return self.data_dir / "content.jsonl"

    @property
    def metadata_path(
        self,
    ) -> Path:

        return self.data_dir / "metadata.json"


def display_path(
    path: Path,
) -> str:
    """
    출력용 경로 (프로젝트 폴더 안이면 상대 경로).
    """

    try:
        return str(Path(path).relative_to(ROOT))

    except ValueError:
        return str(path)


def find_raw_video(
    title: str,
) -> Path:
    """
    "test00" -> data/raw_video/test00.mp4 (지원 확장자 중 존재하는 파일)
    """

    title = Path(title).stem

    for extension in VIDEO_EXTENSIONS:

        candidate = RAW_VIDEO_DIR / f"{title}{extension}"

        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Raw video not found: {RAW_VIDEO_DIR / title}.*\n"
        f"Available: {', '.join(available_titles()) or '(none)'}"
    )


def available_titles() -> list[str]:
    """
    data/raw_video/ 의 영상 파일 이름(확장자 제외) 목록.
    """

    if not RAW_VIDEO_DIR.is_dir():
        return []

    return sorted(
        file.stem
        for file in RAW_VIDEO_DIR.iterdir()
        if file.suffix.lower() in VIDEO_EXTENSIONS
    )


def load_video(
    title: str,
) -> MosaicVideo:

    raw_path = find_raw_video(
        title
    )

    return MosaicVideo(
        name=raw_path.stem,
        video_path=raw_path,
        layout=load_layout(),
    )


def default_title() -> str | None:
    """
    config/detection.yaml 의 video 값 (server / calibrate / play 기본값).
    """

    if not DETECTION_CONFIG_PATH.exists():
        return None

    with DETECTION_CONFIG_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:

        data = yaml.safe_load(file) or {}

    value = data.get("video")

    return str(value) if value else None
