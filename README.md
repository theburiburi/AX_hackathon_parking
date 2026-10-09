# AX Parking

주차장 CCTV 모자이크 영상에서 차량을 검출하고, 카메라별로 추적한 뒤,
실제 주차장 지도(BEV) 위에 차량 위치를 표시하는 시스템이다.

- 원본: 녹화 장비가 만든 **3x3 모자이크 영상** 1개 (칸 7개 = 카메라 7대)
- 검출: YOLO (ultralytics), 미리 계산해 캐시로 저장
- 추적: 카메라별 Local Tracking + 카메라 간 Global Tracking (Re-ID)
- 지도 투영: 카메라별 calibration (Homography + TPS 비선형 보정)
- 뷰어: 웹 브라우저에서 모자이크 영상 + bbox + BEV 지도를 프레임 단위로 동기화해 재생

---

## 1. 전체 흐름

```
data/videos/raw/<title>.mp4  (모자이크 원본)
        │
        │  scripts/preprocess.py <title>
        │    - config/mosaic.yaml 의 칸 배치대로 프레임을 잘라
        │    - 카메라 영상 7개 저장 + 같은 이미지에 YOLO 실행
        ▼
data/videos/<title>/camXX.mp4          (분리 영상)
data/detections/<title>/detections.jsonl  (프레임별 bbox)
        │
        │  scripts/calibrate_camera.py --camera camXX   (카메라마다 1회)
        ▼
config/calibration/camXX.json          (칸 좌표 → BEV 좌표 변환)
        │
        │  python server.py
        │    - 캐시에서 프레임별 bbox를 읽어 Local / Global Tracking
        │    - bbox 바닥 중앙점을 calibration으로 BEV 좌표로 변환
        ▼
웹 뷰어 (http://127.0.0.1:8000)
    모자이크 영상 재생 + 칸별 bbox + BEV 지도
```

핵심 원칙: **모든 카메라가 같은 모자이크 프레임에서 잘리므로
분리 영상, YOLO 결과, tracking, 웹 표시가 하나의 프레임 번호로 일치한다.**

---

## 2. 폴더 구조

```text
AX_Parking2/
├── config/
│   ├── mosaic.yaml            # 모자이크 칸 ↔ 카메라 배치 (모든 원본 영상 공통)
│   ├── detection.yaml         # 기본 영상 제목, YOLO 모델/추론 설정
│   ├── tracking.yaml          # Local Tracking 파라미터
│   ├── global_tracking.yaml   # Global Tracking 파라미터
│   └── calibration/
│       └── camXX.json         # 카메라별 calibration (모든 원본 영상 공통)
├── data/
│   ├── videos/
│   │   ├── raw/<title>.mp4    # 모자이크 원본 (Git 제외)
│   │   └── <title>/camXX.mp4  # 분리 영상 (Git 제외)
│   ├── detections/<title>/    # YOLO 결과 (detections.jsonl, metadata.json)
│   └── maps/
│       ├── map.png            # BEV 지도 (1624 x 968)
│       ├── zones.json         # 주차 구역 정의
│       └── *.png              # 참고용 이미지
├── scripts/
│   ├── preprocess.py          # 원본 분리 + YOLO 검출
│   ├── calibrate_camera.py    # 카메라 calibration 도구
│   ├── play_mosaic.py         # (확인용) 서버 없이 bbox 재생 / 영상 저장
│   └── render_parking_zones.py# (확인용) 주차 구역 이미지 생성
├── src/
│   ├── mosaic.py              # 칸 배치, 영상 제목 → 경로 규칙
│   ├── detection/detector.py  # YOLO 래퍼 (VehicleDetector)
│   ├── calibration/
│   │   ├── projector.py       # CameraProjector: 칸 좌표 → BEV
│   │   └── mapping.py         # Homography + TPS, coverage 계산
│   └── tracking/
│       ├── local_tracker.py   # 카메라별 추적, 상태 판정
│       └── global_tracker.py  # 카메라 간 Global ID 연결
├── web/                       # 웹 뷰어 (index.html, app.js, style.css)
├── server.py                  # tracking 엔진 + API + 정적 파일 서버
└── requirements.txt
```

`outputs/`는 확인용 도구의 출력 위치이며 Git에서 제외된다.

---

## 3. 설치

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

- GPU(CUDA) 환경을 기준으로 한다 (`config/detection.yaml`의 `device: 0`).
- YOLO 가중치(`yolo26x.pt`)는 프로젝트 루트에 둔다.
- Windows에서 여러 Python이 설치돼 있으면 반드시 `.venv`의 Python으로 실행한다.
  (예: `.venv\Scripts\python.exe scripts\preprocess.py test00`)

---

## 4. 실행 방법

### 4.1 전처리: 원본 분리 + YOLO 검출

```bash
python scripts/preprocess.py test00
```

`data/videos/raw/test00.mp4`를 한 번 읽으면서

1. `config/mosaic.yaml`의 칸 배치대로 프레임을 잘라 `data/videos/test00/camXX.mp4` 7개로 저장하고
2. 잘라낸 같은 이미지(재압축 전)에 YOLO를 돌려 `data/detections/test00/`에 저장한다.

| 옵션 | 설명 |
|---|---|
| `--overwrite` | 기존 결과를 덮어쓴다 (없으면 기존 파일이 있을 때 중단) |
| `--max-frames N` | 앞 N프레임만 처리 (빠른 확인용) |
| `--no-split` | 분리 영상을 저장하지 않고 YOLO만 실행 |
| `--no-detect` | YOLO 없이 분리 영상만 저장 |
| `--fourcc` | 분리 영상 코덱 (기본 `mp4v`) |

참고: RTX 5070 기준 11초(330프레임) 영상이 약 40초 걸린다 (초당 약 8.5프레임 × 카메라 7대).

### 4.2 카메라 캘리브레이션 (카메라마다, 필요할 때만)

```bash
python scripts/calibrate_camera.py --camera cam01 --frame 100
```

- 원본 모자이크에서 해당 카메라 칸을 잘라 왼쪽 창에, BEV 지도를 오른쪽 창에 띄운다.
- 결과는 `config/calibration/cam01.json`에 저장된다. (점을 추가 / 삭제할 때마다 자동 저장)
- 배경 프레임을 다른 영상에서 가져오려면 `--video <title>`.

| 조작 | 동작 |
|---|---|
| 왼쪽 클릭 | 영상 점 → BEV 점 순서로 클릭해 보정점 1쌍 추가 |
| 마우스 휠 / 오른쪽 드래그 | 확대·축소 / 화면 이동 |
| C | coverage 히트맵 켜기/끄기 (빨강 = 보정점이 부족한 영역) |
| P | 보정점(빨간 점) 표시 켜기/끄기 |
| U | 마지막 점 취소 (대기 중인 영상 점이 있으면 그것을 취소) |
| S | 저장 |
| Q / ESC | 종료 (변경이 없으면 파일을 덮어쓰지 않음) |

영상 점을 찍으면 BEV 창에 현재 calibration으로 예측한 위치가 **초록색 PRED**로 표시된다.
BEV에서 실제 위치를 클릭하면 콘솔에 예측 오차(px)가 출력되므로,
점을 추가하면서 동시에 정확도를 확인할 수 있다.

### 4.3 서버 실행

```bash
python server.py
```

- `config/detection.yaml`의 `video` 값(영상 제목)을 대상으로 실행한다.
- 브라우저에서 `http://127.0.0.1:8000` 접속.
- calibration 파일이 없거나 깨진 카메라는 시작할 때 `[WARN]`을 출력하고 BEV 투영에서 제외된다.

웹 뷰어 조작:

| 조작 | 동작 |
|---|---|
| Space | 재생 / 일시정지 |
| A / D | 5초 뒤로 / 앞으로 |
| Shift + A / D | 30초 뒤로 / 앞으로 |
| `,` / `.` | 1프레임 뒤로 / 앞으로 |
| R | 처음으로 (tracking 초기화) |
| "트래킹 설정 재로드" 버튼 | tracking 설정과 calibration을 다시 읽음 (서버 재시작 불필요) |

### 4.4 확인용 도구

```bash
# 서버 없이 모자이크 + YOLO bbox 재생 (Space, A/D: 1프레임, J/L: 30프레임, Q)
python scripts/play_mosaic.py test00

# bbox가 그려진 영상으로 저장
python scripts/play_mosaic.py test00 --save outputs/test00_bbox.mp4 --no-show

# 주차 구역을 지도 위에 그린 이미지 → outputs/parking_zone_preview.png
python scripts/render_parking_zones.py
```

### 4.5 새 원본 영상 추가

1. `data/videos/raw/<새 제목>.mp4`에 넣는다. (칸 배치가 `config/mosaic.yaml`과 같아야 함)
2. `python scripts/preprocess.py <새 제목>`
3. `config/detection.yaml`의 `video`를 `<새 제목>`으로 바꾸고 서버를 실행한다.

calibration은 카메라 위치에만 의존하므로 다시 할 필요가 없다.
(카메라 각도가 바뀌었거나 칸 배치가 달라졌을 때만 다시 한다)

---

## 5. 설정 파일

### `config/mosaic.yaml`
모자이크 격자와 칸 ↔ 카메라 대응. 왼쪽 위부터 오른쪽, 아래 순서로 cam01, 02, 03, 05, 06, 07, 08.

```yaml
grid: {rows: 3, cols: 3}
cameras:
  - id: cam01
    cell: [1, 1]          # [행, 열], 1부터
  - id: cam03
    cell: [1, 3]
    # roi: [56, 0, 528, 360]   # (선택) 칸 안의 실제 화면 영역 [x, y, w, h]
```

`roi`를 지정하면 칸 안에서 그 영역만 카메라 화면으로 쓴다 (4:3 카메라의 좌우 검은 여백 제외용).
roi를 바꾸면 카메라 좌표가 달라지므로 **전처리와 calibration을 모두 다시** 해야 한다.
현재는 roi 없이 칸 전체(640x360)를 사용한다.

### `config/detection.yaml`
| 키 | 설명 |
|---|---|
| `video` | 서버 / calibration / 재생 도구의 기본 영상 제목 |
| `model.weights`, `model.device` | YOLO 가중치, GPU 번호 |
| `inference.imgsz / conf / iou / quantize / batch_size` | 추론 크기, 신뢰도·IoU 기준, FP16, 배치(카메라 수) |
| `classes.names` | 검출 대상 클래스 (car, motorcycle, bus, truck) |

### `config/tracking.yaml` (Local Tracking)
- 픽셀 단위 값은 **카메라 칸(640x360) 기준**이다. (1080p 기준으로 맞췄던 값의 1/3)
  - `match_distance_px: 18`, `min_motion_px: 5.5`, `stop_anchor_min_px: 5`, `parked_exit_min_px: 9`
- `*_bbox_ratio` 값은 bbox 크기에 비례하므로 해상도와 무관하다.
- 상태 전환 시간: `unknown_to_active_sec`, `active_to_stopped_sec`, `parked_after_sec` 등.

### `config/global_tracking.yaml` (Global Tracking)
- BEV 지도 픽셀 기준의 거리 / 속도 / 방향 / 시간 점수로 카메라 간 같은 차량을 연결한다.
- `base_match_distance_px`, `max_speed_px_per_sec`, `prediction_weight` 등.

---

## 6. 데이터 형식

### `data/detections/<title>/detections.jsonl`
한 줄이 모자이크의 한 프레임이다.

```json
{"frame_index": 0, "timestamp": 0.0,
 "cameras": {
   "cam01": [],
   "cam02": [{"x1": 148.6, "y1": 60.1, "x2": 277.3, "y2": 116.1,
              "class_name": "car", "confidence": 0.893}]
 }}
```

- bbox 좌표는 **잘라낸 칸 기준 픽셀** (칸 왼쪽 위 = 0, 0)
- `confidence` 0.2 이상만 저장
- tracking 결과(ID, 상태)는 저장하지 않으며, 서버가 실행 중에 계산한다.

### `data/detections/<title>/metadata.json`
생성 시각, 원본 경로·해상도·fps, 프레임 수, 카메라 목록, 검출 수,
YOLO 설정, 칸 배치(`layout.crop_rects`), 분리 영상 경로.
캐시가 어떤 조건으로 만들어졌는지 확인하는 용도이며 서버는 읽지 않는다.

**다시 만들어야 하는 경우:** 원본 영상, `config/mosaic.yaml`(칸 배치 / roi), YOLO 설정이 바뀌었을 때.
tracking 설정이나 calibration만 바뀌었다면 다시 만들 필요 없이 웹에서 재로드만 하면 된다.

### `config/calibration/camXX.json`
| 필드 | 설명 |
|---|---|
| `points[]` | 사용자가 찍은 보정점 (`image`: 칸 좌표, `bev`: 지도 좌표) |
| `homography` | 모든 점으로 계산한 3x3 Homography |
| `mapping` | Homography + TPS 잔차 보정 계수 (없으면 homography만 사용) |
| `reprojection` | Homography 단독 오차와 최종 mapping 오차 |
| `crop_rect` | 모자이크에서 잘라낸 칸 영역 |
| `converted_from` | (변환된 파일만) 원본 1080p calibration에서 변환한 정보 |

현재 calibration 7개는 이전 1080p 카메라 영상 기준 calibration을 칸 좌표로 변환한 것이다.
(16:9 칸은 x, y를 1/3로, 4:3 카메라(cam03, 06, 07)는 칸 안의 실제 화면 528x360 영역에 맞춰 변환)

---

## 7. 동작 방식

### 7.1 칸 좌표 → BEV 변환 (calibration)

```
BEV(p) = Homography(p) + w(p) · TPS_residual(p)
```

- **Homography**: 모든 보정점으로 최소자승 계산. 전체적인 원근 변환을 담당한다.
  RANSAC을 쓰지 않으며, 사용자가 찍은 점은 모두 정답으로 간주한다.
- **TPS (Thin Plate Spline)**: Homography로 설명되지 않는 잔차(렌즈 왜곡 등 위치별 비선형 오차)를
  정확 보간한다. 보정점에서는 지정한 BEV 위치를 그대로 통과한다. 점이 5개 이상일 때 사용한다.
- **w(p)**: 보정점들이 감싸는 영역(convex hull) 안에서는 1, 밖에서는 거리에 따라 연속적으로 0에 가까워진다.
  점이 없는 먼 영역에서 TPS가 발산하지 않고 Homography로 자연스럽게 돌아간다.
- **coverage**: 영상 각 위치에서 가장 가까운 보정점까지의 거리로 신뢰도를 계산해
  calibration 도구에 빨간 히트맵으로 표시한다. 빨간 곳에 점을 더 찍으면 된다.

구현: `src/calibration/mapping.py` (`CalibrationMapping`, `coverage_grid`),
`src/calibration/projector.py` (`CameraProjector.project(x, y)`). numpy와 OpenCV만 사용한다.

### 7.2 차량 위치

- bbox의 **바닥 중앙점** `((x1 + x2) / 2, y2)`을 차량 위치로 사용한다.
- 최근 몇 프레임의 median으로 흔들림을 줄인 뒤 BEV로 변환한다.

### 7.3 Local Tracking (카메라별)

- 프레임 간 bbox 위치와 IoU로 같은 차량을 연결해 Local ID를 부여한다.
- 상태:

| 상태 | 의미 |
|---|---|
| UNKNOWN | 처음부터 있던 차량, 아직 움직임이 확인되지 않음 |
| ACTIVE | 움직이는 중 |
| STOPPED | 움직이다 멈춤 |
| PARKED | 같은 위치에 일정 시간 이상 정지 |

- 움직임이 확인된 차량(`has_moved`)만 BEV로 투영한다.
  (처음부터 주차돼 있던 차량은 BEV에 올리지 않음)

### 7.4 Global Tracking (카메라 간)

- BEV 좌표 기준으로 위치, 예상 이동 위치, 진행 방향, 속도, 시간 차를 점수화해
  다른 카메라에 나타난 같은 차량에 같은 Global ID(G001 …)를 부여한다.
- UNKNOWN 차량이 움직이기 시작하면 ACTIVE 확정 전부터 기존 Global ID 후보를 미리 탐색한다.

### 7.5 웹 뷰어

- 모자이크 원본을 `<video>` 1개로 재생한다.
- 브라우저가 실제로 화면에 표시한 프레임 번호(`requestVideoFrameCallback`)로
  `/api/tracking/frame/{번호}`를 요청하므로 bbox / BEV가 영상과 같은 프레임을 가리킨다.
- bbox는 상태별 색으로 칸 위치에 그리며, ACTIVE 차량에만 ID 라벨(G / L)을 표시한다.
- BEV 지도에는 **ACTIVE 차량만** 카메라별 색으로 표시한다.
- 서버는 프레임을 순서대로 계산하며, 10초마다 tracking 상태를 저장(checkpoint)해 뒤로 이동할 때 사용한다.

### 7.6 서버 API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 웹 뷰어 |
| GET | `/api/health` | 상태 확인 |
| GET | `/api/tracking/info` | 카메라 목록, fps, 프레임 수, 모자이크 정보(영상 URL, 칸 위치) |
| GET | `/api/tracking/frame/{n}` | n번 프레임의 카메라별 bbox·상태·ID와 BEV 위치 |
| POST | `/api/tracking/reset` | tracking 초기화 |
| POST | `/api/tracking/reload` | tracking 설정과 calibration 다시 읽기 |

정적 파일: `/web/*` (웹), `/media/*` (`data/videos/`), `/map/*` (`data/maps/`).

---

## 8. 알려진 제약

- **브라우저 코덱**: 웹은 원본 모자이크를 그대로 재생한다. `test00`은 HEVC(H.265)라
  Windows의 Chrome / Edge + GPU 하드웨어 디코딩 환경에서 재생된다.
  재생되지 않으면 H.264로 변환한 파일이 필요하다 (ffmpeg 필요).
- **분리 영상 코덱**: `mp4v`라 OpenCV로는 읽히지만 브라우저 / VS Code 미리보기에서는 재생되지 않는다.
  확인할 때는 VLC 등을 사용한다.
- **칸 해상도**: 카메라 화면이 640x360(4:3 카메라는 실제 528x360)이라
  멀리 있는 작은 차량은 검출이 약할 수 있다.
- **차량 위치 편향**: bbox 바닥 중앙점은 차량 중심이 아니라 카메라 쪽 범퍼/바퀴 위치에 가까워
  화각에 따라 BEV 위치가 일정하게 치우칠 수 있다.
- **calibration 출처**: 현재 calibration은 이전 1080p 영상 기준 점을 변환한 것이다.
  녹화 시점이 달라 카메라 각도가 미세하게 바뀌었을 수 있으므로,
  calibration 도구의 PRED 표시로 확인하고 필요하면 점을 추가한다.
- **주차 구역 점유 대수**: 웹 BEV에 구역별 `점유/수용` 표시가 있지만 점유 계산은 아직 구현되지 않아 항상 0이다.
- **타임라인 앞으로 크게 이동**: 서버가 중간 프레임을 모두 계산하므로 긴 영상에서는 시간이 걸린다.
  (뒤로 이동은 checkpoint를 사용해 빠르다)

## 9. Git 관리

- 제외: `data/videos/`(원본·분리 영상), `*.pt`(YOLO 가중치), `outputs/`, `*.zip`, 캐시 파일
- 커밋: `data/detections/`(YOLO 결과), `config/calibration/`, `data/maps/`, 코드와 설정
- GitHub는 100MB가 넘는 파일을 거부한다. `detections.jsonl`은 영상 1분에 약 20MB이므로
  긴 영상의 결과는 커밋 전에 크기를 확인한다.
- `yolo26x.pt`, `yolo26l.pt`는 `.gitignore` 추가 전에 커밋돼 있어 아직 추적 중이다.
  추적을 끊으려면 `git rm --cached yolo26x.pt yolo26l.pt`.
