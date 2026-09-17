"""Backward-compatible entry point for synchronized OpenCV playback."""

from .playback.cli import *  # noqa: F403
from .playback.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
