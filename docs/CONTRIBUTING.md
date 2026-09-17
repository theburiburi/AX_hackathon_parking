# 담당과 작업 방법

| 담당 | 이름 | 주 수정 위치 |
|---|---|---|
| 차량 인식·ID | [작성] | `src/tracking.py`, 향후 Global ID 구현 파일 |
| 좌표·동기화 | [작성] | `src/calibration/`, `src/playback/`, `src/camera_config.py`, `src/visualization.py` |
| 웹 | [작성] | 루트 `web/` |
| 실행 통합 (위 두 비웹 담당자 중 한 명) | [작성] | `src/main.py` |

## 작업 규칙

1. 기능을 수정할 때는 README의 작업 위치 표에서 시작한다.
2. 현재 구현할 코드가 없으면 폴더·클래스·호환 파일을 미리 추가하지 않는다.
3. 검출·ID 판단은 차량 담당, 좌표 계산·영상 시간 정렬은 좌표 담당이 맡는다.
4. `cameras.yaml`은 좌표 담당이 관리한다. `config.yaml`과 requirements는 변경 항목을 공유한다.
5. 공용 데이터 형식은 [합의서](INTERFACE_AGREEMENT.md)를 작성한 뒤 변경한다.
6. 각 기능 담당자는 해당 테스트와 README를 함께 갱신한다.
7. 각자 작업 복사본과 브랜치를 사용하고 변경 단위별로 검토한다.

## 검증

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

기본 테스트에는 브라우저·모델 가중치·실제 CCTV가 필요하지 않다.
영상·지도·모델 weight·자격증명·개인 PC 절대경로는 commit하지 않는다.
