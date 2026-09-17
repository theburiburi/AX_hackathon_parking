# Parking BEV

같은 장면을 촬영한 CCTV 영상들을 동기화해 YOLO로 차량을 검출하고,
카메라별 보정값으로 공통 BEV 지도에 표시하는 프로젝트입니다.
Python과 OpenCV로 실행하며 웹은 별도 담당자가 루트 `web/`에서 개발합니다.

현재 기본 실행은 batch 검출과 정적 BEV 지도 표시까지입니다. 차량의 BEV 위치 표시는 연결하지 않았습니다. 화면의 검출 번호는 프레임 내 번호이며
지속되는 차량 ID가 아닙니다. 카메라별 추적의 다중 영상 연결, Global ID와 위치 통합은 후속 작업입니다.

## 어디를 수정하나요?

| 작업 | 수정 위치 |
|---|---|
| 기본 실행·기능 연결 | `src/main.py` |
| YOLO 검출·local tracking | `src/tracking.py` |
| 좌표 변환 | `src/calibration/homography.py` |
| 카메라별 보정 행렬 준비 | `src/calibration/cameras.py` |
| 클릭 보정·저장 | `src/calibration/cli.py` |
| 영상 읽기·시간 동기화 | `src/playback/reader.py` |
| OpenCV 화면 표시 | `src/visualization.py` |
| 카메라 설정 로딩 | `src/camera_config.py` |
| 웹 | 루트 `web/` |

`src/calibrate.py`, `src/multi_player.py`는 보정·재생 도구의 기존 명령 진입점입니다.
Global ID 파일은 [합의서](docs/INTERFACE_AGREEMENT.md) 작성 후 구현할 때 추가합니다.

## 영상 묶음

```text
data/
├── videos/
│   └── scene1/
│       ├── 260914_1.mp4
│       ├── 260914_2.mp4
│       └── ...
└── maps/master_bev.png
```

`scene1`은 영상 묶음입니다. 다른 묶음이 생기면 `scene2/`처럼 추가할 수 있습니다.
영상 목록과 카메라별 설정은 루트 `cameras.yaml`에 명시합니다.
폴더를 추가하는 것만으로 실행 대상이 바뀌지는 않습니다.
영상·지도·모델 가중치는 Git에 포함하지 않습니다.

## 설치

Python 3.10 이상, 프로젝트 루트에서 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Linux/macOS에서는 `source .venv/bin/activate`로 가상환경을 활성화합니다.
`detection.device: auto`는 사용 가능한 CUDA가 있으면 GPU 0, 아니면 CPU를 선택합니다.
모델 가중치는 `models/detection/`에 둡니다. 가중치가 없으면 Ultralytics가
자동 다운로드를 시도할 수 있습니다.

## 1. 카메라 설정과 보정

`cameras.yaml`에 영상 경로, 실제 FPS, 시간차, 보정점을 지정합니다.
경로는 카메라 설정 파일 위치를 기준으로 해석합니다.

```yaml
bev_map: data/maps/master_bev.png
cameras:
  - id: cam01
    video: data/videos/scene1/260914_1.mp4
    fps: 30.0
    offset_frames: 0
    calibration:
      is_sample: true
      ransac_reproj_threshold: 5.0
      image_points: []
      bev_points: []
```

카메라별로 보정합니다. 현재 카메라 ID는 cam01, cam02, cam03, cam05, cam06, cam07, cam08입니다.

```powershell
python -m src.calibrate --camera cam01 --cameras-config cameras.yaml
```

CCTV와 BEV에서 같은 지점을 번갈아 클릭해 최소 4쌍을 지정합니다.
가능하면 넓게 분산된 6~12쌍을 사용합니다. `Enter`로 오차를 확인하고 `s`로 저장합니다.
선택한 카메라의 보정값만 갱신하며, 다른 카메라에서도 반복합니다.

- `Space`: 재생·정지, `n` / `p`: 다음·이전 프레임
- `Backspace`: 마지막 점 취소, `c`: 대응점 초기화
- 마우스 휠: 커서 위치를 중심으로 CCTV·BEV 각각 확대·축소 (1~16배)
- 우클릭 드래그: 확대된 화면 이동
- `r`: 두 화면의 배율·위치 초기화 (선택한 점은 유지)
- `q` / `ESC`: 종료

확대·이동 중에도 보정점은 원본 이미지 좌표로 저장됩니다.

BEV 좌표는 지도 이미지의 픽셀이며 미터가 아닙니다.
미보정 카메라는 차량 검출은 표시하지만 지도에 투영하지 않습니다.

## 2. 실행

```powershell
python -m src.main
```

기본값은 루트의 `cameras.yaml`과 `config.yaml`입니다.
현재 기본 실행 화면은 전체 너비를 사용하는 3×3 CCTV 격자입니다.
BEV 지도는 영상 크기를 줄이지 않고 마지막 행의 빈칸과 아래 여백 중 가장 크게 표시할 수 있는 공간에 배치합니다.
지도 비율은 유지하며, 현재 이 화면에는 차량의 BEV 좌표를 그리지 않습니다.
영상은 설정 순서대로 배치하며 7개 영상 사용 시 남은 두 칸은 비워 둡니다.
각 영상은 원본 비율을 유지해 표시합니다.
CCTV 칸은 영상 비율에 맞는 높이로 위쪽부터 간격 없이 붙이며, 남는 공간은 격자 아래에 둡니다.
창 테두리를 드래그하거나 최대화하면 변경된 크기에 맞춰 CCTV와 BEV를 다시 배치합니다.
영상·지도의 비율은 유지되며 `--width`, `--height`는 최초 창 크기를 지정합니다.
다른 영상 묶음을 사용할 때는 그 묶음의 카메라 설정 파일을 지정합니다.

```powershell
python -m src.main --cameras-config cameras.yaml --config config.yaml
```

- `Space`: 재생·정지
- `a` / `d`: 5초 이전·이후
- `q` / `ESC`: 종료
- `--width 700 --height 500`: 표시 크기

영상 시간차는 `cameras.yaml`의 `offset_frames`로 맞춥니다.
30 FPS에서 같은 사건이 기준 카메라 frame 300, 다른 카메라 frame 309라면
다른 카메라에 `offset_frames: 9`를 설정합니다. 양수는 해당 영상을 앞서 읽습니다.
설정 변경 후 프로그램을 다시 실행합니다.

검출 없는 동기 재생 도구도 사용할 수 있습니다.
이 도구는 `cameras.yaml` 대신 직접 영상 목록과 초 단위 offset을 받습니다.

```powershell
python -m src.multi_player --videos data/videos/scene1/260914_1.mp4 data/videos/scene1/260914_2.mp4 --offsets 0 0
```

## YOLO 끄기

이번 실행에서만 끄려면:

```powershell
python -m src.main --no-yolo
```

계속 꺼두려면 `config.yaml`의 기존 `detection` 아래에서 설정합니다.

```yaml
detection:
  enabled: false
  # model 등 나머지 설정은 유지
```

YOLO를 끄면 모델 로드·다운로드·추론·BEV 차량 좌표 계산을 하지 않습니다.
CCTV 동기 재생은 유지되며 하단에 `YOLO OFF`가 표시됩니다.
영상·지도 파일과 카메라 설정은 필요합니다. 기본 실행에서는 지도를 표시하되 보정 좌표를 계산하지 않습니다.
카메라 설정의 지도 경로·보정 항목은 보정 도구와의 공용 형식으로 유지합니다.
다시 켜려면 `enabled: true`로 설정하고 `--no-yolo` 없이 실행합니다.
`--no-yolo`가 YAML보다 우선하며, 실행 중 토글은 지원하지 않습니다.

## 전체 실행 옵션

모든 명령은 프로젝트 루트에서 실행합니다. 각 명령의 `--help`로도 확인할 수 있습니다.

### 기본 실행: `python -m src.main`

| 옵션 | 생략 시 | 의미 |
|---|---|---|
| `--cameras-config` | `cameras.yaml` | 영상·보정·동기화 설정 파일 |
| `--config` | `config.yaml` | YOLO 등 실행 설정 파일 |
| `--no-yolo` | 사용 안 함 | YAML 설정과 관계없이 YOLO 끄기 |
| `--width` | `700` | 전체 표시 너비, 최소 640 |
| `--height` | `500` | 전체 표시 높이, 최소 480 |

### 보정: `python -m src.calibrate`

| 옵션 | 생략 시 | 의미 |
|---|---|---|
| `--camera` | 없음 | 보정할 카메라 ID, 일반 사용 시 지정 |
| `--cameras-config` | `cameras.yaml` | 카메라 설정·보정 저장 파일 |
| `--frame` | `0` | 시작 프레임 번호, 0 이상 |
| `--scale` | `1.0` | 창 크기 배율, 양수. 휠 확대와 별개 |
| `--video` | 없음 | 이전 방식 호환용 입력 영상, `--camera` 없을 때 사용 |
| `--map` | 없음 | 이전 방식 호환용 지도, `--video`와 함께 필요 |
| `--config` | `config.yaml` | 이전 방식 호환용 보정 저장 파일. `--camera` 사용 시 무시 |

이전 방식은 지정 파일의 최상위 `calibration`에 저장하므로 일반 작업에서는
`--camera`를 사용합니다. 카메라 방식은 `cameras.yaml`의 해당 카메라만 갱신합니다.

### 영상 전용 도구: `python -m src.multi_player`

| 옵션 | 생략 시 | 의미 |
|---|---|---|
| `--videos` | 필수 | 재생할 영상 경로 목록 |
| `--offsets` | 모두 0 | 영상 순서의 초 단위 offset 목록 |
| `--columns` | `3` | 격자 열 수 |
| `--width` | `1280` | 창 너비 |
| `--height` | `900` | 창 높이 |

이 도구에는 YOLO와 BEV 지도가 없습니다. `Space` 재생·정지, `a`/`d` ±5초,
`q`/`ESC` 종료, 재생바로 0.1초 단위 탐색을 지원합니다.

## YAML 설정 항목

### `config.yaml`

아래 값은 현재 파일에 설정된 값입니다. 설정을 바꾼 뒤 프로그램을 재실행합니다.
모델의 상대 경로는 실행 디렉터리를 기준으로 해석합니다.

| 항목 | 현재 값 | 의미 / 적용 범위 |
|---|---|---|
| `detection.enabled` | `true` | YOLO 사용 여부. 생략 시 true |
| `detection.model` | `models/detection/yolo11s.pt` | 기본 실행 모델. 생략 시 yolo11n.pt 경로 |
| `detection.confidence` | `0.3` | 검출 confidence 기준 |
| `detection.iou` | `0.5` | 중복 검출 제거 IoU 기준 |
| `detection.image_size` | `640` | YOLO 입력 크기 |
| `detection.vehicle_classes` | `[2, 5, 7]` | COCO car, bus, truck class ID |
| `detection.device` | `auto` | auto, cpu 또는 GPU 번호 |
| `detection.tracker` | `bytetrack.yaml` | local tracking용 설정. 현재 batch 검출 실행에서는 사용하지 않음 |

기본 실행 `src.main`에는 목표 분석 FPS 제한 설정이 없습니다.

### `cameras.yaml`

| 항목 | 의미 / 생략 시 |
|---|---|
| `bev_map` | 공통 BEV 지도 경로, 필수 |
| `cameras` | 카메라 목록, 한 대 이상 |
| `cameras[].id` | 중복 없는 카메라 ID, 필수 |
| `cameras[].video` | 영상 경로, 필수 |
| `cameras[].fps` | 영상 FPS, 생략 시 30.0. 실제 영상과 일치해야 함 |
| `cameras[].offset_frames` | 프레임 단위 offset, 기본 0 |
| `cameras[].offset_seconds` | 이전 설정 호환용. offset_frames가 없을 때 FPS로 환산 |
| `cameras[].calibration` | 카메라별 보정 객체, 필수 |
| `calibration.is_sample` | true 또는 생략 시 미보정으로 간주 |
| `calibration.ransac_reproj_threshold` | RANSAC 허용 오차, BEV 픽셀 단위, 기본 5.0 |
| `calibration.image_points` | 원본 CCTV 픽셀 `[u, v]` 목록 |
| `calibration.bev_points` | 동일 지점의 BEV 픽셀 `[x, y]` 목록 |

두 점 목록은 같은 순서·같은 개수로 최소 4쌍이 필요합니다.
영상·지도 상대 경로는 `cameras.yaml` 파일 위치를 기준으로 합니다.

## 설정과 협업

- `cameras.yaml`: 영상 목록·FPS·offset·카메라별 보정점
- `config.yaml`의 `detection`: 모델·device·입력 크기·검출 임계값·차량 class

[담당표](docs/CONTRIBUTING.md) · [설계 원칙](docs/ARCHITECTURE.md) ·
[차량 ID·좌표 담당자 합의서](docs/INTERFACE_AGREEMENT.md)

## 테스트

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

기본 테스트에는 실제 영상이나 모델 가중치, 브라우저가 필요하지 않습니다.
