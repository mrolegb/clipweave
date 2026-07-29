from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
    crf: int = 16
    preset: str = "slow"

    @property
    def resolved_input_dir(self) -> Path:
        """Absolute input directory used in manifests and file discovery."""
        return self.input_dir.resolve()

    @property
    def output_path(self) -> Path:
        """Explicit output path, or the default output inside the input folder."""
        return self.output or (self.resolved_input_dir / f"clipweave_{self.media}_{self.orientation}.mp4")

    @property
    def keep_audio(self) -> bool:
        """Whether normalized video clips should preserve audio."""
        return self.audio == "keep"

    @property
    def use_fades(self) -> bool:
        """Fade transitions are enabled only for silent output."""
        return self.transition == "fade" and not self.keep_audio
