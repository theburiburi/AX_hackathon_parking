"""Initialize independent web runtime data; never overwrite existing collections."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def initialize():
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    for source in (ROOT / "fixtures").glob("*.json"):
        target = data / source.name
        if not target.exists():
            target.write_bytes(source.read_bytes())
    for name in ("tracking_logs", "vehicle_schedules"):
        target = data / f"{name}.json"
        if not target.exists():
            target.write_text("[]", encoding="utf-8")


if __name__ == "__main__":
    initialize()
    print("Runtime data ready. Existing data is preserved.")
