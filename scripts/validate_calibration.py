from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
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

CALIBRATION_DIR = (
    ROOT
    / "config"
    / "calibration"
)

VALIDATION_DIR = (
    ROOT
    / "config"
    / "validation"
)


IMAGE_WINDOW = "Camera Validation"
BEV_WINDOW = "BEV Validation"


IMAGE_DISPLAY_MAX_WIDTH = 940
IMAGE_DISPLAY_MAX_HEIGHT = 650

BEV_DISPLAY_MAX_WIDTH = 900
BEV_DISPLAY_MAX_HEIGHT = 650


ZOOM_STEP = 1.25
MIN_ZOOM = 1.0
MAX_ZOOM = 20.0


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

    def reset(
        self,
    ) -> None:
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.dragging = False

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
    ) -> tuple[float, float]:

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
        point: tuple[float, float],
    ) -> tuple[int, int] | None:

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
            or x > viewport_x2
            or y < self.pan_y
            or y > viewport_y2
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

        old_zoom = self.zoom

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

        self.zoom = new_zoom

        self.pan_x = (
            original_x
            -
            normalized_x
            *
            self.viewport_width
        )

        self.pan_y = (
            original_y
            -
            normalized_y
            *
            self.viewport_height
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

        self.pan_x -= original_dx
        self.pan_y -= original_dy

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

        x2 = x1 + viewport_width
        y2 = y1 + viewport_height

        if x2 > self.image_width:
            x2 = self.image_width
            x1 = x2 - viewport_width

        if y2 > self.image_height:
            y2 = self.image_height
            y1 = y2 - viewport_height

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

        return cv2.resize(
            crop,
            (
                self.display_width,
                self.display_height,
            ),
            interpolation=cv2.INTER_LINEAR,
        )


@dataclass
class ValidationPoint:
    image_point: tuple[
        float,
        float,
    ]

    predicted_bev: tuple[
        float,
        float,
    ]

    actual_bev: tuple[
        float,
        float,
    ]

    error_px: float


class CalibrationValidator:
    def __init__(
        self,
        camera_id: str,
        frame_index: int,
    ):
        self.camera_id = camera_id
        self.frame_index = frame_index

        self.config = (
            self._load_detection_config()
        )

        self.video_path = (
            self._find_video_path()
        )

        self.calibration_path = (
            CALIBRATION_DIR
            /
            f"{self.camera_id}.json"
        )

        self.homography = (
            self._load_homography()
        )

        self.frame = (
            self._load_video_frame()
        )

        self.bev_map = (
            self._load_bev_map()
        )

        (
            image_display_width,
            image_display_height,
        ) = self._calculate_display_size(
            self.frame,
            IMAGE_DISPLAY_MAX_WIDTH,
            IMAGE_DISPLAY_MAX_HEIGHT,
        )

        (
            bev_display_width,
            bev_display_height,
        ) = self._calculate_display_size(
            self.bev_map,
            BEV_DISPLAY_MAX_WIDTH,
            BEV_DISPLAY_MAX_HEIGHT,
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

        self.validation_points: list[
            ValidationPoint
        ] = []

        self.pending_image_point: (
            tuple[float, float]
            | None
        ) = None

        self.pending_predicted_bev: (
            tuple[float, float]
            | None
        ) = None

        VALIDATION_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.output_path = (
            VALIDATION_DIR
            /
            f"{self.camera_id}.json"
        )

    def _load_detection_config(
        self,
    ) -> dict:

        with DETECTION_CONFIG_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:

            return yaml.safe_load(
                file
            )

    def _find_video_path(
        self,
    ) -> Path:

        for video in self.config.get(
            "videos",
            [],
        ):

            if (
                video["camera_id"]
                ==
                self.camera_id
            ):

                path = (
                    ROOT
                    /
                    video["path"]
                )

                if not path.exists():
                    raise FileNotFoundError(
                        f"Video not found: "
                        f"{path}"
                    )

                return path

        raise ValueError(
            f"Camera not found: "
            f"{self.camera_id}"
        )

    def _load_homography(
        self,
    ) -> np.ndarray:

        if not self.calibration_path.exists():

            raise FileNotFoundError(
                "Calibration file not found: "
                f"{self.calibration_path}"
            )

        with self.calibration_path.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        homography = data.get(
            "homography"
        )

        if homography is None:

            raise RuntimeError(
                "Homography is missing. "
                "Calibration needs at least "
                "4 valid points."
            )

        matrix = np.array(
            homography,
            dtype=np.float64,
        )

        if matrix.shape != (
            3,
            3,
        ):
            raise RuntimeError(
                "Invalid homography matrix."
            )

        return matrix

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
                f"Failed to open video: "
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
            self.frame_index >= frame_count
        ):
            capture.release()

            raise ValueError(
                f"Invalid frame index: "
                f"{self.frame_index}"
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
                f"Failed to read frame "
                f"{self.frame_index}"
            )

        return frame

    def _load_bev_map(
        self,
    ) -> np.ndarray:

        image = cv2.imread(
            str(
                BEV_MAP_PATH
            ),
            cv2.IMREAD_COLOR,
        )

        if image is None:

            raise RuntimeError(
                f"Failed to load BEV map: "
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

        return (
            int(
                round(
                    width * scale
                )
            ),
            int(
                round(
                    height * scale
                )
            ),
        )

    def _project_to_bev(
        self,
        point: tuple[
            float,
            float,
        ],
    ) -> tuple[
        float,
        float,
    ]:

        src = np.array(
            [
                [
                    point,
                ]
            ],
            dtype=np.float32,
        )

        projected = (
            cv2.perspectiveTransform(
                src,
                self.homography,
            )[0][0]
        )

        return (
            float(
                projected[0]
            ),
            float(
                projected[1]
            ),
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
                    x,
                    y,
                    direction,
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
            self.image_view,
            event,
            x,
            y,
            flags,
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

        predicted = (
            self._project_to_bev(
                point
            )
        )

        self.pending_image_point = (
            point
        )

        self.pending_predicted_bev = (
            predicted
        )

        print()
        print(
            "Validation image point:"
        )

        print(
            f"  Image     : "
            f"({point[0]:.2f}, "
            f"{point[1]:.2f})"
        )

        print(
            f"  Predicted : "
            f"({predicted[0]:.2f}, "
            f"{predicted[1]:.2f})"
        )

        print(
            "Click the ACTUAL matching "
            "point on the BEV map."
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
            self.bev_view,
            event,
            x,
            y,
            flags,
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
            or
            self.pending_predicted_bev
            is None
        ):

            print(
                "Select a camera point first."
            )

            return

        actual = (
            self.bev_view
            .display_to_original(
                x,
                y,
            )
        )

        predicted = (
            self.pending_predicted_bev
        )

        error = float(
            np.linalg.norm(
                np.array(
                    predicted
                )
                -
                np.array(
                    actual
                )
            )
        )

        validation_point = (
            ValidationPoint(
                image_point=(
                    self.pending_image_point
                ),
                predicted_bev=(
                    predicted
                ),
                actual_bev=(
                    actual
                ),
                error_px=error,
            )
        )

        self.validation_points.append(
            validation_point
        )

        index = len(
            self.validation_points
        )

        print()
        print(
            f"Validation #{index}"
        )

        print(
            f"  Predicted : "
            f"({predicted[0]:.2f}, "
            f"{predicted[1]:.2f})"
        )

        print(
            f"  Actual    : "
            f"({actual[0]:.2f}, "
            f"{actual[1]:.2f})"
        )

        print(
            f"  Error     : "
            f"{error:.2f} px"
        )

        self.pending_image_point = None
        self.pending_predicted_bev = None

        self._save()
        self._print_stats()
        self._refresh_windows()

    def _undo(
        self,
    ) -> None:

        if (
            self.pending_image_point
            is not None
        ):

            self.pending_image_point = None
            self.pending_predicted_bev = None

            print(
                "Pending validation cancelled."
            )

            self._refresh_windows()
            return

        if not self.validation_points:

            print(
                "No validation points to undo."
            )

            return

        removed = (
            self.validation_points.pop()
        )

        print()

        print(
            "Removed validation:"
        )

        print(
            f"  Error: "
            f"{removed.error_px:.2f} px"
        )

        self._save()
        self._print_stats()
        self._refresh_windows()

    def _reset_views(
        self,
    ) -> None:

        self.image_view.reset()
        self.bev_view.reset()

        print(
            "Zoom/pan reset."
        )

        self._refresh_windows()

    def _save(
        self,
    ) -> None:

        errors = [
            point.error_px
            for point
            in self.validation_points
        ]

        data = {
            "camera_id": (
                self.camera_id
            ),

            "frame_index": (
                self.frame_index
            ),

            "calibration_file": str(
                self.calibration_path.relative_to(
                    ROOT
                )
            ).replace(
                "\\",
                "/",
            ),

            "points": [],

            "statistics": None,
        }

        for index, point in enumerate(
            self.validation_points,
            start=1,
        ):

            data["points"].append(
                {
                    "id": index,

                    "image": [
                        round(
                            point.image_point[0],
                            3,
                        ),
                        round(
                            point.image_point[1],
                            3,
                        ),
                    ],

                    "predicted_bev": [
                        round(
                            point.predicted_bev[0],
                            3,
                        ),
                        round(
                            point.predicted_bev[1],
                            3,
                        ),
                    ],

                    "actual_bev": [
                        round(
                            point.actual_bev[0],
                            3,
                        ),
                        round(
                            point.actual_bev[1],
                            3,
                        ),
                    ],

                    "error_px": round(
                        point.error_px,
                        3,
                    ),
                }
            )

        if errors:

            error_array = np.array(
                errors,
                dtype=np.float64,
            )

            data[
                "statistics"
            ] = {
                "count": len(
                    errors
                ),

                "mean_error_px": round(
                    float(
                        np.mean(
                            error_array
                        )
                    ),
                    3,
                ),

                "median_error_px": round(
                    float(
                        np.median(
                            error_array
                        )
                    ),
                    3,
                ),

                "max_error_px": round(
                    float(
                        np.max(
                            error_array
                        )
                    ),
                    3,
                ),

                "min_error_px": round(
                    float(
                        np.min(
                            error_array
                        )
                    ),
                    3,
                ),

                "std_error_px": round(
                    float(
                        np.std(
                            error_array
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

    def _print_stats(
        self,
    ) -> None:

        if not self.validation_points:

            print()
            print(
                "Validation points: 0"
            )
            return

        errors = np.array(
            [
                point.error_px
                for point
                in self.validation_points
            ],
            dtype=np.float64,
        )

        print()

        print(
            "--------------------------------------"
        )

        print(
            f"Validation points : "
            f"{len(errors)}"
        )

        print(
            f"Mean error        : "
            f"{np.mean(errors):.2f} px"
        )

        print(
            f"Median error      : "
            f"{np.median(errors):.2f} px"
        )

        print(
            f"Max error         : "
            f"{np.max(errors):.2f} px"
        )

        print(
            f"Min error         : "
            f"{np.min(errors):.2f} px"
        )

        print(
            f"Std deviation     : "
            f"{np.std(errors):.2f} px"
        )

        print(
            "--------------------------------------"
        )

    def _draw_marker(
        self,
        image: np.ndarray,
        point: tuple[
            float,
            float,
        ],
        view: ViewState,
        marker_type: str,
        label: str,
    ) -> None:

        display_point = (
            view.original_to_display(
                point
            )
        )

        if display_point is None:
            return

        x, y = display_point

        if marker_type == "actual":

            cv2.circle(
                image,
                (x, y),
                6,
                (0, 255, 0),
                -1,
            )

            cv2.circle(
                image,
                (x, y),
                10,
                (255, 255, 255),
                2,
            )

        elif marker_type == "predicted":

            size = 8

            cv2.line(
                image,
                (
                    x - size,
                    y - size,
                ),
                (
                    x + size,
                    y + size,
                ),
                (0, 0, 255),
                2,
            )

            cv2.line(
                image,
                (
                    x + size,
                    y - size,
                ),
                (
                    x - size,
                    y + size,
                ),
                (0, 0, 255),
                2,
            )

        elif marker_type == "image":

            cv2.circle(
                image,
                (x, y),
                6,
                (0, 255, 255),
                -1,
            )

        cv2.putText(
            image,
            label,
            (
                x + 10,
                y - 10,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    def _refresh_windows(
        self,
    ) -> None:

        image_display = (
            self.image_view.render()
        )

        bev_display = (
            self.bev_view.render()
        )

        for index, point in enumerate(
            self.validation_points,
            start=1,
        ):

            self._draw_marker(
                image_display,
                point.image_point,
                self.image_view,
                "image",
                str(index),
            )

            self._draw_marker(
                bev_display,
                point.predicted_bev,
                self.bev_view,
                "predicted",
                f"P{index}",
            )

            self._draw_marker(
                bev_display,
                point.actual_bev,
                self.bev_view,
                "actual",
                f"A{index}",
            )

            predicted_display = (
                self.bev_view
                .original_to_display(
                    point.predicted_bev
                )
            )

            actual_display = (
                self.bev_view
                .original_to_display(
                    point.actual_bev
                )
            )

            if (
                predicted_display is not None
                and
                actual_display is not None
            ):

                cv2.line(
                    bev_display,
                    predicted_display,
                    actual_display,
                    (255, 255, 0),
                    1,
                    cv2.LINE_AA,
                )

        if (
            self.pending_image_point
            is not None
        ):

            self._draw_marker(
                image_display,
                self.pending_image_point,
                self.image_view,
                "image",
                "NEXT",
            )

        if (
            self.pending_predicted_bev
            is not None
        ):

            self._draw_marker(
                bev_display,
                self.pending_predicted_bev,
                self.bev_view,
                "predicted",
                "PENDING",
            )

        image_title = (
            f"{self.camera_id} | "
            f"frame {self.frame_index} | "
            f"zoom "
            f"{self.image_view.zoom:.2f}x"
        )

        bev_title = (
            f"BEV validation | "
            f"{len(self.validation_points)} points | "
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
            "AX Parking Calibration Validation"
        )
        print(
            "======================================"
        )

        print(
            f"Camera      : "
            f"{self.camera_id}"
        )

        print(
            f"Video       : "
            f"{self.video_path.name}"
        )

        print(
            f"Frame       : "
            f"{self.frame_index}"
        )

        print(
            f"Calibration : "
            f"{self.calibration_path}"
        )

        print(
            f"Output      : "
            f"{self.output_path}"
        )

        print()

        print(
            "[Mouse]"
        )

        print(
            "Camera left click : "
            "select validation point"
        )

        print(
            "BEV left click    : "
            "select actual matching point"
        )

        print(
            "Mouse wheel       : "
            "zoom in / out"
        )

        print(
            "Right drag        : "
            "pan"
        )

        print()

        print(
            "[BEV markers]"
        )

        print(
            "Red X   : predicted position"
        )

        print(
            "Green O : actual position"
        )

        print()

        print(
            "[Keyboard]"
        )

        print(
            "U : undo"
        )

        print(
            "R : reset zoom / pan"
        )

        print(
            "S : save"
        )

        print(
            "Q / ESC : quit"
        )

        print(
            "======================================"
        )

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

            elif key == ord("r"):
                self._reset_views()

            elif key == ord("s"):

                self._save()

                print(
                    f"Saved: "
                    f"{self.output_path}"
                )

        self._save()

        cv2.destroyAllWindows()

        print()
        print(
            "Validation saved:"
        )
        print(
            self.output_path
        )

        self._print_stats()


def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Validate camera-to-BEV "
            "homography calibration"
        )
    )

    parser.add_argument(
        "--camera",
        type=str,
        default="cam01",
    )

    parser.add_argument(
        "--frame",
        type=int,
        default=300,
    )

    return parser.parse_args()


def main():

    args = parse_args()

    validator = CalibrationValidator(
        camera_id=args.camera,
        frame_index=args.frame,
    )

    validator.run()


if __name__ == "__main__":
    main()