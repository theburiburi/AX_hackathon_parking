"""Backward-compatible entry point for interactive calibration."""

from .calibration.cli import *  # noqa: F403
from .calibration.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
