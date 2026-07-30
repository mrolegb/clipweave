from __future__ import annotations

import shutil
from pathlib import Path

from .media import run
from .models import Clip, Transition
from .selection import transition_similarity


def grade_filter(brightness: float, auto_grade: bool) -> str:
    """Build a conservative FFmpeg eq filter for rough brightness normalization."""
    if not auto_grade:
        return ""
    brightness_adjust = max(-0.18, min(0.18, ((128.0 - brightness) / 255.0) * 0.45))
    if brightness < 110:
        contrast = 1.06
    elif brightness > 155:
        contrast = 0.98
    else:
        contrast = 1.02
    return f",eq=brightness={brightness_adjust:.4f}:contrast={contrast:.3f}:saturation=1.040"


def fade_duration(prev: Clip, nxt: Clip, min_fade: float, max_fade: float) -> float:
    """Choose a shorter fade when adjacent frames are already visually similar."""
    similarity = transition_similarity(prev, nxt)
    if similarity >= 0.90:
        return min_fade
    if similarity >= 0.82:
        return max(min_fade, min(0.15, max_fade))
    if similarity >= 0.72:
        return max(min_fade, min(0.25, max_fade))
    return max_fade


def normalize_clip(
    src: Path,
    dst: Path,
    dimensions: tuple[int, int],
    keep_audio: bool,
    crf: int,
    preset: str,
    start: float = 0.0,
    duration: float | None = None,
    auto_grade: bool = False,
    brightness: float = 128.0,
) -> None:
    """Transcode a video clip into the common output size and codec settings."""
    width, height = dimensions
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
    ]
    if start > 0:
        command += ["-ss", f"{start:.3f}"]
    command += [
        "-i",
        str(src),
    ]
    if duration is not None:
        command += ["-t", f"{duration:.3f}"]
    command += [
        "-vf",
        f"scale={width}:{height}:flags=lanczos:in_range=auto:out_range=tv,setsar=1,fps=30{grade_filter(brightness, auto_grade)},format=yuv420p",
    ]
    if keep_audio:
        command += ["-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-an"]
    command += [
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
    run(command)


def normalize_image(
    src: Path,
    dst: Path,
    dimensions: tuple[int, int],
    duration: float,
    crf: int,
    preset: str,
    auto_grade: bool = False,
    brightness: float = 128.0,
) -> None:
    """Convert a still image into a fixed-duration video segment."""
    width, height = dimensions
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(src),
            "-vf",
            f"scale={width}:{height}:flags=lanczos:in_range=auto:out_range=tv,setsar=1,fps=30{grade_filter(brightness, auto_grade)},format=yuv420p",
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
            str(dst),
        ]
    )


def normalize_source(
    clip: Clip,
    dst: Path,
    dimensions: tuple[int, int],
    keep_audio: bool,
    crf: int,
    preset: str,
    auto_grade: bool = False,
) -> None:
    """Normalize either a video clip or an image clip into a temporary MP4."""
    if clip.media_type == "image":
        normalize_image(clip.path, dst, dimensions, clip.duration, crf, preset, auto_grade, clip.brightness)
        return
    normalize_clip(clip.path, dst, dimensions, keep_audio, crf, preset, clip.source_start, clip.duration, auto_grade, clip.brightness)


def concat_plain(clips: list[Path], output: Path, concat_file: Path) -> None:
    """Join normalized clips with hard cuts using FFmpeg concat demuxer."""
    concat_file.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8")
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(output),
        ]
    )


def concat_xfade(
    normalized_files: list[Path],
    clips: list[Clip],
    output: Path,
    min_fade: float,
    max_fade: float,
    crf: int,
    preset: str,
) -> list[Transition]:
    """Join normalized clips with visual fade transitions and return manifest data."""
    if len(normalized_files) == 1:
        shutil.copy2(normalized_files[0], output)
        return []

    inputs = []
    for path in normalized_files:
        inputs += ["-i", str(path)]

    filters = []
    label = "[0:v]"
    cumulative = clips[0].duration
    transitions: list[Transition] = []
    for index in range(1, len(normalized_files)):
        duration = min(
            fade_duration(clips[index - 1], clips[index], min_fade, max_fade),
            max(0.04, clips[index - 1].duration / 5),
            max(0.04, clips[index].duration / 5),
        )
        offset = max(0.0, cumulative - duration)
        next_label = f"[v{index}]"
        filters.append(
            f"{label}[{index}:v]xfade=transition=fade:"
            f"duration={duration:.3f}:offset={offset:.3f}{next_label}"
        )
        similarity = transition_similarity(clips[index - 1], clips[index])
        transitions.append(
            Transition(
                source=clips[index - 1].path.name,
                target=clips[index].path.name,
                similarity=similarity,
                fade_seconds=duration,
            )
        )
        cumulative += clips[index].duration - duration
        label = next_label

    filters.append(f"{label}format=yuv420p[vout]")
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
            "[vout]",
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
