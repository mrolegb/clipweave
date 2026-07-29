from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildOptions:
    input_dir: Path
    output: Path | None
    orientation: str = "vertical"
    audio: str = "remove"
    max_duration: float | None = None
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
        return self.input_dir.resolve()

    @property
    def output_path(self) -> Path:
        return self.output or (self.resolved_input_dir / f"clipweave_{self.orientation}.mp4")

    @property
    def keep_audio(self) -> bool:
        return self.audio == "keep"

    @property
    def use_fades(self) -> bool:
        return self.transition == "fade" and not self.keep_audio
