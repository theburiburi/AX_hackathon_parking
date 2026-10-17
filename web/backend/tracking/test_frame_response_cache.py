import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase
from rest_framework.renderers import JSONRenderer

from replay.frame_response import FrameResponseCache


class FrameResponseCacheTests(SimpleTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "frames.jsonl"
        self.path.write_text("original", encoding="utf-8")
        self.store = SimpleNamespace(frames_path=self.path, offsets=[0, 20],
                                     manifest={"cache_id": "one"},
                                     frames=Mock(return_value=[{"frame_index": 0, "bev": [{"x": 1.25}]}]))
        self.cache = FrameResponseCache()
        self.renderer = JSONRenderer()

    def render(self, start=0, count=60, media_type="application/json"):
        return self.cache.render(self.store, start, count, self.renderer, media_type)

    def test_same_batch_reuses_immutable_bytes_and_preserves_json_format(self):
        first = self.render()
        self.assertEqual(first, self.renderer.render({"cache_id": "one", "frames": self.store.frames.return_value}))
        decoded = json.loads(first)
        decoded["frames"][0]["bev"][0]["x"] = 999
        self.assertIs(self.render(), first)
        self.store.frames.assert_called_once_with(0, 60)
        self.assertEqual(json.loads(self.render())["frames"][0]["bev"][0]["x"], 1.25)
        pretty = self.render(media_type="application/json; indent=4")
        self.assertIn(b"\n", pretty)
        self.assertEqual(json.loads(pretty), json.loads(first))

    def test_file_replacement_offsets_and_cache_version_invalidate_response(self):
        self.render()
        replacement = self.path.with_suffix(".tmp")
        replacement.write_text("modified", encoding="utf-8")
        replacement.replace(self.path)
        self.render()
        self.assertEqual(self.store.frames.call_count, 2)
        self.store.offsets = [0, 21]
        self.render()
        self.assertEqual(self.store.frames.call_count, 3)
        self.store.manifest["cache_id"] = "two"
        self.assertEqual(json.loads(self.render())["cache_id"], "two")
        self.assertEqual(self.store.frames.call_count, 4)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.render()

    def test_cache_is_bounded_by_bytes_and_entries_and_uses_recent_batches(self):
        size = len(self.render())
        self.cache = FrameResponseCache(max_bytes=size * 2, max_entries=2)
        self.render(0)
        self.render(60)
        self.render(0)  # Keep the recently displayed range.
        self.render(120)
        self.assertEqual(len(self.cache.entries), 2)
        self.assertEqual(self.cache.size, size * 2)
        calls = self.store.frames.call_count
        self.render(0)
        self.assertEqual(self.store.frames.call_count, calls)
        self.render(60)
        self.assertEqual(self.store.frames.call_count, calls + 1)
        self.cache = FrameResponseCache(max_bytes=size - 1)
        self.render()
        self.assertEqual(self.cache.size, 0)
        self.assertFalse(self.cache.entries)

    def test_failed_batches_are_not_cached(self):
        self.store.frames.side_effect = ValueError("corrupt frame")
        with self.assertRaises(ValueError):
            self.render()
        self.assertFalse(self.cache.entries)
        self.store.frames.side_effect = None
        self.assertEqual(json.loads(self.render())["frames"][0]["frame_index"], 0)
