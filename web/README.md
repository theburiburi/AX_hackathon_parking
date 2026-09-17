# AX_Parking 웹 주차 관리

기존 PoC를 이식한 React + Django REST Framework + FastAPI 앱입니다.
모든 웹 코드·의존성 목록·실행 데이터는 이 `web/` 아래에 둡니다.
Python은 기존 `AX_Parking/.venv`를 공용으로 사용하며 `web/.venv`는 생성하지 않습니다.
원본 `poc/` 서버를 실행할 필요가 없습니다.

## 변경 내용과 Python 의존성

| 변경 영역 | 구현 내용 |
|---|---|
| `frontend/src/` | PoC 화면 이식, 영상 분석 메뉴 추가, 지도·로그 주기 갱신 |
| `frontend/src/videoSync.js` | 카메라별 시간차와 공통 재생 구간 반영 |
| `frontend/vite.config.js` | 주차 API·영상 분석 API 프록시 |
| `backend/tracking/` | 로그인·권한·차량 신청/승인·감지 이벤트·미디어 Range 제공 |
| `backend/tracking/project_media.py` | 기존 카메라 설정과 지도·영상 파일을 읽어 제공 |
| `backend/vision/` | 관리자 인증, 영상 업로드·분석·결과 다운로드, YOLO 모델 재사용 |
| `backend/seed.py`, `backend/fixtures/` | 독립적인 데모 계정과 JSON 초기 데이터 생성 |
| `.gitignore`, `backend/config/settings.py` | 실행 데이터 제외, 로컬 서명 키 생성 |
| `tests/`, `frontend/tests/`, `backend/tracking/test_workflows.py` | 영상 처리·동기화·권한·승인 흐름 검증 |

기존 AX_Parking Python 의존성에 추가된 패키지는 Django, djangorestframework,
django-cors-headers, fastapi, uvicorn, python-multipart, httpx입니다.
`requirements.txt`에는 기존 영상 의존성인 ultralytics, opencv-python, numpy, PyYAML도
포함해 웹과 YOLO 분석을 한 번에 설치합니다. PyTorch 등 Ultralytics의 의존성은 pip가 함께 설치합니다.
`requirements-yolo.txt`는 같은 목록을 참조하는 기존 설치 명령 호환용 파일입니다.
React·Vite 등 프런트엔드 의존성은 `frontend/package.json`과 lock 파일에서 관리합니다.

## 설치

AX_Parking/web에서 실행합니다. Python 3.10 이상과 Node.js가 필요합니다.

```powershell
# AX_Parking/.venv가 없다면 부모 폴더에 생성합니다.
python -m venv ../.venv
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm.cmd ci
cd ..
..\.venv\Scripts\python.exe backend/seed.py
```

초기화 시 8자 이상의 데모 비밀번호를 직접 입력합니다.
계정은 `admin`, `digital`, `cold-dx`, `steelmaking`이며 입력한 비밀번호를 사용합니다.
초기화는 기존 JSON 데이터를 덮어쓰지 않습니다. 기존 PoC 계정·신청·로그는 복사하지 않습니다.
이 작업 환경은 이미 초기화되어 있습니다. 생성된 비밀번호는 `backend/data/demo-password.txt`에서 확인합니다.
초기 차량 자료는 데모 fixture입니다. 실제 CCTV의 인식 결과가 아닙니다.

## 실행

세 터미널에서 각각 다음 명령을 실행합니다.

```powershell
# web 폴더에서: 주차 관리 API
..\.venv\Scripts\python.exe backend/manage.py runserver 127.0.0.1:8000
# web 폴더에서: 영상 분석 API
..\.venv\Scripts\python.exe -m uvicorn vision.main:app --app-dir backend --host 127.0.0.1 --port 8001
# web/frontend 폴더에서: 웹 화면
npm.cmd run dev
```

브라우저에서 http://localhost:8080 에 접속합니다.
`./run.ps1 parking`, `vision`, `frontend`, `init`, `test`도 사용할 수 있습니다.
PowerShell 정책에 막히면 위의 직접 실행 명령을 사용하세요.
기존 PoC가 같은 포트에서 실행 중이라면 먼저 종료해야 합니다.

## 구현 기능

- 로그인/로그아웃, 관리자·사용자 권한, 사용자 부서별 차량 조회
- 차량 추가/삭제 신청, 신청 이력, 관리자 승인/반려
- 관리자 CCTV 격자, 공통 재생/정지·탐색·배속·반복
- 주차장 지도·구역·차량 위치 마커·확대·상세, 3초 주기 차량 갱신
- 관리자 영상 업로드(500MB), 분석 진행률, 미리보기, AVI/JSONL 다운로드
- 관리자 감지 이벤트 API를 통한 차량 위치·상태·로그 갱신

## 기존 프로젝트 연결

주차 API는 `../cameras.yaml`을 기존 `src.camera_config`로 읽습니다.
환경 변수 `WEB_CAMERAS_CONFIG`로 다른 설정 파일을 지정할 수 있습니다.
영상은 설정된 파일을 읽고, 없으면 `backend/media/cctv/camera_01/` 등의 웹 로컬 파일을 찾습니다.
지도는 설정된 BEV 파일을 읽고, 없으면 `backend/media/maps/` 파일을 사용합니다.
원본 파일과 YAML은 수정하지 않습니다.

카메라별 `offset_frames / fps`를 브라우저 재생에 반영합니다.
타임라인의 0초는 영상들이 함께 존재하는 구간의 시작입니다.
브라우저 재생은 프레임 단위 동시 표시를 보장하지 않습니다.
OpenCV가 읽을 수 있는 영상이라도 브라우저에서 지원하는 코덱이어야 CCTV 재생이 가능합니다.

지도 마커는 `map_position: {map_id, x, y}`의 0~100 비율 좌표를 사용합니다.
기존 프로젝트의 BEV 픽셀 좌표를 전달할 때는 해당 지도 크기를 기준으로 비율로 변환해야 합니다.
`backend/data/map_layout.json`의 `map_id`가 실제 지도 파일명과 일치할 때만 구역을 표시합니다.
기본 구역은 PoC의 `parkinglot_map.jpg`에 대한 초안이므로 다른 지도에서는 그대로 사용하지 않습니다.
지도·영상이 없으면 화면에 자료 없음 상태가 표시됩니다.

## 선택적 YOLO 영상 분석

관리자 ‘실시간 감지 모드’ 탭은 `cameras.yaml`의 녹화 영상들을 동기화해 반복 재생하며
승용차·버스·트럭 검출 상자, 신뢰도, 카메라별 차량 수를 계속 표시합니다.
이 탭은 WEB_VISION_MODE와 관계없이 YOLO를 사용합니다. 네트워크 CCTV 라이브 입력은 현재 지원하지 않습니다.
서버의 공용 작업자가 모든 카메라를 batch 분석하고 접속자들은 같은 결과를 조회합니다.
목표 갱신 속도는 최대 5 FPS이며 추론 성능에 따라 낮아집니다. 화면 일시정지나 탭 이동으로
모든 접속자의 조회가 끊기면 약 12초 후 영상 읽기와 추론을 멈춥니다.
등록 차량 매칭·지속 ID·주차 상태 갱신은 수행하지 않습니다.
영상 API를 재시작하고 관리자 탭을 열면 시작합니다. 추가 Python 패키지 설치는 필요하지 않습니다.

기본 분석은 PoC의 윤곽선·밝기 분석입니다. `requirements.txt` 설치 후 YOLO를 사용하려면:

```powershell
$env:WEB_VISION_MODE = 'yolo'
..\.venv\Scripts\python.exe -m uvicorn vision.main:app --app-dir backend --host 127.0.0.1 --port 8001
```

YOLO는 기존 `src.tracking.BatchVehicleDetector`와 `../config.yaml`을 사용합니다.
설정된 모델 파일이 먼저 있어야 합니다. 모델은 작업들 사이에서 한 번 로딩해 재사용합니다.
업로드 영상에는 카메라 보정 정보가 지정되지 않으므로 검출 상자만 분석하며 BEV 투영하지 않습니다.
검출 번호는 프레임 내 번호입니다. 번호판 인식·Global ID·자동 주차 상태 판정과
등록 차량의 자동 위치 갱신은 구현하지 않았습니다.

## 검증

```powershell
..\.venv\Scripts\python.exe backend/manage.py check
..\.venv\Scripts\python.exe backend/manage.py test tracking
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm.cmd test
npm.cmd run build
```

주차 API와 영상 API가 실행 중이면 `web`에서 `..\.venv\Scripts\python.exe smoke_test.py`로
실제 HTTP 업로드·분석·다운로드도 점검할 수 있습니다. 직접 입력한 초기 비밀번호를 사용했다면
먼저 `$env:WEB_DEMO_PASSWORD = '초기화 시 입력한 비밀번호'`를 지정합니다.

Vite는 `/api`를 8000 포트, `/vision`을 8001 포트로 프록시합니다.
배포 시 동일한 프록시를 구성하거나 빌드 환경 변수 `VITE_API_URL`, `VITE_VISION_URL`을 지정합니다.
별도 출처의 영상 분석 API를 사용할 경우 해당 서버의 CORS 설정도 필요합니다.
JSON 저장과 DEBUG 설정을 사용하는 로컬 PoC이며 데이터베이스를 사용하는 운영 구성은 아닙니다.

## 파일 구성

`frontend/`: 화면·브라우저 동기 재생 / `backend/tracking/`: 인증·차량·신청·지도 API /
`backend/vision/`: 업로드·분석 작업 / `backend/fixtures/`: 데모 초기 자료 /
`backend/data/`: 초기화 후 생성되는 로컬 JSON / `tests/`: 영상 분석 검증.
가상환경·계정 데이터·미디어·분석 결과·로컬 서명 키는 web/.gitignore에서 제외합니다.
