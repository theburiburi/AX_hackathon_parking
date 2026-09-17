# 영상과 지도

`scene1`은 함께 처리할 영상 묶음 이름이다. 코드나 설정 패키지 이름이 아니다.

```text
data/
├── videos/
│   ├── scene1/          # 현재 카메라 영상 묶음
│   └── scene2/          # 다른 묶음이 생기면 추가 (현재 없음)
└── maps/master_bev.png
```

현재 카메라별 파일 경로·FPS·offset·보정점은 루트 `cameras.yaml`에서 관리한다.
다른 묶음을 사용하려면 해당 영상 경로와 보정값을 지정한 카메라 설정을 준비하고
`python -m src.main --cameras-config <설정 파일>`로 실행한다.
폴더 이름만으로 영상을 자동 선택하지 않는다.

기존 `videos/web/` 프록시는 기본 실행에는 사용하지 않는다.
영상과 지도는 Git에서 제외한다.
