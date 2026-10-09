"""JSON persistence boundary. Replace with database repositories later."""
import json
import threading
from pathlib import Path
from django.conf import settings
DATA_DIR = Path(settings.BASE_DIR) / "data"
_lock = threading.Lock()
def read(collection):
    with _lock:
        with (DATA_DIR / f"{collection}.json").open(encoding="utf-8") as file:
            return json.load(file)
def write(collection, records):
    with _lock:
        target = DATA_DIR / f"{collection}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)