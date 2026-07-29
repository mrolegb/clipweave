from __future__ import annotations

from collections import Counter

from .analysis import correlation
from .models import Clip


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
        by_hash.setdefault(clip.file_hash, clip)

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
