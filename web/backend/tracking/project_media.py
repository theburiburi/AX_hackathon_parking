"""Present native scene metadata and map geometry; never edit project data."""
import json
import os
from pathlib import Path

from native_project import PROJECT


def selected_map(media_dir, first_media, suffixes):
    # Map display does not require split videos, detections metadata or a
    # configured video title. These belong to replay preparation, not this API.
    image = Path(os.environ.get("WEB_BEV_MAP", "data/maps/map.png"))
    if not image.is_absolute():
        image = PROJECT / image
    return image if image.is_file() else first_media(media_dir / "maps", suffixes)


def map_layout(image, fallback):
    """Use the mosaic project's actual map zones without rewriting demo data."""
    if image is None or image.resolve() != (PROJECT / "data/maps/map.png").resolve():
        return fallback
    path = PROJECT / "data/maps/zones.json"
    if not path.is_file():
        return fallback
    data = json.loads(path.read_text(encoding="utf-8"))
    width, height = data["map"]["width"], data["map"]["height"]
    colors = {zone["id"]: zone.get("color", "#2563eb") for zone in fallback.get("zones", [])}
    zones = []
    for zone in data["zones"]:
        b = zone["bndbox"]
        x1, x2 = b["xmin"] / width * 100, b["xmax"] / width * 100
        y1, y2 = b["ymin"] / height * 100, b["ymax"] / height * 100
        zones.append({"id": zone["id"], "name": f"{zone['id']} 구역", "capacity": zone.get("capacity"),
                      "color": colors.get(zone["id"], "#2563eb"), "polygon": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                      "label": [(x1 + x2) / 2, (y1 + y2) / 2]})
    return {"map_id": image.name, "draft": False, "source": "native", "zones": zones}
