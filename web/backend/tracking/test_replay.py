import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from replay import store
from . import views


class ReplayApiTests(SimpleTestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        folder = self.root / "demo"
        folder.mkdir()
        (self.root / "clip.mp4").write_bytes(b"0123456789")
        (self.root / "data/maps").mkdir(parents=True)
        (self.root / "data/maps/map.png").write_bytes(b"map")
        (folder / "frames.jsonl").write_bytes(b'{"frame_index":0,"cameras":{},"bev":[]}\n')
        (folder / "index.json").write_text("[0]")
        manifest = {"schema_version": 1, "title": "demo", "cache_id": "abc", "fps": 30,
                    "frame_count": 1, "duration": 1/30, "scene": {}, "map": {}, "gate_log": {"events": []}, "warnings": [], "generated_at": "2026-10-10",
                    "frames_file": "frames.jsonl", "index_file": "index.json", "video_path": "clip.mp4", "sources": [], "config_digest": store.config_digest(self.root)}
        (folder / "manifest.json").write_text(json.dumps(manifest))
        self.manifest_path = folder / "manifest.json"
        for context in [patch.object(store, "PROJECT", self.root), patch.object(store, "CACHE_ROOT", self.root),
                        patch.dict(os.environ, {"WEB_REPLAY_VIDEO": "demo"}), patch.object(views, "current_user", return_value={"role": "ADMIN"})]:
            context.start()
            self.addCleanup(context.stop)

    def test_all_analysis_and_media_routes_require_admin(self):
        for route in ["manifest", "frames", "video", "map"]:
            for user, expected in [(None, 401), ({"role": "USER"}, 403)]:
                with self.subTest(route=route, user=user), patch.object(views, "current_user", return_value=user):
                    self.assertEqual(self.client.get(f"/api/replay/{route}/").status_code, expected)

    def test_manifest_and_frames_are_read_only_and_match_cache_version(self):
        manifest = self.client.get("/api/replay/manifest/")
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()["scene"]["video_url"], "/replay/video/")
        self.assertNotIn("video_path", manifest.json())
        response = self.client.get("/api/replay/frames/?start=0&count=60&cache_id=abc")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["frames"][0]["frame_index"], 0)
        self.assertEqual(self.client.get("/api/replay/frames/?cache_id=old").status_code, 503)

    def test_invalid_ranges_and_missing_data_are_clear_errors(self):
        for query in ["start=-1", "start=1", "start=oops", "count=0", "count=121"]:
            self.assertEqual(self.client.get("/api/replay/frames/?" + query).status_code, 400)
        self.manifest_path.unlink()
        self.assertEqual(self.client.get("/api/replay/manifest/").status_code, 503)

    def test_cached_frame_response_still_checks_permissions_and_cache_version(self):
        url = "/api/replay/frames/?start=0&count=60&cache_id=abc"
        first = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.get(url).content, first.content)
        for user, status in ((None, 401), ({"role": "USER"}, 403)):
            with patch.object(views, "current_user", return_value=user):
                self.assertEqual(self.client.get(url).status_code, status)
        self.assertEqual(self.client.get(url.replace("abc", "old")).status_code, 503)

    def test_cached_frame_response_rereads_changed_data_and_validates_settings(self):
        url = "/api/replay/frames/?start=0&count=60&cache_id=abc"
        self.assertEqual(self.client.get(url).status_code, 200)
        path = self.root / "demo/frames.jsonl"
        path.write_text('{"frame_index":0,"cameras":{},"bev":[{"global_id":7}]}\n', encoding="utf-8")
        self.assertEqual(self.client.get(url).json()["frames"][0]["bev"], [{"global_id": 7}])
        path.write_text('{"frame_index":99}\n', encoding="utf-8")
        self.assertEqual(self.client.get(url).status_code, 503)
        (self.root / "config").mkdir()
        (self.root / "config/tracking.yaml").write_text("changed", encoding="utf-8")
        self.assertEqual(self.client.get(url).status_code, 503)

    def test_video_supports_range_and_head_without_public_media_route(self):
        response = self.client.get("/api/replay/video/", HTTP_RANGE="bytes=2-4")
        try:
            self.assertEqual(response.status_code, 206)
            self.assertEqual(b"".join(response.streaming_content), b"234")
        finally:
            response.close()
        response = self.client.head("/api/replay/video/")
        self.assertEqual(response["Content-Length"], "10")
        self.assertEqual(response.content, b"")
        self.assertEqual(self.client.get("/media/raw/clip.mp4").status_code, 404)

    def test_shared_gate_log_is_loaded_on_refresh_without_rebuilding_cache(self):
        path = self.root / "data/demo/gate_logs.json"
        path.parent.mkdir()
        data = {"video": "demo", "fps": 30, "gate": {"name": "Gate"},
                "events": [{"frame": 0, "type": "IN", "label": "Arrival"}]}
        path.write_text(json.dumps(data))
        result = self.client.get("/api/replay/manifest/").json()
        self.assertEqual(result["gate_log"]["events"][0]["type"], "IN")
        data["events"][0]["type"] = "OUT"
        path.write_text(json.dumps(data))
        updated = self.client.get("/api/replay/manifest/").json()
        self.assertEqual(updated["cache_id"], result["cache_id"])
        self.assertEqual(updated["gate_log"]["events"][0]["type"], "OUT")

    def test_invalid_gate_log_does_not_break_video_or_mix_other_video_events(self):
        path = self.root / "data/demo/gate_logs.json"
        path.parent.mkdir()
        for data in [
            {"video": "other", "fps": 30, "events": [{"frame": 0}]},
            {"video": "demo", "fps": 60, "events": [{"frame": 0}]},
            {"video": "demo", "fps": 30, "events": [{"frame": 100}]},
            {"video": "demo", "fps": 30, "events": [{"frame": True}]},
        ]:
            path.write_text(json.dumps(data))
            response = self.client.get("/api/replay/manifest/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["gate_log"]["events"], [])
            self.assertTrue(response.json()["warnings"])
        path.write_text("{")
        self.assertEqual(self.client.get("/api/replay/manifest/").json()["gate_log"]["events"], [])

    def test_plural_gate_log_takes_priority_over_legacy_file(self):
        folder = self.root / "data/demo"
        folder.mkdir()
        data = {"video": "demo", "fps": 30, "events": [{"frame": 0, "type": "IN"}]}
        (folder / "gate_log.json").write_text(json.dumps(data))
        self.assertEqual(self.client.get("/api/replay/manifest/").json()["gate_log"]["events"][0]["type"], "IN")
        data["events"][0]["type"] = "OUT"
        (folder / "gate_logs.json").write_text(json.dumps(data))
        self.assertEqual(self.client.get("/api/replay/manifest/").json()["gate_log"]["events"][0]["type"], "OUT")
        (folder / "gate_logs.json").write_text("{")
        self.assertEqual(self.client.get("/api/replay/manifest/").json()["gate_log"]["events"], [])


class BuiltFrontendTests(SimpleTestCase):
    def test_built_shell_assets_and_api_routing(self):
        with TemporaryDirectory() as temp, override_settings(WEB_DIR=Path(temp)):
            root = Path(temp) / "frontend/dist"
            (root / "assets").mkdir(parents=True)
            (root / "index.html").write_text("<div id='root'></div>")
            (root / "assets/app.js").write_text("console.log('app')")
            response = self.client.get("/")
            try:
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"root", b"".join(response.streaming_content))
                self.assertEqual(response["Cache-Control"], "no-cache")
            finally:
                response.close()
            response = self.client.get("/assets/app.js")
            self.assertEqual(response.status_code, 200)
            response.close()
            self.assertEqual(self.client.get("/assets/../../secret").status_code, 404)
            self.assertEqual(self.client.get("/api/missing/").status_code, 404)
