"""Interactive point-pair calibration for CCTV-to-BEV homography."""

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import sys

import cv2
import numpy as np
import yaml

from .homography import compute_homography


@dataclass
class Viewport:
    """Transform only the display; calibration points stay in source pixels."""

    zoom: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    def source_point(self, point):
        return ((point[0] - self.tx) / self.zoom,
                (point[1] - self.ty) / self.zoom)

    def clamp(self, shape):
        height, width = shape[:2]
        self.tx = min(0.0, max(width * (1 - self.zoom), self.tx))
        self.ty = min(0.0, max(height * (1 - self.zoom), self.ty))

    def zoom_at(self, point, factor, shape):
        source = self.source_point(point)
        self.zoom = min(16.0, max(1.0, self.zoom * factor))
        self.tx = point[0] - source[0] * self.zoom
        self.ty = point[1] - source[1] * self.zoom
        self.clamp(shape)

    def pan(self, dx, dy, shape):
        self.tx += dx
        self.ty += dy
        self.clamp(shape)

    def render(self, image):
        matrix = np.array([[self.zoom, 0, self.tx], [0, self.zoom, self.ty]], dtype=float)
        return cv2.warpAffine(image, matrix, (image.shape[1], image.shape[0]))


def handle_view_mouse(event, x, y, flags, geometries, viewports, shapes, drag, session):
    """Handle navigation separately from point selection for both panels."""
    if event == cv2.EVENT_RBUTTONUP:
        drag.clear()
        return
    if event == cv2.EVENT_MOUSEMOVE and drag:
        if not flags & cv2.EVENT_FLAG_RBUTTON:
            drag.clear()
            return
        name = drag['name']
        scale = geometries[name][0]
        viewports[name].pan((x - drag['x']) / scale, (y - drag['y']) / scale, shapes[name])
        drag.update(x=x, y=y)
        return
    for name, geometry in geometries.items():
        point = source_point_from_click(x, y, geometry)
        if point is None:
            continue
        if event == cv2.EVENT_MOUSEWHEEL:
            # OpenCV stores the signed wheel delta in the upper 16 bits.
            delta = (flags >> 16) & 0xffff
            if delta >= 0x8000:
                delta -= 0x10000
            if delta:
                viewports[name].zoom_at(point, 1.25 if delta > 0 else 0.8, shapes[name])
        elif event == cv2.EVENT_RBUTTONDOWN:
            drag.update(name=name, x=x, y=y)
        elif event == cv2.EVENT_LBUTTONDOWN:
            if name != session.expecting:
                session.message = f"Select a point in the {session.expecting.upper()} view first."
                return
            source = viewports[name].source_point(point)
            if name == 'image':
                session.add_image_point(source)
            else:
                session.add_bev_point(source)
        return


@dataclass
class CalibrationSession:
    image_points: list[list[float]] = field(default_factory=list)
    bev_points: list[list[float]] = field(default_factory=list)
    matrix: np.ndarray | None = None
    inliers: np.ndarray | None = None
    errors: np.ndarray | None = None
    message: str = "Click a ground point in the CCTV view."

    @property
    def expecting(self) -> str:
        return "bev" if len(self.image_points) > len(self.bev_points) else "image"

    @property
    def pair_count(self) -> int:
        return min(len(self.image_points), len(self.bev_points))

    def add_image_point(self, point: tuple[float, float]) -> None:
        if self.expecting != "image":
            self.message = "Select the matching point in the BEV view first."
            return
        self.image_points.append([float(point[0]), float(point[1])])
        self.invalidate()
        self.message = "Now click the SAME physical point in the BEV view."

    def add_bev_point(self, point: tuple[float, float]) -> None:
        if self.expecting != "bev":
            self.message = "Select a point in the CCTV view first."
            return
        self.bev_points.append([float(point[0]), float(point[1])])
        self.invalidate()
        self.message = f"Pair {self.pair_count} added. Click the next CCTV point."

    def invalidate(self) -> None:
        self.matrix = None
        self.inliers = None
        self.errors = None

    def undo(self) -> None:
        if len(self.image_points) > len(self.bev_points):
            self.image_points.pop()
        elif self.bev_points:
            self.bev_points.pop()
            self.image_points.pop()
        self.invalidate()
        self.message = f"Last selection removed. {self.pair_count} complete pairs."

    def clear(self) -> None:
        self.image_points.clear()
        self.bev_points.clear()
        self.invalidate()
        self.message = "All points cleared. Click a CCTV ground point."

    def calculate(self, threshold: float) -> None:
        if len(self.image_points) != len(self.bev_points):
            raise ValueError("finish the current CCTV/BEV point pair first")
        self.matrix, self.inliers = compute_homography(
            self.image_points, self.bev_points, threshold
        )
        source = np.asarray([self.image_points], dtype=np.float32)
        projected = cv2.perspectiveTransform(source, self.matrix)[0]
        targets = np.asarray(self.bev_points, dtype=np.float32)
        self.errors = np.linalg.norm(projected - targets, axis=1)
        mean_error = float(self.errors.mean())
        max_error = float(self.errors.max())
        self.message = (
            f"Preview: mean error {mean_error:.1f}px, max {max_error:.1f}px. "
            "Press S to save."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Click matching CCTV and BEV points and save calibration to YAML."
    )
    parser.add_argument("--video", type=Path, help="input video (legacy single-camera mode)")
    parser.add_argument("--map", dest="map_path", type=Path, help="BEV map (legacy mode)")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"), help="YAML config to update")
    parser.add_argument("--cameras-config", type=Path, default=Path("cameras.yaml"))
    parser.add_argument("--camera", help="camera ID from --cameras-config")
    parser.add_argument("--frame", type=int, default=0, help="initial zero-based video frame")
    parser.add_argument("--scale", type=float, default=1.0, help="display scale for both windows")
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed multiplier")
    return parser.parse_args()


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError("config must contain a YAML mapping")
    return data


def save_calibration(
    path: Path,
    config: dict,
    session: CalibrationSession,
    threshold: float,
) -> None:
    if session.matrix is None:
        session.calculate(threshold)
    calibration = config.setdefault("calibration", {})
    update_calibration(calibration, session, threshold)
    write_yaml(path, config)


def update_calibration(
    calibration: dict,
    session: CalibrationSession,
    threshold: float,
) -> None:
    if session.matrix is None:
        session.calculate(threshold)
    calibration["is_sample"] = False
    calibration["ransac_reproj_threshold"] = float(threshold)
    calibration["image_points"] = [list(point) for point in session.image_points]
    calibration["bev_points"] = [list(point) for point in session.bev_points]
def write_yaml(path: Path, config: dict) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        yaml.safe_dump(config, file, sort_keys=False, allow_unicode=True)


def camera_context(args: argparse.Namespace) -> tuple[Path, Path, Path, dict, dict]:
    """Resolve video/map/config/calibration for legacy or camera-registry mode."""
    if args.camera:
        config_path = args.cameras_config
        config = load_yaml(config_path)
        cameras = config.get("cameras")
        if not isinstance(cameras, list):
            raise ValueError("cameras config must contain a cameras list")
        camera = next(
            (item for item in cameras if isinstance(item, dict) and item.get("id") == args.camera),
            None,
        )
        if camera is None:
            choices = ", ".join(str(item.get("id")) for item in cameras if isinstance(item, dict))
            raise ValueError(f"unknown camera '{args.camera}'; available: {choices}")
        calibration = camera.setdefault("calibration", {})
        base = config_path.resolve().parent
        video = Path(camera["video"])
        bev_map = Path(config["bev_map"])
        video = video if video.is_absolute() else base / video
        bev_map = bev_map if bev_map.is_absolute() else base / bev_map
        return video, bev_map, config_path, config, calibration

    if args.video is None or args.map_path is None:
        raise ValueError("use --camera, or provide both --video and --map")
    config = load_yaml(args.config)
    return args.video, args.map_path, args.config, config, config.get("calibration", {})


def _color(index: int) -> tuple[int, int, int]:
    return (64 + index * 53 % 192, 64 + index * 97 % 192, 64 + index * 31 % 192)


def _draw_header(image: np.ndarray, lines: list[str]) -> None:
    height = 30 * len(lines) + 10
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (image.shape[1], height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.65, image, 0.35, 0, image)
    for index, line in enumerate(lines):
        cv2.putText(
            image,
            line,
            (12, 27 + index * 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )


def draw_image_view(frame: np.ndarray, session: CalibrationSession, frame_number: int, show_header: bool = True) -> np.ndarray:
    output = frame.copy()
    for index, point in enumerate(session.image_points):
        pixel = tuple(np.rint(point).astype(int))
        cv2.circle(output, pixel, 7, _color(index), -1, cv2.LINE_AA)
        cv2.putText(output, str(index + 1), (pixel[0] + 9, pixel[1] - 7),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, _color(index), 2, cv2.LINE_AA)
    if show_header:
        _draw_header(output, [f"CCTV frame {frame_number} | pairs: {session.pair_count}", session.message])
    return output


def draw_bev_view(bev_map: np.ndarray, session: CalibrationSession, show_header: bool = True) -> np.ndarray:
    output = bev_map.copy()
    for index, target in enumerate(session.bev_points):
        target_pixel = tuple(np.rint(target).astype(int))
        color = _color(index)
        cv2.drawMarker(output, target_pixel, color, cv2.MARKER_CROSS, 18, 2, cv2.LINE_AA)
        cv2.putText(output, str(index + 1), (target_pixel[0] + 10, target_pixel[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)

    if session.matrix is not None and session.image_points:
        source = np.asarray([session.image_points], dtype=np.float32)
        projected = cv2.perspectiveTransform(source, session.matrix)[0]
        for index, (target, estimate) in enumerate(zip(session.bev_points, projected)):
            target_pixel = tuple(np.rint(target).astype(int))
            estimate_pixel = tuple(np.rint(estimate).astype(int))
            inlier = bool(session.inliers[index]) if session.inliers is not None else True
            status_color = (0, 255, 0) if inlier else (0, 0, 255)
            cv2.line(output, target_pixel, estimate_pixel, status_color, 2, cv2.LINE_AA)
            cv2.circle(output, estimate_pixel, 6, status_color, 2, cv2.LINE_AA)
            if session.errors is not None:
                cv2.putText(
                    output, f"{session.errors[index]:.1f}px",
                    (target_pixel[0] + 10, target_pixel[1] + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, status_color, 1, cv2.LINE_AA,
                )
    if show_header:
        _draw_header(output, ["BEV: cross=clicked, circle=projected", "ENTER preview | S save | Backspace undo | C clear | Q quit"])
    return output


def _fit_geometry(
    image: np.ndarray, cell_x: int, cell_y: int, cell_width: int, cell_height: int
) -> tuple[float, int, int, int, int]:
    image_height, image_width = image.shape[:2]
    scale = min(cell_width / image_width, cell_height / image_height)
    width = max(1, int(round(image_width * scale)))
    height = max(1, int(round(image_height * scale)))
    x = cell_x + (cell_width - width) // 2
    y = cell_y + (cell_height - height) // 2
    return scale, x, y, width, height


def _place_in_cell(
    canvas: np.ndarray,
    image: np.ndarray,
    cell_x: int,
    cell_y: int,
    cell_width: int,
    cell_height: int,
) -> tuple[float, int, int, int, int]:
    geometry = _fit_geometry(image, cell_x, cell_y, cell_width, cell_height)
    _scale, x, y, width, height = geometry
    interpolation = cv2.INTER_AREA if width < image.shape[1] else cv2.INTER_LINEAR
    canvas[y : y + height, x : x + width] = cv2.resize(
        image, (width, height), interpolation=interpolation
    )
    return geometry


def compose_calibration_view(
    cctv_view: np.ndarray,
    bev_view: np.ndarray,
    width: int,
    height: int,
) -> tuple[np.ndarray, dict[str, tuple[float, int, int, int, int]]]:
    """Compose vertical views and return geometry used for click conversion."""
    gap = 4
    top_height = (height - gap) // 2
    bottom_y = top_height + gap
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    geometries = {
        "image": _place_in_cell(canvas, cctv_view, 0, 0, width, top_height),
        "bev": _place_in_cell(canvas, bev_view, 0, bottom_y, width, height - bottom_y),
    }
    return canvas, geometries


def source_point_from_click(
    x: int,
    y: int,
    geometry: tuple[float, int, int, int, int],
) -> tuple[float, float] | None:
    """Convert a composed-window click to an original image pixel coordinate."""
    scale, offset_x, offset_y, width, height = geometry
    if not (offset_x <= x < offset_x + width and offset_y <= y < offset_y + height):
        return None
    return (x - offset_x) / scale, (y - offset_y) / scale


def read_image(path: Path) -> np.ndarray:
    """Read an image through bytes so Windows Unicode paths work reliably."""
    image_bytes = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"failed to decode image: {path}")
    return image


def run(args: argparse.Namespace) -> None:
    if args.scale <= 0:
        raise ValueError("--scale must be greater than zero")
    if args.speed <= 0:
        raise ValueError("--speed must be greater than zero")
    if args.frame < 0:
        raise ValueError("--frame cannot be negative")
    video_path, map_path, save_path, config, calibration = camera_context(args)
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not map_path.is_file():
        raise FileNotFoundError(f"BEV map not found: {map_path}")
    threshold = float(calibration.get("ransac_reproj_threshold", 5.0))
    bev_map = read_image(map_path)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"failed to open video: {video_path}")
    capture.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
    ok, frame = capture.read()
    if not ok:
        capture.release()
        raise ValueError(f"could not read frame {args.frame} from video")

    session = CalibrationSession()
    if not calibration.get("is_sample", True):
        existing_image = calibration.get("image_points", [])
        existing_bev = calibration.get("bev_points", [])
        if existing_image and len(existing_image) == len(existing_bev):
            session.image_points = [[float(x), float(y)] for x, y in existing_image]
            session.bev_points = [[float(x), float(y)] for x, y in existing_bev]
            try:
                session.calculate(threshold)
                session.message = (
                    f"Loaded {session.pair_count} saved pairs. "
                    "Undo/clear to edit, or add another pair."
                )
            except ValueError as error:
                session.invalidate()
                session.message = f"Existing calibration is invalid: {error}"
    playing = False
    frame_number = int(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
    fps = capture.get(cv2.CAP_PROP_FPS)
    delay = max(1, round(1000 / (fps * args.speed))) if fps > 0 else 33
    window = "CCTV to BEV Calibration - top: CCTV / bottom: BEV"
    window_width = max(320, int(round(1100 * args.scale)))
    window_height = max(240, int(round(900 * args.scale)))
    geometries: dict[str, tuple[float, int, int, int, int]] = {}
    viewports = {name: Viewport() for name in ('image', 'bev')}
    shapes = {'image': frame.shape, 'bev': bev_map.shape}
    drag = {}
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)

    def on_click(event, x, y, _flags, _parameter):
        handle_view_mouse(event, x, y, _flags, geometries, viewports, shapes, drag, session)

    cv2.setMouseCallback(window, on_click)

    try:
        while True:
            cctv_view = viewports['image'].render(draw_image_view(frame, session, frame_number, False))
            bev_view = viewports['bev'].render(draw_bev_view(bev_map, session, False))
            _draw_header(cctv_view, [f"CCTV frame {frame_number} | zoom {viewports['image'].zoom:.1f}x", session.message])
            _draw_header(bev_view, [f"BEV | zoom {viewports['bev'].zoom:.1f}x | Wheel zoom | Right drag pan | R reset",
                                    "ENTER preview | S save | Backspace undo | C clear | Q quit"])
            combined, current_geometries = compose_calibration_view(
                cctv_view, bev_view, window_width, window_height
            )
            geometries.clear()
            geometries.update(current_geometries)
            cv2.imshow(window, combined)

            key = cv2.waitKey(delay if playing else 30) & 0xFF
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key in (27, ord("q")):
                break
            if key == ord(" "):
                playing = not playing
                session.message = "Video playing." if playing else "Video paused. Select a CCTV point."
            elif key == ord("n"):
                playing = False
                ok, next_frame = capture.read()
                if ok:
                    frame = next_frame
                    frame_number = int(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            elif key == ord("p"):
                playing = False
                target = max(0, frame_number - 1)
                capture.set(cv2.CAP_PROP_POS_FRAMES, target)
                ok, previous_frame = capture.read()
                if ok:
                    frame = previous_frame
                    frame_number = target
            elif key in (8, 127):
                session.undo()
            elif key == ord("c"):
                session.clear()
            elif key == ord("r"):
                viewports.update({name: Viewport() for name in viewports})
                drag.clear()
            elif key in (10, 13):
                try:
                    session.calculate(threshold)
                except ValueError as error:
                    session.message = f"Cannot preview: {error}"
            elif key == ord("s"):
                try:
                    update_calibration(calibration, session, threshold)
                    write_yaml(save_path, config)
                    session.message = f"Saved {session.pair_count} pairs to {save_path}"
                    print(session.message)
                except ValueError as error:
                    session.message = f"Cannot save: {error}"

            if playing:
                ok = True
                for _ in range(max(1, round(args.speed))):
                    ok, next_frame = capture.read()
                    if not ok:
                        break
                if ok:
                    frame = next_frame
                    frame_number = int(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                else:
                    playing = False
                    session.message = "End of video. Video paused."
    finally:
        capture.release()
        cv2.destroyAllWindows()


def main() -> int:
    try:
        run(parse_args())
    except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
