import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src import main
from src.tracking import DetectedVehicle


class DetectionToggleTests(unittest.TestCase):
    def test_entry_region_filters_by_vehicle_ground_point(self):
        inside = DetectedVehicle(2, 0.9, (40, 40, 60, 90))
        outside = DetectedVehicle(2, 0.9, (140, 40, 160, 90))
        self.assertEqual(
            main.filter_entry_detections([inside, outside], (0, 0, 100, 100)),
            [inside],
        )

    def test_entry_region_parser_rejects_invalid_rectangle(self):
        with self.assertRaises(ValueError):
            main.parse_entry_region([0, 0, 0, 100])

    def test_default_window_is_half_width_and_height(self):
        with patch('sys.argv', ['main']):
            args = main.parse_args()
        self.assertEqual((args.width, args.height), (700, 500))

    def test_playback_runs_with_and_without_yolo(self):
        for settings, flag, expected in [({}, False, True), ({'enabled': False}, False, False),
                                          ({'enabled': True}, True, False)]:
            with self.subTest(settings=settings, flag=flag), ExitStack() as stack:
                camera = SimpleNamespace(camera_id='cam01', fps=30, video=Path('video.mp4'), offset_seconds=0,
                                         calibration={'is_sample': False, 'image_points': [[0,0],[100,0],[100,100],[0,100]],
                                                      'bev_points': [[10,10],[110,10],[110,110],[10,110]]})
                registry = SimpleNamespace(cameras=[camera], bev_map=Path('map.png'))
                stack.enter_context(patch.object(main, 'load_camera_registry', return_value=registry))
                stack.enter_context(patch.object(main, 'load_runtime_config', return_value={'detection': settings}))
                detector = stack.enter_context(patch.object(main, 'BatchVehicleDetector'))
                detector.return_value.detect.return_value = [[DetectedVehicle(2, 0.9, (20, 10, 40, 50))]]
                bev_draw = stack.enter_context(patch.object(main, 'draw_bev_positions', wraps=main.draw_bev_positions))
                reader = stack.enter_context(patch.object(main, 'SynchronizedVideoReader')).return_value.__enter__.return_value
                reader.infos = [SimpleNamespace(fps=30)]
                reader.start_ms, reader.end_ms = 0, 1000
                reader.read_at.return_value = [np.zeros((90, 160, 3), dtype=np.uint8)]
                map_read = stack.enter_context(patch.object(main.cv2, 'imread', return_value=np.zeros((100, 100, 3), dtype=np.uint8)))
                display = stack.enter_context(patch.object(main.cv2, 'imshow'))
                named = stack.enter_context(patch.object(main.cv2, 'namedWindow'))
                resize = stack.enter_context(patch.object(main.cv2, 'resizeWindow'))
                stack.enter_context(patch.object(main.cv2, 'getWindowProperty', return_value=1))
                stack.enter_context(patch.object(main.cv2, 'getWindowImageRect',
                                                side_effect=[(0, 0, 700, 500), (0, 0, 1000, 600), (0, 0, 0, 0)]))
                stack.enter_context(patch.object(main.cv2, 'waitKey', side_effect=[-1, -1, ord('q')]))
                stack.enter_context(patch.object(main.cv2, 'destroyAllWindows'))
                main.run(SimpleNamespace(width=640, height=480, cameras_config=Path('cameras.yaml'),
                                         config=Path('config.yaml'), no_yolo=flag))
                self.assertEqual(detector.called, expected)
                self.assertEqual(detector.return_value.detect.called, expected)
                points = bev_draw.call_args.args[1]
                if expected:
                    self.assertEqual(points[0][:2], ('cam01', 1))
                    np.testing.assert_allclose(points[0][2], (40, 60))
                else:
                    self.assertEqual(points, [])
                map_read.assert_called_once()
                self.assertEqual(reader.read_at.call_count, 3)
                self.assertEqual([call.args[1].shape for call in display.call_args_list],
                                 [(500, 700, 3), (600, 1000, 3), (600, 1000, 3)])
                named.assert_called_once()
                resize.assert_called_once_with(named.call_args.args[0], 640, 480)

    def test_cli_accepts_no_yolo(self):
        with patch('sys.argv', ['main', '--no-yolo']):
            self.assertTrue(main.parse_args().no_yolo)

