from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

LAYOUT_PATH = ROOT / "config" / "mosaic.yaml"

DETECTION_CONFIG_PATH = ROOT / "config" / "detection.yaml"

RAW_VIDEO_DIR = ROOT / "data" / "videos" / "raw"

SPLIT_VIDEO_ROOT = ROOT / "data" / "videos"

DETECTIONS_ROOT = ROOT / "data" / "detections"

# 카메라 위치는 영상과 무관하므로 calibration은 모든 원본 영상이 공유한다.
CALIBRATION_DIR = ROOT / "config" / "calibration"

VIDEO_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
)


"""
모자이크 원본 영상과 칸 배치.

- 원본       : data/videos/raw/<title>.mp4
- 칸 배치    : config/mosaic.yaml (모든 원본 영상 공통)
- 분리 영상  : data/videos/<title>/<camera_id>.mp4
- YOLO 결과  : data/detections/<title>/detections.jsonl
- calibration: config/calibration/<camera_id>.json (공통)

카메라 좌표계는 "잘라낸 칸의 왼쪽 위 = (0, 0)"인 픽셀 좌표다.
YOLO 결과, calibration, tracking이 모두 이 좌표를 사용한다.
"""


def cell_bounds(
    size: int,
    count: int,
) -> list[tuple[int, int]]:
    """
    size를 count 등분한 [start, end) 구간 목록.
    나누어떨어지지 않으면 경계를 반올림해서 전체를 빠짐없이 덮는다.
    """

    edges = [
        int(round(index * size / count))
        for index in range(count + 1)
    ]

    return [
        (
            edges[index],
            edges[index + 1],
        )
        for index in range(count)
    ]


@dataclass
class MosaicCamera:
    camera_id: str
    row: int
    col: int
    roi: tuple[int, int, int, int] | None = None


@dataclass
class MosaicLayout:
    rows: int
    cols: int
    cameras: list[MosaicCamera]

    @property
    def camera_ids(
        self,
    ) -> list[str]:

        return [
            camera.camera_id
            for camera in self.cameras
        ]

    def crop_rects(
        self,
        width: int,
        height: int,
    ) -> dict[str, tuple[int, int, int, int]]:
        """
        모자이크 해상도에서 카메라별 잘라낼 영역.
        returns: {camera_id: (x1, y1, x2, y2)}  (모자이크 픽셀 좌표)
        """

        rows = cell_bounds(height, self.rows)
        cols = cell_bounds(width, self.cols)

        rects = {}

        for camera in self.cameras:

            y1, y2 = rows[camera.row - 1]
            x1, x2 = cols[camera.col - 1]

            if camera.roi is not None:

                roi_x, roi_y, roi_w, roi_h = camera.roi

                x1, y1 = x1 + roi_x, y1 + roi_y
                x2, y2 = x1 + roi_w, y1 + roi_h

            rects[camera.camera_id] = (
                x1,
                y1,
                x2,
                y2,
            )

        return rects

    def to_dict(
        self,
    ) -> dict:

        return {
            "grid": {
                "rows": self.rows,
                "cols": self.cols,
            },
            "cameras": [
                {
                    "id": camera.camera_id,
                    "cell": [camera.row, camera.col],
                    **(
                        {"roi": list(camera.roi)}
                        if camera.roi is not None
                        else {}
                    ),
                }
                for camera in self.cameras
            ],
        }


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
    def split_dir(
        self,
    ) -> Path:

        return SPLIT_VIDEO_ROOT / self.name

    @property
    def detections_dir(
        self,
    ) -> Path:

        return DETECTIONS_ROOT / self.name

    @property
    def calibration_dir(
        self,
    ) -> Path:

        return CALIBRATION_DIR


def load_layout(
    path: Path = LAYOUT_PATH,
) -> MosaicLayout:

    if not path.exists():
        raise FileNotFoundError(
            f"Mosaic layout not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:

        data = yaml.safe_load(file) or {}

    grid = data.get("grid", {})

    rows = int(grid.get("rows", 3))
    cols = int(grid.get("cols", 3))

    cameras = []
    seen_cells = set()

    for item in data.get("cameras", []):

        row, col = (
            int(value)
            for value in item["cell"]
        )

        if not (
            1 <= row <= rows
            and
            1 <= col <= cols
        ):
            raise ValueError(
                f"{path.name}: {item['id']} cell "
                f"{[row, col]} is outside {rows}x{cols} grid"
            )

        if (row, col) in seen_cells:
            raise ValueError(
                f"{path.name}: cell {[row, col]} "
                f"is used more than once"
            )

        seen_cells.add((row, col))

        roi = item.get("roi")

        cameras.append(
            MosaicCamera(
                camera_id=str(item["id"]),
                row=row,
                col=col,
                roi=(
                    tuple(int(value) for value in roi)
                    if roi is not None
                    else None
                ),
            )
        )

    if not cameras:
        raise ValueError(
            f"{path.name}: no cameras configured"
        )

    return MosaicLayout(
        rows=rows,
        cols=cols,
        cameras=cameras,
    )


def find_raw_video(
    title: str,
) -> Path:
    """
    "test00" -> data/videos/raw/test00.mp4 (지원 확장자 중 존재하는 파일)
    """

    path = Path(title)

    if path.suffix.lower() in VIDEO_EXTENSIONS:

        title = path.stem

    for extension in VIDEO_EXTENSIONS:

        candidate = RAW_VIDEO_DIR / f"{title}{extension}"

        if candidate.exists():
            return candidate

    available = sorted(
        file.stem
        for file in RAW_VIDEO_DIR.glob("*")
        if file.suffix.lower() in VIDEO_EXTENSIONS
    )

    raise FileNotFoundError(
        f"Raw video not found: {RAW_VIDEO_DIR / title}.*\n"
        f"Available: {', '.join(available) or '(none)'}"
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
