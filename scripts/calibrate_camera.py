from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from src.mosaic import default_title, load_video  # noqa: E402
from src.calibration.mapping import (  # noqa: E402
    CalibrationMapping,
    apply_homography,
    coverage_grid,
)


DETECTION_CONFIG_PATH = (
    ROOT
    / "config"
    / "detection.yaml"
)

BEV_MAP_PATH = (
    ROOT
    / "data"
    / "maps"
    / "map.png"
)


IMAGE_WINDOW = "Camera Image"
BEV_WINDOW = "BEV Map"


IMAGE_DISPLAY_MAX_WIDTH = 940
IMAGE_DISPLAY_MAX_HEIGHT = 650

BEV_DISPLAY_MAX_WIDTH = 900
BEV_DISPLAY_MAX_HEIGHT = 650


ZOOM_STEP = 1.25
MIN_ZOOM = 1.0
MAX_ZOOM = 20.0


# coverage heatmap: 이 confidence 미만인 영역만 붉게 표시한다.
COVERAGE_GRID_STEP = 40
COVERAGE_LOW_THRESHOLD = 0.5
COVERAGE_MAX_ALPHA = 0.30

# BEV 예측 마커 색 (BGR). 확정 점(빨강)과 구분한다.
PREDICT_COLOR = (0, 255, 0)


@dataclass
class ViewState:
    image: np.ndarray

    display_width: int
    display_height: int

    zoom: float = 1.0

    pan_x: float = 0.0
    pan_y: float = 0.0

    dragging: bool = False

    last_mouse_x: int = 0
    last_mouse_y: int = 0

    @property
    def image_height(
        self,
    ) -> int:

        return self.image.shape[0]

    @property
    def image_width(
        self,
    ) -> int:

        return self.image.shape[1]

    @property
    def viewport_width(
        self,
    ) -> float:

        return (
            self.image_width
            /
            self.zoom
        )

    @property
    def viewport_height(
        self,
    ) -> float:

        return (
            self.image_height
            /
            self.zoom
        )

    def clamp_pan(
        self,
    ) -> None:

        max_x = max(
            0.0,
            self.image_width
            -
            self.viewport_width,
        )

        max_y = max(
            0.0,
            self.image_height
            -
            self.viewport_height,
        )

        self.pan_x = float(
            np.clip(
                self.pan_x,
                0.0,
                max_x,
            )
        )

        self.pan_y = float(
            np.clip(
                self.pan_y,
                0.0,
                max_y,
            )
        )

    def display_to_original(
        self,
        x: int,
        y: int,
    ) -> tuple[
        float,
        float,
    ]:

        normalized_x = (
            x
            /
            self.display_width
        )

        normalized_y = (
            y
            /
            self.display_height
        )

        original_x = (
            self.pan_x
            +
            normalized_x
            *
            self.viewport_width
        )

        original_y = (
            self.pan_y
            +
            normalized_y
            *
            self.viewport_height
        )

        original_x = float(
            np.clip(
                original_x,
                0,
                self.image_width - 1,
            )
        )

        original_y = float(
            np.clip(
                original_y,
                0,
                self.image_height - 1,
            )
        )

        return (
            original_x,
            original_y,
        )

    def original_to_display(
        self,
        point: tuple[
            float,
            float,
        ],
    ) -> (
        tuple[int, int]
        | None
    ):

        x, y = point

        viewport_x2 = (
            self.pan_x
            +
            self.viewport_width
        )

        viewport_y2 = (
            self.pan_y
            +
            self.viewport_height
        )

        if (
            x < self.pan_x
            or
            x > viewport_x2
            or
            y < self.pan_y
            or
            y > viewport_y2
        ):
            return None

        display_x = (
            (
                x
                -
                self.pan_x
            )
            /
            self.viewport_width
            *
            self.display_width
        )

        display_y = (
            (
                y
                -
                self.pan_y
            )
            /
            self.viewport_height
            *
            self.display_height
        )

        return (
            int(
                round(
                    display_x
                )
            ),
            int(
                round(
                    display_y
                )
            ),
        )

    def zoom_at(
        self,
        mouse_x: int,
        mouse_y: int,
        direction: int,
    ) -> None:

        original_x, original_y = (
            self.display_to_original(
                mouse_x,
                mouse_y,
            )
        )

        old_zoom = (
            self.zoom
        )

        if direction > 0:

            new_zoom = (
                old_zoom
                *
                ZOOM_STEP
            )

        else:

            new_zoom = (
                old_zoom
                /
                ZOOM_STEP
            )

        new_zoom = float(
            np.clip(
                new_zoom,
                MIN_ZOOM,
                MAX_ZOOM,
            )
        )

        if (
            abs(
                new_zoom
                -
                old_zoom
            )
            <
            1e-9
        ):
            return

        normalized_x = (
            mouse_x
            /
            self.display_width
        )

        normalized_y = (
            mouse_y
            /
            self.display_height
        )

        self.zoom = (
            new_zoom
        )

        new_viewport_width = (
            self.viewport_width
        )

        new_viewport_height = (
            self.viewport_height
        )

        self.pan_x = (
            original_x
            -
            normalized_x
            *
            new_viewport_width
        )

        self.pan_y = (
            original_y
            -
            normalized_y
            *
            new_viewport_height
        )

        self.clamp_pan()

    def start_drag(
        self,
        x: int,
        y: int,
    ) -> None:

        self.dragging = True

        self.last_mouse_x = x
        self.last_mouse_y = y

    def drag(
        self,
        x: int,
        y: int,
    ) -> None:

        if not self.dragging:
            return

        dx = (
            x
            -
            self.last_mouse_x
        )

        dy = (
            y
            -
            self.last_mouse_y
        )

        original_dx = (
            dx
            /
            self.display_width
            *
            self.viewport_width
        )

        original_dy = (
            dy
            /
            self.display_height
            *
            self.viewport_height
        )

        self.pan_x -= (
            original_dx
        )

        self.pan_y -= (
            original_dy
        )

        self.clamp_pan()

        self.last_mouse_x = x
        self.last_mouse_y = y

    def end_drag(
        self,
    ) -> None:

        self.dragging = False

    def render(
        self,
    ) -> np.ndarray:

        self.clamp_pan()

        x1 = int(
            round(
                self.pan_x
            )
        )

        y1 = int(
            round(
                self.pan_y
            )
        )

        viewport_width = int(
            round(
                self.viewport_width
            )
        )

        viewport_height = int(
            round(
                self.viewport_height
            )
        )

        viewport_width = max(
            2,
            min(
                viewport_width,
                self.image_width,
            ),
        )

        viewport_height = max(
            2,
            min(
                viewport_height,
                self.image_height,
            ),
        )

        x2 = (
            x1
            +
            viewport_width
        )

        y2 = (
            y1
            +
            viewport_height
        )

        if x2 > self.image_width:

            x2 = (
                self.image_width
            )

            x1 = (
                x2
                -
                viewport_width
            )

        if y2 > self.image_height:

            y2 = (
                self.image_height
            )

            y1 = (
                y2
                -
                viewport_height
            )

        x1 = max(
            0,
            x1,
        )

        y1 = max(
            0,
            y1,
        )

        crop = self.image[
            y1:y2,
            x1:x2,
        ]

        rendered = cv2.resize(
            crop,
            (
                self.display_width,
                self.display_height,
            ),
            interpolation=cv2.INTER_LINEAR,
        )

        return rendered


class CalibrationTool:
    def __init__(
        self,
        camera_id: str,
        frame_index: int,
        video_title: str | None = None,
    ):
        self.camera_id = (
            camera_id
        )

        self.frame_index = (
            frame_index
        )

        # 원본 모자이크 영상에서 해당 카메라 칸을 잘라 사용하고,
        # 결과는 config/calibration/<camera>.json 에 칸 좌표 기준으로 저장한다.
        # (카메라 위치는 영상과 무관하므로 모든 원본 영상이 공유)
        video_title = (
            video_title
            or
            default_title()
        )

        if not video_title:

            raise ValueError(
                "No video given. Use --video or set "
                f"'video' in {DETECTION_CONFIG_PATH}"
            )

        self.scene = load_video(
            video_title
        )

        if camera_id not in self.scene.camera_ids:

            raise ValueError(
                f"Camera not found in config/mosaic.yaml: "
                f"{camera_id}"
            )

        self.video_path = (
            self.scene.video_path
        )

        mosaic = (
            self._load_video_frame()
        )

        # 모자이크에서 잘라낸 영역 (x1, y1, x2, y2)
        self.crop_rect = (
            self.scene.crop_rects(
                mosaic.shape[1],
                mosaic.shape[0],
            )[camera_id]
        )

        x1, y1, x2, y2 = self.crop_rect

        self.frame = (
            mosaic[y1:y2, x1:x2].copy()
        )

        self.bev_map = (
            self._load_bev_map()
        )

        (
            image_display_width,
            image_display_height,
        ) = self._calculate_display_size(
            image=self.frame,
            max_width=(
                IMAGE_DISPLAY_MAX_WIDTH
            ),
            max_height=(
                IMAGE_DISPLAY_MAX_HEIGHT
            ),
        )

        (
            bev_display_width,
            bev_display_height,
        ) = self._calculate_display_size(
            image=self.bev_map,
            max_width=(
                BEV_DISPLAY_MAX_WIDTH
            ),
            max_height=(
                BEV_DISPLAY_MAX_HEIGHT
            ),
        )

        self.image_view = ViewState(
            image=self.frame,
            display_width=(
                image_display_width
            ),
            display_height=(
                image_display_height
            ),
        )

        self.bev_view = ViewState(
            image=self.bev_map,
            display_width=(
                bev_display_width
            ),
            display_height=(
                bev_display_height
            ),
        )

        self.image_points: list[
            tuple[float, float]
        ] = []

        self.bev_points: list[
            tuple[float, float]
        ] = []

        self.pending_image_point: (
            tuple[float, float]
            | None
        ) = None

        # 영상 점을 찍었을 때 현재 mapping으로 예측한 BEV 위치.
        # 예측이 불가능하면 None.
        self.pending_predicted_bev: (
            tuple[float, float]
            | None
        ) = None

        self.output_path = (
            self.scene.calibration_dir
            /
            f"{self.camera_id}.json"
        )

        self.mapping: (
            CalibrationMapping
            | None
        ) = None

        self.homography_errors: list[float] = []
        self.mapping_errors: list[float] = []

        self.show_coverage = True

        # 확정된 calibration 점(빨강) 표시 여부
        self.show_points = True

        self.coverage_image: np.ndarray = (
            self.frame
        )

        self.coverage_ratio = 0.0

        # 점이 추가/삭제되었지만 아직 저장되지 않았는지 여부.
        # 변경이 없으면 종료 시 파일을 덮어쓰지 않는다.
        self.dirty = False

        self._load_existing_points()

        self._update_mapping()

    def _load_video_frame(
        self,
    ) -> np.ndarray:

        capture = cv2.VideoCapture(
            str(
                self.video_path
            )
        )

        if not capture.isOpened():

            raise RuntimeError(
                "Failed to open video: "
                f"{self.video_path}"
            )

        frame_count = int(
            capture.get(
                cv2.CAP_PROP_FRAME_COUNT
            )
        )

        if (
            self.frame_index < 0
            or
            self.frame_index
            >=
            frame_count
        ):

            capture.release()

            raise ValueError(
                f"Invalid frame index: "
                f"{self.frame_index}\n"
                f"Valid range: "
                f"0 ~ {frame_count - 1}"
            )

        capture.set(
            cv2.CAP_PROP_POS_FRAMES,
            self.frame_index,
        )

        success, frame = (
            capture.read()
        )

        capture.release()

        if not success:

            raise RuntimeError(
                "Failed to read frame "
                f"{self.frame_index}"
            )

        return frame

    def _load_bev_map(
        self,
    ) -> np.ndarray:

        if not BEV_MAP_PATH.exists():

            raise FileNotFoundError(
                f"BEV map not found: "
                f"{BEV_MAP_PATH}"
            )

        image = cv2.imread(
            str(
                BEV_MAP_PATH
            ),
            cv2.IMREAD_COLOR,
        )

        if image is None:

            raise RuntimeError(
                "Failed to load BEV map: "
                f"{BEV_MAP_PATH}"
            )

        return image

    def _calculate_display_size(
        self,
        image: np.ndarray,
        max_width: int,
        max_height: int,
    ) -> tuple[int, int]:

        height, width = (
            image.shape[:2]
        )

        scale = min(
            max_width / width,
            max_height / height,
            1.0,
        )

        display_width = int(
            round(
                width
                *
                scale
            )
        )

        display_height = int(
            round(
                height
                *
                scale
            )
        )

        return (
            display_width,
            display_height,
        )

    def _get_wheel_direction(
        self,
        flags: int,
    ) -> int:

        delta = (
            flags
            >>
            16
        )

        if delta > 32767:

            delta -= 65536

        if delta > 0:
            return 1

        if delta < 0:
            return -1

        return 0

    def _handle_view_mouse(
        self,
        view: ViewState,
        event: int,
        x: int,
        y: int,
        flags: int,
    ) -> bool:

        changed = False

        if (
            event
            ==
            cv2.EVENT_MOUSEWHEEL
        ):

            direction = (
                self._get_wheel_direction(
                    flags
                )
            )

            if direction != 0:

                view.zoom_at(
                    mouse_x=x,
                    mouse_y=y,
                    direction=direction,
                )

                changed = True

        elif (
            event
            ==
            cv2.EVENT_RBUTTONDOWN
        ):

            view.start_drag(
                x,
                y,
            )

        elif (
            event
            ==
            cv2.EVENT_MOUSEMOVE
        ):

            if view.dragging:

                view.drag(
                    x,
                    y,
                )

                changed = True

        elif (
            event
            ==
            cv2.EVENT_RBUTTONUP
        ):

            view.end_drag()

        return changed

    def _on_image_mouse(
        self,
        event,
        x,
        y,
        flags,
        param,
    ) -> None:

        if self._handle_view_mouse(
            view=self.image_view,
            event=event,
            x=x,
            y=y,
            flags=flags,
        ):

            self._refresh_windows()

            return

        if (
            event
            !=
            cv2.EVENT_LBUTTONDOWN
        ):

            return

        point = (
            self.image_view
            .display_to_original(
                x,
                y,
            )
        )

        self.pending_image_point = (
            point
        )

        self.pending_predicted_bev = (
            self._predict_bev(
                point
            )
        )

        print()

        print(
            "Image point selected:"
        )

        print(
            f"  x={point[0]:.2f}, "
            f"y={point[1]:.2f}"
        )

        if self.pending_predicted_bev is None:

            print(
                "  Predicted BEV: not available"
            )

        else:

            print(
                "  Predicted BEV: "
                f"("
                f"{self.pending_predicted_bev[0]:.2f}, "
                f"{self.pending_predicted_bev[1]:.2f}"
                f")"
            )

        print(
            "Now click the SAME point "
            "on the BEV map."
        )

        self._refresh_windows()

    def _on_bev_mouse(
        self,
        event,
        x,
        y,
        flags,
        param,
    ) -> None:

        if self._handle_view_mouse(
            view=self.bev_view,
            event=event,
            x=x,
            y=y,
            flags=flags,
        ):

            self._refresh_windows()

            return

        if (
            event
            !=
            cv2.EVENT_LBUTTONDOWN
        ):

            return

        if (
            self.pending_image_point
            is None
        ):

            print()

            print(
                "Select a point on the "
                "camera image first."
            )

            return

        bev_point = (
            self.bev_view
            .display_to_original(
                x,
                y,
            )
        )

        self.image_points.append(
            self.pending_image_point
        )

        self.bev_points.append(
            bev_point
        )

        point_number = len(
            self.image_points
        )

        print()

        print(
            f"Point #{point_number} added"
        )

        print(
            "  Image: "
            f"("
            f"{self.pending_image_point[0]:.2f}, "
            f"{self.pending_image_point[1]:.2f}"
            f")"
        )

        print(
            "  BEV  : "
            f"("
            f"{bev_point[0]:.2f}, "
            f"{bev_point[1]:.2f}"
            f")"
        )

        if self.pending_predicted_bev is not None:

            prediction_error = float(
                np.hypot(
                    bev_point[0]
                    -
                    self.pending_predicted_bev[0],

                    bev_point[1]
                    -
                    self.pending_predicted_bev[1],
                )
            )

            print(
                "  Prediction error "
                "(before adding this point): "
                f"{prediction_error:.2f} px"
            )

        self.pending_image_point = (
            None
        )

        self.pending_predicted_bev = (
            None
        )

        self._update_mapping()

        self.dirty = True

        self._save()

        self._print_calibration_status()

        self._refresh_windows()

    def _load_existing_points(
        self,
    ) -> None:

        if not self.output_path.exists():
            return

        try:

            with self.output_path.open(
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(
                    file
                )

            saved_frame_index = (
                data.get(
                    "frame_index"
                )
            )

            if (
                saved_frame_index
                !=
                self.frame_index
            ):

                print(
                    "Existing calibration found, "
                    "but frame index is different."
                )

                print(
                    f"Saved frame: "
                    f"{saved_frame_index}"
                )

                print(
                    f"Current frame: "
                    f"{self.frame_index}"
                )

                # 고정 카메라이므로 프레임이 달라도 바닥 위치는 같다.
                # 기존 점을 그대로 불러오고, 저장 시 frame_index만 갱신한다.
                print(
                    "Existing points will be loaded anyway. "
                    "frame_index will be updated on next save."
                )

            points = data.get(
                "points",
                [],
            )

            for point in points:

                image_point = (
                    float(
                        point["image"][0]
                    ),
                    float(
                        point["image"][1]
                    ),
                )

                bev_point = (
                    float(
                        point["bev"][0]
                    ),
                    float(
                        point["bev"][1]
                    ),
                )

                self.image_points.append(
                    image_point
                )

                self.bev_points.append(
                    bev_point
                )

            if points:

                print(
                    f"Loaded "
                    f"{len(points)} "
                    f"existing calibration points."
                )

        except Exception as error:

            print(
                "Failed to load existing "
                "calibration:"
            )

            print(
                error
            )

    def _update_mapping(
        self,
    ) -> None:
        """
        사용자 점 전체로 Homography + TPS mapping을 다시 계산하고
        coverage heatmap / 추천 위치도 함께 갱신한다.

        사용자 점은 모두 정답으로 간주한다.
        (RANSAC / outlier 제거 없음)
        """

        self.mapping = (
            CalibrationMapping.from_points(
                self.image_points,
                self.bev_points,
            )
        )

        self.homography_errors = []
        self.mapping_errors = []

        if self.mapping is not None:

            src = np.array(
                self.image_points,
                dtype=np.float64,
            )

            dst = np.array(
                self.bev_points,
                dtype=np.float64,
            )

            self.homography_errors = np.linalg.norm(
                apply_homography(
                    self.mapping.homography,
                    src,
                )
                -
                dst,
                axis=1,
            ).tolist()

            self.mapping_errors = np.linalg.norm(
                self.mapping.project_many(
                    src
                )
                -
                dst,
                axis=1,
            ).tolist()

        self._update_coverage()

    def _update_coverage(
        self,
    ) -> None:

        height, width = (
            self.frame.shape[:2]
        )

        _, _, confidence = coverage_grid(
            self.image_points,
            width=width,
            height=height,
            step=COVERAGE_GRID_STEP,
        )

        self.coverage_ratio = float(
            np.mean(
                confidence
                >=
                COVERAGE_LOW_THRESHOLD
            )
        )

        confidence_map = cv2.resize(
            confidence.astype(
                np.float32
            ),
            (
                width,
                height,
            ),
            interpolation=cv2.INTER_LINEAR,
        )

        # confidence가 낮을수록 진하게, threshold 이상은 원본 그대로
        alpha = np.clip(
            (
                COVERAGE_LOW_THRESHOLD
                -
                confidence_map
            )
            /
            COVERAGE_LOW_THRESHOLD,
            0.0,
            1.0,
        ) * COVERAGE_MAX_ALPHA

        tint = np.zeros_like(
            self.frame,
            dtype=np.float32,
        )

        tint[..., 2] = 255.0

        self.coverage_image = (
            self.frame.astype(
                np.float32
            )
            *
            (1.0 - alpha[..., None])
            +
            tint
            *
            alpha[..., None]
        ).astype(
            np.uint8
        )

    def _predict_bev(
        self,
        point: tuple[
            float,
            float,
        ],
    ) -> (
        tuple[float, float]
        | None
    ):
        """
        현재 mapping으로 BEV 위치를 예측한다 (검증용 표시).

        mapping이 없거나, 점이 바닥 평면의 지평선 너머에 있어
        Homography가 의미 없는 경우에는 None.
        정확도와 무관하게 계산 가능하면 반환한다.
        """

        if self.mapping is None:
            return None

        homography = self.mapping.homography

        def denominator(x, y):
            return (
                homography[2, 0] * x
                +
                homography[2, 1] * y
                +
                homography[2, 2]
            )

        reference = np.median(
            [
                denominator(x, y)
                for x, y in self.image_points
            ]
        )

        if (
            denominator(*point)
            *
            np.sign(reference)
            <=
            0.0
        ):
            return None

        bev_x, bev_y = self.mapping.project(
            point[0],
            point[1],
        )

        if not (
            np.isfinite(bev_x)
            and
            np.isfinite(bev_y)
        ):
            return None

        return (
            bev_x,
            bev_y,
        )

    def _save(
        self,
    ) -> None:

        self.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        homography = (
            self.mapping.homography
            if self.mapping is not None
            else None
        )

        # reprojection_error_px : Homography 단독 오차 (기존 의미 유지)
        # mapping_error_px      : 최종 mapping(H + TPS) 오차
        errors = self.homography_errors

        mapping_errors = self.mapping_errors

        points = []

        for index, (
            image_point,
            bev_point,
        ) in enumerate(
            zip(
                self.image_points,
                self.bev_points,
            ),
            start=1,
        ):

            point_data = {
                "id": index,

                "image": [
                    round(
                        image_point[0],
                        3,
                    ),
                    round(
                        image_point[1],
                        3,
                    ),
                ],

                "bev": [
                    round(
                        bev_point[0],
                        3,
                    ),
                    round(
                        bev_point[1],
                        3,
                    ),
                ],
            }

            if errors:

                point_data[
                    "reprojection_error_px"
                ] = round(
                    errors[
                        index - 1
                    ],
                    3,
                )

            if mapping_errors:

                point_data[
                    "mapping_error_px"
                ] = round(
                    mapping_errors[
                        index - 1
                    ],
                    3,
                )

            points.append(
                point_data
            )

        data = {
            "camera_id": (
                self.camera_id
            ),

            "video_path": str(
                self.video_path.relative_to(
                    ROOT
                )
            ).replace(
                "\\",
                "/",
            ),

            "frame_index": (
                self.frame_index
            ),

            # image 좌표는 잘라낸 칸 기준이다.
            "video": self.scene.name,

            "crop_rect": list(
                self.crop_rect
            ),

            "image_size": {
                "width": (
                    self.frame.shape[1]
                ),

                "height": (
                    self.frame.shape[0]
                ),
            },

            "bev_map": str(
                BEV_MAP_PATH.relative_to(
                    ROOT
                )
            ).replace(
                "\\",
                "/",
            ),

            "bev_size": {
                "width": (
                    self.bev_map.shape[1]
                ),

                "height": (
                    self.bev_map.shape[0]
                ),
            },

            "points": points,

            "homography": (
                homography.tolist()
                if homography is not None
                else None
            ),

            "mapping": (
                self.mapping.to_dict()
                if self.mapping is not None
                else None
            ),

            "reprojection": None,
        }

        if errors:

            data[
                "reprojection"
            ] = {
                "mean_error_px": round(
                    float(
                        np.mean(
                            errors
                        )
                    ),
                    3,
                ),

                "max_error_px": round(
                    float(
                        np.max(
                            errors
                        )
                    ),
                    3,
                ),

                "mapping_type": (
                    self.mapping.type
                ),

                "mapping_mean_error_px": round(
                    float(
                        np.mean(
                            mapping_errors
                        )
                    ),
                    3,
                ),

                "mapping_max_error_px": round(
                    float(
                        np.max(
                            mapping_errors
                        )
                    ),
                    3,
                ),
            }

        with self.output_path.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        self.dirty = False

    def _undo(
        self,
    ) -> None:

        if (
            self.pending_image_point
            is not None
        ):

            self.pending_image_point = (
                None
            )

            self.pending_predicted_bev = (
                None
            )

            print(
                "Pending image point cancelled."
            )

            self._refresh_windows()

            return

        if not self.image_points:

            print(
                "No calibration points to undo."
            )

            return

        removed_image = (
            self.image_points.pop()
        )

        removed_bev = (
            self.bev_points.pop()
        )

        print()

        print(
            "Removed last point:"
        )

        print(
            f"  Image: "
            f"{removed_image}"
        )

        print(
            f"  BEV  : "
            f"{removed_bev}"
        )

        self._update_mapping()

        self.dirty = True

        self._save()

        self._print_calibration_status()

        self._refresh_windows()

    def _print_calibration_status(
        self,
    ) -> None:

        count = len(
            self.image_points
        )

        print()

        print(
            "--------------------------------------"
        )

        print(
            f"Calibration points: "
            f"{count}"
        )

        if count < 4:

            print(
                "Need at least 4 points "
                "for Homography."
            )

        elif self.mapping is None:

            print(
                "Homography failed "
                "(points may be degenerate)."
            )

        else:

            print(
                f"Mapping type: "
                f"{self.mapping.type}"
            )

            print(
                f"Homography only error : "
                f"mean {np.mean(self.homography_errors):.2f} px, "
                f"max {np.max(self.homography_errors):.2f} px"
            )

            print(
                f"Final mapping error   : "
                f"mean {np.mean(self.mapping_errors):.2f} px, "
                f"max {np.max(self.mapping_errors):.2f} px"
            )

        print(
            f"Coverage (conf >= "
            f"{COVERAGE_LOW_THRESHOLD:.1f}): "
            f"{self.coverage_ratio * 100.0:.1f}% "
            f"of image"
        )

        print(
            "--------------------------------------"
        )

    def _draw_point(
        self,
        image: np.ndarray,
        view: ViewState,
        point: tuple[
            float,
            float,
        ],
        number: int,
    ) -> None:

        display_point = (
            view.original_to_display(
                point
            )
        )

        if display_point is None:
            return

        cv2.circle(
            image,
            display_point,
            5,
            (0, 0, 255),
            -1,
        )

        cv2.circle(
            image,
            display_point,
            9,
            (255, 255, 255),
            2,
        )

        cv2.putText(
            image,
            str(number),
            (
                display_point[0]
                +
                10,

                display_point[1]
                -
                10,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )

    def _draw_key_guide(
        self,
        image: np.ndarray,
    ) -> None:

        guide = (
            f"[C] coverage "
            f"{'ON' if self.show_coverage else 'OFF'}  "
            f"[P] points "
            f"{'ON' if self.show_points else 'OFF'}  "
            f"[U] undo  [S] save  [Q] quit"
        )

        height = image.shape[0]

        # 반투명 배경: 아래쪽 점이 가려지지 않도록
        strip = image[
            height - 24:height
        ]

        strip[:] = (
            strip.astype(np.float32)
            *
            0.45
        ).astype(np.uint8)

        cv2.putText(
            image,
            guide,
            (10, height - 7),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    def _refresh_windows(
        self,
    ) -> None:

        self.image_view.image = (
            self.coverage_image
            if self.show_coverage
            else self.frame
        )

        image_display = (
            self.image_view.render()
        )

        bev_display = (
            self.bev_view.render()
        )

        if self.show_points:

            for index, point in enumerate(
                self.image_points,
                start=1,
            ):

                self._draw_point(
                    image=image_display,
                    view=self.image_view,
                    point=point,
                    number=index,
                )

            for index, point in enumerate(
                self.bev_points,
                start=1,
            ):

                self._draw_point(
                    image=bev_display,
                    view=self.bev_view,
                    point=point,
                    number=index,
                )

        if (
            self.pending_image_point
            is not None
        ):

            pending_display_point = (
                self.image_view
                .original_to_display(
                    self.pending_image_point
                )
            )

            if (
                pending_display_point
                is not None
            ):

                cv2.circle(
                    image_display,
                    pending_display_point,
                    7,
                    (0, 255, 255),
                    -1,
                )

                cv2.putText(
                    image_display,
                    "NEXT",
                    (
                        pending_display_point[0]
                        +
                        10,

                        pending_display_point[1]
                        -
                        10,
                    ),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )

        if (
            self.pending_predicted_bev
            is not None
        ):

            predicted_display_point = (
                self.bev_view
                .original_to_display(
                    self.pending_predicted_bev
                )
            )

            if (
                predicted_display_point
                is not None
            ):

                cv2.drawMarker(
                    bev_display,
                    predicted_display_point,
                    PREDICT_COLOR,
                    cv2.MARKER_CROSS,
                    18,
                    2,
                    cv2.LINE_AA,
                )

                cv2.circle(
                    bev_display,
                    predicted_display_point,
                    10,
                    PREDICT_COLOR,
                    1,
                    cv2.LINE_AA,
                )

                cv2.putText(
                    bev_display,
                    "PRED",
                    (
                        predicted_display_point[0]
                        +
                        12,

                        predicted_display_point[1]
                        -
                        12,
                    ),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    PREDICT_COLOR,
                    2,
                    cv2.LINE_AA,
                )

        mapping_type = (
            self.mapping.type
            if self.mapping is not None
            else "none"
        )

        image_title = (
            f"{self.camera_id} | "
            f"frame {self.frame_index} | "
            f"zoom "
            f"{self.image_view.zoom:.2f}x | "
            f"{mapping_type} | "
            f"coverage "
            f"{self.coverage_ratio * 100.0:.0f}%"
        )

        bev_title = (
            f"BEV | "
            f"{len(self.bev_points)} points | "
            f"zoom "
            f"{self.bev_view.zoom:.2f}x"
        )

        cv2.putText(
            image_display,
            image_title,
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        cv2.putText(
            bev_display,
            bev_title,
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        self._draw_key_guide(
            image_display
        )

        cv2.imshow(
            IMAGE_WINDOW,
            image_display,
        )

        cv2.imshow(
            BEV_WINDOW,
            bev_display,
        )

    def run(
        self,
    ) -> None:

        print()
        print(
            "======================================"
        )
        print(
            "AX Parking Calibration Tool"
        )
        print(
            "======================================"
        )

        print(
            f"Camera : "
            f"{self.camera_id}"
        )

        print(
            f"Video  : "
            f"{self.video_path.name}"
        )

        print(
            f"Frame  : "
            f"{self.frame_index}"
        )

        print(
            f"Image  : "
            f"{self.frame.shape[1]}x"
            f"{self.frame.shape[0]}"
        )

        print(
            f"BEV    : "
            f"{self.bev_map.shape[1]}x"
            f"{self.bev_map.shape[0]}"
        )

        print(
            f"Output : "
            f"{self.output_path}"
        )

        print()

        print(
            "[Mouse]"
        )

        print(
            "Left click       : "
            "select calibration point"
        )

        print(
            "Mouse wheel      : "
            "zoom in / out"
        )

        print(
            "Right drag       : "
            "pan view"
        )

        print()

        print(
            "[Keyboard]"
        )

        print(
            "U : undo last point"
        )

        print(
            "S : save"
        )

        print(
            "C : toggle coverage heatmap "
            "(red = few calibration points)"
        )

        print(
            "P : toggle calibration point markers"
        )

        print(
            "Q / ESC : quit"
        )

        print()

        print(
            "After clicking an image point, "
            "the BEV window shows the predicted "
            "position (green PRED) if available."
        )

        print()

        print(
            "Calibration points are "
            "automatically saved."
        )

        print(
            "======================================"
        )

        self._print_calibration_status()

        cv2.namedWindow(
            IMAGE_WINDOW,
            cv2.WINDOW_AUTOSIZE,
        )

        cv2.namedWindow(
            BEV_WINDOW,
            cv2.WINDOW_AUTOSIZE,
        )

        cv2.moveWindow(
            IMAGE_WINDOW,
            0,
            50,
        )

        cv2.moveWindow(
            BEV_WINDOW,
            960,
            50,
        )

        cv2.setMouseCallback(
            IMAGE_WINDOW,
            self._on_image_mouse,
        )

        cv2.setMouseCallback(
            BEV_WINDOW,
            self._on_bev_mouse,
        )

        self._refresh_windows()

        while True:

            key = (
                cv2.waitKey(20)
                &
                0xFF
            )

            if key in (
                ord("q"),
                27,
            ):
                break

            if key == ord("u"):

                self._undo()

            elif key == ord("c"):

                self.show_coverage = (
                    not self.show_coverage
                )

                self._refresh_windows()

            elif key == ord("p"):

                self.show_points = (
                    not self.show_points
                )

                self._refresh_windows()

            elif key == ord("s"):

                self._save()

                print(
                    f"Saved: "
                    f"{self.output_path}"
                )

        cv2.destroyAllWindows()

        print()

        if not self.dirty:

            print(
                "No unsaved changes. "
                "Calibration file was not modified."
            )

            return

        self._save()

        print(
            "Calibration saved:"
        )

        print(
            self.output_path
        )


def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Camera to BEV calibration "
            "point collection tool"
        )
    )

    parser.add_argument(
        "--camera",
        type=str,
        default="cam01",
        help=(
            "Camera ID, "
            "e.g. cam01"
        ),
    )

    parser.add_argument(
        "--frame",
        type=int,
        default=0,
        help=(
            "Video frame index"
        ),
    )

    parser.add_argument(
        "--video",
        type=str,
        default=None,
        help=(
            "Raw video title used for the background frame "
            "(data/videos/raw/<title>.mp4). "
            "Default: 'video' in config/detection.yaml. "
            "Saved to config/calibration/<camera>.json."
        ),
    )

    return parser.parse_args()


def main():

    args = parse_args()

    tool = CalibrationTool(
        camera_id=args.camera,
        frame_index=args.frame,
        video_title=args.video,
    )

    tool.run()


if __name__ == "__main__":
    main()