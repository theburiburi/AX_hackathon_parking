"""Read indexed, precomputed frames without loading a whole video into memory."""
import hashlib
import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path

from native_project import video, gate_log_candidates, read_native_gate_log, open_native_cache

PROJECT = Path(__file__).resolve().parents[3]
CACHE_ROOT = Path(__file__).resolve().parents[1] / "replay_data"


class ReplayError(ValueError):
    pass


def read_gate_log(project, title, fps, frame_count):
    """Read independently of the tracking cache so log edits need no rebuild."""
    candidates = gate_log_candidates(project, title)
    path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    empty = {"video": title, "gate": None, "events": []}
    if not path.is_file():
        return empty, f"data/{title}/gate_log.json 파일이 없습니다."
    try:
        data = read_native_gate_log(path, title)
        if not isinstance(data, dict) or data.get("video") != title:
            raise ValueError("video 값이 현재 재생 영상과 다릅니다.")
        log_fps = data.get("fps")
        if type(log_fps) not in (int, float) or not math.isfinite(log_fps) or not math.isclose(log_fps, fps, abs_tol=.01):
            raise ValueError("fps 값이 현재 재생 영상과 다릅니다.")
        events = data.get("events")
        if not isinstance(events, list) or any(
            not isinstance(event, dict) or type(event.get("frame")) is not int
            or not 0 <= event["frame"] < frame_count for event in events
        ):
            raise ValueError("events의 frame 값은 영상 범위 안의 정수여야 합니다.")
        return data, None
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return empty, f"차단기 기록을 읽지 못했습니다: {exc}"


def title_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ReplayError("영상 이름은 영문, 숫자, 밑줄, 하이픈만 사용할 수 있습니다.")
    return value


def selected_title():
    override = os.environ.get("WEB_REPLAY_VIDEO")
    if override:
        return title_value(override)
    import yaml
    try:
        return title_value(video.default_title())
    except (OSError, ValueError, AttributeError, yaml.YAMLError) as exc:
        raise ReplayError("config/detection.yaml의 video 설정을 확인하세요. 예: video: test02") from exc


def signature(path):
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


@lru_cache(maxsize=12)
def file_digest(path, size, mtime_ns):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def config_digest(project=PROJECT):
    files = [project / "server.py", project / "config/mosaic.yaml",
             project / "config/tracking.yaml", project / "config/global_tracking.yaml",
             project / "data/maps/map.png", project / "data/maps/zones.json"]
    files.extend(sorted((project / "config/calibration").glob("*.json")))
    files.extend(sorted((project / "src").rglob("*.py")))
    files.extend([project / "web/backend/replay/export.py", project / "web/backend/native_project.py"])
    stamps = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else (str(p), 0, 0) for p in files)
    return _config_digest(str(project), stamps)


@lru_cache(maxsize=8)
def _config_digest(project, stamps):
    project = Path(project)
    digest = hashlib.sha256()
    for name, _, _ in stamps:
        path = Path(name)
        digest.update(path.relative_to(project).as_posix().encode())
        digest.update(path.read_bytes() if path.is_file() else b"MISSING")
    return digest.hexdigest()


@lru_cache(maxsize=8)
def _index(path, size, mtime_ns):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ReplayStore:
    def __init__(self, title=None, *, root=None, project=None, validate=True):
        self.title = title_value(title) if title is not None else selected_title()
        self.root = Path(root) if root is not None else CACHE_ROOT
        self.project = Path(project) if project is not None else PROJECT
        folder = self.root / self.title
        try:
            self.manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            if self.manifest["schema_version"] != 1 or self.manifest["title"] != self.title:
                raise ReplayError("지원하지 않는 재생 캐시 형식입니다.")
            self.frames_path = self._inside(folder, self.manifest["frames_file"])
            index_path = self._inside(folder, self.manifest["index_file"])
            stat = index_path.stat()
            self.offsets = _index(str(index_path), stat.st_size, stat.st_mtime_ns)
            if len(self.offsets) != self.manifest["frame_count"] or not self.frames_path.is_file():
                raise ReplayError("재생 캐시가 완성되지 않았습니다. 다시 생성하세요.")
            self.video_path = self._inside(self.project, self.manifest["video_path"])
            if validate:
                for source in self.manifest["sources"]:
                    # Older manifests embedded per-video gate logs. The current
                    # UI reads gate_logs.json separately, not that old snapshot.
                    if Path(source["path"]).parts[:2] == ("data", "gate_logs"):
                        continue
                    path = self._inside(self.project, source["path"])
                    current = signature(path)
                    if current != source["stat"]:
                        # Copying files to a teammate's computer changes mtimes,
                        # not necessarily content. Hash once per file revision.
                        if current["size"] != source["stat"]["size"] or file_digest(str(path), **current) != source.get("sha256"):
                            raise ReplayError("원본 영상 또는 검출 결과가 변경됐습니다. 재생 캐시를 다시 생성하세요.")
                if config_digest(self.project) != self.manifest["config_digest"]:
                    raise ReplayError("보정·추적·지도 설정이 변경됐습니다. 재생 캐시를 다시 생성하세요.")
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ReplayError(f"재생 결과가 준비되지 않았습니다. python -B web/build_replay.py --video {self.title}") from exc

    @staticmethod
    def _inside(root, relative):
        target = (root / relative).resolve()
        if not target.is_relative_to(root.resolve()):
            raise ReplayError("잘못된 재생 파일 경로입니다.")
        return target

    def frames(self, start, count):
        if not 0 <= start < len(self.offsets):
            raise ReplayError("영상 프레임 범위를 벗어났습니다.")
        if not 1 <= count <= 120:
            raise ReplayError("한 번에 1~120프레임을 요청할 수 있습니다.")
        try:
            with open_native_cache(self.frames_path, self.offsets) as source:
                return [source.read_frame(n) for n in range(start, min(start + count, len(self.offsets)))]
        except (RuntimeError, IndexError, ValueError) as exc:
            raise ReplayError("프레임 캐시가 손상됐습니다. 재생 캐시를 다시 생성하세요.") from exc

    def public_manifest(self):
        result = {key: self.manifest[key] for key in (
            "schema_version", "title", "cache_id", "fps", "frame_count", "duration",
            "scene", "map", "gate_log", "warnings", "generated_at")}
        result["gate_log"], warning = read_gate_log(self.project, self.title, result["fps"], result["frame_count"])
        result["warnings"] = [item for item in result["warnings"] if item != "이 영상의 차단기 기록이 없습니다."]
        if warning:
            result["warnings"].append(warning)
        return result
