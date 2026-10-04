from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]

MAP_PATH = ROOT / "data" / "maps" / "map.png"
ZONES_PATH = ROOT / "data" / "parking" / "zones.json"
OUTPUT_PATH = ROOT / "outputs" / "parking_zone_preview.png"

ZONE_COLORS: Dict[str, Tuple[int, int, int]] = {
    "A": (235, 72, 72),
    "B": (245, 132, 38),
    "C": (220, 190, 35),
    "D": (80, 210, 70),
    "E": (67, 191, 232),
    "F": (53, 106, 245),
    "G": (138, 72, 245),
    "H": (225, 75, 190),
    "I": (210, 95, 170),
    "J": (40, 198, 190),
    "K": (120, 215, 70),
    "L": (214, 173, 54),
    "M": (155, 110, 245),
    "N": (235, 92, 92),
}

LINE_WIDTH = 4

LABEL_PADDING_X = 10
LABEL_PADDING_Y = 6

LEGEND_BOX_WIDTH = 255
LEGEND_ITEM_HEIGHT = 28
LEGEND_MARGIN = 18
LEGEND_PADDING = 14


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def ensure_output_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def get_font(size: int):
    candidates = [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    for font_path in candidates:
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception:
            continue

    return ImageFont.load_default()


def draw_zone_bbox(
    base: Image.Image,
    bbox: Dict[str, int],
    color: Tuple[int, int, int],
    label: str,
    font_label,
) -> None:
    x1 = bbox["xmin"]
    y1 = bbox["ymin"]
    x2 = bbox["xmax"]
    y2 = bbox["ymax"]

    overlay = Image.new(
        "RGBA",
        base.size,
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(overlay)

    outline = (*color, 255)

    # 구역 내부는 채우지 않고 테두리만 표시
    draw.rectangle(
        [x1, y1, x2, y2],
        outline=outline,
        width=LINE_WIDTH,
    )

    # 라벨 크기 계산
    label_bbox = draw.textbbox(
        (0, 0),
        label,
        font=font_label,
    )

    text_width = label_bbox[2] - label_bbox[0]
    text_height = label_bbox[3] - label_bbox[1]

    box_x1 = x1 + 6
    box_y1 = y1 + 6

    box_x2 = (
        box_x1
        + text_width
        + LABEL_PADDING_X * 2
    )

    box_y2 = (
        box_y1
        + text_height
        + LABEL_PADDING_Y * 2
    )

    # 라벨 배경만 색상 유지
    draw.rounded_rectangle(
        [
            box_x1,
            box_y1,
            box_x2,
            box_y2,
        ],
        radius=8,
        fill=outline,
    )

    draw.text(
        (
            box_x1 + LABEL_PADDING_X,
            box_y1 + LABEL_PADDING_Y - 2,
        ),
        label,
        font=font_label,
        fill=(255, 255, 255, 255),
    )

    base.alpha_composite(overlay)


def draw_legend(
    base: Image.Image,
    zones: List[dict],
    font_title,
    font_item,
) -> None:
    overlay = Image.new(
        "RGBA",
        base.size,
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(overlay)

    rows = (len(zones) + 1) // 2

    legend_height = (
        LEGEND_PADDING * 2
        + 42
        + rows * LEGEND_ITEM_HEIGHT
    )

    x2 = base.width - LEGEND_MARGIN
    y1 = LEGEND_MARGIN

    x1 = x2 - LEGEND_BOX_WIDTH
    y2 = y1 + legend_height

    draw.rounded_rectangle(
        [x1, y1, x2, y2],
        radius=14,
        fill=(255, 255, 255, 235),
        outline=(35, 35, 35, 255),
        width=3,
    )

    draw.text(
        (
            x1 + 16,
            y1 + 12,
        ),
        "Parking Zone Legend",
        font=font_title,
        fill=(20, 20, 20, 255),
    )

    left_col_x = x1 + 18
    right_col_x = x1 + 132
    start_y = y1 + 50

    split_index = (len(zones) + 1) // 2

    left_items = zones[:split_index]
    right_items = zones[split_index:]

    def render_column(
        items: List[dict],
        column_x: int,
    ) -> None:
        for index, zone in enumerate(items):
            y = start_y + index * LEGEND_ITEM_HEIGHT

            color = ZONE_COLORS.get(
                zone["id"],
                (180, 180, 180),
            )

            draw.rounded_rectangle(
                [
                    column_x,
                    y + 2,
                    column_x + 20,
                    y + 22,
                ],
                radius=4,
                fill=(*color, 255),
                outline=(120, 120, 120, 255),
                width=1,
            )

            text = (
                f'{zone["id"]}    '
                f'{zone["capacity"]}'
            )

            draw.text(
                (
                    column_x + 30,
                    y,
                ),
                text,
                font=font_item,
                fill=(20, 20, 20, 255),
            )

    render_column(
        left_items,
        left_col_x,
    )

    render_column(
        right_items,
        right_col_x,
    )

    base.alpha_composite(overlay)


def main() -> None:
    zones_data = load_json(
        ZONES_PATH
    )

    zones = zones_data["zones"]

    image = Image.open(
        MAP_PATH
    ).convert("RGBA")

    font_label = get_font(28)
    font_title = get_font(20)
    font_item = get_font(18)

    for zone in zones:
        zone_id = zone["id"]
        bbox = zone["bndbox"]

        color = ZONE_COLORS.get(
            zone_id,
            (180, 180, 180),
        )

        draw_zone_bbox(
            image,
            bbox,
            color,
            zone_id,
            font_label,
        )

    draw_legend(
        image,
        zones,
        font_title,
        font_item,
    )

    ensure_output_dir(
        OUTPUT_PATH
    )

    image.convert("RGB").save(
        OUTPUT_PATH,
        quality=95,
    )

    print(
        f"Saved: {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()