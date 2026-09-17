import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml
import numpy as np
import cv2

from src.calibration.cli import (
    CalibrationSession,
    camera_context,
    compose_calibration_view,
    save_calibration,
    source_point_from_click,
    Viewport,
    handle_view_mouse,
)


class CalibrationSessionTests(unittest.TestCase):
    def test_zoom_preserves_cursor_anchor_and_limits_pan(self):
        view = Viewport()
        shape = (200, 400, 3)
        view.zoom_at((100, 80), 2, shape)
        self.assertEqual(view.source_point((100, 80)), (100, 80))
        view.pan(-10000, -10000, shape)
        self.assertEqual((view.tx, view.ty), (-400, -200))
        view.zoom_at((100, 80), 100, shape)
        self.assertEqual(view.zoom, 16)
        view.zoom_at((100, 80), 0.001, shape)
        self.assertEqual((view.zoom, view.tx, view.ty), (1, 0, 0))

    def test_zoom_render_matches_inverse_click_coordinates(self):
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        image[40, 80] = (20, 100, 240)
        view = Viewport(2, -40, -20)
        rendered = view.render(image)
        np.testing.assert_array_equal(rendered[60, 120], image[40, 80])
        self.assertEqual(view.source_point((120, 60)), (80, 40))

    def test_mouse_navigation_is_independent_and_does_not_select_points(self):
        session = CalibrationSession()
        views = {'image': Viewport(), 'bev': Viewport()}
        shapes = dict.fromkeys(views, (100, 200, 3))
        _, geometries = compose_calibration_view(
            np.zeros(shapes['image'], dtype=np.uint8),
            np.zeros(shapes['bev'], dtype=np.uint8), 400, 404,
        )
        drag = {}
        def event(kind, x, y, flags=0):
            handle_view_mouse(kind, x, y, flags, geometries, views, shapes, drag, session)
        event(cv2.EVENT_MOUSEWHEEL, 200, 100, 120 << 16)
        self.assertEqual(views['image'].zoom, 1.25)
        self.assertEqual(views['bev'].zoom, 1)
        event(cv2.EVENT_RBUTTONDOWN, 200, 100)
        event(cv2.EVENT_MOUSEMOVE, 220, 110, cv2.EVENT_FLAG_RBUTTON)
        event(cv2.EVENT_RBUTTONUP, 220, 110)
        self.assertFalse(drag)
        self.assertEqual(session.image_points, [])
        event(cv2.EVENT_LBUTTONDOWN, 220, 110)
        np.testing.assert_allclose(session.image_points[0], (100, 50))
        event(cv2.EVENT_LBUTTONDOWN, 220, 110)  # wrong panel
        self.assertEqual(len(session.image_points), 1)
        event(cv2.EVENT_LBUTTONDOWN, 200, 304)
        np.testing.assert_allclose(session.bev_points[0], (100, 50))
        for point in ((20, 20), (180, 20), (180, 80)):
            session.add_image_point(point)
            session.add_bev_point(point)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calibration.yaml'
            save_calibration(path, {}, session, 5.0)
            saved = yaml.safe_load(path.read_text(encoding='utf-8'))
        np.testing.assert_allclose(saved['calibration']['image_points'][0], (100, 50))
        np.testing.assert_allclose(saved['calibration']['bev_points'][0], (100, 50))
        event(cv2.EVENT_MOUSEWHEEL, 200, 100, (-120) << 16)
        self.assertEqual(views['image'].zoom, 1)

    def test_alternates_image_and_bev_points(self):
        session = CalibrationSession()
        session.add_bev_point((50, 60))
        self.assertEqual(session.bev_points, [])

        session.add_image_point((10, 20))
        session.add_image_point((30, 40))
        self.assertEqual(session.image_points, [[10.0, 20.0]])
        session.add_bev_point((50, 60))
        self.assertEqual(session.pair_count, 1)
        self.assertEqual(session.expecting, "image")

    def test_calculates_errors_and_saves_yaml(self):
        session = CalibrationSession(
            image_points=[[0, 0], [10, 0], [10, 10], [0, 10]],
            bev_points=[[100, 50], [200, 50], [200, 250], [100, 250]],
        )
        config = {"calibration": {"is_sample": True}, "detection": {"model": "test.pt"}}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            save_calibration(path, config, session, 5.0)
            saved = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertFalse(saved["calibration"]["is_sample"])
        self.assertEqual(len(saved["calibration"]["image_points"]), 4)
        self.assertEqual(saved["detection"]["model"], "test.pt")
        self.assertLess(float(session.errors.max()), 0.001)

    def test_undo_removes_incomplete_or_complete_pair(self):
        session = CalibrationSession()
        session.add_image_point((1, 2))
        session.undo()
        self.assertEqual(session.pair_count, 0)
        session.add_image_point((1, 2))
        session.add_bev_point((3, 4))
        session.undo()
        self.assertEqual(session.pair_count, 0)

    def test_combined_view_click_maps_back_to_source_pixel(self):
        cctv = np.zeros((100, 200, 3), dtype=np.uint8)
        bev = np.zeros((200, 100, 3), dtype=np.uint8)
        combined, geometries = compose_calibration_view(cctv, bev, 400, 500)
        self.assertEqual(combined.shape, (500, 400, 3))

        scale, x, y, _width, _height = geometries["bev"]
        click = (round(x + 25 * scale), round(y + 50 * scale))
        mapped = source_point_from_click(*click, geometries["bev"])
        self.assertAlmostEqual(mapped[0], 25, delta=0.6)
        self.assertAlmostEqual(mapped[1], 50, delta=0.6)

    def test_camera_context_selects_only_requested_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "cameras.yaml"
            path.write_text(
                """bev_map: map.png
cameras:
  - {id: cam01, video: one.mp4, calibration: {is_sample: true}}
  - {id: cam02, video: two.mp4, calibration: {is_sample: true}}
""",
                encoding="utf-8",
            )
            args = SimpleNamespace(
                camera="cam02", cameras_config=path, video=None, map_path=None, config=None
            )
            _video, _map, _save_path, config, calibration = camera_context(args)
            calibration["marker"] = "selected"

        self.assertNotIn("marker", config["cameras"][0]["calibration"])
        self.assertEqual(config["cameras"][1]["calibration"]["marker"], "selected")


if __name__ == "__main__":
    unittest.main()
