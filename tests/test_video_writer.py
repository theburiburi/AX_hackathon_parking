"""
ffmpeg H.264 저장 (src/video_writer.py).
"""

import cv2
import numpy as np
import pytest

from src.video_writer import FFmpegWriter


def test_writes_readable_h264(tmp_path):

    path = tmp_path / "clip.mp4"

    writer = FFmpegWriter(path, 160, 90, 30.0, "libx264", 18)

    for index in range(10):
        frame = np.full((90, 160, 3), index * 20, dtype=np.uint8)
        writer.write(frame)

    writer.close()

    capture = cv2.VideoCapture(str(path))

    fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
    codec = "".join(chr((fourcc >> (8 * i)) & 255) for i in range(4))

    assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 10
    assert int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) == 160
    assert codec.lower() in ("avc1", "h264")

    capture.release()


def test_rejects_wrong_frame_size(tmp_path):

    writer = FFmpegWriter(tmp_path / "clip.mp4", 160, 90, 30.0, "libx264", 18)

    with pytest.raises(ValueError):
        writer.write(np.zeros((100, 160, 3), dtype=np.uint8))

    writer.write(np.zeros((90, 160, 3), dtype=np.uint8))
    writer.close()
