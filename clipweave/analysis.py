from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .media import file_sha1, frames_at, probe_video, read_image
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


def motion_score(sequence: tuple[np.ndarray, ...]) -> float:
    """Estimate clip motion from average visual change between sampled frames."""
    if len(sequence) < 2:
        return 0.0
    changes = [max(0.0, 1.0 - correlation(sequence[index - 1], sequence[index])) for index in range(1, len(sequence))]
    return float(sum(changes) / len(changes))


def skin_ratio(frame: np.ndarray) -> float:
    """Estimate visible skin-colored area in the central body region of one frame."""
    height, width = frame.shape[:2]
    if not height or not width:
        return 0.0

    y1 = int(height * 0.12)
    y2 = int(height * 0.95)
    x1 = int(width * 0.12)
    x2 = int(width * 0.88)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    ycrcb = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
    hsv_mask = cv2.inRange(hsv, np.array([0, 25, 45]), np.array([35, 230, 255]))
    ycrcb_mask = cv2.inRange(ycrcb, np.array([35, 133, 77]), np.array([255, 173, 127]))
    mask = cv2.bitwise_and(hsv_mask, ycrcb_mask)
    return float(np.count_nonzero(mask) / mask.size)


def skin_exposure_score(frames: list[np.ndarray]) -> float:
    """Return a stable skin-exposure estimate across sampled frames."""
    ratios = [skin_ratio(frame) for frame in frames if frame is not None]
    return float(np.median(ratios)) if ratios else 0.0


def sequence_fractions(duration: float, sample_rate: float) -> list[float]:
    """Choose frame positions for sequence-level visual duplicate checks."""
    if sample_rate <= 0:
        return [0.04, 0.50, 0.96]
    count = max(3, min(120, int(duration * sample_rate) + 1))
    if count == 1:
        return [0.50]
    return [0.02 + (0.96 * index / (count - 1)) for index in range(count)]


def fraction_times(duration: float, fractions: list[float]) -> tuple[float, ...]:
    """Convert sampled frame fractions into source timestamps."""
    return tuple(max(0.0, min(duration, duration * fraction)) for fraction in fractions)


def read_clip(path: Path, sequence_sample_rate: float = 0.0) -> Clip | None:
    """Read a video and sample start/middle/end frames into a Clip descriptor."""
    meta = probe_video(path)
    if not meta.width or not meta.height or meta.duration <= 0:
        return None

    frames = frames_at(path, [0.04, 0.50, 0.96])
    if any(frame is None for frame in frames):
        return None

    mid_gray = cv2.cvtColor(frames[1], cv2.COLOR_BGR2GRAY)
    start_vector = frame_vector(frames[0])
    mid_vector = frame_vector(frames[1])
    end_vector = frame_vector(frames[2])
    sequence_fractions_used = [0.04, 0.50, 0.96]
    sequence = (start_vector, mid_vector, end_vector)
    if sequence_sample_rate > 0:
        sequence_fractions_used = sequence_fractions(meta.duration, sequence_sample_rate)
        sequence_frames = frames_at(path, sequence_fractions_used)
        sequence = tuple(frame_vector(frame) for frame in sequence_frames if frame is not None)
        sequence_fractions_used = [
            fraction
            for fraction, frame in zip(sequence_fractions_used, sequence_frames)
            if frame is not None
        ]

    return Clip(
        path=path,
        meta=meta,
        file_hash=file_sha1(path),
        start=start_vector,
        mid=mid_vector,
        end=end_vector,
        brightness=float(np.mean(mid_gray)),
        motion_score=motion_score(sequence),
        skin_exposure_score=skin_exposure_score(frames),
        media_type="video",
        sequence=sequence,
        sequence_times=fraction_times(meta.duration, sequence_fractions_used),
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
        motion_score=0.0,
        skin_exposure_score=skin_exposure_score([frame]),
        media_type="image",
        sequence=(vector,),
        sequence_times=(0.0,),
    )
