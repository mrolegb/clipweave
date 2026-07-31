from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import OUTPUT_PREFIX


def prefixed_output_path(path: Path) -> Path:
    """Return an output path whose filename uses Clipweave's fixed generated-file prefix."""
    if path.name.startswith(OUTPUT_PREFIX):
        return path
    return path.with_name(f"{OUTPUT_PREFIX}{path.name}")


@dataclass(frozen=True)
class BuildOptions:
    """Typed configuration for one Clipweave render run."""

    input_dir: Path
    output: Path | None
    orientation: str = "vertical"
    media: str = "videos"
    audio: str = "remove"
    image_duration: float = 3.0
    max_duration: float | None = None
    target: Path | None = None
    target_threshold: float = 0.35
    work_dir: Path | None = None
    keep_work: bool = False
    transition: str = "fade"
    min_fade: float = 0.08
    max_fade: float = 0.45
    duplicate_threshold: float = 0.965
    aspect_tolerance: float = 0.04
    order: str = "visual"
    structure: str = "smooth"
    clothing_priority: str = "none"
    split_aspects: bool = False
    auto_grade: bool = False
    crf: int = 16
    preset: str = "slow"
    save_manifest: bool = False
    save_contact_sheet: bool = False
    smart_editing: bool = False
    smart_sample_rate: float = 1.0
    smart_threshold: float = 0.94
    smart_max_known_ratio: float = 0.55
    smart_min_segment_duration: float = 2.0
    smart_scene_threshold: float = 0.55
    smart_reorder_segments: bool = True
    smart_dedupe_segments: bool = True

    @property
    def resolved_input_dir(self) -> Path:
        """Absolute input directory used in manifests and file discovery."""
        return self.input_dir.resolve()

    @property
    def output_path(self) -> Path:
        """Explicit output path, or the default output inside the input folder."""
        return prefixed_output_path(self.output) if self.output else self.resolved_input_dir / f"{OUTPUT_PREFIX}{self.media}_{self.orientation}.mp4"

    @property
    def keep_audio(self) -> bool:
        """Whether normalized video clips should preserve audio."""
        return self.audio == "keep"

    @property
    def use_fades(self) -> bool:
        """Fade transitions are enabled only for silent output."""
        return self.transition == "fade" and not self.keep_audio
