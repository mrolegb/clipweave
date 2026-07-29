from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class VideoMeta:
    width: int
    height: int
    duration: float

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.width, self.height


@dataclass(frozen=True)
class Clip:
    path: Path
    meta: VideoMeta
    file_hash: str
    start: np.ndarray
    mid: np.ndarray
    end: np.ndarray
    brightness: float
    media_type: str = "video"

    @property
    def width(self) -> int:
        return self.meta.width

    @property
    def height(self) -> int:
        return self.meta.height

    @property
    def duration(self) -> float:
        return self.meta.duration

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.meta.dimensions


@dataclass(frozen=True)
class Transition:
    source: str
    target: str
    similarity: float
    fade_seconds: float

    def to_manifest(self) -> dict:
        return {
            "from": self.source,
            "to": self.target,
            "similarity": round(self.similarity, 4),
            "fade_seconds": round(self.fade_seconds, 3),
        }
