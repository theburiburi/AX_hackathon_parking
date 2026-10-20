# AX Parking 통합 웹 운용 문서

현재 코드 기준: **2026-10-20**. 명령은 별도 안내가 없으면 **AX_Parking 프로젝트 루트의 PowerShell**에서 실행합니다.

통합 웹은 React 화면과 Django 업무 API를 Waitress 서버 하나로 제공합니다.
관리자는 녹화 영상과 사전 계산된 분석 결과를 재생하고, 사용자는 같은 영상 시점의 차량 상태·주차 현황과 섹션별 운행 일정을 확인합니다.
화면의 ‘실시간 분석’은 현재 재생 프레임을 따라가는 표시 기능이며, 재생 중 YOLO를 새로 실행하는 기능은 아닙니다.

## 최신 화면과 기능

| 구분 | 현재 동작 |
|---|---|
| 화면 테마 | 사용자 차량 현황·운행 일정은 밝은 테마, 관리자와 공용 로그인은 다크모드 |
| 관리자 화면 | 왼쪽 분석 영상, 오른쪽 위 지도·아래 차단기 기록. 별도 구역별 현재 주차 표는 표시하지 않음 |
| 관리자 재생 조작 | 재생·일시정지·배속·프레임 이동·반복·타임라인을 화면 맨 아래에 배치 |
| 사용자 차량 현황 | 지도와 차량 목록 표시. 별도 구역별 현재 주차 표는 표시하지 않음 |
| 사용자 지도 | 구역 경계·구역명·주차 대수 표시. 개별 차량 아이콘·번호판·연결선·별도 차량 표시 칸은 제공하지 않음 |
| 시점 동기화 | 관리자 영상 시점으로 차량 상태와 주차 현황을 자동 갱신. ‘관리자 영상 연동 · 00:00’ 안내는 표시하지 않음 |
| 주차 대수 | 현재 대수 / 최대 대수. 정원 초과도 실제 대수 그대로 표시하며 오버플로우 안내 문구는 표시하지 않음 |
| 차량 선택 | 운행 일정 입력과 시간표에 차량번호·소속을 표시하며 차종 설명은 생략 |
| 일정 공유 | 같은 섹션의 같은 날짜 시간표에 등록·수정·취소 결과를 약 1초 간격으로 자동 반영 |
| 평일 반복 | 최대 한 달, 월~금만 운행. 주말 시작이면 첫 운행일 안내 및 저장 후 실제 운행일 시간표 표시 |

차량 현황·주차 대수와 운행 일정은 서로 다른 데이터입니다. 일정 등록만으로 입차·주차 완료 상태나 주차 대수가 변경되지는 않습니다.

## 실행과 최초 설치

### 이미 준비된 환경

```powershell
.\.venv\Scripts\python.exe -B web/run.py
```

접속: **http://127.0.0.1:8080/** 또는 **http://localhost:8080/**.
종료: 실행 터미널에서 `Ctrl+C`. 포트 변경은 `--port 8081`처럼 지정합니다.
가상환경을 활성화하지 않아도 위 경로로 루트 `.venv`의 Python을 사용합니다.

### 처음 설치할 때

Python 의존성은 루트 [requirements.txt](../requirements.txt), 프론트엔드 의존성은 [package-lock.json](frontend/package-lock.json)으로 관리합니다.
Python은 루트 `.venv`를 사용합니다. 현재 프론트엔드에 설치된 Vite 8.2.2의 Node.js 요구 범위는 `^20.19.0 || >=22.12.0`입니다.

```powershell
# .venv가 없는 경우에만 생성
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Push-Location web/frontend
npm.cmd ci
npm.cmd run build
Pop-Location

# 없는 업무 JSON만 생성. 기존 파일은 덮어쓰지 않음
.\.venv\Scripts\python.exe -B web/backend/seed.py
```

`web/frontend/dist/`가 실제 8080 화면입니다. 프론트엔드 소스만 수정하고 빌드하지 않으면 8080 화면에는 적용되지 않습니다.
업무 데이터는 JSON 파일에 저장합니다. 현재 기능을 실행하기 위해 데이터베이스 마이그레이션을 수행할 필요는 없습니다.

기본 계정 템플릿은 다음과 같습니다. 초기 템플릿의 비밀번호는 `test`이며, 실제 로그인에는 `backend/data/users.json`에 저장된 값을 사용합니다.

| ID | 역할·조회 범위 |
|---|---|
| `admin` | 관리자 분석 화면 |
| `digital`, `digital2`, `digital3` | 디지털통신기술섹션 |
| `steelmaking` | 제강연주섹션 |
| `cold-dx` | 냉간 DX 섹션 |

`seed.py`는 기존 비밀번호·일정을 재설정하지 않습니다. 이미 설치한 환경에서는 `fixtures/` 수정만으로 기존 `data/` 파일이 바뀌지 않습니다.

### 입력 자료와 재생 캐시

현재 기본 영상은 `config/detection.yaml`의 `video: video`입니다.
다른 영상을 사용하면 아래 명령의 `video`를 해당 파일 제목으로 바꿉니다.

| 루트 기준 경로 | 용도 |
|---|---|
| `data/videos/raw/<title>.mp4` | 브라우저에서 재생하는 모자이크 원본 |
| `data/detections/<title>/detections.jsonl` | 카메라별 검출 박스 |
| `data/detections/<title>/metadata.json` | 원본 크기·FPS·프레임 수·카메라 배치. 캐시 생성 시 일치 여부 검증 |
| `data/detections/<title>/view_modes.json` | 전체/축소 화면 구간. 레터박스 좌표 보정에 사용 |
| `config/mosaic.yaml` | 모자이크 칸과 카메라 배치 |
| `config/tracking.yaml`, `config/global_tracking.yaml` | 기존 추적·ID 연결·주차 판정 설정 |
| `config/calibration/camXX.json` | 카메라별 영상→BEV 보정 |
| `data/maps/map.png`, `data/maps/zones.json` | 지도 이미지·구역 좌표·기본 정원 |

현재 카메라는 `cam01`, `cam02`, `cam03`, `cam05`, `cam06`, `cam07`, `cam08`입니다.
`<title>`에는 영문·숫자·밑줄·하이픈으로 된 1~80자만 사용합니다.

검출 결과가 없다면 원본 영상과 YOLO 가중치·추론 환경을 준비한 뒤 기존 도구로 생성합니다.

```powershell
.\.venv\Scripts\python.exe -B scripts/preprocess.py video
```

전처리는 YOLO를 실행합니다. 기존 검출 자료에 `view_modes.json`만 빠졌다면 다음 명령으로 보완합니다.

```powershell
.\.venv\Scripts\python.exe -B scripts/detect_view_modes.py video
```

필요한 자료가 준비되면 웹 재생 캐시를 생성합니다. 이 단계는 기존 검출 결과로 Local/Global Tracking과 지도 투영을 계산하며 YOLO 추론을 다시 실행하지 않습니다.

```powershell
# 최초 생성
.\.venv\Scripts\python.exe -B web/build_replay.py --video video

# 원본·설정 변경 등으로 재생성이 필요한 경우
.\.venv\Scripts\python.exe -B web/build_replay.py --video video --overwrite
```

캐시는 다음 세 파일이 한 세트입니다.

```text
web/backend/replay_data/<title>/
├── manifest.json                # 영상·지도·설정 서명·활성 캐시 파일명
├── frames-<cache_id>.jsonl       # 프레임별 검출·추적·BEV·주차 이벤트
└── index-<cache_id>.json         # 프레임 접근용 바이트 오프셋
```

기존 유효 캐시가 있으면 생성하지 않고 서버를 실행합니다.
새 캐시 생성 후 열려 있던 관리자 페이지는 새로고침해 새 `cache_id`를 읽습니다.

웹 대상 영상은 `WEB_REPLAY_VIDEO` 환경변수가 있으면 이를 우선하고, 없으면 `config/detection.yaml`의 `video`를 사용합니다.
`--video`로 특정 캐시를 생성해도 서버의 선택 영상이 자동 변경되지는 않습니다.

```powershell
$env:WEB_REPLAY_VIDEO = "video"
.\.venv\Scripts\python.exe -B web/run.py
```

## 일상 운용과 데모 촬영

### 관리자 화면

1. 서버를 실행하고 `admin`으로 로그인합니다.
2. 왼쪽 분석 영상과 오른쪽 위 ‘구역별 차량 현황’ 지도·아래 ‘차단기 기록’을 확인합니다. 좌우 너비 비율은 2:1이며, 900px 이하 화면에서는 영상·지도·기록을 세로로 배치합니다.
3. 화면 맨 아래에서 재생, 일시정지, 배속, 타임라인을 조작합니다.
4. ‘실시간 추적 모드’를 ON으로 하면 기존 모델의 해당 프레임 지도 관측을 표시합니다. OFF여도 주차 현황·사용자 차량 상태 동기화는 계속됩니다.
5. ‘재생 설정’을 펼치면 이전/다음 프레임, 처음으로, 반복, 검출 박스, 주차장 구역 표시, 카메라 필터를 변경할 수 있습니다. ‘주차장 구역 표시’를 해제하면 지도 위 경계·구역명·대수·구역 안내를 숨깁니다. 지도 차량 추적과 아래 주차 현황 표는 계속 표시합니다.
6. 차단기 기록을 누르면 해당 이벤트 프레임으로 이동합니다. 기록은 현재 재생 시점까지의 이벤트를 최신순으로 표시합니다. 기록이 0건이어도 제목과 빈 기록 영역은 유지하며 설명·건수·빈 목록 안내 문구는 표시하지 않습니다. 관리자 콘텐츠는 화면 전체 너비를 사용합니다. 데스크톱에서는 분석 영역에 화면 높이를 기준으로 최소 높이를 두어 재생 바가 첫 화면 아래에 배치되며, 페이지를 스크롤하면 재생 설정을 사용할 수 있습니다. 차단기 패널 높이는 296px로 고정하고, 기록은 패널 내부에서 스크롤합니다. CCTV 패널은 영상 원본 비율에 따른 높이로 상단 정렬하며 강제 최소 높이나 세로 중앙 정렬을 적용하지 않습니다. 차단기 기록은 설정한 높이를 넘겨 늘어나지 않습니다. 지도와 영상의 원본 비율은 유지하며, 추가 기록은 목록 내부에서 스크롤합니다.

| 단축키 | 동작 |
|---|---|
| Space | 재생 / 일시정지 |
| A / D | 5초 뒤로 / 앞으로 |
| Shift+A / Shift+D | 30초 뒤로 / 앞으로 |
| `,` / `.` | 이전 / 다음 프레임 |
| R | 처음으로 이동 |

입력창·버튼에 포커스가 있으면 재생 단축키를 처리하지 않습니다.
지도 추적은 모델이 제공한 `ACTIVE`·`STOPPED`·`PARKED` 관측을 사용하며, 번호판 기반 사용자 차량 목록과는 구분됩니다.

### 사용자 화면

1. 사용자 계정으로 로그인하고 ‘차량 현황’을 엽니다.
2. 지도에서 주차 구역을 확인합니다. 구역 경계 표시를 켜거나 끌 수 있습니다.
3. 차량 목록에서 차량번호와 차량 상태를 확인합니다.
4. ‘차량 운행 스케줄’로 이동해 날짜를 선택하고 운행을 등록합니다.

차량 목록·예약 가능한 차량은 현재 소속 섹션으로 제한됩니다.
사용자 화면은 최대 너비 760px, 배율 90%로 가운데 배치합니다. 차량 목록 아래에 지도를 표시합니다. 차량 목록은 한 열로 표시하며 각 차량번호와 상태는 줄바꿈 없이 한 줄에 표시합니다.
운행 시간표는 왼쪽에 차량, 상단 가로축에 07:30~18:00 시간을 30분 눈금으로 표시하는 가로형입니다. 시간표 범위 밖의 일정도 운행 상세 목록에서는 확인할 수 있으며, 등록 가능 시간은 06:00~20:00으로 유지합니다. 좌우로 스크롤해 시간을 조회하며 왼쪽 차량 열과 상단 시간 축은 고정됩니다. 차량별 일정은 한 행씩 표시합니다. 작은 화면의 운행 상세 목록은 카드 형태로 표시합니다.

### 관리자·사용자 시점 동기화

1. 일반 브라우저에서 관리자 계정으로 로그인합니다.
2. 다른 브라우저나 시크릿 창에서 사용자 계정으로 로그인합니다. 로그인 정보가 `localStorage`에 저장되므로 같은 브라우저의 일반 탭끼리는 계정이 공유될 수 있습니다.
3. 관리자 창 하나에서 영상을 재생하거나 원하는 시점으로 이동합니다.
4. 사용자 화면의 차량 상태·주차 대수가 자동으로 따라오는지 확인합니다.

관리자는 약 250ms 간격과 재생·정지·시간 이동 이벤트를 통해 시점을 저장합니다.
사용자와 관리자 주차 표는 공유 상태를 약 250ms 간격으로 조회합니다. 네트워크와 요청 시간만큼 지연될 수 있습니다.
사용자 조회는 관리자 재생 시점을 변경하지 않습니다. 두 화면의 동기화 시간 안내 문구는 삭제된 상태입니다.
여러 관리자 창에서 동시에 재생하면 마지막으로 저장한 시점이 공유되므로 촬영 시에는 관리자 재생 창을 하나만 사용합니다.
영상 되감기·반복 재생 시 차량 상태와 대수도 해당 시점으로 복원됩니다. 서버 재시작만으로 초기 프레임으로 돌아가지는 않습니다.
처음 상태를 확인하려면 관리자에서 ‘처음으로’를 누릅니다.

### 운행 일정 등록·공유

1. ‘차량 운행 스케줄’ 메뉴 오른쪽의 날짜 선택에서 조회 날짜를 정하고 ‘운행 등록’을 누릅니다. 스케줄 화면에서는 이 날짜 선택이 상단의 ‘조회 범위’ 문구를 대신합니다.
2. 차량번호, 운행 날짜, 시작·종료 시간, 목적지, 운행 목적을 입력합니다. 일반 사용자의 운전자는 본인으로 고정됩니다.
3. 필요하면 ‘평일 반복 (월~금)’과 종료일을 지정합니다.
4. 저장 결과를 확인합니다. 등록 날짜가 조회 날짜와 다르거나 반복 시작일이 주말이면 실제 운행일 시간표로 이동합니다.
5. 같은 섹션의 다른 사용자도 같은 날짜를 열면 약 1초 간격으로 변경 내용을 받습니다. 브라우저 탭으로 돌아올 때도 다시 조회합니다.

| 규칙 | 동작 |
|---|---|
| 운행 가능 시간 | 06:00~20:00, 시작·종료 모두 30분 단위(00분 또는 30분). 종료 시간이 시작 시간보다 늦어야 함 |
| 중복 예약 | 같은 날짜·시간의 차량 중복 또는 운전자 중복은 409 오류로 거부. 오류에 겹치는 일정의 차량번호·날짜·시간 표시 |
| 연속 예약 | 앞 일정의 종료 시간과 다음 일정의 시작 시간이 같으면 허용 |
| 수정·취소 | 등록자 본인 또는 관리자만 가능. 다른 섹션에서는 조회할 수 없음 |
| 평일 반복 | 시작일부터 최대 한 달 이내의 지정 기간. 토·일 제외, 평일 공휴일 포함 |
| 반복 일정 수정·취소 | 선택한 하루만이 아니라 반복 기간 전체에 적용 |
| 통신 실패 | 마지막 정상 시간표와 입력 중인 폼 유지. 오류 표시 후 자동 재시도 |

예: 2026-10-18(일)부터 평일 반복을 등록하면 첫 운행일은 2026-10-19(월)입니다.
일요일 시간표에 해당 반복 일정이 없는 것은 정상이며, 주말의 빈 시간표에서 다음 평일 시간표로 이동할 수 있습니다.
관리자용 일정 조회·편집 API는 있지만 현재 관리자 화면에는 일정 메뉴를 표시하지 않습니다.

## 업무 JSON과 차량 상태

실제 운용 데이터는 `web/backend/data/`, 새 설치용 템플릿은 `web/backend/fixtures/`입니다.
파일 수정 시 유효한 UTF-8 JSON으로 저장합니다.

| 파일 | 작성·사용 방법 |
|---|---|
| `users.json` | 계정 `id`, `name`, `password`, `role`, `team_id`, `team_name`. 현재 계정 정보는 서버에서 조회 |
| `teams.json` | 섹션 목록·메타데이터 |
| `vehicles.json` | 등록 차량 ID·번호판·이름·기본 소속·초기 상태. 재생 시점 상태가 원장을 덮어쓰지는 않음 |
| `vehicle_schedules.json` | 등록된 운행 일정과 반복 기간. API가 저장하며 영상 타임라인과 독립적 |
| `initial_parking.json` | 구역별 초기 주차 대수·최대 대수 |
| `vehicle_replay_state.json` | 관리자 공유 시점·차량 상태·주차 변동분. API가 생성하며 직접 입력하지 않음 |
| `tracking_logs.json` | 관리자 `tracking-events` API로 기록한 등록 차량 감지 로그. 모델의 모든 주차 이벤트를 자동 복사하는 파일은 아님 |
| `parking_zones.json`, `map_layout.json` | 웹 구역 메타데이터·대체 지도 레이아웃. 기본 지도 좌표는 루트 `data/maps/zones.json` 사용 |
| `vehicle_requests.json` | 현재 화면·URL에서 사용하지 않는 기존 자료 |

`users.json`의 이름·섹션 정보는 페이지 진입·탭 복귀와 약 30초 간격 조회로 반영됩니다.
로그인 토큰의 유효 시간은 8시간입니다. 이름과 별개로 `id`는 일정의 등록자·운전자 식별에 사용됩니다.
현재 인증·JSON 저장은 로컬 데모 방식이며 기본 계정 비밀번호는 JSON에 저장됩니다.

### 구역별 초기 대수와 최대 대수

[`backend/data/initial_parking.json`](backend/data/initial_parking.json)은 다음 배열 형식입니다. 아래는 형식 예시이며 실제 전체 목록을 대체하는 값은 아닙니다.

```json
[
  {"zone_id": "A", "parked_count": 0, "capacity": 14},
  {"zone_id": "L", "parked_count": 1, "capacity": 13}
]
```

- `zone_id`: 지도에 정의된 구역 ID. 소문자 입력도 허용하며 같은 구역을 중복 입력할 수 없습니다.
- `parked_count`: 영상 시작 시 이미 주차된 대수. 번호판 목록·`schema_version`·`observed_at`은 입력하지 않습니다.
- `capacity`: 최대 주차 가능 대수. 0 이상의 정수이며 생략하면 지도 구역의 기본 정원을 사용합니다.
- 목록에 없는 구역의 초기 대수는 0입니다. 현재 시나리오는 **L구역 1대, 나머지 구역 0대**입니다.
- 현재 대수는 `초기 대수 + 재생 시점 변동분 + 수동 갱신 보정분`으로 계산하며 음수는 0으로 표시합니다.
- 이중주차를 별도 종류로 입력하지 않습니다. 정원이 14대여도 20대가 있으면 `20대 / 14대`로 표시합니다.

```powershell
# 현재 파일 검증만 수행
.\.venv\Scripts\python.exe -B web/initialize_parking.py --check

# 다른 JSON을 검증한 뒤 운용 파일로 가져오기
.\.venv\Scripts\python.exe -B web/initialize_parking.py --input my_parking.json
```

저장한 초기 대수·정원은 다음 주차 현황 조회부터 반영됩니다. 캐시 재생성이나 서버 재시작은 필요 없습니다.
차량 원장의 주차 차량을 다시 더하지 않으므로 `initial_parking.json`에는 영상 시작 시 전체 대수를 입력합니다.

### 입차·주차·출차 상태

| 시점 | 차량 목록 표시·처리 |
|---|---|
| 인식 전 | 원장의 초기 상태 유지. 현재 7번은 L구역 주차, 나머지는 외부 운행 차량으로 `MOVING`(운행중) |
| 차단기 `IN` 이후 | `PARKING` → ‘주차중’. 아직 주차 대수에 추가하지 않음 |
| 주차 완료 | `PARKED` → ‘K 구역’ 등 구역명 표시. 해당 구역 대수 반영 |
| 차단기 `OUT` 이후 | 구역을 비우고 `MOVING` → ‘운행중’. 현재 소속은 디지털통신기술섹션 |
| 되감기 | 해당 시점의 상태·소속으로 복원 |

현재 차량 원장 기준 분류는 1~3번과 7번이 디지털통신기술섹션, 4~6번이 제강연주섹션, 8~10번이 냉간 DX 섹션입니다.
7번은 기본 소속 자체가 디지털통신기술섹션이므로 출차 전으로 돌려도 이 섹션에 남습니다.
일반적인 출차 차량의 소속 전환도 차량 목록과 일정 차량 선택 권한에 반영됩니다.

## 입출차·주차 시나리오

### 로그 파일과 우선순위

차단기 로그는 다음 순서에서 **처음 존재하는 파일 하나**를 사용합니다.

1. `data/gate_logs/gate_logs.json`
2. `data/gate_logs/gate_log.json`
3. `data/gate_logs/<title>.json`

상위 우선순위 파일이 다른 영상이거나 형식이 잘못됐어도 하위 파일로 자동 전환하지 않습니다.
현재 사용하는 공유 파일은 `data/gate_logs/gate_log.json`입니다.
`video`·`fps`가 선택 영상과 맞고 `events[].frame`이 영상 범위 안의 정수여야 합니다.
`frame`은 0부터 시작하며 동기화 기준이고, `time`은 사람이 확인하는 시각입니다.

```json
{
  "video": "video",
  "start_time": "07:32:15",
  "fps": 30.0,
  "gate": {"id": "GATE-01", "name": "정문 차단기", "camera_id": "cam01"},
  "events": [
    {"frame": 240, "type": "IN", "scenario_vehicle_id": 1, "plate": "11가1111", "time": "07:32:23"}
  ]
}
```

차단기 로그에는 `IN`·`OUT`, `data/parking_logs/parking_log.json`에는 `initial_vehicles`와 `PARKED`·`LOST`·`LEFT` 이벤트를 기록합니다.
등록 차량은 원장 `plate_number`와 로그 `plate`의 공백을 제거한 번호판으로 연결합니다.
`scenario_vehicle_id`는 시나리오 순번이며 모델 Global ID나 카메라 Local ID와 다릅니다.

선택 영상과 같은 `video`의 수동 주차 로그가 있으면 주차 집계·등록 차량 상태에 이를 우선 사용합니다.
`final_positions`·`final_zone_counts`는 최종 결과 참고값이며, 재생 도중에는 이벤트를 적용해 미래 위치가 미리 표시되지 않게 합니다.
수동 시나리오가 없거나 다른 영상이면 모델 캐시의 주차 이벤트를 사용합니다.

모델 이벤트 집계는 Global ID별 `LOST`(주차 추정)·`PARKED`를 한 번만 더하고, 추정→확정 변경 시 대수를 유지합니다.
구역이 바뀌면 이전 구역에서 빼고 새 구역에 더합니다. 집계된 차량의 `LEFT` 발생 시 차감합니다.
여러 카메라·반복 조회·반복 재생으로 같은 차량을 중복 증가시키지 않습니다.

### 현재 `video` 시나리오

영상 시작 시각은 `07:32:15`, FPS는 30이며 `frame = 경과 초 × FPS`입니다.
현재 차단기 로그는 입차 9건·출차 1건, 수동 주차 이벤트는 주차 완료 8건·구역 출발 1건입니다.

| 차량 | 번호판 | 기본 섹션 | 입차 또는 초기 상태 | 주차 완료·출차 |
|---|---|---|---|---|
| 1 | 11가1111 | 디지털통신기술 | +8초 입차 | +83초 K구역 |
| 2 | 22나2222 | 디지털통신기술 | +27초 입차 | +122초 I구역 |
| 3 | 33다3333 | 디지털통신기술 | +122초 입차 | +160초 K구역 |
| 4 | 44라4444 | 제강연주 | +135초 입차 | +196초 B구역 |
| 5 | 55마5555 | 제강연주 | +153초 입차 | +233초 M구역 |
| 6 | 66바6666 | 제강연주 | +165초 입차 | +281초 B구역 |
| 7 | 77사7777 | 디지털통신기술 | 시작 시 L구역 주차 | +253초 L구역 출발·출차, 운행중 |
| 8 | 88아8888 | 냉간 DX | +287초 입차 | +378초 G구역 |
| 9 | 99자9999 | 냉간 DX | +293초 입차 | +407초 G구역 |
| 10 | 10차1010 | 냉간 DX | +402초 입차 | 주차 완료 기록 없음, 주차중 |

최종 주차 대수는 **B 2대·G 2대·I 1대·K 2대·M 1대, 합계 8대**입니다. L은 0대입니다.
초기 상태를 점검할 때는 관리자에서 0초로 이동해 L 1대, 나머지 0대인지 확인합니다.

## 파일 구조와 내부 동작

```text
web/
├── run.py                         # Waitress 통합 실행 진입점
├── run.ps1                        # app·prepare·build·init·test 도우미
├── build_replay.py                 # 기존 모델로 사전 재생 결과 생성
├── initialize_parking.py           # 초기 대수 JSON 검증·가져오기
├── examples/initial_parking.json   # 초기 대수 형식 예시
├── backend/
│   ├── manage.py                  # Django 검사·테스트 명령
│   ├── seed.py                    # 없는 운용 JSON 생성
│   ├── native_project.py          # 기존 모델 정의·캐시 읽기 연동
│   ├── config/                    # URL·설정·React 정적 파일·JSON 압축
│   ├── data/                      # 실제 업무 JSON
│   ├── fixtures/                  # 신규 설치 템플릿
│   ├── replay_data/<title>/        # 생성한 웹 재생 캐시
│   ├── replay/
│   │   ├── export.py              # 추적 캐시 생성
│   │   ├── store.py               # 캐시 검증·인덱스 조회·차단기 로그
│   │   ├── scenario.py            # 수동 주차 이벤트 타임라인
│   │   ├── parking_state.py       # 시점별 주차 변동 집계
│   │   ├── vehicle_state.py       # 번호판 연결·차량 상태·소속 적용
│   │   └── frame_response.py      # 프레임 JSON 응답 재사용
│   └── tracking/
│       ├── views.py               # 로그인·차량·지도·주차 대수 API
│       ├── schedules.py           # 일정 권한·검증·중복 방지·저장
│       ├── replay_views.py        # 재생 API·공유 시점 저장·조회
│       ├── parking_state.py       # 초기 대수 검증·변동분 병합
│       ├── json_store.py          # JSON 읽기·변경 감지·파일 교체 저장
│       ├── media_stream.py        # 원본 영상·지도와 HTTP Range
│       └── test*.py               # 업무·권한·재생 테스트
├── frontend/
│   ├── package.json·package-lock.json
│   ├── vite.config.js             # 개발 5173 → API 8080 프록시
│   ├── src/
│   │   ├── main.jsx               # 로그인·대시보드·차량 목록
│   │   ├── CachedReplay.jsx       # 관리자 영상·지도·차단기·하단 재생 바
│   │   ├── ParkingMap.jsx         # 사용자 지도·구역 표시
│   │   ├── ParkingOccupancy.jsx   # 현재 대수 / 최대 대수
│   │   ├── VehicleSchedule.jsx    # 일정 입력·시간표·상세
│   │   ├── scheduleSync.js        # 일정 1초 갱신·저장 후 조회 날짜
│   │   ├── DemoSync.jsx           # 공유 차량·주차 현황 상태
│   │   ├── demoStatePolling.js    # 공유 상태 조회
│   │   ├── replayVehicleSync.js   # 관리자 영상 시점 전송
│   │   ├── replayBuffer.js        # 프레임 버퍼·시간 이동·단축키
│   │   ├── replayCanvas.js        # 캔버스 갱신
│   │   └── sessionProfile.js      # 계정 정보 갱신
│   ├── tests/                     # 화면·갱신·재생 동작 테스트
│   └── dist/                      # 8080 서버가 제공하는 빌드 산출물
├── tests/                         # 모델 어댑터·재생 캐시 검증
└── index.html·app.js·style.css·bev_items.js·viewer-rendering.js
                                   # 기존 뷰어와 공용 렌더링 코드
```

동작 순서는 다음과 같습니다.

1. `build_replay.py`가 `native_project.py`를 통해 기존 `server.py`·`src/`의 추적 구현을 사용해 프레임 결과를 저장합니다.
2. `run.py`가 Django 업무 API, React 빌드, 원본 영상·지도를 같은 주소에서 제공합니다.
3. 관리자 브라우저가 영상의 현재 프레임에 필요한 캐시 구간만 조회해 검출 박스·지도 관측을 그립니다.
4. 관리자 브라우저가 현재 프레임을 `replay/vehicle-state/`로 전송합니다.
5. 서버는 시나리오 또는 모델 타임라인에서 차량 상태·주차 변동분을 계산해 공유 JSON을 저장합니다.
6. `replay/demo-state/`는 공유 시점을 한 번 읽어 권한 범위의 차량과 전체 구역 대수를 함께 반환합니다.
7. 일정은 별도 API가 JSON으로 저장합니다. 충돌 검사와 저장은 프로세스 내 잠금으로 직렬화합니다.

원본 영상과 프레임 JSON 전체를 매번 메모리에 올리지 않습니다. 인덱스와 제한된 프레임·JSON 캐시를 사용하며, 작은 업무 JSON은 파일 변경을 확인해 다시 읽습니다.
현재 저장 방식은 단일 서버 프로세스에서 운용하는 로컬 데모 기준입니다.

## 변경 사항 적용 기준

| 변경 대상 | 적용 방법 |
|---|---|
| `users.json` 이름·섹션 | 계정 정보 자동 조회. 즉시 확인하려면 새로고침 |
| 일정 등록·수정·취소 | 저장자 즉시 재조회, 다른 사용자는 같은 날짜에서 약 1초 간격 자동 반영 |
| `initial_parking.json` 대수·정원 | 다음 현황 조회에 반영. 캐시 재생성 불필요 |
| 차단기·수동 주차 로그 | 다음 시점 동기화에 반영. 차단기 기록 패널은 manifest를 다시 읽도록 관리자 페이지 새로고침 |
| React 소스·CSS | `npm.cmd run build` 후 브라우저 새로고침 |
| Python 웹 API·설정 | 서버 재시작 후 재조회 |
| 원본·검출 결과·metadata | 서로 일치하는 자료를 준비하고 웹 재생 캐시 `--overwrite` |
| 카메라 배치·보정·추적 코드/설정·지도 좌표 | 웹 재생 캐시 `--overwrite` 후 관리자 새로고침 |
| `view_modes.json` | 화면 모드 파일 생성·수정 후 웹 재생 캐시 `--overwrite` |

캐시 서명에는 `server.py`, `src/**/*.py`, 카메라·추적·보정·지도 자료와 웹 캐시 생성기·모델 어댑터가 포함됩니다.
따라서 동작 코드가 달라졌다는 오류를 웹 화면 새로고침만으로 해결할 수는 없습니다.
지도 원본 `data/maps/zones.json`의 정원만 바꿔도 서명이 달라지므로, 웹 표시용 정원 조정은 `initial_parking.json`에서 합니다.

## API와 환경변수

경로는 모두 `/api` 기준이며 로그인 후 `Authorization: Bearer <token>`을 사용합니다.
이미지·영상 요청은 `token` 쿼리 인증을 사용할 수 있습니다. 관리자 재생 요청은 `cache_id`도 확인합니다.

| 경로 | 메서드 | 권한·용도 |
|---|---|---|
| `/auth/login/`, `/auth/me/` | POST, GET | 로그인·현재 계정 |
| `/vehicles/`, `/vehicles/<id>/` | GET | 관리자 전체 / 사용자 현재 섹션 차량 |
| `/admin/vehicles/` | POST | 관리자 차량 등록 |
| `/vehicle-schedules/` | GET, POST | 권한 범위 날짜별 일정 조회·등록 |
| `/vehicle-schedules/<id>/` | PUT, DELETE | 등록자 또는 관리자 수정·취소 |
| `/parking-map/`, `/parking-map/image/` | GET, GET/HEAD | 지도 레이아웃·이미지 |
| `/parking-zones/` | GET | 초기 대수·변동분·현재 대수·정원·초과 대수 |
| `/tracking-events/`, `/tracking-logs/` | POST, GET | 관리자 수동 감지 입력·이력 |
| `/replay/manifest/` | GET | 관리자 캐시 정보·차단기 기록 |
| `/replay/frames/?start=0&count=60` | GET | 관리자 프레임 구간, 한 번에 1~120프레임 |
| `/replay/vehicle-state/` | POST | 관리자 공유 시점 저장. `cache_id`, 정수 `frame` |
| `/replay/demo-state/` | GET | 로그인 사용자 공유 시점·차량·구역 대수 조회. 읽기 전용 |
| `/replay/video/`, `/replay/map/` | GET, HEAD | 관리자 원본 영상·지도. 영상 Range 지원 |

| 변수 | 역할 |
|---|---|
| `WEB_REPLAY_VIDEO` | 웹 재생 대상 영상 제목. 없으면 `config/detection.yaml` 사용 |
| `WEB_BEV_MAP` | 사용자 지도 이미지 경로. 별도 이미지는 `map_layout.json` 좌표와 맞춰야 함 |
| `WEB_SECRET_KEY` | 로그인 토큰 서명 키. 미지정 시 `web/.secret-key` 사용 |
| `WEB_ALLOWED_HOSTS` | 허용 호스트·IP를 쉼표로 구분. 기본 localhost·127.0.0.1·testserver |
| `WEB_DEBUG=1` | Django 디버그 모드 |
| `VITE_API_URL` | 프론트엔드 API 기본 URL. 기본 `/api`, 개발·빌드 시 적용 |

같은 네트워크의 다른 기기에서 접속하려면 PC IP를 확인한 뒤 실행합니다. 예시 주소는 실제 PC 주소로 변경합니다.

```powershell
ipconfig
$env:WEB_ALLOWED_HOSTS = "localhost,127.0.0.1,192.168.0.10"
.\.venv\Scripts\python.exe -B web/run.py --host 0.0.0.0 --port 8080
```

다른 기기에서는 `http://192.168.0.10:8080/`으로 접속합니다. Windows 방화벽의 해당 포트 허용 상태도 확인합니다.

## 개발과 검증

프론트엔드 개발은 첫 터미널에서 통합 서버를 실행한 뒤 다른 터미널에서 진행합니다.

```powershell
Push-Location web/frontend
npm.cmd run dev
Pop-Location
```

개발 주소는 **http://localhost:5173/**이며 `/api`를 **127.0.0.1:8080**으로 프록시합니다.
서버 포트를 변경하면 `frontend/vite.config.js`의 프록시도 맞춥니다. 실제 8080 화면 반영에는 별도 빌드가 필요합니다.

```powershell
.\.venv\Scripts\python.exe -B web/backend/manage.py check
.\.venv\Scripts\python.exe -B web/backend/manage.py test tracking
.\.venv\Scripts\python.exe -B -m unittest discover -s web/tests -v

Push-Location web/frontend
npm.cmd test
npm.cmd run build
Pop-Location
```

업무 API 테스트는 임시 JSON 저장소를 사용합니다. 로그인·섹션 권한·등록/수정/취소·중복 예약·주말 반복·영상 시점 복원·주차 집계를 검증합니다.
프론트엔드 테스트는 화면 출력, 일정 갱신·오류 복구·동시 요청 제어, 프레임 처리·렌더링을 검증합니다.
실제 브라우저 영상 코덱과 화면 배치는 별도로 확인합니다.

PowerShell 도우미도 사용할 수 있습니다.

| 명령 | 실행 내용 |
|---|---|
| `.\web\run.ps1 app` | 통합 서버 실행 |
| `.\web\run.ps1 prepare` | 선택된 기본 영상의 최초 캐시 생성 |
| `.\web\run.ps1 build` | React 빌드. 사전 `npm.cmd ci` 필요 |
| `.\web\run.ps1 init` | 없는 업무 JSON 초기화 |
| `.\web\run.ps1 test` | Django·웹 어댑터·프론트엔드 테스트 |

`prepare`에는 덮어쓰기 옵션이 없으므로 재생성은 `build_replay.py --overwrite`로 수행합니다.
PowerShell 실행 정책으로 `.ps1`이 막히면 가상환경 활성화 없이 위의 Python 직접 실행 명령과 `npm.cmd`를 사용합니다.

## 문제 확인 순서

| 증상 | 확인·해결 |
|---|---|
| 서버 접속 불가·포트 충돌 | 실행 터미널 오류와 8080 포트를 확인. 기존 서버를 종료하거나 `--port` 변경 |
| `No module named waitress` 등 | 시스템 Python 대신 `.venv` Python 사용, 루트 `requirements.txt` 설치 |
| 웹 화면 빌드 필요·화면 수정 미반영 | `web/frontend`에서 `npm.cmd ci`, `npm.cmd run build` 후 새로고침 |
| 로그인 실패 | 운용 `users.json` 확인. seed는 기존 비밀번호를 재설정하지 않음 |
| 보정·추적·지도 변경 오류 | 선택 영상 자료를 확인하고 `web/build_replay.py --video video --overwrite` 실행 |
| 원본·검출 결과 불일치 | 원본·metadata·검출 JSONL의 해상도·FPS·프레임 수·칸 배치를 맞춘 뒤 캐시 재생성 |
| `view_modes.json not found` 경고 | `scripts/detect_view_modes.py video` 실행 후 캐시 재생성. 경고 상태에서는 축소 화면을 원본 좌표로 추적 |
| `load_json_file`·`format_parking_event` 이름 오류 | 기존 엔진과 `backend/native_project.py`가 서로 맞는 버전인지 확인. 현재 어댑터는 두 함수를 포함 |
| 관리자 지도 추적이 없음 | 추적 모드 ON, 현재 프레임 결과·카메라 필터·지도 범위·모델 상태 확인. 사용자 지도에는 차량 아이콘이 없는 것이 현재 사양 |
| 현재 프레임 위치 로딩 표시 | 프레임 API 오류·캐시 유효성 확인. 같은 시점의 결과가 없을 때 이전 프레임을 대신 표시하지 않음 |
| 차단기 기록 미반영 | 로그 우선순위·`video`·`fps`·`frame` 확인 후 관리자 페이지 새로고침 |
| 초기 대수가 예상과 다름 | 현재 공유 영상 시점을 확인하고 ‘처음으로’ 이동. 초기 JSON은 영상 시작 기준 |
| 출차 차량이 이전 섹션에 없음 | 출차 후 현재 소속은 디지털통신기술섹션. 해당 사용자 목록에서 운행중 상태 확인 |
| 일정 저장 후 오늘 표에 없음 | 조회 날짜와 실제 운행일 확인. 평일 반복은 주말 제외. 같은 섹션·같은 날짜에서 확인 |
| 일정 409 오류 | 같은 차량 또는 운전자의 시간이 겹침. 기존 일정 시간·반복 기간 확인 |
| 다른 사용자에게 일정 미반영 | 같은 섹션·날짜인지 확인. 최신 빌드 적용 후 한 번 새로고침, 통신 오류 메시지 확인 |
| 영상 재생 불가 | 원본 파일·로그인·브라우저 코덱 확인. OpenCV에서 읽힌다고 브라우저 재생이 보장되지는 않음 |

## Git과 전달 자료

원본·분리 영상, YOLO 가중치, 검출 `detections.jsonl`, `.venv`, `node_modules`, React `dist`,
`backend/replay_data`, 공유 시점 `vehicle_replay_state.json`, 업로드 자료, SQLite 파일, `web/.secret-key`는 ignore 대상입니다.
새 컴퓨터에는 제외된 영상·분석 자료를 별도로 준비하고 React 빌드·재생 캐시를 생성해야 합니다.

`backend/data/`의 다른 업무 JSON과 `fixtures/`는 현재 ignore 대상이 아닙니다.
커밋 전 변경 내용을 확인합니다. 예제 계정 외 실제 비밀번호를 저장소에 포함하지 않습니다.
서명 키가 다른 컴퓨터로 이동하면 다시 로그인해야 합니다.
