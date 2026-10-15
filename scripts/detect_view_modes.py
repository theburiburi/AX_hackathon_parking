"""
원본 모자이크 영상에서 카메라별 화면 모드(전체 / 축소)를 기록한다.

    python scripts/detect_view_modes.py test02

결과: data/detections/<title>/view_modes.json
(preprocess.py로 새로 전처리하면 자동으로 함께 만들어진다.)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mosaic import default_title, load_video  # noqa: E402
from src.view_mode import VIEW_MODES_FILENAME, ViewModeRecorder, load_letterbox  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Record letterboxed camera frames")
    parser.add_argument("video", nargs="?", default=None,
                        help="Raw video title (default: 'video' in config/detection.yaml)")
    args = parser.parse_args()

    scene = load_video(args.video or default_title())
    capture = cv2.VideoCapture(str(scene.video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open video: {scene.video_path}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    rects = scene.crop_rects(width, height)
    recorder = ViewModeRecorder(list(rects), *load_letterbox())

    started_at = time.perf_counter()
    frame_index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        recorder.add(frame_index, {
            camera_id: frame[y1:y2, x1:x2]
            for camera_id, (x1, y1, x2, y2) in rects.items()
        })
        frame_index += 1
        if frame_index % 500 == 0:
            print(f"{frame_index}/{frame_count} frames "
                  f"({time.perf_counter() - started_at:.0f}s)", flush=True)
    capture.release()

    modes = recorder.finish()
    scene.detections_dir.mkdir(parents=True, exist_ok=True)
    output_path = scene.detections_dir / VIEW_MODES_FILENAME
    modes.save(output_path, recorder.frame_count)

    fps = 30.0
    print(f"Saved: {output_path}")
    for camera_id, segments in modes.segments.items():
        boxed = sum(end - start for start, end in segments)
        print(f"  {camera_id}: 축소 모드 {boxed / fps:.0f}s / {recorder.frame_count / fps:.0f}s"
              f" ({len(segments)}구간)")


if __name__ == "__main__":
    main()
