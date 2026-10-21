from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

LAYOUT_PATH = ROOT / "config" / "mosaic.yaml"


"""
모자이크 칸 배치 (config/mosaic.yaml, 모든 영상 공통).

모자이크 한 프레임 = rows x cols 칸, 칸 1개 = 카메라 1대.
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


def pixel_scale(
    cell_rect: tuple[int, int, int, int],
    reference_size,
) -> float:
    """
    칸 기준 픽셀 설정값(거리 / 이동량 / 속도)에 곱할 배율.
    reference_size [width, height] 칸에서 정한 값을 cell_rect 칸 크기에 맞춘다.
    """

    x1, y1, x2, y2 = cell_rect

    reference_width, reference_height = (
        float(value)
        for value in reference_size
    )

    return (
        (x2 - x1) / reference_width
        *
        (y2 - y1) / reference_height
    ) ** 0.5
