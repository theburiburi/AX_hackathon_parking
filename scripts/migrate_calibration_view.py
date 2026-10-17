"""
축소 모드(좌우 검은 띠) 프레임에서 찍은 calibration 점을 전체 화면 좌표로 바꾼다.

    python scripts/migrate_calibration_view.py

calibration 파일의 frame_index가 해당 영상의 view_modes.json 기준 축소 모드이면
image 점의 x를 전체 화면 좌표로 되돌리고 Homography + TPS mapping을 다시 계산한다.
변환한 파일에는 "view": "full"을 기록하므로 다시 실행해도 두 번 바뀌지 않는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.mapping import CalibrationMapping, apply_homography  # noqa: E402
from src.mosaic import CALIBRATION_DIR, DETECTIONS_ROOT  # noqa: E402
from src.view_mode import VIEW_MODES_FILENAME, ViewModes  # noqa: E402


def refit(data: dict, image_points: np.ndarray, bev_points: np.ndarray) -> None:
    fade_px = (data.get("mapping") or {}).get("fade_px")
    mapping = (CalibrationMapping.from_points(image_points, bev_points, fade_px=fade_px)
               if fade_px is not None else
               CalibrationMapping.from_points(image_points, bev_points))
    homography_errors = np.linalg.norm(
        apply_homography(mapping.homography, image_points) - bev_points, axis=1)
    mapping_errors = np.linalg.norm(mapping.project_many(image_points) - bev_points, axis=1)
    for point, image, h_error, m_error in zip(
            data["points"], image_points, homography_errors, mapping_errors):
        point["image"] = [round(float(image[0]), 3), round(float(image[1]), 3)]
        point["reprojection_error_px"] = round(float(h_error), 3)
        point["mapping_error_px"] = round(float(m_error), 3)
    data["homography"] = mapping.homography.tolist()
    data["mapping"] = mapping.to_dict()
    data["reprojection"] = {
        "mean_error_px": round(float(np.mean(homography_errors)), 3),
        "max_error_px": round(float(np.max(homography_errors)), 3),
        "mapping_type": mapping.type,
        "mapping_mean_error_px": round(float(np.mean(mapping_errors)), 3),
        "mapping_max_error_px": round(float(np.max(mapping_errors)), 3),
    }


def main() -> None:
    for path in sorted(CALIBRATION_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        camera_id = data["camera_id"]
        if data.get("view") == "full":
            print(f"{camera_id}: already in full-view coordinates")
            continue
        modes = ViewModes.load(DETECTIONS_ROOT / data["video"] / VIEW_MODES_FILENAME)
        if modes is None:
            print(f"{camera_id}: {data['video']}/{VIEW_MODES_FILENAME} not found, skipped")
            continue
        boxed = modes.letterboxed(camera_id, int(data["frame_index"]))
        if boxed:
            image_points = np.array([p["image"] for p in data["points"]], dtype=np.float64)
            bev_points = np.array([p["bev"] for p in data["points"]], dtype=np.float64)
            before = data.get("reprojection") or {}
            image_points[:, 0] = modes.to_full_x(image_points[:, 0])
            refit(data, image_points, bev_points)
            print(f"{camera_id}: frame {data['frame_index']} was letterboxed -> converted "
                  f"(homography mean error {before.get('mean_error_px')} -> "
                  f"{data['reprojection']['mean_error_px']})")
        else:
            print(f"{camera_id}: frame {data['frame_index']} was full view, unchanged")
        data["view"] = "full"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
