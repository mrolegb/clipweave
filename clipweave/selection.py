from __future__ import annotations

from collections import Counter
from dataclasses import replace

import numpy as np

from .analysis import correlation
from .models import Clip, VideoMeta


def transition_similarity(previous: Clip, candidate: Clip) -> float:
    """Score visual continuity using both boundary frames and short frame sequences."""
    previous_tail = (previous.sequence or (previous.start, previous.mid, previous.end))[-3:]
    candidate_head = (candidate.sequence or (candidate.start, candidate.mid, candidate.end))[:3]
    pairs = zip(previous_tail, candidate_head)
    sequence_scores = [correlation(left, right) for left, right in pairs]
    sequence_score = sum(sequence_scores) / len(sequence_scores) if sequence_scores else correlation(previous.end, candidate.start)
    boundary_score = correlation(previous.end, candidate.start)
    return (boundary_score * 0.55) + (sequence_score * 0.45)


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


def scene_ranges(sequence: tuple[np.ndarray, ...], threshold: float) -> list[tuple[int, int]]:
    """Split sampled frames into rough scene ranges using adjacent-frame similarity."""
    if not sequence:
        return []
    ranges: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(sequence)):
        if correlation(sequence[index - 1], sequence[index]) < threshold:
            ranges.append((start, index - 1))
            start = index
    ranges.append((start, len(sequence) - 1))
    return ranges


def range_known_ratio(flags: list[bool], start: int, end: int) -> float:
    """Return the known-frame ratio inside an inclusive sampled-frame range."""
    chunk = flags[start : end + 1]
    return sum(chunk) / len(chunk) if chunk else 0.0


def smart_segment_ranges(
    sequence: tuple[np.ndarray, ...],
    flags: list[bool],
    max_known_ratio: float,
    scene_threshold: float,
) -> list[tuple[int, int]]:
    """Choose scene-aware ranges that are fresh enough to keep."""
    ranges = [
        (start, end)
        for start, end in scene_ranges(sequence, scene_threshold)
        if range_known_ratio(flags, start, end) <= max_known_ratio
    ]
    if ranges:
        return ranges
    if range_known_ratio(flags, 0, len(flags) - 1) <= max_known_ratio:
        return [(0, len(flags) - 1)]
    return novel_ranges(flags)


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
    segment_motion = 0.0
    if len(segment_sequence) > 1:
        changes = [
            max(0.0, 1.0 - correlation(segment_sequence[index - 1], segment_sequence[index]))
            for index in range(1, len(segment_sequence))
        ]
        segment_motion = float(sum(changes) / len(changes))
    return replace(
        clip,
        meta=VideoMeta(width=clip.width, height=clip.height, duration=duration),
        start=sequence[start_index],
        mid=sequence[mid_index],
        end=sequence[end_index],
        motion_score=segment_motion,
        sequence=segment_sequence,
        sequence_times=tuple(time - start for time in times[start_index : end_index + 1]),
        source_start=clip.source_start + start,
    )


def select_smart_sequences(
    clips: list[Clip],
    threshold: float,
    max_known_ratio: float,
    min_segment_duration: float = 2.0,
    scene_threshold: float = 0.55,
) -> list[Clip]:
    """Split clips into scene-aware ranges, then keep ranges that are still visually fresh."""
    selected: list[Clip] = []
    known_frames: list[np.ndarray] = []
    for clip in clips:
        sequence = clip.sequence or (clip.start, clip.mid, clip.end)
        flags = known_frame_flags(sequence, known_frames, threshold)
        ratio = sum(flags) / len(flags) if flags else 0.0
        for start_index, end_index in smart_segment_ranges(sequence, flags, max_known_ratio, scene_threshold):
            selected_clip = replace(
                clip_segment(clip, start_index, end_index),
                known_frame_ratio=ratio,
            )
            if selected_clip.duration < min_segment_duration:
                continue
            selected.append(selected_clip)
            known_frames.extend(selected_clip.sequence)
    return selected


def select_unique_segments(
    clips: list[Clip],
    threshold: float,
    max_known_ratio: float,
) -> list[Clip]:
    """Remove duplicated trimmed segments without collapsing segments from the same file."""
    selected: list[Clip] = []
    known_frames: list[np.ndarray] = []
    for clip in clips:
        ratio = known_frame_ratio(clip, known_frames, threshold)
        if ratio <= max_known_ratio:
            selected_clip = replace(clip, known_frame_ratio=ratio)
            selected.append(selected_clip)
            known_frames.extend(selected_clip.sequence or (selected_clip.start, selected_clip.mid, selected_clip.end))
    return selected


def prioritize_by_clothing(clips: list[Clip], priority: str) -> list[Clip]:
    """Move clips with lower or higher estimated clothing coverage earlier."""
    if priority == "less":
        return sorted(clips, key=lambda clip: (-clip.skin_exposure_score, clip.path.name, clip.source_start))
    if priority == "more":
        return sorted(clips, key=lambda clip: (clip.skin_exposure_score, clip.path.name, clip.source_start))
    return clips


def group_motion(group: list[Clip]) -> float:
    """Return average motion score for a chronological source group."""
    return sum(clip.motion_score for clip in group) / len(group) if group else 0.0


def visual_group_key(previous: Clip, group: list[Clip], structure: str, position: float, max_motion: float) -> tuple[float, float, float]:
    """Score the next visual group while honoring the requested pacing structure."""
    similarity = transition_similarity(previous, group[0])
    motion_delta = abs(previous.motion_score - group_motion(group))
    brightness_delta = abs(previous.brightness - group[0].brightness) / 255.0
    if structure == "variety":
        return (abs(similarity - 0.58), -motion_delta, -brightness_delta)
    if structure == "arc":
        target_motion = max_motion * float(np.sin(np.pi * position))
        return (1 - similarity, abs(group_motion(group) - target_motion), brightness_delta)
    return (1 - similarity, motion_delta, brightness_delta)


def order_clips(clips: list[Clip], mode: str, structure: str = "smooth") -> list[Clip]:
    """Order clips by filename, duration, or greedy visual continuity with pacing."""
    if mode == "name":
        return sorted(clips, key=lambda clip: (clip.path.name, clip.source_start))
    if mode == "duration":
        return sorted(clips, key=lambda clip: (-clip.duration, clip.path.name, clip.source_start))
    if not clips:
        return []

    grouped: dict[str, list[Clip]] = {}
    for clip in clips:
        grouped.setdefault(str(clip.path), []).append(clip)
    groups = [sorted(group, key=lambda clip: clip.source_start) for group in grouped.values()]

    unused = groups[:]
    current_group = min(unused, key=lambda group: (min(clip.brightness for clip in group), -sum(clip.duration for clip in group)))
    ordered_groups = [current_group]
    unused.remove(current_group)
    while unused:
        previous = ordered_groups[-1][-1]
        position = len(ordered_groups) / max(1, len(groups) - 1)
        max_motion = max(group_motion(group) for group in groups)
        current_group = min(
            unused,
            key=lambda group: visual_group_key(previous, group, structure, position, max_motion),
        )
        ordered_groups.append(current_group)
        unused.remove(current_group)
    return [clip for group in ordered_groups for clip in group]


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
