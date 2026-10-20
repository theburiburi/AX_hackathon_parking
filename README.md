# AX Parking

주차장 CCTV 모자이크 영상의 차량 검출·추적 결과를 지도에 표시하고, 섹션별 차량 현황과 운행 일정을 관리하는 프로젝트입니다.

현재 통합 웹의 실행 진입점은 **`web/run.py`**, 접속 주소는 **http://127.0.0.1:8080/** 입니다.
설치, 데모 촬영, JSON 작성, API와 장애 처리에 대한 상세 설명은 [통합 웹 운용 문서](web/README.md)를 참고하세요.

## 현재 제공 기능

- 관리자: 녹화 영상, 기존 모델의 검출 박스·Global ID·지도 추적, 차단기 입출차 기록, 구역별 주차 현황.
- 사용자: 소속 섹션의 차량번호·주차 상태, 지도 구역별 대수, 운행 일정 등록·수정·취소.
- 관리자 영상 시점에 따른 사용자 차량 상태·구역별 주차 대수 동기화.
- 같은 섹션의 일정 공유와 약 1초 간격 자동 갱신, 차량·운전자 중복 예약 방지.
- `현재 주차 대수 / 최대 주차 가능 대수` 표시. 초기 대수·정원은 JSON으로 설정.

사용자 지도에는 개별 차량 아이콘·번호판을 그리지 않습니다. 지도 옆 차량 목록에서 차량별 상태를 확인합니다.
관리자 지도 추적 표시는 별도로 제공하며, 재생 조작 바는 관리자 화면 맨 아래에 있습니다.

## 빠른 실행

아래 명령은 **AX_Parking 루트의 PowerShell** 기준입니다.
가상환경·의존성·업무 데이터·React 빌드·재생 캐시가 준비됐다면 서버만 실행합니다.

```powershell
.\.venv\Scripts\python.exe -B web/run.py
```

종료는 서버 터미널에서 `Ctrl+C`입니다. 통합 웹 실행에 루트 `server.py`를 함께 실행할 필요는 없습니다.

처음 설치하는 경우:

```powershell
# .venv가 없을 때만 생성
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Push-Location web/frontend
npm.cmd ci
npm.cmd run build
Pop-Location

# 없는 업무 JSON만 생성하며 기존 파일은 보존
.\.venv\Scripts\python.exe -B web/backend/seed.py
```

영상 자료를 준비한 뒤 재생 캐시를 생성하고 실행합니다.
현재 `config/detection.yaml`의 기본 영상 제목은 `video`입니다.

```powershell
.\.venv\Scripts\python.exe -B web/build_replay.py --video video
.\.venv\Scripts\python.exe -B web/run.py
```

기존 캐시를 다시 생성해야 할 때만 생성 명령에 `--overwrite`를 붙입니다.
필요한 원본 영상·검출 결과·지도·보정 파일은 [입력 자료와 캐시 관리](web/README.md#입력-자료와-재생-캐시)에 정리했습니다.

## 동작 절차

```text
모자이크 원본 영상
  → 전처리: 카메라별 분리 + YOLO 검출 + 화면 모드 기록
  → 보정·Local/Global Tracking을 사용해 웹 재생 캐시 생성
  → 통합 서버가 원본 영상과 프레임별 결과 제공
  → 관리자 영상 시점 저장
  → 같은 시점의 차량 상태·구역별 주차 현황을 사용자에게 제공
```

검출과 추적은 분리되어 있습니다. `scripts/preprocess.py`는 YOLO 검출 결과를 만들고,
`web/build_replay.py`는 기존 검출 결과로 추적·지도 결과를 사전 계산합니다.
통합 웹에서 영상을 재생할 때는 YOLO 추론을 실행하지 않습니다.
수동 주차 시나리오가 선택 영상과 일치하면 웹의 주차 집계·등록 차량 상태에는 해당 시나리오를 우선 사용합니다.
운행 일정의 날짜·시간은 영상 타임라인과 독립적인 업무 데이터입니다.

## 파일 구조

```text
AX_Parking/
├── config/
│   ├── detection.yaml          # 기본 영상 제목·YOLO 설정
│   ├── mosaic.yaml             # 모자이크 칸과 카메라 배치
│   ├── tracking.yaml           # 카메라별 추적 설정
│   ├── global_tracking.yaml    # 카메라 간 ID 연결·주차 판정 설정
│   ├── gate.yaml               # 차단기 자동 감지 설정
│   └── calibration/            # 카메라별 영상→지도 보정
├── data/
│   ├── videos/raw/             # 모자이크 원본 영상
│   ├── videos/<title>/         # 분리 영상
│   ├── detections/<title>/     # detections.jsonl·metadata.json·view_modes.json
│   ├── maps/                   # 지도와 zones.json
│   ├── gate_logs/              # 차단기 입출차 로그
│   └── parking_logs/           # 수동 주차 시나리오
├── scripts/                    # 전처리·보정·화면 모드·차단기 분석 도구
├── src/                        # 기존 검출·보정·Local/Global Tracking 구현
├── web/
│   ├── README.md               # 상세 운용 문서
│   ├── run.py                  # 통합 웹 서버, 기본 8080
│   ├── build_replay.py         # 웹 재생 캐시 생성
│   ├── initialize_parking.py   # 초기 주차 JSON 검증·가져오기
│   ├── backend/                # Django API·업무 JSON·재생 캐시
│   ├── frontend/               # React 화면·프론트엔드 테스트
│   ├── tests/                  # 웹 캐시·기존 모델 연동 테스트
│   └── index.html·app.js 등     # 루트 server.py용 기본 분석 뷰어
├── server.py                   # 기존 분석 서버, 기본 8000
├── tests/                      # 기존 모델·기본 뷰어 테스트
└── requirements.txt            # Python 의존성
```

## 분석 자료 준비와 기존 뷰어

검출 결과를 전달받았다면 전처리는 생략합니다. 새 영상은 다음 순서로 준비합니다.
`video`는 `data/videos/raw/video.mp4`의 파일 제목이며 다른 영상을 사용하면 제목을 바꿉니다.

```powershell
# 원본 분리·YOLO 검출. 가중치·추론 장치 설정은 config/detection.yaml 확인
.\.venv\Scripts\python.exe -B scripts/preprocess.py video

# 화면 모드 파일이 없는 기존 검출 자료에 대해 실행
.\.venv\Scripts\python.exe -B scripts/detect_view_modes.py video

# 보정이 필요한 카메라에 대해 실행
.\.venv\Scripts\python.exe -B scripts/calibrate_camera.py --camera cam01 --video video --frame 100
```

보정 도구에서는 영상 점과 지도 점을 순서대로 선택해 대응점을 추가합니다.
보정 파일은 `config/calibration/camXX.json`에 저장됩니다.
지도·카메라 배치·보정·추적 설정을 변경했다면 통합 웹 재생 캐시도 다시 생성합니다.

기존 모델을 직접 확인하는 기본 분석 뷰어는 별도로 실행할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -B server.py
```

주소는 **http://127.0.0.1:8000/** 입니다.
이 서버는 기존 추적 엔진을 요청에 따라 실행하며, 통합 웹의 로그인·일정·공유 재생 시점 기능은 제공하지 않습니다.
두 서버의 API와 캐시 운용 방식은 다르므로 통합 웹 작업은 [web/README.md](web/README.md)를 기준으로 진행합니다.

## 검증과 배포 자료

웹 검증 명령과 개발 서버 실행법은 [개발과 검증](web/README.md#개발과-검증)에 있습니다.
원본·분리 영상, YOLO 가중치, 대용량 검출 JSONL, `.venv`, `node_modules`, React `dist`,
웹 재생 캐시는 Git에서 제외됩니다. 새 컴퓨터에서는 해당 자료를 별도로 준비하거나 생성해야 합니다.
업무 JSON은 `web/backend/data/`, 초기 템플릿은 `web/backend/fixtures/`에서 관리합니다.
