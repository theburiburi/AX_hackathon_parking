from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class CameraInfo:
    camera_id: str
    path: Path

    fps: float
    frame_count: int

    width: int
    height: int


@dataclass
class SynchronizedFrameSet:
    frame_index: int
    timestamp: float

    frames: list[np.ndarray]

    read_time_ms: float


class SynchronizedVideoReader:
    def __init__(
        self,
        video_configs: list[dict],
        root: Path,
        queue_size: int = 2,
    ):
        self.root = root

        self.video_configs = (
            video_configs
        )

        self.queue_size = max(
            1,
            int(queue_size),
        )

        self.captures: list[
            cv2.VideoCapture
        ] = []

        self.cameras: list[
            CameraInfo
        ] = []

        self.frame_queue: queue.Queue = (
            queue.Queue(
                maxsize=self.queue_size
            )
        )

        self.stop_event = (
            threading.Event()
        )

        self.thread: (
            threading.Thread
            | None
        ) = None

        self.error: (
            Exception
            | None
        ) = None

        self.finished = False

        self.reference_fps = 0.0

        self.common_frame_count = 0

        self._open_videos()

    def _open_videos(
        self,
    ) -> None:

        for config in (
            self.video_configs
        ):

            camera_id = config[
                "camera_id"
            ]

            video_path = (
                self.root
                /
                config["path"]
            )

            if not video_path.exists():

                raise FileNotFoundError(
                    f"Video not found: "
                    f"{video_path}"
                )

            capture = (
                cv2.VideoCapture(
                    str(video_path)
                )
            )

            if not capture.isOpened():

                raise RuntimeError(
                    "Failed to open video: "
                    f"{video_path}"
                )

            fps = float(
                capture.get(
                    cv2.CAP_PROP_FPS
                )
            )

            frame_count = int(
                capture.get(
                    cv2.CAP_PROP_FRAME_COUNT
                )
            )

            width = int(
                capture.get(
                    cv2.CAP_PROP_FRAME_WIDTH
                )
            )

            height = int(
                capture.get(
                    cv2.CAP_PROP_FRAME_HEIGHT
                )
            )

            self.captures.append(
                capture
            )

            self.cameras.append(
                CameraInfo(
                    camera_id=camera_id,
                    path=video_path,
                    fps=fps,
                    frame_count=frame_count,
                    width=width,
                    height=height,
                )
            )

        self._validate_videos()

        self.reference_fps = (
            self.cameras[0].fps
        )

        self.common_frame_count = min(
            camera.frame_count
            for camera
            in self.cameras
        )

    def _validate_videos(
        self,
    ) -> None:

        if not self.cameras:

            raise RuntimeError(
                "No videos configured."
            )

        reference_fps = (
            self.cameras[0].fps
        )

        for camera in (
            self.cameras[1:]
        ):

            if (
                abs(
                    camera.fps
                    -
                    reference_fps
                )
                >
                0.01
            ):

                raise RuntimeError(
                    "Camera FPS mismatch: "
                    f"{self.cameras[0].camera_id}="
                    f"{reference_fps:.3f}, "
                    f"{camera.camera_id}="
                    f"{camera.fps:.3f}"
                )

    def start(
        self,
    ) -> None:

        if (
            self.thread is not None
            and
            self.thread.is_alive()
        ):
            return

        self.stop_event.clear()

        self.finished = False

        self.error = None

        self.thread = threading.Thread(
            target=self._reader_loop,
            name="video-reader",
            daemon=True,
        )

        self.thread.start()

    def _reader_loop(
        self,
    ) -> None:

        try:

            for frame_index in range(
                self.common_frame_count
            ):

                if (
                    self.stop_event.is_set()
                ):
                    break

                read_start = (
                    time.perf_counter()
                )

                frames = []

                for (
                    camera,
                    capture,
                ) in zip(
                    self.cameras,
                    self.captures,
                ):

                    success, frame = (
                        capture.read()
                    )

                    if not success:

                        raise RuntimeError(
                            "Failed to read "
                            f"{camera.camera_id} "
                            f"at frame "
                            f"{frame_index}"
                        )

                    frames.append(
                        frame
                    )

                read_time_ms = (
                    (
                        time.perf_counter()
                        -
                        read_start
                    )
                    *
                    1000.0
                )

                timestamp = (
                    frame_index
                    /
                    self.reference_fps
                )

                frame_set = (
                    SynchronizedFrameSet(
                        frame_index=(
                            frame_index
                        ),
                        timestamp=timestamp,
                        frames=frames,
                        read_time_ms=(
                            read_time_ms
                        ),
                    )
                )

                while (
                    not
                    self.stop_event.is_set()
                ):

                    try:

                        self.frame_queue.put(
                            frame_set,
                            timeout=0.1,
                        )

                        break

                    except queue.Full:

                        continue

        except Exception as error:

            self.error = error

        finally:

            self.finished = True

    def get(
        self,
        timeout: float = 1.0,
    ) -> (
        SynchronizedFrameSet
        | None
    ):

        while True:

            if self.error is not None:

                raise self.error

            try:

                return (
                    self.frame_queue.get(
                        timeout=timeout
                    )
                )

            except queue.Empty:

                if (
                    self.finished
                    and
                    self.frame_queue.empty()
                ):

                    return None

    def stop(
        self,
    ) -> None:

        self.stop_event.set()

        if self.thread is not None:

            self.thread.join(
                timeout=2.0
            )

        for capture in (
            self.captures
        ):

            capture.release()

    @property
    def camera_ids(
        self,
    ) -> list[str]:

        return [
            camera.camera_id
            for camera
            in self.cameras
        ]

    def print_info(
        self,
    ) -> None:

        print()

        print(
            "======================================"
        )

        print(
            "Synchronized camera set"
        )

        print(
            "======================================"
        )

        for camera in self.cameras:

            duration = (
                camera.frame_count
                /
                camera.fps
                if camera.fps > 0
                else 0.0
            )

            print(
                f"{camera.camera_id}: "
                f"{camera.path.name} | "
                f"{camera.width}x"
                f"{camera.height} | "
                f"{camera.fps:.3f} FPS | "
                f"{camera.frame_count} frames | "
                f"{duration:.2f}s"
            )

        print(
            "======================================"
        )

        print()