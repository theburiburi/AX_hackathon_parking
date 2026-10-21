"""Read-only bridge to the native project; no HTTP server or inference on import.

src.video is safe to import directly. server.py initializes its engine at module
scope, so compile its existing definitions instead of executing its entrypoint.
The algorithms remain in the native files; this module contains no tracker.
"""
import ast
import json
import sys
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[2]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from src import video



class NativeProjectError(ValueError):
    pass


def tracking_definitions(project=PROJECT):
    """Offline only: execute the native tracking classes verbatim, without app startup."""
    path = project / "server.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    body = []
    required = {"FrameRequestCancelled", "CachedDetection", "DetectionCacheStore", "TrackingEngine"}
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VIDEO_TITLE" for t in node.targets):
            break
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(("fastapi", "starlette")):
                continue
            body.append(node)
        elif isinstance(node, ast.ClassDef) and node.name in required:
            found.add(node.name)
            body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {"load_yaml", "load_json_file", "format_parking_event"}:
            body.append(node)
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id.isupper() for t in node.targets):
            body.append(node)
    else:
        raise NativeProjectError("server.py의 엔진 초기화 경계를 찾을 수 없습니다.")
    if found != required:
        raise NativeProjectError("server.py의 추적 인터페이스가 변경되었습니다. 웹 어댑터를 확인하세요.")
    module = ModuleType("_ax_offline_tracking")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), module.__dict__)
    return module


class _NativeHTTPError(NativeProjectError):
    def __init__(self, *, status_code, detail):
        super().__init__(detail)


@lru_cache(maxsize=4)
def _gate_code(path, size, mtime_ns):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
    node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "gate_log"), None)
    if node is None:
        raise NativeProjectError("server.py의 gate_log 함수를 찾을 수 없습니다.")
    node.decorator_list = []
    return compile(ast.Module(body=[node], type_ignores=[]), path, "exec")


def read_native_gate_log(path, title):
    """Invoke server.py's gate reader with an isolated scene, without its FastAPI app."""
    source = PROJECT / "server.py"
    stat = source.stat()
    namespace = {
        "json": json, "HTTPException": _NativeHTTPError,
        "tracking_engine": SimpleNamespace(scene=SimpleNamespace(name=title, gate_log_path=path)),
    }
    exec(_gate_code(str(source), stat.st_size, stat.st_mtime_ns), namespace)
    return namespace["gate_log"]()


def gate_log_candidates(project, title):
    """Explicit shared-log overrides, then the native MosaicVideo per-video path."""
    scene = video.MosaicVideo(title, Path(), None)
    native_path = project / scene.gate_log_path.relative_to(video.ROOT)
    return (native_path.parent / "gate_logs.json", native_path.parent / "gate_log.json", native_path)


@lru_cache(maxsize=4)
def _cache_class(path, size, mtime_ns):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
    node = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DetectionCacheStore"), None)
    if node is None:
        raise NativeProjectError("server.py의 DetectionCacheStore를 찾을 수 없습니다.")
    namespace = {"__name__": "_ax_native_cache", "Path": Path, "json": json}
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)
    return namespace["DetectionCacheStore"]


@contextmanager
def open_native_cache(path, offsets):
    """Use the native reader with the offline index; avoid rescanning JSONL per request."""
    source = PROJECT / "server.py"
    stat = source.stat()
    cls = _cache_class(str(source), stat.st_size, stat.st_mtime_ns)
    reader = cls.__new__(cls)
    reader.path = path
    reader.offsets = offsets
    with path.open("rb") as reader.file:
        yield reader
