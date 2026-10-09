# 데이터 폴더

`scene1`은 함께 처리할 영상 묶음 이름이다. 코드나 설정 패키지 이름이 아니다.

```text
data/
├── videos/scene1/        # 카메라 영상 (Git 제외)
├── detections/scene1/    # YOLO detection 캐시 (detections.jsonl, metadata.json)
├── maps/map.png          # BEV 지도 (1624 x 968)
└── parking/
    ├── zones.json        # 주차 구역 정의 (웹 BEV 표시용)
    └── *.png             # 참고용 이미지
```

## 설정 파일

- `config/detection.yaml`
  - 카메라 ID와 영상 경로 목록 (`videos`)
  - YOLO 모델, 추론 설정
- `config/calibration/camXX.json`
  - 카메라별 영상 → BEV 보정점과 변환 정보
  - `mapping` 필드가 있으면 Homography + TPS를 사용하고, 없으면 `homography`만 사용한다.
- `config/tracking.yaml`, `config/global_tracking.yaml`
  - Local / Global tracking 파라미터

## 실행 순서

1. YOLO detection 캐시 생성

   ```bash
   python scripts/preprocess_yolo.py
   ```

   결과는 `data/detections/<scene_name>/`에 저장된다.

2. 카메라 캘리브레이션 (카메라마다)

   ```bash
   python scripts/calibrate_camera.py --camera cam01 --frame 300
   ```

   - 왼쪽 클릭: 영상 점 → BEV 점 순서로 보정점 추가
   - 영상 점을 찍으면 BEV에 예측 위치(초록 PRED)가 표시된다.
   - C: coverage 표시 / P: 보정점 표시 / U: undo / S: 저장 / Q: 종료
   - 변경 사항이 없으면 종료할 때 파일을 덮어쓰지 않는다.

3. 서버 실행

   ```bash
   python server.py
   ```

   브라우저에서 `http://127.0.0.1:8000` 접속.
   캘리브레이션을 수정한 뒤에는 웹의 Reload 버튼으로 다시 읽을 수 있다.

## 참고

- 서버는 현재 `data/detections/scene1/detections.jsonl`을 고정 경로로 읽는다.
- 영상(`data/videos/`)은 Git에서 제외한다.
