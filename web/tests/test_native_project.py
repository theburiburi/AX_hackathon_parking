"""Contract tests for external source reuse and the lightweight HTTP boundary."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from native_project import PROJECT, mosaic, read_native_gate_log, tracking_definitions, open_native_cache
from replay.store import read_gate_log, selected_title
from tracking import project_media


class NativeProjectTests(unittest.TestCase):
    def test_runtime_import_does_not_load_engine_or_inference_frameworks(self):
        code = r"""
import sys
sys.path.insert(0, sys.argv[1])
import native_project
import replay.store
import tracking.project_media
import tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "frames.jsonl"
    path.write_text('{"frame_index":0,"bev":[]}\n', encoding="utf-8")
    with native_project.open_native_cache(path, [0]) as reader:
        assert reader.read_frame(0) == {"frame_index": 0, "bev": []}
assert not ({'server', 'cv2', 'numpy', 'torch', 'ultralytics', 'fastapi'} & sys.modules.keys())
"""
        subprocess.run([sys.executable, "-B", "-c", code, str(BACKEND)], check=True, cwd=PROJECT)

    def test_replay_reader_is_native_and_preserves_engine_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "frames.jsonl"
            row = {"frame_index": 0, "cameras": {"cam01": []}, "bev": [
                {"state": "ACTIVE", "global_id": 8, "x": 12.5, "y": 28.25}]}
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with open_native_cache(path, [0]) as reader:
                self.assertEqual(reader.read_frame(0), row)
                self.assertEqual(Path(reader.read_frame.__code__.co_filename), PROJECT / "server.py")
            self.assertTrue(reader.file.closed)
            path.write_text('{"frame_index":5}\n', encoding="utf-8")
            with open_native_cache(path, [0]) as reader:
                with self.assertRaisesRegex(RuntimeError, "not sequential"):
                    reader.read_frame(0)
            self.assertTrue(reader.file.closed)

    def test_selection_delegates_to_native_mosaic_and_keeps_explicit_web_override(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(mosaic, "default_title", return_value="native_video") as choose:
            self.assertEqual(selected_title(), "native_video")
            choose.assert_called_once_with()
        with patch.dict(os.environ, {"WEB_REPLAY_VIDEO": "override"}), patch.object(mosaic, "default_title") as choose:
            self.assertEqual(selected_title(), "override")
            choose.assert_not_called()

    def test_offline_definitions_keep_native_source_and_tracker_identity(self):
        native = tracking_definitions()
        from src.tracking import LocalTracker, GlobalTracker
        self.assertIs(native.LocalTracker, LocalTracker)
        self.assertIs(native.GlobalTracker, GlobalTracker)
        self.assertIs(native.load_video, mosaic.load_video)
        self.assertEqual(Path(native.TrackingEngine.get_frame.__code__.co_filename), PROJECT / "server.py")
        self.assertFalse(hasattr(native, "tracking_engine"))
        self.assertFalse(hasattr(native, "app"))

    def test_native_gate_reader_sorts_and_rereads_file_without_engine_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "data/gate_logs/demo.json"
            path.parent.mkdir(parents=True)
            data = {"video": "demo", "fps": 30, "events": [{"frame": 3, "type": "OUT"}, {"frame": 1, "type": "IN"}]}
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual([e["frame"] for e in read_native_gate_log(path, "demo")["events"]], [1, 3])
            # No shared log: use the native MosaicVideo <title>.json convention.
            result, warning = read_gate_log(root, "demo", 30, 5)
            self.assertIsNone(warning)
            self.assertEqual(result["events"][0]["type"], "IN")
            data["events"] = [{"frame": 2, "type": "OUT"}]
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(read_gate_log(root, "demo", 30, 5)[0]["events"], data["events"])

    def test_native_map_display_does_not_require_video_or_detection_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "data/maps/map.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"map")
            with patch.object(project_media, "PROJECT", root), patch.dict(os.environ, {}, clear=True), patch.object(mosaic, "load_layout", side_effect=AssertionError("Map API must not load video layout")):
                self.assertEqual(project_media.selected_map(root / "media", lambda *args: None, {".png"}), image)

    def test_zone_geometry_and_capacity_come_from_external_json(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "data/maps/map.png"
            image.parent.mkdir(parents=True)
            source = {"map": {"width": 1000, "height": 500}, "zones": [
                {"id": "NEW", "capacity": 12, "bndbox": {"xmin": 100, "ymin": 50, "xmax": 300, "ymax": 250}}]}
            (image.parent / "zones.json").write_text(json.dumps(source))
            with patch.object(project_media, "PROJECT", root):
                layout = project_media.map_layout(image, {"zones": []})
            self.assertEqual(layout["map_id"], "map.png")
            self.assertEqual(layout["zones"][0]["id"], "NEW")
            self.assertEqual(layout["zones"][0]["capacity"], 12)
            self.assertEqual(layout["zones"][0]["polygon"], [[10, 10], [30, 10], [30, 50], [10, 50]])
