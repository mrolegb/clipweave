from __future__ import annotations

import shutil
import traceback

from PySide6.QtCore import QObject, Signal

from .config import BuildOptions
from .pipeline import build_video


def ffmpeg_available() -> bool:
    """Check that the external FFmpeg tools required by the renderer are available."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class BuildWorker(QObject):
    """Run Clipweave in a background thread so the UI stays responsive."""

    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, options: BuildOptions) -> None:
        super().__init__()
        self.options = options

    def run(self) -> None:
        """Build the video and notify the UI with either a manifest or traceback."""
        try:
            self.finished.emit(build_video(self.options))
        except Exception:
            self.failed.emit(traceback.format_exc())
