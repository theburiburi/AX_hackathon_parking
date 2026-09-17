import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from src.calibration.homography import project_point as legacy_project_point
from src.calibration import project_point
from src.calibration.cameras import camera_homographies
from src.tracking import DetectedVehicle, TrackedVehicle


class ModuleBoundaryTests(unittest.TestCase):
    def test_runtime_settings_load_without_single_camera_calibration(self):
        from src.main import load_runtime_config

        root = Path(__file__).resolve().parents[1]
        config = load_runtime_config(root / 'config.yaml')
        self.assertIn('model', config['detection'])
        self.assertNotIn('calibration', config)
        self.assertNotIn('visualization', config)

    def test_legacy_geometry_import_preserves_coordinate_result(self):
        matrix = np.array([[2., 0., 10.], [0., 3., 20.], [0., 0., 1.]])
        self.assertIs(legacy_project_point, project_point)
        self.assertEqual(legacy_project_point((5., 7.), matrix), (20., 41.))

    def test_vehicle_observations_keep_existing_constructors(self):
        tracked = TrackedVehicle(7, 2, 0.9, (10, 20, 30, 80))
        detected = DetectedVehicle(2, 0.9, tracked.bbox)
        self.assertEqual(tracked.track_id, 7)
        self.assertEqual(tracked.ground_point, detected.ground_point)
        self.assertEqual(detected.ground_point, (20., 80.))

    def test_camera_transforms_skip_samples_and_project_calibrated_camera(self):
        registry = SimpleNamespace(cameras=[
            SimpleNamespace(camera_id='sample', calibration={'is_sample': True}),
            SimpleNamespace(camera_id='ready', calibration={
                'is_sample': False,
                'image_points': [[0, 0], [10, 0], [10, 10], [0, 10]],
                'bev_points': [[100, 50], [200, 50], [200, 250], [100, 250]],
            }),
        ])
        matrices, missing = camera_homographies(registry)
        self.assertEqual(missing, ['sample'])
        np.testing.assert_allclose(project_point((5, 5), matrices['ready']), (150, 150))

    def test_invalid_camera_calibration_identifies_camera(self):
        registry = SimpleNamespace(cameras=[
            SimpleNamespace(camera_id='broken', calibration={'is_sample': False}),
        ])
        with self.assertRaisesRegex(ValueError, 'invalid calibration for broken'):
            camera_homographies(registry)

    def test_existing_cli_commands_work_without_models_or_browser(self):
        root = Path(__file__).resolve().parents[1]
        for module in ('src.main', 'src.calibrate', 'src.multi_player'):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, '-m', module, '--help'], cwd=root,
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)
                if module == 'src.main':
                    self.assertIn('--cameras-config', result.stdout)
                    self.assertNotIn('--video ', result.stdout)

    def test_core_imports_do_not_load_web_or_yolo_runtime(self):
        result = subprocess.run(
            [sys.executable, '-c',
             'import sys; import src.tracking; import src.calibration; '
             'assert not ({"fastapi", "ultralytics", "torch"} & set(sys.modules))'],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
