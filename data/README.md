# 데이터 폴더

실행 방법과 데이터 형식은 루트 [README.md](../README.md)를 참고한다.

```text
data/
├── videos/
│   ├── raw/<title>.mp4             # 모자이크 원본 (Git 제외)
│   └── <title>/camXX.mp4           # scripts/preprocess.py가 만든 분리 영상 (Git 제외)
├── detections/<title>/             # scripts/preprocess.py가 만든 YOLO 결과
│   ├── detections.jsonl            #   프레임별 카메라별 bbox (칸 기준 좌표)
│   └── metadata.json               #   생성 조건 기록
└── maps/
    ├── map.png                     # BEV 지도 (1624 x 968)
    ├── zones.json                  # 주차 구역 정의 (웹 BEV 표시용)
    └── *.png                       # 참고용 이미지
```

- 영상 제목(`<title>`) = `videos/raw/` 안의 파일 이름에서 확장자를 뺀 것 (예: `test00`)
- `videos/`와 `detections/` 아래 내용은 원본과 설정만 있으면 `scripts/preprocess.py`로 다시 만들 수 있다.
