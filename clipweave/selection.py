from __future__ import annotations

from collections import Counter
from dataclasses import replace

import numpy as np

from .analysis import correlation
from .models import Clip, VideoMeta


def orientation_ok(clip: Clip, orientation: str) -> bool:
    """Check whether a clip matches the requested orientation filter."""
    if orientation == "vertical":
        return clip.height > clip.width
    if orientation == "horizontal":
        return clip.width > clip.height
    return True


def choose_dimensions(clips: list[Clip], aspect_tolerance: float) -> tuple[int, int]:
    """Pick the target output size from the most common matching source size."""
    dimensions = Counter(clip.dimensions for clip in clips)
    best_dimensions, best_count = dimensions.most_common(1)[0]
    if best_count >= 3:
        return best_dimensions

    ratios = Counter(round(clip.width / clip.height, 2) for clip in clips)
    target_ratio = ratios.most_common(1)[0][0]
    close = [
        clip
        for clip in clips
        if abs((clip.width / clip.height) - target_ratio) <= aspect_tolerance
    ]
    return Counter(clip.dimensions for clip in close).most_common(1)[0][0]


def is_extension_duplicate(shorter: Clip, longer: Clip, threshold: float) -> bool:
    """Detect likely Grok extension duplicates where a short clip repeats a long one."""
    if longer.duration < 28 or shorter.duration >= 28:
        return False
    return max(
        correlation(shorter.start, longer.start),
        correlation(shorter.mid, longer.mid),
        correlation(shorter.end, longer.end),
    ) >= threshold


def select_unique(clips: list[Clip], duplicate_threshold: float) -> list[Clip]:
    """Remove exact duplicates and strong visual duplicates, preferring longer clips."""
    by_hash: dict[str, Clip] = {}
    for clip in clips:
        existing = by_hash.get(clip.file_hash)
        if existing is None or clip.duration > existing.duration:
            by_hash[clip.file_hash] = clip
        elif clip.duration == existing.duration and clip.path.name < existing.path.name:
            by_hash[clip.file_hash] = clip

    selected: list[Clip] = []
    for clip in sorted(by_hash.values(), key=lambda item: (-item.duration, item.path.name)):
        duplicate = False
        for existing in selected:
            if correlation(clip.mid, existing.mid) >= duplicate_threshold:
                duplicate = True
                break
            if is_extension_duplicate(clip, existing, duplicate_threshold):
                duplicate = True
                break
        if not duplicate:
            selected.append(clip)
    return selected


def target_similarity(clip: Clip, target: Clip) -> float:
    """Score how close a clip is to a target image/video descriptor."""
    return max(
        correlation(clip.start, target.start),
        correlation(clip.mid, target.mid),
        correlation(clip.end, target.end),
    )


def filter_by_target(clips: list[Clip], target: Clip | None, threshold: float) -> list[Clip]:
    """Drop clips whose sampled frames are not visually close enough to the target."""
    if target is None:
        return clips
    return [clip for clip in clips if target_similarity(clip, target) >= threshold]


def known_frame_ratio(clip: Clip, known_frames: list[np.ndarray], threshold: float) -> float:
    """Return the share of a clip's sampled sequence already represented by known frames."""
    sequence = clip.sequence or (clip.start, clip.mid, clip.end)
    flags = known_frame_flags(sequence, known_frames, threshold)
    return sum(flags) / len(flags) if flags else 0.0


def known_frame_flags(
    sequence: tuple[np.ndarray, ...],
    known_frames: list[np.ndarray],
    threshold: float,
) -> list[bool]:
    """Mark sampled frames that are visually represented by earlier selected frames."""
    if not sequence or not known_frames:
        return [False for _ in sequence]
    return [max(correlation(frame, known) for known in known_frames) >= threshold for frame in sequence]


def novel_ranges(flags: list[bool]) -> list[tuple[int, int]]:
    """Return inclusive ranges of sampled frames that are not known yet."""
    ranges: list[tuple[int, int]] = []
    start = None
    for index, is_known in enumerate(flags):
        if not is_known and start is None:
            start = index
        elif is_known and start is not None:
            ranges.append((start, index - 1))
            start = None
    if start is not None:
        ranges.append((start, len(flags) - 1))
    return ranges


def clip_segment(clip: Clip, start_index: int, end_index: int) -> Clip:
    """Create a source-trimmed Clip from a sampled frame index range."""
    sequence = clip.sequence or (clip.start, clip.mid, clip.end)
    times = clip.sequence_times
    if len(times) != len(sequence):
        step = clip.duration / max(1, len(sequence) - 1)
        times = tuple(index * step for index in range(len(sequence)))

    start_margin = (times[start_index] - times[start_index - 1]) / 2 if start_index > 0 else times[start_index]
    if end_index + 1 < len(times):
        end_margin = (times[end_index + 1] - times[end_index]) / 2
    else:
        end_margin = (times[end_index] - times[end_index - 1]) / 2 if end_index > 0 else clip.duration - times[end_index]
    start = max(0.0, times[start_index] - start_margin)
    end = min(clip.duration, times[end_index] + end_margin)
    duration = max(0.0, end - start)
    segment_sequence = sequence[start_index : end_index + 1]
    mid_index = start_index + ((end_index - start_index) // 2)
    return replace(
        clip,
        meta=VideoMeta(width=clip.width, height=clip.height, duration=duration),
        start=sequence[start_index],
        mid=sequence[mid_index],
        end=sequence[end_index],
        sequence=segment_sequence,
        sequence_times=tuple(time - start for time in times[start_index : end_index + 1]),
        source_start=clip.source_start + start,
    )


def select_smart_sequences(
    clips: list[Clip],
    threshold: float,
    max_known_ratio: float,
    min_segment_duration: float = 2.0,
) -> list[Clip]:
    """Keep whole clips when mostly fresh and salvage novel segments from repeated clips."""
    selected: list[Clip] = []
    known_frames: list[np.ndarray] = []
    for clip in clips:
        sequence = clip.sequence or (clip.start, clip.mid, clip.end)
        flags = known_frame_flags(sequence, known_frames, threshold)
        ratio = sum(flags) / len(flags) if flags else 0.0
        if ratio <= max_known_ratio:
            selected_clip = replace(clip, known_frame_ratio=ratio)
            selected.append(selected_clip)
            known_frames.extend(selected_clip.sequence or (selected_clip.start, selected_clip.mid, selected_clip.end))
            continue

        for start_index, end_index in novel_ranges(flags):
            selected_clip = replace(
                clip_segment(clip, start_index, end_index),
                known_frame_ratio=ratio,
            )
            if selected_clip.duration < min_segment_duration:
                continue
            selected.append(selected_clip)
            known_frames.extend(selected_clip.sequence)
    return selected


def order_clips(clips: list[Clip], mode: str) -> list[Clip]:
    """Order clips by filename, duration, or greedy visual continuity."""
    if mode == "name":
        return sorted(clips, key=lambda clip: clip.path.name)
    if mode == "duration":
        return sorted(clips, key=lambda clip: (-clip.duration, clip.path.name))
    if not clips:
        return []

    unused = clips[:]
    current = min(unused, key=lambda clip: (clip.brightness, -clip.duration))
    ordered = [current]
    unused.remove(current)
    while unused:
        current = min(
            unused,
            key=lambda clip: (
                1 - correlation(ordered[-1].end, clip.start),
                abs(ordered[-1].brightness - clip.brightness),
            ),
        )
        ordered.append(current)
        unused.remove(current)
    return ordered


def apply_duration_limit(clips: list[Clip], max_duration: float | None) -> list[Clip]:
    """Keep whole clips while staying as close as possible to the duration limit."""
    if not max_duration:
        return clips

    total = 0.0
    selected = []
    for clip in clips:
        if selected and total + clip.duration > max_duration:
            continue
        selected.append(clip)
        total += clip.duration
        if total >= max_duration:
            break
    return selected
