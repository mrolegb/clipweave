from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def probe(path: Path) -> dict:
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
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    duration = float(stream.get("duration") or 0)
    return {"width": width, "height": height, "duration": duration}


def sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frame_at(path: Path, frac: float):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(count - 1, int(count * frac))))
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def frame_vec(frame) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (64, 96), interpolation=cv2.INTER_AREA).astype("float32").reshape(-1)
    small -= small.mean()
    return small / max(float(np.linalg.norm(small)), 1e-9)


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def read_clip(path: Path) -> dict | None:
    meta = probe(path)
    if not meta["width"] or not meta["height"] or meta["duration"] <= 0:
        return None
    frames = [frame_at(path, frac) for frac in (0.04, 0.50, 0.96)]
    if any(frame is None for frame in frames):
        return None
    mid_gray = cv2.cvtColor(frames[1], cv2.COLOR_BGR2GRAY)
    return {
        "path": path,
        **meta,
        "sha1": sha1(path),
        "start": frame_vec(frames[0]),
        "mid": frame_vec(frames[1]),
        "end": frame_vec(frames[2]),
        "brightness": float(np.mean(mid_gray)),
    }


def orientation_ok(clip: dict, orientation: str) -> bool:
    if orientation == "vertical":
        return clip["height"] > clip["width"]
    if orientation == "horizontal":
        return clip["width"] > clip["height"]
    return True


def choose_dimensions(clips: list[dict], aspect_tolerance: float) -> tuple[int, int]:
    dims = Counter((clip["width"], clip["height"]) for clip in clips)
    best_dim, best_count = dims.most_common(1)[0]
    if best_count >= 3:
        return best_dim

    ratios = Counter(round(clip["width"] / clip["height"], 2) for clip in clips)
    target_ratio = ratios.most_common(1)[0][0]
    close = [
        clip
        for clip in clips
        if abs((clip["width"] / clip["height"]) - target_ratio) <= aspect_tolerance
    ]
    dims = Counter((clip["width"], clip["height"]) for clip in close)
    return dims.most_common(1)[0][0]


def is_extension_duplicate(shorter: dict, longer: dict, threshold: float) -> bool:
    if longer["duration"] < 28 or shorter["duration"] >= 28:
        return False
    return max(
        correlation(shorter["start"], longer["start"]),
        correlation(shorter["mid"], longer["mid"]),
        correlation(shorter["end"], longer["end"]),
    ) >= threshold


def select_unique(clips: list[dict], duplicate_threshold: float) -> list[dict]:
    by_sha = {}
    for clip in clips:
        by_sha.setdefault(clip["sha1"], clip)
    clips = list(by_sha.values())

    selected: list[dict] = []
    for clip in sorted(clips, key=lambda c: (-c["duration"], c["path"].name)):
        skip = False
        for existing in selected:
            mid_sim = correlation(clip["mid"], existing["mid"])
            if mid_sim >= duplicate_threshold:
                skip = True
                break
            if is_extension_duplicate(clip, existing, duplicate_threshold):
                skip = True
                break
        if not skip:
            selected.append(clip)
    return selected


def order_clips(clips: list[dict], mode: str) -> list[dict]:
    if mode == "name":
        return sorted(clips, key=lambda c: c["path"].name)
    if mode == "duration":
        return sorted(clips, key=lambda c: (-c["duration"], c["path"].name))
    if not clips:
        return []

    unused = clips[:]
    current = min(unused, key=lambda c: (c["brightness"], -c["duration"]))
    ordered = [current]
    unused.remove(current)
    while unused:
        current = min(
            unused,
            key=lambda c: (
                1 - correlation(ordered[-1]["end"], c["start"]),
                abs(ordered[-1]["brightness"] - c["brightness"]),
            ),
        )
        ordered.append(current)
        unused.remove(current)
    return ordered


def apply_duration_limit(clips: list[dict], max_duration: float | None) -> list[dict]:
    if not max_duration:
        return clips
    total = 0.0
    selected = []
    for clip in clips:
        if selected and total + clip["duration"] > max_duration:
            continue
        selected.append(clip)
        total += clip["duration"]
        if total >= max_duration:
            break
    return selected


def fade_duration(prev: dict, nxt: dict, min_fade: float, max_fade: float) -> float:
    sim = correlation(prev["end"], nxt["start"])
    if sim >= 0.90:
        return min_fade
    if sim >= 0.82:
        return max(min_fade, min(0.15, max_fade))
    if sim >= 0.72:
        return max(min_fade, min(0.25, max_fade))
    return max_fade


def normalize_clip(src: Path, dst: Path, width: int, height: int, audio: bool, crf: int, preset: str) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-vf",
        f"scale={width}:{height}:flags=lanczos,setsar=1,fps=30,format=yuv420p",
    ]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-movflags",
        "+faststart",
        str(dst),
    ]
    run(cmd)


def concat_plain(clips: list[Path], output: Path) -> None:
    concat_file = output.parent / "concat.txt"
    concat_file.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(output)])


def concat_xfade(clips: list[Path], rows: list[dict], output: Path, min_fade: float, max_fade: float, crf: int, preset: str) -> list[dict]:
    if len(clips) == 1:
        shutil.copy2(clips[0], output)
        return []
    inputs = []
    for clip in clips:
        inputs += ["-i", str(clip)]

    filters = []
    label = "[0:v]"
    cumulative = rows[0]["duration"]
    transitions = []
    for i in range(1, len(clips)):
        duration = min(
            fade_duration(rows[i - 1], rows[i], min_fade, max_fade),
            max(0.04, rows[i - 1]["duration"] / 5),
            max(0.04, rows[i]["duration"] / 5),
        )
        offset = max(0.0, cumulative - duration)
        next_label = f"[v{i}]"
        filters.append(f"{label}[{i}:v]xfade=transition=fade:duration={duration:.3f}:offset={offset:.3f}{next_label}")
        transitions.append(
            {
                "from": rows[i - 1]["path"].name,
                "to": rows[i]["path"].name,
                "similarity": round(correlation(rows[i - 1]["end"], rows[i]["start"]), 4),
                "fade_seconds": round(duration, 3),
            }
        )
        cumulative += rows[i]["duration"] - duration
        label = next_label

    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            label,
            "-an",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return transitions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble a coherent montage from a folder of clips.")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--orientation", choices=["vertical", "horizontal", "any"], default="vertical")
    parser.add_argument("--audio", choices=["keep", "remove"], default="remove")
    parser.add_argument("--max-duration", type=float, default=None, help="Maximum output duration in seconds.")
    parser.add_argument("--output", type=Path, default=None, help="Default: <input_dir>/clipweave_<orientation>.mp4")
    parser.add_argument("--work-dir", type=Path, default=None, help="Default: temporary directory, deleted after build.")
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("--transition", choices=["fade", "cut"], default="fade")
    parser.add_argument("--min-fade", type=float, default=0.08)
    parser.add_argument("--max-fade", type=float, default=0.45)
    parser.add_argument("--duplicate-threshold", type=float, default=0.965)
    parser.add_argument("--aspect-tolerance", type=float, default=0.04)
    parser.add_argument("--order", choices=["visual", "name", "duration"], default="visual")
    parser.add_argument("--crf", type=int, default=16)
    parser.add_argument("--preset", default="slow")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output = args.output or (input_dir / f"clipweave_{args.orientation}.mp4")
    manifest_path = output.with_suffix(".manifest.json")

    clips = []
    for path in sorted(input_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTS and not path.name.startswith("clipweave_"):
            clip = read_clip(path)
            if clip and orientation_ok(clip, args.orientation):
                clips.append(clip)
    if not clips:
        raise RuntimeError("No readable clips match the requested orientation.")

    width, height = choose_dimensions(clips, args.aspect_tolerance)
    clips = [clip for clip in clips if (clip["width"], clip["height"]) == (width, height)]
    selected = select_unique(clips, args.duplicate_threshold)
    selected = order_clips(selected, args.order)
    selected = apply_duration_limit(selected, args.max_duration)
    if not selected:
        raise RuntimeError("No clips selected after filtering.")

    temp_root = args.work_dir or Path(tempfile.mkdtemp(prefix="clipweave_"))
    temp_root.mkdir(parents=True, exist_ok=True)
    transitions = []
    try:
        normalized = []
        for index, clip in enumerate(selected, 1):
            dst = temp_root / f"clip_{index:03d}.mp4"
            normalize_clip(clip["path"], dst, width, height, args.audio == "keep", args.crf, args.preset)
            normalized.append(dst)

        if args.transition == "fade" and args.audio == "remove":
            transitions = concat_xfade(normalized, selected, output, args.min_fade, args.max_fade, args.crf, args.preset)
        else:
            concat_plain(normalized, output)
    finally:
        if not args.keep_work and not args.work_dir:
            shutil.rmtree(temp_root, ignore_errors=True)

    manifest = {
        "input_dir": str(input_dir),
        "output": str(output),
        "orientation": args.orientation,
        "dimensions": {"width": width, "height": height},
        "audio": args.audio,
        "transition": args.transition if args.audio == "remove" else "cut",
        "source_candidates": len(clips),
        "selected_clips_count": len(selected),
        "selected_clips_duration_sum": round(sum(clip["duration"] for clip in selected), 3),
        "output_duration_is_shorter_by_fades": args.transition == "fade" and args.audio == "remove",
        "selected_clips": [{"file": str(clip["path"]), "duration": round(clip["duration"], 3)} for clip in selected],
        "transitions": transitions,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
