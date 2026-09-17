"""Time-based synchronized reading for multiple video files."""

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    fps: float
    frame_count: int
    width: int
    height: int

    @property
    def duration_ms(self) -> float:
        return self.frame_count / self.fps * 1000.0


def common_time_range(
    infos: Sequence[VideoInfo], offsets_ms: Sequence[float]
) -> tuple[float, float]:
    """Return global times for which every camera has a valid local frame."""
    if not infos:
        raise ValueError("at least one video is required")
    if len(infos) != len(offsets_ms):
        raise ValueError("the number of offsets must match the number of videos")
    start = max(0.0, max(-offset for offset in offsets_ms))
    end = min(info.duration_ms - offset for info, offset in zip(infos, offsets_ms))
    if end <= start:
        raise ValueError("video offsets leave no overlapping playback interval")
    return start, end


class SynchronizedVideoReader:
    """Return one frame per camera at a shared global video timestamp."""

    def __init__(self, paths: Sequence[Path], offsets_seconds: Sequence[float] | None = None):
        if not paths:
            raise ValueError("at least one video path is required")
        if offsets_seconds is None:
            offsets_seconds = [0.0] * len(paths)
        if len(offsets_seconds) != len(paths):
            raise ValueError("the number of --offsets must match --videos")

        self.captures: list[cv2.VideoCapture] = []
        self.infos: list[VideoInfo] = []
        self.offsets_ms = [float(value) * 1000.0 for value in offsets_seconds]
        self._last_indices = [-2] * len(paths)
        self._last_frames: list[np.ndarray | None] = [None] * len(paths)
        self._executor: ThreadPoolExecutor | None = None

        try:
            for path in paths:
                if not path.is_file():
                    raise FileNotFoundError(f"video not found: {path}")
                capture = cv2.VideoCapture(str(path))
                if not capture.isOpened():
                    capture.release()
                    raise ValueError(f"failed to open video: {path}")
                fps = float(capture.get(cv2.CAP_PROP_FPS))
                frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
                if fps <= 0 or frame_count <= 0:
                    capture.release()
                    raise ValueError(f"invalid FPS or frame count: {path}")
                self.captures.append(capture)
                self.infos.append(
                    VideoInfo(
                        path=path,
                        fps=fps,
                        frame_count=frame_count,
                        width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                        height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    )
                )
            self.start_ms, self.end_ms = common_time_range(self.infos, self.offsets_ms)
            # Each capture belongs to one worker during a read. OpenCV's native
            # decoding releases the GIL, so independent camera files can decode
            # concurrently instead of serially blocking the display loop.
            self._executor = ThreadPoolExecutor(
                max_workers=len(self.captures), thread_name_prefix="video-decode"
            )
        except Exception:
            self.release()
            raise

    def read_at(self, global_time_ms: float) -> list[np.ndarray]:
        """Read frames nearest to a global time, seeking only when necessary."""
        global_time_ms = min(max(global_time_ms, self.start_ms), self.end_ms - 0.001)
        if self._executor is None:
            raise RuntimeError("video reader has been released")
        futures = [
            self._executor.submit(self._read_one, index, global_time_ms)
            for index in range(len(self.captures))
        ]
        return [future.result() for future in futures]

    def _read_one(self, index: int, global_time_ms: float) -> np.ndarray:
        capture = self.captures[index]
        info = self.infos[index]
        local_ms = global_time_ms + self.offsets_ms[index]
        frame_index = min(
            info.frame_count - 1,
            max(0, int(round(local_ms * info.fps / 1000.0))),
        )
        previous_index = self._last_indices[index]
        previous_frame = self._last_frames[index]
        if frame_index == previous_index and previous_frame is not None:
            return previous_frame

        gap = frame_index - previous_index
        if previous_frame is not None and 1 < gap <= 120:
            # During playback, skip compressed frames sequentially. Repeated
            # CAP_PROP_POS_FRAMES seeks are dramatically slower for H.264.
            for _ in range(gap - 1):
                if not capture.grab():
                    raise ValueError(f"failed to skip a frame in {info.path.name}")
        elif gap != 1:
            # Backward movement or a large timeline jump is a real seek.
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

        ok, frame = capture.read()
        if not ok:
            raise ValueError(f"failed to read {info.path.name} at {local_ms / 1000:.3f}s")
        self._last_indices[index] = frame_index
        self._last_frames[index] = frame
        return frame

    def release(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        for capture in self.captures:
            capture.release()
        self.captures.clear()

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.release()
