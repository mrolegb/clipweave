from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from .media import read_image
from .models import Clip

THUMB_WIDTH = 220
THUMB_HEIGHT = 330
LABEL_HEIGHT = 44
PADDING = 10
BACKGROUND = (24, 24, 24)
TEXT = (235, 235, 235)
MUTED = (165, 165, 165)


def frame_at_time(path: Path, seconds: float) -> np.ndarray | None:
    """Read a frame near a source timestamp."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000)
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def representative_frame(clip: Clip) -> np.ndarray | None:
    """Read the representative source frame for a selected clip or segment."""
    if clip.media_type == "image":
        return read_image(clip.path)
    return frame_at_time(clip.path, clip.source_start + (clip.duration / 2))


def fit_thumbnail(frame: np.ndarray) -> np.ndarray:
    """Resize a frame into a letterboxed thumbnail."""
    height, width = frame.shape[:2]
    scale = min(THUMB_WIDTH / width, THUMB_HEIGHT / height)
    scaled_width = max(1, int(width * scale))
    scaled_height = max(1, int(height * scale))
    resized = cv2.resize(frame, (scaled_width, scaled_height), interpolation=cv2.INTER_AREA)
    thumb = np.full((THUMB_HEIGHT, THUMB_WIDTH, 3), BACKGROUND, dtype=np.uint8)
    y = (THUMB_HEIGHT - scaled_height) // 2
    x = (THUMB_WIDTH - scaled_width) // 2
    thumb[y : y + scaled_height, x : x + scaled_width] = resized
    return thumb


def clip_label(index: int, clip: Clip) -> tuple[str, str]:
    """Build compact label text for a selected clip cell."""
    title = f"{index:02d} {clip.path.name}"
    timing = f"{clip.source_start:.1f}-{clip.trim_end:.1f}s ({clip.duration:.1f}s)"
    return title, timing


def render_cell(index: int, clip: Clip) -> np.ndarray:
    """Render one contact-sheet cell with thumbnail and source timing."""
    frame = representative_frame(clip)
    thumb = fit_thumbnail(frame) if frame is not None else np.full((THUMB_HEIGHT, THUMB_WIDTH, 3), BACKGROUND, dtype=np.uint8)
    cell = np.full((THUMB_HEIGHT + LABEL_HEIGHT, THUMB_WIDTH, 3), BACKGROUND, dtype=np.uint8)
    cell[:THUMB_HEIGHT, :THUMB_WIDTH] = thumb
    title, timing = clip_label(index, clip)
    cv2.putText(cell, title[:32], (6, THUMB_HEIGHT + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, TEXT, 1, cv2.LINE_AA)
    cv2.putText(cell, timing, (6, THUMB_HEIGHT + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.42, MUTED, 1, cv2.LINE_AA)
    return cell


def save_contact_sheet(clips: list[Clip], output: Path, columns: int | None = None) -> Path:
    """Write a debug contact sheet with one representative frame per selected clip."""
    if not clips:
        raise RuntimeError("Cannot build a contact sheet without selected clips.")

    column_count = columns or max(1, min(6, math.ceil(math.sqrt(len(clips)))))
    row_count = math.ceil(len(clips) / column_count)
    cell_width = THUMB_WIDTH + PADDING
    cell_height = THUMB_HEIGHT + LABEL_HEIGHT + PADDING
    sheet = np.full(
        (row_count * cell_height + PADDING, column_count * cell_width + PADDING, 3),
        BACKGROUND,
        dtype=np.uint8,
    )

    for index, clip in enumerate(clips, 1):
        row = (index - 1) // column_count
        column = (index - 1) % column_count
        y = PADDING + (row * cell_height)
        x = PADDING + (column * cell_width)
        sheet[y : y + THUMB_HEIGHT + LABEL_HEIGHT, x : x + THUMB_WIDTH] = render_cell(index, clip)

    contact_path = output.with_suffix(".contact.jpg")
    cv2.imwrite(str(contact_path), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    return contact_path
