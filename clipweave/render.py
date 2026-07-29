from __future__ import annotations

import shutil
from pathlib import Path

from .analysis import correlation
from .media import run
from .models import Clip, Transition


def fade_duration(prev: Clip, nxt: Clip, min_fade: float, max_fade: float) -> float:
    similarity = correlation(prev.end, nxt.start)
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
) -> None:
    width, height = dimensions
    command = [
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


def concat_plain(clips: list[Path], output: Path, concat_file: Path) -> None:
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
        similarity = correlation(clips[index - 1].end, clips[index].start)
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
