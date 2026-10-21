# 데이터 폴더

실행 방법과 데이터 형식은 루트 [README.md](../README.md)를 참고한다.

```text
data/
├── raw_video/<title>.mp4       # 모자이크 원본. 파일 이름 = 영상 제목 (Git 제외)
├── <title>/                    # 영상 1개의 결과 (스크립트가 만듦)
│   ├── mosaic.mp4              #   칸 좌우 여백을 없앤 모자이크, 웹 재생용 (00_prepare_video.py, Git 제외)
│   ├── cams/camXX.mp4          #   칸 좌우 여백을 없앤 카메라 영상 (00_prepare_video.py, Git 제외)
│   ├── content.jsonl           #   프레임별 원래 화면 가로 범위 (00_prepare_video.py, Git 제외)
│   ├── detections.jsonl        #   프레임별 카메라별 bbox (01_detect_vehicles.py, Git 제외)
│   ├── metadata.json           #   영상 준비 / 검출 조건 기록
│   └── gate_log.json           #   차단기 입출차 기록 (scripts/04_detect_gate_events.py, 선택)
└── maps/                       # 모든 영상 공통
    ├── map.png                 # BEV 지도 (1624 x 968)
    ├── zones.json              # 주차 구역 정의 (웹 BEV 표시용)
    └── zones.png               # 주차 구역 참고 이미지 (코드에서 사용하지 않음)
```

- 영상 제목(`<title>`) = `data/raw_video/`의 파일 이름에서 확장자를 뺀 것 (예: `test00`)
- `mosaic.mp4`, `cams/`, `content.jsonl`, `detections.jsonl`은 원본과 설정만 있으면
  `scripts/00_prepare_video.py` → `scripts/01_detect_vehicles.py`로 다시 만들 수 있다.
