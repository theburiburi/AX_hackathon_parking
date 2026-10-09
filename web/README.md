# AX_Parking 웹 주차 관리

## 외부 기능 연동 원칙 · 2026-10-10

웹은 외부 프로젝트의 기능과 결과를 표시하는 역할을 우선합니다.
[기능 전수 조사·호출 흐름·남은 한계](EXTERNAL_INTEGRATION.md)에 전체 기능별 외부 구현과 웹의 역할을 정리했습니다.
`src.mosaic`의 영상·카메라 설정, `server.py`의 추적 엔진·차단기 기록 함수를 공통 어댑터에서 호출합니다.
지도 경계·수용량·위치 저장 검증도 외부 지도 자료를 따릅니다. 로그인·스케줄 등 외부에 없는 업무 기능은 유지합니다.
이번 변경은 `web/` 안에서만 수행했습니다.

## 현재 실행 방식 · 2026-10-10

기존 React 로그인·관리자/사용자 화면·섹션별 차량 운행 스케줄을 유지하고,
관리자 영상 기능을 **사전 계산 결과 재생**으로 통합했습니다.
웹 코드와 생성 결과는 `web/` 안에 두며, Python은 루트 `.venv`를 사용합니다.
루트 `server.py`, `src/`, `config/`, 원본 데이터는 수정하지 않습니다.

**일상 실행은 서버 하나, 접속 주소 하나입니다.**

```powershell
# AX_Parking 프로젝트 루트에서 실행
.\.venv\Scripts\python.exe -B web/run.py
```

접속 주소: http://127.0.0.1:8080/

`server.py`, 예전 8001 영상 서버, `npm run dev`를 동시에 실행하지 않습니다.
React는 미리 빌드한 `dist`를 Python 웹 서버가 제공합니다.
기본 호스트는 로컬 전용이며 외부 배포에는 HTTPS 등 별도 운영 환경 구성이 필요합니다.

### 처음 준비할 때

```powershell
# .venv가 없는 경우에만 생성
python -m venv .venv

# 업무 API + 웹 서버 + 오프라인 추적 캐시 생성 라이브러리
.\.venv\Scripts\python.exe -m pip install -r web/requirements.txt

# React 의존성 설치 및 화면 빌드
cd web/frontend
npm.cmd ci
npm.cmd run build
cd ../..

# 새 설치에서 JSON 초기 자료 생성. 기존 계정·스케줄은 덮어쓰지 않음
.\.venv\Scripts\python.exe -B web/backend/seed.py

# 기존 검출 결과로 추적·BEV 결과를 한 번 생성 (YOLO 실행 없음)
.\.venv\Scripts\python.exe -B web/build_replay.py --video test02

# 웹 실행
.\.venv\Scripts\python.exe -B web/run.py
```

이미 준비된 로컬에서는 설치·초기화·빌드·캐시 생성을 반복하지 않고 `web/run.py`만 실행합니다.
`--port 8081`로 포트를 바꿀 수 있고, 종료는 실행한 터미널에서 Ctrl+C입니다.

웹 재생에는 YOLO·PyTorch·GPU가 필요 없습니다. 오프라인 추적 캐시는 CPU로 생성합니다.
최초 YOLO 검출 결과까지 생성하는 컴퓨터만 루트 `requirements.txt`와 가중치가 필요합니다.
팀원이 같은 코드·설정으로 만든 `web/backend/replay_data/<영상 이름>/` 전체를 전달받으면
운영 컴퓨터에는 아래의 가벼운 실행 의존성만 설치할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r web/requirements-runtime.txt
```

Node.js는 화면 빌드 시에만 필요합니다. `web/frontend/dist`도 함께 전달받으면
운영 컴퓨터에서는 npm이나 Node 서버를 실행하지 않습니다.

### 필요한 파일

| 경로 | 용도 |
|---|---|
| `data/videos/raw/test02.mp4` | 브라우저에서 재생할 원본 모자이크 영상 |
| `data/detections/test02/detections.jsonl` | YOLO가 이미 검출한 프레임별 박스 |
| `data/detections/test02/metadata.json` | 해상도·FPS·카메라 칸 배치 확인 |
| `config/calibration/camXX.json` | 기존 카메라→BEV 보정 |
| `config/mosaic.yaml`, `tracking.yaml`, `global_tracking.yaml` | 카메라 배치와 추적 설정 |
| `data/maps/map.png`, `zones.json` | 지도와 A~N 구역 경계 |
| `data/gate_logs/gate_logs.json` | 차단기 기록. `video`와 `fps`가 재생 영상과 일치해야 함 |
| `web/backend/replay_data/test02/` | 사전 계산한 결과·프레임 인덱스·manifest |

생성 도구는 원본 영상·검출 캐시·metadata의 해상도, FPS, 프레임 수, 칸 배치를 검사합니다.
보정 해상도가 같은 종횡비로 다르면 검출 좌표를 보정 해상도로 변환해 추적과 BEV를 계산하고,
영상 박스는 원본 크기로 복원해 저장합니다. 카메라 각도 변경까지 자동 보정하지는 않습니다.

기본 영상은 `config/detection.yaml`의 `video: test02`로 선택합니다.
루트 설정을 수정하지 않고 웹에서만 영상을 선택하려면:

```powershell
$env:WEB_REPLAY_VIDEO = 'test02'
.\.venv\Scripts\python.exe -B web/build_replay.py
.\.venv\Scripts\python.exe -B web/run.py
```

영상·검출 결과·추적 코드·보정·지도·칸 배치를 변경했다면 캐시를 다시 생성합니다.

```powershell
.\.venv\Scripts\python.exe -B web/build_replay.py --video test02 --overwrite
```

새 manifest를 마지막에 교체하므로 실패 시 기존 manifest를 덮어쓰지 않습니다.
다른 컴퓨터로 복사해 파일 수정 시각이 달라져도 SHA-256으로 원본 내용이 같음을 확인하면 사용 가능합니다.
변경된 원본/설정 또는 미완성 캐시는 안내 오류를 반환하며 HTTP 요청에서 재분석하지 않습니다.

### 계정과 유지되는 업무 기능

현재 로컬의 더미 계정은 모두 비밀번호 `test`입니다. 새 설치에서 seed를 실행하면 직접 지정한
비밀번호를 사용하며 기존 비밀번호는 바꾸지 않습니다.

| 아이디 | 이름 | 권한/섹션 |
|---|---|---|
| `admin` | 관리자 | 전체 업무 및 영상 분석 조회 |
| `digital` | 권혁돈 | 디지털통신기술섹션 |
| `digital2`, `digital3` | 디지털 사용자 2, 3 | 디지털통신기술섹션 |
| `cold-dx` | 조의재 | 냉간 DX 섹션 |
| `steelmaking` | 한용만 | 제강연주섹션 |

사용자는 본인 섹션의 차량·일일 스케줄을 조회합니다. 일정 등록·수정·취소,
차량/운전자 시간 중복 방지, 관리자 전체 섹션 필터를 유지합니다.
영상·프레임 결과·영상 지도는 서버에서도 관리자 권한을 검사합니다.
제거했던 관리 요청/승인 화면은 다시 추가하지 않았습니다.

### 관리자 영상 화면

관리자로 로그인하면 **실시간 분석** 화면을 바로 표시합니다.
상단 실시간·차량 운행 스케줄 메뉴와 운영 현황·실시간 분석 전환 버튼은 제거했습니다.
영상 재생, 지도, 실시간 추적 ON/OFF, 차단기 기록을 한 화면에서 제공합니다.
넓은 화면에서는 왼쪽에 큰 영상, 오른쪽에 작은 지도와 그 아래 차단기 기록을 배치합니다.
화면 폭이 1,100px 이하이면 영상 → 지도 → 차단기 기록 순서로 세로 배치합니다.
일반 사용자는 기존 차량 현황·차량 운행 스케줄 메뉴를 사용합니다.

- 원본 모자이크 영상 위에 Canvas로 저장된 박스를 겹쳐 표시합니다.
- 재생/일시정지, ±5초, 프레임 이동, 배속, 반복, 박스 표시, 카메라 필터를 제공합니다.
- 단축키: Space 재생/정지, A/D ±5초, Shift+A/D ±30초, 쉼표/마침표 한 프레임, R 처음으로.
- 실제 표시된 영상 프레임을 기준으로 결과를 선택합니다. 결과가 늦으면 이전 박스를 대신 표시하지 않습니다.
- **실시간 추적 모드 ON/OFF** 버튼은 기본 OFF입니다. ON을 누르면 영상 재생을 시작하고
  현재 영상 프레임의 차량 위치와 추적 ID를 지도에 표시합니다. OFF는 차량 마커를 즉시 숨기며
  영상 재생은 계속됩니다. 일시정지하면 차량 위치도 멈추고, 탐색하면 해당 프레임 위치로 바뀝니다.
- 추적 모드는 기존 캐시의 `frame.bev`를 사용합니다. 이동을 시작해 기존 엔진에서 추적된 차량만
  표시하며, 처음부터 주차 중인 차량의 모든 검출을 추적 마커로 바꾸지는 않습니다.
  루트 README의 ACTIVE 차량 표시 기준과 카메라 필터를 적용합니다. 외부 엔진의 관측 좌표와 ID를 그대로 사용하며 웹에서 신뢰도에 따른 위치 선택이나 Global ID 재결합을 하지 않습니다.
  잘못된 좌표·지도 범위 밖 위치·결과 없는 프레임에는 마커를 표시하지 않습니다.
  YOLO·추적 엔진은 재생 중 실행하지 않습니다. “실시간”은 녹화 영상의 현재 재생 시점에 동기화된 위치 갱신을 뜻합니다.
- A~N 구역에 마우스를 올리거나 Tab으로 초점을 맞추면 추적 모드와 관계없이 이동 차량 수를 보여줍니다.
- 구역 수는 기존 엔진이 BEV에 출력한 ACTIVE 이동 차량 관측만 집계합니다. 처음부터 주차돼 있던 차량과 STOPPED/PARKED는 추가 투영하지 않습니다. 주차면 점유 수가 아닙니다.
- 차단기 기록은 현재 프레임까지의 기록만 표시하며 클릭하면 해당 프레임으로 이동합니다.
- 기록 첫 줄은 `[입차] 123 가 4567` 또는 `[출차] 12 나 3456` 형식입니다. 번호판은 기록의
  `plate` 값을 사용하며, 값이 없으면 `[입차] 번호판 미확인`처럼 표시합니다. 하단 시각과 프레임 번호는 화면에 표시하지 않습니다.
- 차단기 기록은 `data/gate_logs/gate_logs.json`을 우선 읽고, 해당 파일이 없으면 기존 `gate_log.json`을 읽습니다. 파일 수정 후 페이지를 새로고침하면 반영되며 추적 캐시를 다시 만들 필요가 없습니다. 공유 파일 둘 다 없으면 외부 기본 경로인 `data/gate_logs/<title>.json`을 읽습니다. 선택된 파일의 형식·영상 이름·FPS가 맞지 않으면 기록을 비웁니다. 진단 사유는 manifest API의 `warnings`에 남기며 화면 하단의 분석 데이터 안내 영역은 제거했습니다.
- 등록 차량 감지 로그와 영상 차단기 기록은 구분합니다.
- Global ID는 분석 영상의 추적 번호이며 번호판·등록 차량·스케줄과 자동 연결하지 않습니다.

서버는 최대 120프레임씩 읽고, 브라우저는 기본 60프레임씩 선행 요청하며 최대 360프레임만 보관합니다.
사용자별 재생 위치는 독립적이며 뒤로 이동해도 저장된 ID가 유지됩니다.
JSON 응답은 압축하지만 영상 Range 응답은 압축하지 않습니다.
화면 탭을 벗어나면 요청을 취소하고 재생을 멈추며 브라우저가 숨겨져도 재생을 멈춥니다.

OpenCV에서 열리는 영상도 브라우저 코덱 지원에 따라 재생되지 않을 수 있습니다.
HEVC 미지원 환경은 동일 프레임 수·FPS·해상도를 보존한 H.264 영상이 필요합니다.
원본을 교체했다면 metadata와 캐시의 일치 여부도 확인해야 합니다.

### 코드 구조

- `frontend/src/main.jsx`: 기존 로그인, 사용자 현황·스케줄 메뉴, 관리자 실시간 분석 연결.
- `frontend/src/VehicleSchedule.jsx`: 기존 섹션별 운행 일정.
- `viewer-rendering.js`: 기존 app.js의 박스·카메라 이름·BEV 그리기 함수를 공유.
- `frontend/src/CachedReplay.jsx`, `replayBuffer.js`, `cached-replay.css`: 영상·박스·지도·기록 재생과 제한된 프레임 캐시.
- `backend/native_project.py`: 외부 영상·배치·추적·차단기 함수의 읽기 전용 연결.
- `backend/replay/export.py`: 루트 TrackingEngine을 재사용하는 오프라인 생성기.
- `backend/replay/store.py`: 유효성 검사 및 외부 DetectionCacheStore를 통한 인덱스 기반 결과 읽기. 추적 엔진을 import하지 않음.
- `backend/tracking/replay_views.py`: 기존 로그인 토큰으로 보호되는 읽기 전용 재생 API.
- `backend/tracking/project_media.py`: 새 모자이크 프로젝트의 지도·미디어 연결.
- `backend/config/frontend.py`: React dist 제공.
- `run.py`: Waitress로 업무 API·React·영상 파일을 한 포트에서 제공.
- `build_replay.py`: 캐시 생성 CLI.

루트 `server.py`는 import할 때 엔진을 초기화하므로 공통 어댑터는 AST로 TrackingEngine과 관련 정의 또는 차단기 기록 함수만
로드합니다. 원본 소스를 복제하거나 변경하지 않습니다. 원본 엔진 구조가 크게 바뀌면 이 어댑터를 점검해야 합니다.

현재 메뉴에서 사용하지 않는 실시간 YOLO 서버·업로드 분석·개별 CCTV 동기 재생 코드와
해당 구버전 테스트, 설치 파일, 점검 스크립트는 삭제했습니다. 기존 업로드 결과인
`backend/vision/data/`는 보존하며 현재 서버에서는 사용하지 않습니다.
중복 WSGI 진입점은 `backend/config/wsgi.py`로 통일했습니다.

`web/index.html`, `app.js`, `style.css`는 루트 `server.py`가 직접 참조하므로 유지합니다.
통합 웹 서버 `web/run.py`는 `frontend/dist/`의 React 화면을 제공합니다.

### API와 검증

관리자 전용 GET: `/api/replay/manifest/`, `/api/replay/frames/?start=0&count=60`,
`/api/replay/video/`, `/api/replay/map/`. 영상은 Range/HEAD를 지원합니다.
기존 로그인·스케줄 API는 유지합니다.

```powershell
.\.venv\Scripts\python.exe -B web/backend/manage.py test tracking
.\.venv\Scripts\python.exe -B -m unittest discover -s web/tests -v
cd web/frontend
npm.cmd test
npm.cmd run build
```

외부 연동 정리 후 Django 업무·재생 테스트 38개, 캐시·외부 연동 13개,
프론트엔드 27개 테스트와 React 빌드를 통과했습니다.
실제 4,980프레임 캐시를 기존 엔진으로 다시 생성하고 지도 14개 구역·차단기 기록 6건·영상 Range 응답을 확인했습니다.
기존 캐시에서 웹 자체 추가 필드를 제외한 후 4,980프레임 전체를 비교해 기존 엔진의 좌표·ID·상태·박스가 보존됨을 확인했습니다.
외부 코드·설정·자료와 사용자 데이터 46개 파일의 작업 전후 SHA-256이 같아 변경되지 않았음을 확인했습니다.
연결 가능한 브라우저가 없어 실제 코덱 재생과 화면 조작은 직접 확인하지 못했습니다.

`web/run.ps1`은 기본으로 통합 서버를 실행하며 `prepare`, `build`, `init`, `test`도 지원합니다.
구형 개별 서버 실행 옵션 `parking`, `frontend`는 제거했습니다.
React 개발 화면이 필요할 때만 `web/frontend`에서 `npm.cmd run dev`를 실행합니다.
개발 화면은 `http://localhost:5173/`이며, 먼저 실행한 8080 통합 서버로 API를 프록시합니다.
운영에서는 8080 서버만 실행합니다.
영상·검출 결과·모델·생성 캐시·dist·node_modules·DB·서명 키는 Git에서 제외합니다.

### 실행에 불필요한 부분 정리 · 2026-10-10

- 제거: 화면에서 사용하지 않는 관리 요청·승인 API, 구형 개별 CCTV API·카메라 등록 연결 코드와 관련 테스트.
- 제거: 이전 운영 현황·개별 CCTV·관리 요청 화면의 미사용 CSS, 중복 서버 실행 옵션, CORS 설정과 의존성.
- 정리: 현재 manifest가 참조하지 않는 이전 프레임·인덱스, 생성된 Ultralytics 설정, 내용이 없는 SQLite 파일. 약 181 MiB를 확보했습니다.
- 유지: 로그인·섹션별 스케줄·등록 차량 위치 갱신·현재 영상 재생, 원본 자료와 기존 업로드 자료, 현재 캐시·dist·개발 및 테스트 코드.
- 외부 `server.py`가 참조하는 `web/index.html`, `app.js`, `style.css`는 필요하므로 보존했습니다.
- 관리 요청 API는 더 이상 제공하지 않습니다. 기존 `backend/data/vehicle_requests.json`은 보관하고 새 설치에서는 생성하지 않습니다.

새로운 설치 라이브러리는 없습니다. 기존 실행 명령은 그대로입니다.

```powershell
.\.venv\Scripts\python.exe -B web/run.py
```

### 루트 구현 재사용 정리 · 2026-10-10

외부 추적 결과에 웹이 따로 지도 위치를 만드는 코드를 제거했습니다.
`server.py`의 `TrackingEngine`이 만든 `bev`를 그대로 사용하고,
`DetectionCacheStore.read_frame()`으로 캐시 프레임을 읽습니다.
기존 `app.js`의 `drawCameraLabel()`, `drawDetection()`, `drawBevTracking()`은
`viewer-rendering.js`로 옮겨 원래 뷰어와 React가 같은 함수 본문을 호출합니다.
웹 자체 SVG 차량 마커·상태 색상·별도 박스 그리기는 제거했습니다.

구역 툴팁은 현재 엔진이 출력한 이동 차량만 표시합니다. 처음부터 주차된 차량은
루트 README의 `has_moved` 기준에 따라 지도 집계에 포함하지 않습니다.
로그인·섹션별 스케줄과 사전 계산 재생 방식은 유지하며 변경은 `web/` 내부에 한정했습니다.
