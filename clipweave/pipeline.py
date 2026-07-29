from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from .analysis import read_clip, read_image_clip
from .config import BuildOptions
from .constants import IMAGE_EXTS, VIDEO_EXTS
from .models import Clip, Transition
from .render import concat_plain, concat_xfade, normalize_source
from .selection import (
    apply_duration_limit,
    choose_dimensions,
    filter_by_target,
    order_clips,
    orientation_ok,
    select_unique,
    target_similarity,
)


def discover_clips(input_dir: Path, options: BuildOptions) -> list[Clip]:
    """Scan the input directory and build Clip descriptors for eligible media."""
    clips = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name.startswith("clipweave_"):
            continue
        suffix = path.suffix.lower()
        clip = None
        if options.media in {"videos", "mixed"} and suffix in VIDEO_EXTS:
            clip = read_clip(path)
        elif options.media in {"images", "mixed"} and suffix in IMAGE_EXTS:
            clip = read_image_clip(path, options.image_duration)
        if clip and orientation_ok(clip, options.orientation):
            clips.append(clip)
    return clips


def read_target(options: BuildOptions) -> Clip | None:
    """Read the optional target image/video used for visual theme filtering."""
    if options.target is None:
        return None
    suffix = options.target.suffix.lower()
    if suffix in VIDEO_EXTS:
        return read_clip(options.target)
    if suffix in IMAGE_EXTS:
        return read_image_clip(options.target, options.image_duration)
    raise RuntimeError(f"Unsupported target file type: {options.target}")


def select_clips(options: BuildOptions) -> tuple[list[Clip], tuple[int, int], dict[str, int], Clip | None]:
    """Apply orientation, size, duplicate, ordering, and duration filters."""
    discovered = discover_clips(options.resolved_input_dir, options)
    if not discovered:
        raise RuntimeError("No readable clips match the requested orientation.")

    target = read_target(options)
    if options.target and target is None:
        raise RuntimeError(f"Could not read target media: {options.target}")

    clips = discovered
    clips = filter_by_target(clips, target, options.target_threshold)
    if not clips:
        raise RuntimeError("No clips remain after target similarity filtering.")

    dimensions = choose_dimensions(clips, options.aspect_tolerance)
    same_size = [clip for clip in clips if clip.dimensions == dimensions]
    selected = select_unique(same_size, options.duplicate_threshold)
    selected = order_clips(selected, options.order)
    selected = apply_duration_limit(selected, options.max_duration)
    if not selected:
        raise RuntimeError("No clips selected after filtering.")
    counts = {
        "after_orientation": len(discovered),
        "after_target_filter": len(clips),
        "after_size_filter": len(same_size),
    }
    return selected, dimensions, counts, target


def render_video(
    clips: list[Clip],
    dimensions: tuple[int, int],
    output: Path,
    options: BuildOptions,
) -> list[Transition]:
    """Normalize selected media, render the final output, and clean intermediates."""
    temp_root = options.work_dir or Path(tempfile.mkdtemp(prefix="clipweave_"))
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        normalized = []
        for index, clip in enumerate(clips, 1):
            path = temp_root / f"clip_{index:03d}.mp4"
            normalize_source(clip, path, dimensions, options.keep_audio, options.crf, options.preset)
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
    candidate_count: dict[str, int],
    transitions: list[Transition],
    target: Clip | None,
) -> dict:
    """Build the JSON-serializable manifest written next to the output video."""
    return {
        "input_dir": str(options.resolved_input_dir),
        "output": str(options.output_path),
        "orientation": options.orientation,
        "media": options.media,
        "dimensions": {"width": dimensions[0], "height": dimensions[1]},
        "audio": options.audio,
        "image_duration": options.image_duration,
        "target": str(options.target) if options.target else None,
        "target_threshold": options.target_threshold if options.target else None,
        "transition": options.transition if not options.keep_audio else "cut",
        "source_candidates": candidate_count["after_size_filter"],
        "source_candidates_after_orientation": candidate_count["after_orientation"],
        "source_candidates_after_target_filter": candidate_count["after_target_filter"],
        "selected_clips_count": len(clips),
        "selected_clips_duration_sum": round(sum(clip.duration for clip in clips), 3),
        "output_duration_is_shorter_by_fades": options.use_fades,
        "selected_clips": [
            {
                "file": str(clip.path),
                "duration": round(clip.duration, 3),
                "media_type": clip.media_type,
                "target_similarity": round(target_similarity(clip, target), 4) if target else None,
            }
            for clip in clips
        ],
        "transitions": [transition.to_manifest() for transition in transitions],
    }


def build_video(options: BuildOptions) -> dict:
    """Run the full montage pipeline and write output video plus manifest."""
    clips, dimensions, candidate_count, target = select_clips(options)
    output = options.output_path
    output.parent.mkdir(parents=True, exist_ok=True)
    transitions = render_video(clips, dimensions, output, options)

    manifest = build_manifest(options, clips, dimensions, candidate_count, transitions, target)
    output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
