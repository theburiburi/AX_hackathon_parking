# 데이터 폴더

원본은 **모자이크 영상**이다. 영상을 격자로 나눈 각 칸이 카메라 1대이며,
모든 카메라가 같은 프레임에서 잘리므로 프레임 번호가 항상 일치한다.

영상 제목 = `data/videos/raw/` 안의 파일 이름에서 확장자를 뺀 것 (예: `test00`).

```text
data/
├── videos/
│   ├── raw/<title>.mp4             # 모자이크 원본 (Git 제외)
│   └── <title>/camXX.mp4           # 전처리로 분리한 카메라 영상 (Git 제외)
├── detections/<title>/             # 전처리로 만든 YOLO 결과 (detections.jsonl, metadata.json)
└── maps/
    ├── map.png                     # BEV 지도 (1624 x 968)
    ├── zones.json                  # 주차 구역 정의 (웹 BEV 표시용)
    └── *.png                       # 참고용 이미지
```

## 좌표 기준

카메라 좌표는 **잘라낸 칸 기준 픽셀**이다 (칸 왼쪽 위 = 0, 0).
3x3 모자이크(1920x1080)이면 칸 하나가 640x360이다.
분리 영상, YOLO 결과, calibration, local tracking이 모두 이 좌표를 쓴다.

## 설정 파일

- `config/mosaic.yaml`: 모자이크 칸 ↔ 카메라 ID 배치 (모든 원본 영상 공통)
- `config/detection.yaml`
  - `video`: server / 캘리브레이션 / 재생 도구가 기본으로 사용할 영상 제목
  - YOLO 모델, 추론 설정
- `config/calibration/camXX.json`: 카메라별 칸 → BEV 보정 (모든 원본 영상 공통)
- `config/tracking.yaml`, `config/global_tracking.yaml`: Local / Global tracking 파라미터

## 실행 순서

1. 전처리: 원본 분리 + YOLO 검출

   ```bash
   python scripts/preprocess.py test00
   ```

   - `data/videos/test00/camXX.mp4` (분리 영상 7개)
   - `data/detections/test00/detections.jsonl`, `metadata.json` (bbox)
   - 다시 만들 때는 `--overwrite`, 빠른 확인은 `--max-frames 100`
   - 분리만: `--no-detect` / bbox만: `--no-split`

2. 카메라 캘리브레이션 (카메라마다, 필요할 때만)

   ```bash
   python scripts/calibrate_camera.py --camera cam01 --frame 100
   ```

   원본 모자이크에서 해당 칸을 잘라 보여 주고, `config/calibration/cam01.json`에 저장한다.
   배경으로 쓸 영상을 바꾸려면 `--video <title>`.

   - 왼쪽 클릭: 영상 점 → BEV 점 순서로 보정점 추가
   - 영상 점을 찍으면 BEV에 예측 위치(초록 PRED)가 표시된다.
   - C: coverage 표시 / P: 보정점 표시 / U: undo / S: 저장 / Q: 종료
   - 변경 사항이 없으면 종료할 때 파일을 덮어쓰지 않는다.

3. 서버 실행 (`config/detection.yaml`의 `video`를 사용)

   ```bash
   python server.py
   ```

   브라우저에서 `http://127.0.0.1:8000` 접속.
   웹은 원본 모자이크 영상을 재생하고, 화면에 표시된 프레임 번호의 tracking 결과를 칸 위치에 그린다.

   - Space: 재생/일시정지 / A, D: ±5초 / Shift+A, D: ±30초 / `,` `.`: 1프레임 / R: 처음

## 확인용 도구

- `python scripts/play_mosaic.py [title]`
  - 서버 없이 모자이크 + YOLO bbox를 재생한다. `--save`로 영상 저장 가능.
- `python scripts/render_parking_zones.py`
  - `data/maps/zones.json`의 주차 구역을 지도 위에 그려 `outputs/`에 저장한다.

## 참고

- 분리 영상은 `mp4v` 코덱이라 OpenCV로는 읽히지만 브라우저에서는 재생되지 않는다.
- 웹은 원본 모자이크를 재생하므로 브라우저가 원본 코덱을 지원해야 한다.
  `test00`은 HEVC(H.265)라 Windows의 Chrome / Edge + GPU 하드웨어 디코딩 환경에서 재생된다.
- 영상(`data/videos/`)은 Git에서 제외한다.
