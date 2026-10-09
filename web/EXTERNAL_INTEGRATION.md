# 외부 기능 연동 조사와 구현 기준

## 우선순위

웹의 첫 역할은 `web/` 밖에서 구현·생성한 기능과 데이터를 보여 주는 것입니다.
같은 기능이 외부에 있으면 기존 함수를 호출하고, 웹에는 인증·응답 변환·재생·표시를 위한 연결 코드만 둡니다.
이번 작업의 수정 범위는 `web/` 내부입니다. `src/`, `server.py`, `scripts/`, `config/`, 원본 `data/`는 읽기만 합니다.

## 기능 전수 조사 결과

| 웹 기능 | 외부 구현·데이터 | 반영 방식과 웹의 역할 |
|---|---|---|
| 기본 영상 선택 | `src/mosaic.py: default_title()` | 직접 호출. `WEB_REPLAY_VIDEO`를 지정한 경우에만 웹 선택값을 우선합니다. |
| 카메라 목록·타일·ROI | `load_layout()`, `MosaicLayout.crop_rects()`, `MosaicVideo` | 외부 검증과 경로 규칙을 사용합니다. 웹에서 YAML을 별도로 해석하거나 카메라 목록을 고정하지 않습니다. |
| YOLO 검출 | `scripts/preprocess.py`, `data/detections/<title>/` | 이미 생성된 `detections.jsonl`과 `metadata.json`을 읽습니다. 웹 재생에서는 검출을 실행하지 않습니다. |
| 로컬 추적·상태·Global ID | `server.py: TrackingEngine`, `DetectionCacheStore`, `src/tracking/` | 외부 정의를 그대로 실행해 오프라인 재생 캐시를 만듭니다. 별도 웹 추적 알고리즘을 만들지 않습니다. |
| 영상 좌표 → 지도 좌표 | `src/calibration/CameraProjector`, 엔진의 `projectors`와 `frame.bev` | 외부 엔진의 `frame.bev`만 전달합니다. 웹에서 카메라 검출을 추가 투영하거나 `bev_position`을 만들지 않습니다. |
| 해상도 연결 | 외부 검출 metadata와 보정 JSON의 `image_size` | 웹 어댑터가 동일 종횡비의 좌표 단위만 맞춥니다. 추적 전에 보정 기준으로 축소하고 영상 박스는 원본 크기로 복원합니다. 다른 종횡비·지도 크기는 오류로 처리합니다. |
| 영상 박스 표시 | 외부 엔진의 `cameras` 결과·추적 상태 | 기존 뷰어의 `drawDetection()`·`drawCameraLabel()`을 공통 모듈로 옮겨 그대로 호출합니다. 위치·ID·상태를 새로 추론하지 않습니다. |
| 지도 위치 표시 | 외부 엔진의 `bev` 결과 | 기존 뷰어의 `drawBevTracking()`을 그대로 호출해 ACTIVE·카메라 색상·ID 표시를 공유합니다. 웹은 카메라 필터와 표시 범위 검사만 적용합니다. |
| 지도 이미지·구역 경계·수용량 | `data/maps/map.png`, `zones.json` | 실제 외부 자료를 읽습니다. 사용자 지도에는 픽셀 좌표를 화면 비율로 변환해 전달합니다. 구역 API와 위치 저장 API도 같은 지도 ID·구역 목록을 사용합니다. |
| 구역별 마우스 집계 | 외부 `zones.json` 경계 + 엔진의 ACTIVE BEV 관측 | 출력된 이동 차량 위치가 구역 안에 있는지만 표시용으로 집계합니다. 처음부터 주차된 UNKNOWN 차량이나 STOPPED/PARKED 상태를 추가 투영하지 않습니다. 주차면 점유 수를 계산하는 기능은 아닙니다. |
| 차단기 이벤트 생성 | `scripts/detect_gate_events.py` → `data/gate_logs/*.json` | 외부 생성 결과를 소비합니다. 웹에서 차단기 분석을 다시 실행하지 않습니다. |
| 차단기 기록 읽기 | `server.py: gate_log()`, `MosaicVideo.gate_log_path` | 외부 읽기·정렬 함수를 호출합니다. 웹은 영상·FPS·프레임 범위를 확인하고 현재 재생 시점까지의 기록만 표시합니다. |
| 프레임 읽기 | `server.py: DetectionCacheStore.read_frame()` | 기존 클래스를 호출합니다. 오프라인 인덱스를 전달해 요청마다 전체 파일을 스캔하지 않고, 각 요청에서 별도 파일 핸들을 사용합니다. |
| 영상 전송·탐색 | 외부 원본 영상 | Django 인증 뒤 Range/HEAD를 제공합니다. 브라우저의 표시 프레임에 저장 결과를 맞추며 서버에서 영상을 매번 디코딩하지 않습니다. |
| 로그인·이름·섹션별 권한 | 외부 대응 기능 없음 | 기존 웹 계정과 인증을 유지합니다. 외부 모델 코드가 사용자 권한을 대체하지 않습니다. |
| 등록 차량·섹션별 운행 스케줄 | 외부 대응 기능 없음 | 기존 JSON 업무 데이터와 예약 검증을 유지합니다. 일반 사용자는 본인 섹션, 관리자는 전체를 조회합니다. |
| 등록 차량 위치 갱신 API | 외부에는 Global ID 추적만 존재 | 기존 번호판 기반 API를 유지하되 실제 지도 설정으로 검증합니다. Global ID를 등록 차량·번호판·스케줄에 임의로 연결하지 않습니다. |
| 기존 등록 차량 감지 로그 API | 외부 대응 기능 없음 | 번호판 기반 위치 갱신 기록을 유지합니다. 차단기 기록과 별개입니다. 사용하지 않는 관리 요청·승인 API와 구형 개별 CCTV API는 제거했습니다. |
| 초기 계정·더미 자료·서명 키 | 외부 대응 기능 없음 | `web/backend/data/`와 웹 설정에서 관리합니다. `fixtures`의 지도 자료는 대체 자료이며 외부 지도 자료가 우선합니다. |
| 기존 HTML 뷰어 | 루트 `server.py`가 `web/index.html`, `app.js`, `style.css` 참조 | 외부 서버와의 호환을 위해 보존합니다. 통합 운영 화면은 React dist이며 별도 서버를 추가하지 않습니다. |

## 실제 호출 흐름

```text
[별도 분석 작업: 웹 실행 중에는 수행하지 않음]
scripts/preprocess.py → data/detections/<title>/
scripts/detect_gate_events.py → data/gate_logs/<title>.json

[오프라인 웹 재생 준비]
web/build_replay.py
  → replay/export.py
  → native_project.tracking_definitions()
  → server.py의 TrackingEngine + src/tracking + src/calibration
  → web/backend/replay_data/<title>/

[일상 웹 실행]
web/run.py → Django 인증 → replay/store.py → 저장 프레임·원본 영상·지도
  → CachedReplay.jsx → 현재 영상 프레임의 박스·BEV 위치·구역 집계
  → native_project.read_native_gate_log() → server.py의 gate_log()
  → 현재 재생 시점의 차단기 기록
```

지도 위의 최종 원·글자는 브라우저에서 기존 뷰어의 함수를 호출해 그립니다. `web/viewer-rendering.js`에 기존 `app.js`의 세 함수 본문을 그대로 옮겼고, 원래 HTML 뷰어와 React 화면이 함께 사용합니다. 외부 추적 코드가 계산한 좌표를 전달하는 구조입니다.
외부 보정 도구의 `cv2.circle`은 보정 작업용 표시이며 React 지도에 직접 삽입할 그림 생성 함수는 아닙니다.

## `native_project.py`가 필요한 이유

`src.mosaic`은 직접 import할 수 있습니다. 반면 `server.py`는 import만 해도 엔진을 초기화하므로 그대로 import하지 않습니다.
공통 어댑터는 외부 파일의 AST에서 기존 추적 정의·캐시 읽기 클래스 또는 `gate_log()`만 로드합니다.
외부 함수 본문을 웹에 복사하지 않고, FastAPI 앱·전역 엔진·외부 서버 실행 부분을 제외합니다.
차단기 읽기는 요청마다 독립적인 scene을 전달하므로 다른 요청과 추적 상태를 공유하지 않습니다.
외부 인터페이스가 바뀌면 어댑터를 점검해야 합니다. 오류를 숨기고 임의의 추적 결과를 대신 만들지 않습니다.

HTTP 서버가 시작될 때 YOLO·PyTorch·OpenCV·추적 엔진을 로드하지 않는 것을 테스트합니다.
추적 캐시 준비 때만 기존 엔진과 OpenCV를 사용하며 생성 결과는 모두 `web/` 안에 저장합니다.

## 차단기 파일 선택

사용자가 지정한 공유 파일과 외부 프로젝트 기본 규칙을 다음 순서로 적용합니다.

1. `data/gate_logs/gate_logs.json`
2. 위 파일이 없으면 `data/gate_logs/gate_log.json`
3. 공유 파일 둘 다 없으면 외부 `MosaicVideo.gate_log_path`인 `data/gate_logs/<title>.json`

선택된 파일에 오류가 있으면 다른 영상의 기록으로 대체하지 않습니다.
외부 함수와 동일하게 UTF-8 JSON을 사용하며 `video`, `fps`, 정수 `frame` 범위를 확인합니다.
파일 변경은 페이지 새로고침 후 반영됩니다. 기록은 추적 캐시와 독립적으로 읽으므로 캐시 재생성은 필요 없습니다.

## 남아 있는 한계

- 번호판과 Global ID의 확정 연결은 외부에서 제공되지 않습니다. 현재 더미 계정·등록 차량·스케줄과 자동 연동하지 않습니다.
- 외부에는 주차면 단위 점유 판정이 없습니다. 구역 검출 집계를 점유율로 바꾸지 않습니다.
- 웹은 기존 보정·검출 결과의 정확도를 개선하지 않습니다. 카메라 각도나 지도 기준이 바뀌면 외부 분석 자료를 먼저 준비해야 합니다.
- 소스·설정·영상·검출 결과가 바뀌면 재생 캐시를 다시 만듭니다. 좌표를 임의로 보간하거나 누락 프레임에 이전 결과를 표시하지 않습니다.
- 원본 영상의 브라우저 코덱 지원은 별도 조건입니다. OpenCV에서 읽힌다는 이유만으로 브라우저 재생을 보장할 수 없습니다.

## 확인 방법

`web/README.md`의 실행·검증 명령을 사용합니다.
연동 테스트는 원본 함수의 소스 경로·추적 클래스 동일성, 외부 추적 연결, 지도 경계,
차단기 파일 재조회, 가벼운 런타임 import, 프레임별 좌표 보존을 확인합니다.

## 실행 경로 정리

현재 운영 경로는 `web/run.py` → Django API + React dist + 저장된 영상 결과입니다.
사용하지 않는 관리 요청·승인 API와 개별 CCTV 미디어 API, 해당 테스트와 CSS를 제거했습니다.
사용자 지도 조회는 영상 선택·분리 영상·검출 metadata가 없어도 외부 지도 이미지를 읽을 수 있습니다.

같은 출처에서 화면과 API를 제공하므로 CORS 미들웨어와 `django-cors-headers` 의존성을 제거했습니다.
`run.ps1`의 별도 Django·프론트 서버 실행 분기는 삭제했습니다. 개발 시 Vite가 필요한 경우에만
5173 포트의 개발 화면에서 8080 통합 API로 프록시합니다.

manifest가 참조하지 않는 이전 프레임·인덱스 한 세트, 생성된 `web/Ultralytics` 설정과
내용이 없는 SQLite 파일을 정리했습니다. 현재 재생 캐시, 로그인 키·계정·스케줄,
기존 분석 업로드 자료, 외부 서버가 참조하는 HTML 뷰어는 보존합니다.

## 루트 README 기준 재정리 · 2026-10-10

이번 변경에서 제거한 웹 자체 구현은 다음과 같습니다.

- 모든 카메라 검출을 다시 투영해 만드는 `bev_position`과 자체 `zone_for()` 결과.
- 별도 bbox·ID 그리기 루프, SVG 차량 마커, 독립적인 상태별 색상 정의.
- 별도 JSONL 프레임 파싱·프레임 번호 검사 코드. 외부 `DetectionCacheStore.read_frame()`으로 대체했습니다.

기존 엔진 결과를 저장하는 오프라인 캐시와 좌표 단위를 맞추는 어댑터는 유지합니다.
검출 metadata의 1280×720과 보정 기준 640×360을 연결해야 기존 함수에 올바른 단위가 전달됩니다.
이를 삭제하면 기존 추적 임계값과 보정 좌표가 맞지 않습니다. 추적·상태 판정·Global ID·BEV 계산은 외부 엔진만 수행합니다.

루트 뷰어는 탐색 때 추적을 다시 시작하지만, 웹은 컴퓨팅 제약 때문에 기존 엔진으로 미리 생성한 결과를 읽습니다.
원본 HTML 뷰어의 실행도 유지하며 공통 그리기 모듈은 ES module로 불러옵니다.
차단기 기록 하단 시간은 표시하지 않고, 기록 클릭·영상 프레임 동기화는 유지합니다.
