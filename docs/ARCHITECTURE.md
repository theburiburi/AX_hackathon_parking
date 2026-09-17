# Architecture

## 현재 원칙

초기 프로젝트에서는 파일을 열면 해당 기능의 구현을 바로 찾을 수 있게 한다.
단일 파일로 충분한 기능은 패키지로 나누지 않는다. 미구현 기능의 폴더도 만들지 않는다.

- `tracking.py`: 기존 차량 데이터 타입, YOLO 검출, local tracking.
- `calibration/`: Homography 계산, 카메라별 행렬 준비, 클릭 보정 도구.
- `playback/`: 공통 시간으로 영상 읽기, OpenCV 동기 재생.
- `main.py`: 다중 카메라의 읽기 → 선택적 검출 → CCTV·정적 지도 표시 연결.
- `camera_config.py`: 카메라 설정 로딩·검증.
- `visualization.py`: OpenCV 그리기와 화면 배치.
- 루트 `web/`: 웹 담당 영역. 현재 웹 구현은 없다.

## 의존 방향

```text
main → tracking
          → playback / camera_config
          → visualization
```

검출·좌표·동기화 모듈은 FastAPI나 브라우저를 import하지 않는다.
좌표 함수는 좌표와 행렬만 받아 계산하며, 차량 ID 판단을 하지 않는다.
`calibration/cameras.py`는 카메라별 보정 행렬을 준비한다.
현재 기본 화면은 정적 지도만 표시하며 차량 위치 투영은 연결하지 않았다.

## 확장과 호환

Global ID와 동일 차량의 위치 통합은 아직 미구현이다.
[합의서](INTERFACE_AGREEMENT.md) 작성 후 실제 구현에 필요한 파일부터 추가한다.
Global ID는 `src/association.py`에서 시작할 수 있으며, 미리 패키지를 만들지 않는다.

기본 실행은 `python -m src.main`으로 통일한다. 보정·재생 명령과 `src.tracking`, `src.calibration.homography`의
공개 기능은 유지한다. TrackedVehicle 필드, 보정점 형식, reader 반환값은 변경하지 않는다.
BEV 좌표는 지도 이미지 픽셀이며, 다중 카메라 검출 번호는 지속 ID가 아니다.

웹 API가 필요해지면 그때 경계를 정한다. API route나 브라우저 클라이언트마다
YOLO 모델을 생성하지 않는다. 입력 영상·지도·모델 가중치는 Git에 포함하지 않는다.
