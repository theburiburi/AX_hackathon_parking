"""Bounded, immutable responses for repeated seeks and concurrent viewers."""
from collections import OrderedDict
from threading import Lock

from django.http import HttpResponse


class FrameResponseCache:
    def __init__(self, max_bytes=16 * 1024 * 1024, max_entries=32):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.entries = OrderedDict()
        self.size = 0
        self.lock = Lock()

    def render(self, store, start, count, renderer, media_type):
        # ReplayStore validation and authorization run before this lookup. File
        # replacement, edits and index changes must not reuse a previous result.
        stat = store.frames_path.stat()
        key = (str(store.frames_path), stat.st_dev, stat.st_ino, stat.st_size,
               stat.st_mtime_ns, stat.st_ctime_ns, tuple(store.offsets),
               store.manifest["cache_id"], start, count, type(renderer), media_type)
        with self.lock:
            cached = self.entries.get(key)
            if cached is not None:
                self.entries.move_to_end(key)
                return cached

        # Each miss uses its own native reader. Unrelated viewers need not wait
        # for another request to decode and render its batch.
        content = renderer.render({"cache_id": store.manifest["cache_id"],
                                   "frames": store.frames(start, count)}, media_type)
        if len(content) <= self.max_bytes and self.max_entries > 0:
            with self.lock:
                previous = self.entries.pop(key, None)
                if previous is not None:
                    self.size -= len(previous)
                while self.entries and (self.size + len(content) > self.max_bytes
                                        or len(self.entries) >= self.max_entries):
                    _, oldest = self.entries.popitem(last=False)
                    self.size -= len(oldest)
                self.entries[key] = content
                self.size += len(content)
        return content


_responses = FrameResponseCache()


def frame_response(store, start, count, request):
    content = _responses.render(store, start, count, request.accepted_renderer, request.accepted_media_type)
    return HttpResponse(content, content_type=request.accepted_renderer.media_type)
