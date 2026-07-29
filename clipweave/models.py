from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class VideoMeta:
    """Basic stream properties used for filtering and output sizing."""

    width: int
    height: int
    duration: float

    @property
    def dimensions(self) -> tuple[int, int]:
        """Return dimensions as an FFmpeg-friendly (width, height) tuple."""
        return self.width, self.height


@dataclass(frozen=True)
class Clip:
    """A source video or image plus visual descriptors for ordering and dedupe."""

    path: Path
    meta: VideoMeta
    file_hash: str
    start: np.ndarray
    mid: np.ndarray
    end: np.ndarray
    brightness: float
    media_type: str = "video"
    sequence: tuple[np.ndarray, ...] = field(default_factory=tuple)
    known_frame_ratio: float | None = None

    @property
    def width(self) -> int:
        """Source width in pixels."""
        return self.meta.width

    @property
    def height(self) -> int:
        """Source height in pixels."""
        return self.meta.height

    @property
    def duration(self) -> float:
        """Duration in seconds; for images this is the configured slide length."""
        return self.meta.duration

    @property
    def dimensions(self) -> tuple[int, int]:
        """Return source dimensions as (width, height)."""
        return self.meta.dimensions


@dataclass(frozen=True)
class Transition:
    """Manifest record for one transition between two selected clips."""

    source: str
    target: str
    similarity: float
    fade_seconds: float

    def to_manifest(self) -> dict:
        """Serialize transition data with stable rounding for JSON output."""
        return {
            "from": self.source,
            "to": self.target,
            "similarity": round(self.similarity, 4),
            "fade_seconds": round(self.fade_seconds, 3),
        }
