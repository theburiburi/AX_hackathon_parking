"""
영상 목록, 영상별 데이터 경로, calibration 자동 선택 (src/video.py), 해상도 배율 (src/mosaic.py).
"""

import pytest

import src.mosaic as mosaic
import src.video as video_module


def test_pixel_scale_same_cell_is_one():

    assert mosaic.pixel_scale((0, 0, 640, 360), [640, 360]) == 1.0


def test_pixel_scale_4k_cell_is_two():

    # test02: 3840x2160 모자이크의 칸 1280x720
    assert mosaic.pixel_scale((1280, 0, 2560, 720), [640, 360]) == 2.0


@pytest.fixture
def data_root(tmp_path, monkeypatch):

    raw_dir = tmp_path / "raw_video"
    raw_dir.mkdir()

    for title in ("clip_b", "clip_a"):
        (raw_dir / f"{title}.mp4").write_bytes(b"")

    # 영상이 아닌 파일은 무시
    (raw_dir / "notes.txt").write_text("x")

    monkeypatch.setattr(video_module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(video_module, "RAW_VIDEO_DIR", raw_dir)

    return tmp_path


def test_available_titles_are_raw_video_files(data_root):

    assert video_module.available_titles() == ["clip_a", "clip_b"]


def test_load_video_paths(data_root):

    video = video_module.load_video("clip_a")

    assert video.name == "clip_a"
    assert video.video_path == data_root / "raw_video" / "clip_a.mp4"
    assert video.data_dir == data_root / "clip_a"
    assert video.split_dir == data_root / "clip_a" / "cams"
    assert video.mosaic_path == data_root / "clip_a" / "mosaic.mp4"
    assert video.gate_log_path == data_root / "clip_a" / "gate_log.json"


def test_calibration_dir_is_shared_and_cells_follow_resolution(data_root):

    video = video_module.load_video("clip_a")

    # 원본 해상도를 읽는 대신 값을 넣어 확인
    video.__dict__["video_size"] = (3840, 2160)

    # calibration은 모든 영상 공통 (config/calibration/<camera_id>.json)
    assert video.calibration_dir == video_module.CALIBRATION_ROOT

    # 칸 위치는 원본 해상도로 계산 (3x3, 칸 1280x720)
    assert video.cell_rects["cam01"] == (0, 0, 1280, 720)
    assert video.cell_rects["cam08"] == (0, 1440, 1280, 2160)


def test_calibration_files_exist_for_all_cameras():

    for camera_id in mosaic.load_layout().camera_ids:
        assert (video_module.CALIBRATION_ROOT / f"{camera_id}.json").is_file()


def test_load_video_missing_lists_available(data_root):

    with pytest.raises(FileNotFoundError, match="clip_a, clip_b"):
        video_module.load_video("nope")
