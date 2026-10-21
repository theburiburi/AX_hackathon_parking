from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np


"""
ffmpeg(imageio-ffmpeg에 포함)로 프레임을 H.264 mp4로 저장한다.

OpenCV의 mp4v는 브라우저에서 재생되지 않으므로
웹에서 재생할 영상과 분리 영상은 H.264(yuv420p, faststart)로 만든다.
키프레임을 1초마다 넣어 웹에서 재생바를 옮길 때 바로 이동하게 한다.
"""


def ffmpeg_path() -> str:

    try:
        import imageio_ffmpeg

    except ImportError as error:
        raise RuntimeError(
            "imageio-ffmpeg is required: pip install imageio-ffmpeg"
        ) from error

    return imageio_ffmpeg.get_ffmpeg_exe()


def encoder_available(
    encoder: str,
) -> bool:
    """
    실제로 1프레임을 인코딩해 본다 (NVENC는 GPU / 드라이버가 없으면 실패).
    """

    result = subprocess.run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", "color=black:s=256x256:d=0.1",
            "-frames:v", "1",
            "-c:v", encoder,
            "-f", "null",
            "-",
        ],
        capture_output=True,
    )

    return result.returncode == 0


def pick_encoder(
    preferred: str = "auto",
) -> str:
    """
    auto: GPU(h264_nvenc)를 쓸 수 있으면 쓰고, 아니면 libx264.
    """

    if preferred != "auto":
        return preferred

    return "h264_nvenc" if encoder_available("h264_nvenc") else "libx264"


def quality_args(
    encoder: str,
    quality: int,
) -> list[str]:
    """
    quality: 작을수록 고화질 (libx264 CRF / NVENC CQ, 18 ~ 23 권장).
    """

    if encoder == "h264_nvenc":
        return [
            "-preset", "p5",
            "-rc", "vbr",
            "-cq", str(quality),
            "-b:v", "0",
        ]

    return [
        "-preset", "veryfast",
        "-crf", str(quality),
    ]


class FFmpegWriter:
    """
    BGR 프레임(numpy)을 받아 H.264 mp4로 저장한다.
    """

    def __init__(
        self,
        path: str | Path,
        width: int,
        height: int,
        fps: float,
        encoder: str = "libx264",
        quality: int = 18,
    ):
        self.path = Path(path)
        self.width = int(width)
        self.height = int(height)

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        gop = max(1, int(round(fps)))

        command = [
            ffmpeg_path(),
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self.width}x{self.height}",
            "-r", f"{fps:g}",
            "-i", "-",
            "-an",
            "-c:v", encoder,
            *quality_args(encoder, quality),
            "-g", str(gop),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(self.path),
        ]

        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def write(
        self,
        frame: np.ndarray,
    ) -> None:

        if frame.shape[:2] != (self.height, self.width):
            raise ValueError(
                f"{self.path.name}: frame {frame.shape[1]}x{frame.shape[0]} "
                f"!= {self.width}x{self.height}"
            )

        self.process.stdin.write(
            np.ascontiguousarray(frame).tobytes()
        )

    def close(self) -> None:

        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()

        error = self.process.stderr.read().decode("utf-8", "replace")

        code = self.process.wait()

        if code != 0:
            raise RuntimeError(
                f"ffmpeg failed for {self.path} (exit {code}):\n{error}"
            )
