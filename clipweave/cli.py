from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import BuildOptions
from .pipeline import build_video


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble a coherent montage from a folder of clips.")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--orientation", choices=["vertical", "horizontal", "any"], default="vertical")
    parser.add_argument("--audio", choices=["keep", "remove"], default="remove")
    parser.add_argument("--max-duration", type=float, default=None, help="Maximum output duration in seconds.")
    parser.add_argument("--output", type=Path, default=None, help="Default: <input_dir>/clipweave_<orientation>.mp4")
    parser.add_argument("--work-dir", type=Path, default=None, help="Default: temporary directory, deleted after build.")
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("--transition", choices=["fade", "cut"], default="fade")
    parser.add_argument("--min-fade", type=float, default=0.08)
    parser.add_argument("--max-fade", type=float, default=0.45)
    parser.add_argument("--duplicate-threshold", type=float, default=0.965)
    parser.add_argument("--aspect-tolerance", type=float, default=0.04)
    parser.add_argument("--order", choices=["visual", "name", "duration"], default="visual")
    parser.add_argument("--crf", type=int, default=16)
    parser.add_argument("--preset", default="slow")
    return parser.parse_args()


def options_from_args(args: argparse.Namespace) -> BuildOptions:
    return BuildOptions(
        input_dir=args.input_dir,
        output=args.output,
        orientation=args.orientation,
        audio=args.audio,
        max_duration=args.max_duration,
        work_dir=args.work_dir,
        keep_work=args.keep_work,
        transition=args.transition,
        min_fade=args.min_fade,
        max_fade=args.max_fade,
        duplicate_threshold=args.duplicate_threshold,
        aspect_tolerance=args.aspect_tolerance,
        order=args.order,
        crf=args.crf,
        preset=args.preset,
    )


def main() -> None:
    manifest = build_video(options_from_args(parse_args()))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
