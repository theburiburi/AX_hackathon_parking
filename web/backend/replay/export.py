"""Run the native tracking engine once, outside the HTTP server."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from native_project import tracking_definitions as native_definitions

from .store import CACHE_ROOT, PROJECT, ReplayError, config_digest, file_digest, signature, title_value


def export(title, *, overwrite=False, progress=print):
    title = title_value(title)
    folder = CACHE_ROOT / title
    if (folder / "manifest.json").exists() and not overwrite:
        raise ReplayError("이미 생성된 재생 결과가 있습니다. 다시 만들려면 --overwrite를 사용하세요.")
    native = native_definitions()
    scene = native.load_video(title)
    engine = native.TrackingEngine(scene)
    try:
        import cv2
        image = cv2.imread(str(PROJECT / "data/maps/map.png"))
        if image is None:
            raise ReplayError("data/maps/map.png를 읽을 수 없습니다.")
        height, width = image.shape[:2]
        zones_data = json.loads((PROJECT / "data/maps/zones.json").read_text(encoding="utf-8"))
        zones = zones_data["zones"]
        if zones_data["map"] != {"width": width, "height": height}:
            raise ReplayError("지도와 구역 JSON의 이미지 크기가 다릅니다.")
        metadata = json.loads((scene.detections_dir / "metadata.json").read_text(encoding="utf-8"))
        capture = cv2.VideoCapture(str(scene.video_path))
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            capture.release()
        if not math.isfinite(fps) or fps <= 0 or count != engine.cache.frame_count:
            raise ReplayError("영상 프레임 수와 검출 캐시가 일치하지 않습니다.")
        if metadata["source_size"] != [engine.mosaic_width, engine.mosaic_height] or metadata["frame_count"] != count or abs(metadata["fps"] - fps) > .01:
            raise ReplayError("검출 metadata와 원본 영상의 해상도·FPS·프레임 수가 다릅니다.")
        if metadata["layout"]["crop_rects"] != {k: list(v) for k, v in engine.crop_rects.items()}:
            raise ReplayError("검출 캐시와 현재 카메라 칸 배치가 다릅니다.")
        engine.nominal_fps = fps
        warnings = []
        calibration_sizes = {}
        for camera in engine.camera_ids:
            if camera not in engine.projectors:
                raise ReplayError(f"{camera} 보정 파일을 읽지 못했습니다.")
            data = json.loads((scene.calibration_dir / f"{camera}.json").read_text(encoding="utf-8"))
            expected = data["image_size"]["width"], data["image_size"]["height"]
            x1, y1, x2, y2 = engine.crop_rects[camera]
            actual = x2 - x1, y2 - y1
            if min(*expected, *actual) <= 0 or abs(expected[0] / expected[1] - actual[0] / actual[1]) > .001:
                raise ReplayError(f"{camera}의 보정과 영상 종횡비가 다릅니다. 보정을 확인하세요.")
            if data.get("bev_size") != {"width": width, "height": height}:
                raise ReplayError(f"{camera} 보정의 지도 크기가 다릅니다.")
            calibration_sizes[camera] = (expected, actual)
            # Tracking's pixel thresholds were calibrated at the same resolution.
            # Scale the raw boxes down BEFORE local tracking, then scale the overlay
            # boxes back up when serializing. BEV projection receives native units.
            if expected != actual:
                warnings.append(f"{camera}: {actual[0]}×{actual[1]} 검출을 {expected[0]}×{expected[1]} 보정·추적 기준으로 변환했습니다.")
        original_read = engine.cache.read_frame

        def scaled_read(n):
            frame = original_read(n)
            for camera, items in frame["cameras"].items():
                expected, actual = calibration_sizes[camera]
                for item in items:
                    for field in ("x1", "x2"):
                        item[field] *= expected[0] / actual[0]
                    for field in ("y1", "y2"):
                        item[field] *= expected[1] / actual[1]
            return frame

        engine.cache.read_frame = scaled_read
        # Gate events are read independently at request time, not frozen into
        # the expensive tracking export or included in its source signature.
        gate = {"events": [], "gate": None}
        source_paths = [scene.video_path, engine.cache_path, scene.detections_dir / "metadata.json"]
        sources = [{"path": p.relative_to(PROJECT).as_posix(), "stat": signature(p),
                    "sha256": file_digest(str(p), **signature(p))} for p in source_paths]
        digest = config_digest()
        folder.mkdir(parents=True, exist_ok=True)
        cache_id = uuid4().hex
        frames_path = folder / f"frames-{cache_id}.jsonl"
        offsets = []
        with frames_path.open("wb") as target:
            for n in range(count):
                frame = engine.get_frame(n)
                for camera, items in frame["cameras"].items():
                    expected, actual = calibration_sizes[camera]
                    for item in items:
                        for field in ("x1", "x2", "ground_x"):
                            item[field] *= actual[0] / expected[0]
                        for field in ("y1", "y2", "ground_y"):
                            item[field] *= actual[1] / expected[1]
                # get_frame returns its last_result; only serialized camera boxes
                # are changed, never the track's internal coordinates.
                # BEV positions, eligibility, states and IDs are supplied only
                # by TrackingEngine. Do not project UNKNOWN/parked detections or
                # attach an independent web location/zone result.
                offsets.append(target.tell())
                target.write((json.dumps(frame, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8"))
                if n % 300 == 0 or n == count - 1:
                    progress(f"Tracking cache {n + 1}/{count}")
        for source in sources:
            if signature(PROJECT / source["path"]) != source["stat"]:
                raise ReplayError("캐시 생성 중 원본 파일이 변경됐습니다. 다시 생성하세요.")
        if config_digest() != digest:
            raise ReplayError("캐시 생성 중 보정·설정 파일이 변경됐습니다. 다시 생성하세요.")
        index_file = folder / f"index-{cache_id}.json"
        index_file.write_text(json.dumps(offsets), encoding="utf-8")
        manifest = {"schema_version": 1, "title": title, "cache_id": cache_id,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "fps": fps, "frame_count": count, "duration": count / fps,
                    "video_path": scene.video_path.relative_to(PROJECT).as_posix(),
                    "frames_file": frames_path.name, "index_file": index_file.name,
                    "sources": sources, "config_digest": digest,
                    "scene": engine.scene_info(),
                    "map": {"width": width, "height": height, "zones": zones},
                    "gate_log": gate, "warnings": warnings}
        temporary = folder / f"manifest-{cache_id}.tmp"
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(folder / "manifest.json")
        return manifest
    finally:
        engine.cache.file.close()
