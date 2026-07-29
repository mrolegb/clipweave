from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .media import file_sha1, frame_at, probe_video, read_image
from .models import Clip, VideoMeta


def frame_vector(frame: np.ndarray) -> np.ndarray:
    """Convert a frame into a normalized grayscale vector for similarity checks."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (64, 96), interpolation=cv2.INTER_AREA).astype("float32").reshape(-1)
    small -= small.mean()
    return small / max(float(np.linalg.norm(small)), 1e-9)


def correlation(left: np.ndarray, right: np.ndarray) -> float:
    """Return cosine-like similarity for already normalized frame vectors."""
    return float(np.dot(left, right))


def read_clip(path: Path) -> Clip | None:
    """Read a video and sample start/middle/end frames into a Clip descriptor."""
    meta = probe_video(path)
    if not meta.width or not meta.height or meta.duration <= 0:
        return None

    frames = [frame_at(path, fraction) for fraction in (0.04, 0.50, 0.96)]
    if any(frame is None for frame in frames):
        return None

    mid_gray = cv2.cvtColor(frames[1], cv2.COLOR_BGR2GRAY)
    return Clip(
        path=path,
        meta=meta,
        file_hash=file_sha1(path),
        start=frame_vector(frames[0]),
        mid=frame_vector(frames[1]),
        end=frame_vector(frames[2]),
        brightness=float(np.mean(mid_gray)),
        media_type="video",
    )


def read_image_clip(path: Path, duration: float) -> Clip | None:
    """Read an image as a still Clip with the requested slideshow duration."""
    frame = read_image(path)
    if frame is None:
        return None

    height, width = frame.shape[:2]
    if not width or not height:
        return None

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    vector = frame_vector(frame)
    return Clip(
        path=path,
        meta=VideoMeta(width=width, height=height, duration=duration),
        file_hash=file_sha1(path),
        start=vector,
        mid=vector,
        end=vector,
        brightness=float(np.mean(gray)),
        media_type="image",
    )
