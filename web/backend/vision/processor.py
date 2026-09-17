"""이 파일의 process_frame()에 객체 탐지, 추적 등 비전 코드를 작성하세요."""
import cv2
import os
from pathlib import Path
import sys
from threading import Lock

_detector = None
_model_lock = Lock()


def detect_batch(frames):
    global _detector
    project = Path(__file__).resolve().parents[3]
    sys.dont_write_bytecode = True
    if str(project) not in sys.path:
        sys.path.insert(0, str(project))
    config_dir = Path(__file__).resolve().parent / "data/ultralytics"
    (config_dir / "Ultralytics").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(config_dir))
    from src.tracking import BatchVehicleDetector
    import yaml
    with _model_lock:
        if _detector is None:
            with (project / "config.yaml").open(encoding="utf-8") as file:
                config = yaml.safe_load(file)["detection"]
            model = Path(config.get("model", "models/detection/yolo11n.pt"))
            if not model.is_absolute():
                model = project / model
            if not model.is_file():
                raise ValueError("YOLO model weights are missing. Configure an existing model in config.yaml.")
            _detector = BatchVehicleDetector(str(model), config.get("confidence", .3),
                config.get("iou", .5), config.get("vehicle_classes", [2, 5, 7]),
                config.get("image_size", 640), config.get("device", "auto"))
        return _detector.detect(frames)


def detect_vehicles(frame, frame_index, timestamp):
    detections = detect_batch([frame])[0]
    output = frame.copy()
    observations = []
    for index, vehicle in enumerate(detections, 1):
        x1, y1, x2, y2 = vehicle.bbox
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 220, 0), 2)
        cv2.putText(output, f"#{index} {vehicle.confidence:.2f}", (x1, max(15, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 220, 0), 1)
        observations.append({"detection_id": index, "class_id": vehicle.class_id,
                             "confidence": vehicle.confidence, "bbox": list(vehicle.bbox)})
    return output, {"frame_index": frame_index, "timestamp_seconds": round(timestamp, 3),
                    "mode": "yolo", "detections": observations}


def process_frame(frame, frame_index: int, timestamp: float):
    """BGR ndarray를 받아 (결과 BGR 이미지, JSON 저장 가능한 분석값)을 반환합니다.

    모델을 사용한다면 매 프레임마다 로드하지 말고 모듈 수준에서 한 번 로드하세요.
    출력 이미지 크기는 입력과 같아야 합니다.
    """
    mode = os.environ.get("WEB_VISION_MODE", "edges")
    if mode == "yolo":
        return detect_vehicles(frame, frame_index, timestamp)
    if mode != "edges":
        raise ValueError("WEB_VISION_MODE must be edges or yolo")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 160)
    output = frame.copy()
    output[edges > 0] = (0, 255, 0)
    return output, {
        "frame_index": frame_index,
        "timestamp_seconds": round(timestamp, 3),
        "mean_brightness": round(float(gray.mean()), 2),
        "edge_pixels": int((edges > 0).sum()),
    }
