"""JSON persistence boundary. Replace with database repositories later."""
import json
import threading
from collections import OrderedDict
from pathlib import Path
from django.conf import settings

DATA_DIR = Path(settings.BASE_DIR) / "data"
_lock = threading.Lock()
_read_cache = OrderedDict()
_CACHE_ENTRIES = 32
_CACHE_CHARACTERS_PER_FILE = 64 * 1024


def _signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def read(collection):
    with _lock:
        target = DATA_DIR / f"{collection}.json"
        signature = _signature(target)
        cached = _read_cache.get(target)
        if cached is not None and cached[0] == signature:
            _read_cache.move_to_end(target)
            # Parse a fresh object so callers can edit their result safely.
            return json.loads(cached[1])

        _read_cache.pop(target, None)
        text = target.read_text(encoding="utf-8")
        records = json.loads(text)
        if len(text) <= _CACHE_CHARACTERS_PER_FILE:
            try:
                unchanged = signature == _signature(target)
            except OSError:
                unchanged = False
            # An editor may have replaced the file while it was being read.
            if unchanged:
                _read_cache[target] = (signature, text)
                if len(_read_cache) > _CACHE_ENTRIES:
                    _read_cache.popitem(last=False)
        return records


def write(collection, records):
    with _lock:
        target = DATA_DIR / f"{collection}.json"
        _read_cache.pop(target, None)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
