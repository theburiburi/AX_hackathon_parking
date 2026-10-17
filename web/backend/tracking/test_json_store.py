import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from . import json_store


class JsonStoreTests(SimpleTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = patch.object(json_store, "DATA_DIR", Path(temporary.name))
        directory.start()
        self.addCleanup(directory.stop)
        self.addCleanup(json_store._read_cache.clear)
        self.path = json_store.DATA_DIR / "sample.json"

    def test_repeated_reads_are_independent_and_avoid_reopening_unchanged_file(self):
        json_store.write("sample", [{"nested": {"values": [1, 2]}}])
        first = json_store.read("sample")
        first[0]["nested"]["values"].append(3)
        with patch.object(Path, "open", side_effect=AssertionError("Unchanged file reopened")):
            self.assertEqual(json_store.read("sample"), [{"nested": {"values": [1, 2]}}])

    def test_manual_same_size_edit_and_atomic_replacement_are_visible(self):
        self.path.write_text('{"value": 1}', encoding="utf-8")
        self.assertEqual(json_store.read("sample"), {"value": 1})
        original = self.path.stat()
        self.path.write_text('{"value": 2}', encoding="utf-8")
        os.utime(self.path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000_000))
        self.assertEqual(json_store.read("sample"), {"value": 2})

        original = self.path.stat()
        replacement = self.path.with_suffix(".replacement")
        replacement.write_text('{"value": 3}', encoding="utf-8")
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        replacement.replace(self.path)
        self.assertEqual(json_store.read("sample"), {"value": 3})

    def test_deleted_and_invalid_files_raise_instead_of_returning_cached_data(self):
        json_store.write("sample", [1])
        self.assertEqual(json_store.read("sample"), [1])
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            json_store.read("sample")
        self.path.write_text("invalid", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            json_store.read("sample")
        self.path.write_text("[2]", encoding="utf-8")
        self.assertEqual(json_store.read("sample"), [2])

    def test_writes_round_trip_and_failed_replace_keeps_previous_document(self):
        json_store.write("sample", {"values": (1, 2)})
        self.assertEqual(json_store.read("sample"), {"values": [1, 2]})
        json_store.write("sample", {"values": [3]})
        self.assertEqual(json_store.read("sample"), {"values": [3]})
        with patch.object(Path, "replace", side_effect=OSError("Replace failed")):
            with self.assertRaises(OSError):
                json_store.write("sample", {"values": [4]})
        self.assertEqual(json_store.read("sample"), {"values": [3]})

    def test_concurrent_reads_and_writes_only_return_complete_documents(self):
        json_store.write("sample", {"version": 0, "values": [0] * 20})

        def write_versions():
            for version in range(1, 21):
                json_store.write("sample", {"version": version, "values": [version] * 20})

        def read_versions():
            for _ in range(40):
                record = json_store.read("sample")
                self.assertEqual(record["values"], [record["version"]] * 20)

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(write_versions), executor.submit(read_versions), executor.submit(read_versions)]
            for future in futures:
                future.result()
        self.assertEqual(json_store.read("sample")["version"], 20)
