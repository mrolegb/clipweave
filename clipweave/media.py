from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .models import VideoMeta


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def probe_video(path: Path) -> VideoMeta:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    stream = (json.loads(proc.stdout or "{}").get("streams") or [{}])[0]
    return VideoMeta(
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        duration=float(stream.get("duration") or 0),
    )


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frame_at(path: Path, fraction: float):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(count - 1, int(count * fraction))))
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def read_image(path: Path):
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)
