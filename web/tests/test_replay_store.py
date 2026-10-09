import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from replay.store import ReplayError, ReplayStore, config_digest, file_digest, signature, title_value


class ReplayStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "demo"
        self.folder.mkdir()
        rows = [{"frame_index": n, "cameras": {"cam01": [{"global_id": 7}]} } for n in range(4)]
        offsets = []
        with (self.folder / "frames.jsonl").open("wb") as output:
            for row in rows:
                offsets.append(output.tell())
                output.write((json.dumps(row) + "\n").encode())
        (self.folder / "index.json").write_text(json.dumps(offsets))
        self.manifest = {"schema_version": 1, "title": "demo", "frames_file": "frames.jsonl", "index_file": "index.json", "frame_count": 4, "video_path": "video.mp4", "sources": [], "config_digest": config_digest(self.root)}
        self.save()

    def save(self):
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest))

    def store(self):
        return ReplayStore("demo", root=self.root, project=self.root)

    def test_random_seek_preserves_precomputed_id_and_is_independent(self):
        a, b = self.store(), self.store()
        self.assertEqual(a.frames(3, 1)[0]["frame_index"], 3)
        self.assertEqual(b.frames(0, 2)[0]["cameras"]["cam01"][0]["global_id"], 7)
        self.assertEqual(a.frames(0, 1), b.frames(0, 1))

    def test_range_is_bounded_and_end_is_clipped(self):
        self.assertEqual(len(self.store().frames(3, 120)), 1)
        for start, count in [(-1, 1), (4, 1), (0, 0), (0, 121)]:
            with self.subTest(start=start, count=count), self.assertRaises(ReplayError):
                self.store().frames(start, count)

    def test_traversal_and_missing_cache_fail_explicitly(self):
        for value in ["../demo", "/demo", "a/b", "", None]:
            with self.subTest(value=value), self.assertRaises(ReplayError):
                title_value(value)
        self.manifest["frames_file"] = "../../outside.jsonl"
        self.save()
        with self.assertRaises(ReplayError):
            self.store()

    def test_index_must_match_count_and_frame_number(self):
        self.manifest["frame_count"] = 6
        self.save()
        with self.assertRaises(ReplayError):
            self.store()
        self.manifest["frame_count"] = 4
        self.save()
        (self.folder / "frames.jsonl").write_text('{"frame_index":99}\n')
        with self.assertRaises(ReplayError):
            self.store().frames(0, 1)

    def test_changed_source_or_settings_require_regeneration(self):
        self.manifest["sources"] = [{"path": "video.mp4", "stat": {"size": 1, "mtime_ns": 0}}]
        (self.root / "video.mp4").write_bytes(b"changed")
        self.save()
        with self.assertRaises(ReplayError):
            self.store()

        self.manifest["sources"] = []
        self.save()
        (self.root / "config").mkdir()
        (self.root / "config/mosaic.yaml").write_text("changed")
        with self.assertRaises(ReplayError):
            self.store()

    def test_copied_source_with_different_timestamp_is_accepted_by_content(self):
        path = self.root / "video.mp4"
        path.write_bytes(b"same-content")
        stat = signature(path)
        self.manifest["sources"] = [{"path": "video.mp4", "stat": stat, "sha256": file_digest(str(path), **stat)}]
        self.save()
        os.utime(path, ns=(stat["mtime_ns"] + 10000000, stat["mtime_ns"] + 10000000))
        self.assertEqual(self.store().frames(0, 1)[0]["frame_index"], 0)


if __name__ == "__main__":
    unittest.main()
