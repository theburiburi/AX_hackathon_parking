# Repository collaboration rules

- Read `docs/ARCHITECTURE.md` before changing module boundaries.
- Put new business logic in the owning module; keep CLI wrappers thin.
- Keep `src/calibrate.py` and `src/multi_player.py` backward compatible.
- Keep calibration, tracking, and playback independent from FastAPI and browser code.
- Do not instantiate YOLO models inside API routes or once per browser client.
- Add or update focused tests for every behavior change and run the full unittest suite.
- Do not commit CCTV videos, generated model weights, credentials, or machine-specific paths.
- Coordinate before changing shared contracts such as `TrackedVehicle`, calibration point formats,
  or `SynchronizedVideoReader.read_at()` return values.

## Keep the initial project simple

- Use the editing map in README.md and ownership in docs/CONTRIBUTING.md.
- Keep vehicle detection and tracking in src/tracking.py, geometry in src/calibration/,
  video synchronization in src/playback/, and multi-camera orchestration in src/main.py.
- Keep frontend work in root web/.
- Do not create placeholder packages, abstraction layers, or compatibility wrappers for unimplemented features.
- docs/INTERFACE_AGREEMENT.md is an unfilled template, not an approved data contract.
