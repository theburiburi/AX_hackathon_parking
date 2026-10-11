"""Validate or import a plate-free zone parking inventory."""
import argparse
import json
from pathlib import Path
import sys

WEB = Path(__file__).resolve().parent
sys.path.insert(0, str(WEB / "backend"))
from tracking.parking_state import initial_zone_counts, zone_occupancy


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=WEB / "backend/data/initial_parking.json")
    parser.add_argument("--check", action="store_true", help="Validate and preview counts without saving.")
    args = parser.parse_args(argv)
    target = WEB / "backend/data/initial_parking.json"
    try:
        document = json.loads(args.input.read_text(encoding="utf-8-sig"))
        zones = json.loads((WEB.parent / "data/maps/zones.json").read_text(encoding="utf-8-sig"))["zones"]
        result = initial_zone_counts(document, zones)
        if not args.check and args.input.resolve() != target.resolve():
            temporary = target.with_suffix(".initial.tmp")
            temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(target)
        print("Validated (no changes saved)." if args.check else "Zone parking data ready. The web reads initial_parking.json directly.")
        for zone_id, counts in zone_occupancy(result, zones).items():
            print(f"{zone_id}: {counts['parked_count']} / {counts['capacity']}, overflow={counts['overflow_count']}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
