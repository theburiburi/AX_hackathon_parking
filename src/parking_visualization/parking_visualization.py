import json
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "parking"
# 원본 주차장 이미지와 주석, 생성 결과를 같은 폴더에서 관리한다.
IMAGE_PATH = DATA_DIR / "parking.png"
ANNOTATION_PATH = DATA_DIR / "annotation.json"
OUTPUT_PATH = DATA_DIR / "verified_parking.png"

# Windows의 한글 경로에서도 이미지를 읽을 수 있도록 바이트로 불러온다.
image_bytes = np.fromfile(IMAGE_PATH, dtype=np.uint8)
image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
if image is None:
  raise FileNotFoundError(f"이미지를 읽을 수 없습니다: {IMAGE_PATH}")

with ANNOTATION_PATH.open(encoding="utf-8") as annotation_file:
  data = json.load(annotation_file)

objects = data["annotation"]["objects"]

# annotation.json의 좌표를 그대로 사용해 주차면과 번호만 표시한다.
for index, obj in enumerate(objects, start=1):
  box = obj["bndbox"]
  xmin = int(box["xmin"])
  ymin = int(box["ymin"])
  xmax = int(box["xmax"])
  ymax = int(box["ymax"])

  cv2.rectangle(image, (xmin, ymin), (xmax, ymax), (0, 0, 255), 2)
  cv2.putText(
    image,
    str(index),
    (xmin + 2, max(ymin - 4, 12)),
    cv2.FONT_HERSHEY_SIMPLEX,
    0.45,
    (0, 0, 255),
    1,
    cv2.LINE_AA,
  )

# OpenCV로 인코딩한 이미지를 한글 경로에서도 저장할 수 있게 기록한다.
encoded_image = cv2.imencode(".png", image)[1]
encoded_image.tofile(OUTPUT_PATH)
if not OUTPUT_PATH.exists():
  raise OSError(f"결과 이미지를 저장할 수 없습니다: {OUTPUT_PATH}")

print(f"시각화 완료: {OUTPUT_PATH} ({len(objects)}개 주차면)")
