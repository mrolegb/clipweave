from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from .analysis import read_clip
from .config import BuildOptions
from .constants import VIDEO_EXTS
from .models import Clip, Transition
from .render import concat_plain, concat_xfade, normalize_clip
from .selection import (
    apply_duration_limit,
    choose_dimensions,
    order_clips,
    orientation_ok,
    select_unique,
)


def discover_clips(input_dir: Path, orientation: str) -> list[Clip]:
    clips = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS:
            continue
        if path.name.startswith("clipweave_"):
            continue
        clip = read_clip(path)
        if clip and orientation_ok(clip, orientation):
            clips.append(clip)
    return clips


def select_clips(options: BuildOptions) -> tuple[list[Clip], tuple[int, int], int]:
    clips = discover_clips(options.resolved_input_dir, options.orientation)
    if not clips:
        raise RuntimeError("No readable clips match the requested orientation.")

    dimensions = choose_dimensions(clips, options.aspect_tolerance)
    same_size = [clip for clip in clips if clip.dimensions == dimensions]
    selected = select_unique(same_size, options.duplicate_threshold)
    selected = order_clips(selected, options.order)
    selected = apply_duration_limit(selected, options.max_duration)
    if not selected:
        raise RuntimeError("No clips selected after filtering.")
    return selected, dimensions, len(same_size)


def render_video(
    clips: list[Clip],
    dimensions: tuple[int, int],
    output: Path,
    options: BuildOptions,
) -> list[Transition]:
    temp_root = options.work_dir or Path(tempfile.mkdtemp(prefix="clipweave_"))
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        normalized = []
        for index, clip in enumerate(clips, 1):
            path = temp_root / f"clip_{index:03d}.mp4"
            normalize_clip(clip.path, path, dimensions, options.keep_audio, options.crf, options.preset)
            normalized.append(path)

        if options.use_fades:
            return concat_xfade(
                normalized,
                clips,
                output,
                options.min_fade,
                options.max_fade,
                options.crf,
                options.preset,
            )
        concat_plain(normalized, output, temp_root / "concat.txt")
        return []
    finally:
        if not options.keep_work and not options.work_dir:
            shutil.rmtree(temp_root, ignore_errors=True)


def build_manifest(
    options: BuildOptions,
    clips: list[Clip],
    dimensions: tuple[int, int],
    candidate_count: int,
    transitions: list[Transition],
) -> dict:
    return {
        "input_dir": str(options.resolved_input_dir),
        "output": str(options.output_path),
        "orientation": options.orientation,
        "dimensions": {"width": dimensions[0], "height": dimensions[1]},
        "audio": options.audio,
        "transition": options.transition if not options.keep_audio else "cut",
        "source_candidates": candidate_count,
        "selected_clips_count": len(clips),
        "selected_clips_duration_sum": round(sum(clip.duration for clip in clips), 3),
        "output_duration_is_shorter_by_fades": options.use_fades,
        "selected_clips": [
            {"file": str(clip.path), "duration": round(clip.duration, 3)}
            for clip in clips
        ],
        "transitions": [transition.to_manifest() for transition in transitions],
    }


def build_video(options: BuildOptions) -> dict:
    clips, dimensions, candidate_count = select_clips(options)
    output = options.output_path
    output.parent.mkdir(parents=True, exist_ok=True)
    transitions = render_video(clips, dimensions, output, options)

    manifest = build_manifest(options, clips, dimensions, candidate_count, transitions)
    output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
