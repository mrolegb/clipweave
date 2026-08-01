from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

from .analysis import read_clip, read_image_clip
from .config import BuildOptions
from .constants import IMAGE_EXTS, OUTPUT_PREFIX, VIDEO_EXTS
from .contact_sheet import save_contact_sheet
from .models import Clip, Transition
from .render import concat_plain, concat_xfade, normalize_source
from .selection import (
    apply_duration_limit,
    aspect_matches,
    choose_dimensions,
    filter_by_target,
    order_clips,
    orientation_ok,
    prioritize_by_clothing,
    select_unique,
    select_unique_segments,
    select_smart_sequences,
    target_similarity,
)


def discover_clips(input_dir: Path, options: BuildOptions) -> list[Clip]:
    """Scan the input directory and build Clip descriptors for eligible media."""
    clips = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name.startswith(OUTPUT_PREFIX):
            continue
        suffix = path.suffix.lower()
        clip = None
        if options.media in {"videos", "mixed"} and suffix in VIDEO_EXTS:
            sample_rate = options.smart_sample_rate if options.smart_editing else 0.0
            clip = read_clip(path, sample_rate)
        elif options.media in {"images", "mixed"} and suffix in IMAGE_EXTS:
            clip = read_image_clip(path, options.image_duration)
        if clip and orientation_ok(clip, options.orientation):
            clips.append(clip)
    return clips


def normalized_media_path(path: Path) -> str:
    """Normalize media paths so manifest history checks survive case and relative paths."""
    return os.path.normcase(str(path.resolve()))


def current_manifest_paths(options: BuildOptions) -> set[Path]:
    """Return manifest paths that belong to the output currently being generated."""
    output = options.output_path
    paths = {output.with_suffix(".manifest.json").resolve()}
    if options.split_aspects:
        paths.update(output.parent.glob(f"{output.stem}_*.manifest.json"))
    return paths


def manifest_used_files(input_dir: Path, ignored_manifests: set[Path] | None = None) -> set[str]:
    """Read existing manifests in a folder and return source files already selected."""
    ignored = {path.resolve() for path in ignored_manifests or set()}
    used: set[str] = set()
    for manifest_path in sorted(input_dir.glob(f"{OUTPUT_PREFIX}*.manifest.json")):
        if manifest_path.resolve() in ignored:
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        manifests = []
        if isinstance(manifest, dict):
            manifests.append(manifest)
            manifests.extend(manifest.get("outputs", []))
        for item in manifests:
            if not isinstance(item, dict):
                continue
            for selected in item.get("selected_clips", []):
                file_name = selected.get("file")
                if file_name:
                    used.add(normalized_media_path(Path(file_name)))
    return used


def exclude_manifest_history(clips: list[Clip], options: BuildOptions) -> list[Clip]:
    """Drop clips whose source file already appears in another folder manifest."""
    if not options.exclude_manifest_history:
        return clips
    used_files = manifest_used_files(options.resolved_input_dir, current_manifest_paths(options))
    if not used_files:
        return clips
    return [clip for clip in clips if normalized_media_path(clip.path) not in used_files]


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


def order_and_smart_edit(clips: list[Clip], options: BuildOptions) -> tuple[list[Clip], dict[str, int | None]]:
    """Order clips, apply smart editing, and optionally re-order salvaged segments."""
    selected = order_clips(clips, options.order, options.structure)
    if not options.smart_editing:
        return selected, {"after_smart_trim": None, "after_smart_dedupe": None}

    selected = select_smart_sequences(
        selected,
        options.smart_threshold,
        options.smart_max_known_ratio,
        options.smart_min_segment_duration,
        options.smart_scene_threshold,
    )
    trim_count = len(selected)
    if options.smart_dedupe_segments:
        selected = select_unique_segments(
            selected,
            options.smart_threshold,
            options.smart_max_known_ratio,
        )
    dedupe_count = len(selected)
    if options.smart_reorder_segments:
        selected = order_clips(selected, options.order, options.structure)
    return selected, {"after_smart_trim": trim_count, "after_smart_dedupe": dedupe_count}


def aspect_key(clip: Clip) -> float:
    """Group clips by source aspect ratio with enough tolerance for common encodes."""
    return round(clip.width / clip.height, 2)


def grouped_by_aspect(clips: list[Clip]) -> list[list[Clip]]:
    """Return source clips grouped by rounded aspect ratio, largest groups first."""
    groups: dict[float, list[Clip]] = defaultdict(list)
    for clip in clips:
        groups[aspect_key(clip)].append(clip)
    return sorted(groups.values(), key=lambda group: (-len(group), aspect_key(group[0])))


def variant_output_path(base: Path, dimensions: tuple[int, int]) -> Path:
    """Append output dimensions before the file extension for split-aspect renders."""
    return base.with_name(f"{base.stem}_{dimensions[0]}x{dimensions[1]}{base.suffix}")


def select_from_pool(
    pool: list[Clip],
    options: BuildOptions,
    target: Clip | None,
    discovered_count: int,
    target_count: int,
    keep_exact_size: bool,
) -> tuple[list[Clip], tuple[int, int], dict[str, int | None], Clip | None]:
    """Select, order, and limit clips from an already-filtered source pool."""
    dimensions = choose_dimensions(pool, options.aspect_tolerance)
    candidates = [clip for clip in pool if aspect_matches(clip, dimensions, options.aspect_tolerance)] if keep_exact_size else pool
    selected = select_unique(candidates, options.duplicate_threshold)
    selected, smart_counts = order_and_smart_edit(selected, options)
    smart_count = len(selected)
    selected = prioritize_by_clothing(selected, options.clothing_priority)
    selected = apply_duration_limit(selected, options.max_duration)
    if not selected:
        raise RuntimeError("No clips selected after filtering.")
    counts = {
        "after_orientation": discovered_count,
        "after_target_filter": target_count,
        "after_manifest_filter": len(pool),
        "after_size_filter": len(candidates),
        "after_smart_filter": smart_count,
        "after_smart_trim": smart_counts["after_smart_trim"],
        "after_smart_dedupe": smart_counts["after_smart_dedupe"],
    }
    return selected, dimensions, counts, target


def source_pool(options: BuildOptions) -> tuple[list[Clip], Clip | None, int, int]:
    """Discover media and apply target filtering before final selection."""
    discovered = discover_clips(options.resolved_input_dir, options)
    if not discovered:
        raise RuntimeError("No readable clips match the requested orientation.")

    target = read_target(options)
    if options.target and target is None:
        raise RuntimeError(f"Could not read target media: {options.target}")

    clips = filter_by_target(discovered, target, options.target_threshold)
    if not clips:
        raise RuntimeError("No clips remain after target similarity filtering.")
    target_count = len(clips)
    clips = exclude_manifest_history(clips, options)
    if not clips:
        raise RuntimeError("No clips remain after manifest history filtering.")
    return clips, target, len(discovered), target_count


def select_clips(options: BuildOptions) -> tuple[list[Clip], tuple[int, int], dict[str, int | None], Clip | None]:
    """Apply orientation, size, duplicate, ordering, and duration filters."""
    clips, target, discovered_count, target_count = source_pool(options)
    return select_from_pool(clips, options, target, discovered_count, target_count, True)


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
            normalize_source(clip, path, dimensions, options.keep_audio, options.crf, options.preset, options.auto_grade)
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
    candidate_count: dict[str, int | None],
    transitions: list[Transition],
    target: Clip | None,
    output: Path | None = None,
) -> dict:
    """Build the JSON-serializable manifest written next to the output video."""
    return {
        "input_dir": str(options.resolved_input_dir),
        "output": str(output or options.output_path),
        "orientation": options.orientation,
        "media": options.media,
        "dimensions": {"width": dimensions[0], "height": dimensions[1]},
        "audio": options.audio,
        "image_duration": options.image_duration,
        "auto_grade": options.auto_grade,
        "structure": options.structure,
        "split_aspects": options.split_aspects,
        "exclude_manifest_history": options.exclude_manifest_history,
        "clothing_priority": options.clothing_priority,
        "smart_editing": options.smart_editing,
        "smart_sample_rate": options.smart_sample_rate if options.smart_editing else None,
        "smart_threshold": options.smart_threshold if options.smart_editing else None,
        "smart_max_known_ratio": options.smart_max_known_ratio if options.smart_editing else None,
        "smart_min_segment_duration": options.smart_min_segment_duration if options.smart_editing else None,
        "smart_scene_threshold": options.smart_scene_threshold if options.smart_editing else None,
        "smart_reorder_segments": options.smart_reorder_segments if options.smart_editing else None,
        "smart_dedupe_segments": options.smart_dedupe_segments if options.smart_editing else None,
        "target": str(options.target) if options.target else None,
        "target_threshold": options.target_threshold if options.target else None,
        "transition": options.transition if not options.keep_audio else "cut",
        "source_candidates": candidate_count["after_size_filter"],
        "source_candidates_after_orientation": candidate_count["after_orientation"],
        "source_candidates_after_target_filter": candidate_count["after_target_filter"],
        "source_candidates_after_manifest_filter": candidate_count.get("after_manifest_filter"),
        "source_candidates_after_smart_filter": candidate_count["after_smart_filter"] if options.smart_editing else None,
        "source_candidates_after_smart_trim": candidate_count["after_smart_trim"] if options.smart_editing else None,
        "source_candidates_after_smart_dedupe": candidate_count["after_smart_dedupe"] if options.smart_editing else None,
        "selected_clips_count": len(clips),
        "selected_clips_duration_sum": round(sum(clip.duration for clip in clips), 3),
        "output_duration_is_shorter_by_fades": options.use_fades,
        "selected_clips": [
            {
                "file": str(clip.path),
                "duration": round(clip.duration, 3),
                "source_start": round(clip.source_start, 3),
                "source_end": round(clip.trim_end, 3),
                "media_type": clip.media_type,
                "motion_score": round(clip.motion_score, 4),
                "skin_exposure_score": round(clip.skin_exposure_score, 4),
                "target_similarity": round(target_similarity(clip, target), 4) if target else None,
                "known_frame_ratio": round(clip.known_frame_ratio, 4) if clip.known_frame_ratio is not None else None,
            }
            for clip in clips
        ],
        "transitions": [transition.to_manifest() for transition in transitions],
    }


def write_sidecars(options: BuildOptions, clips: list[Clip], output: Path, manifest: dict) -> None:
    """Write optional manifest and contact sheet sidecars for one rendered output."""
    if options.save_contact_sheet:
        manifest["contact_sheet"] = str(save_contact_sheet(clips, output))
    if options.save_manifest:
        output.with_suffix(".manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def build_split_aspect_videos(options: BuildOptions) -> dict:
    """Build one output video for each source aspect-ratio group."""
    clips, target, discovered_count, target_count = source_pool(options)
    outputs = []
    for group in grouped_by_aspect(clips):
        selected, dimensions, candidate_count, _ = select_from_pool(
            group,
            options,
            target,
            discovered_count,
            target_count,
            False,
        )
        output = variant_output_path(options.output_path, dimensions)
        output.parent.mkdir(parents=True, exist_ok=True)
        transitions = render_video(selected, dimensions, output, options)
        manifest = build_manifest(options, selected, dimensions, candidate_count, transitions, target, output)
        write_sidecars(options, selected, output, manifest)
        outputs.append(manifest)

    return {
        "input_dir": str(options.resolved_input_dir),
        "split_aspects": True,
        "exclude_manifest_history": options.exclude_manifest_history,
        "outputs_count": len(outputs),
        "outputs": outputs,
    }


def build_video(options: BuildOptions) -> dict:
    """Run the full montage pipeline and write output video plus manifest."""
    if options.split_aspects:
        return build_split_aspect_videos(options)

    clips, dimensions, candidate_count, target = select_clips(options)
    output = options.output_path
    output.parent.mkdir(parents=True, exist_ok=True)
    transitions = render_video(clips, dimensions, output, options)

    manifest = build_manifest(options, clips, dimensions, candidate_count, transitions, target)
    write_sidecars(options, clips, output, manifest)
    return manifest
