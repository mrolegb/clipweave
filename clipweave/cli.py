from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import BuildOptions
from .pipeline import build_video


def parse_args() -> argparse.Namespace:
    """Parse CLI flags into argparse's raw namespace."""
    parser = argparse.ArgumentParser(description="Assemble a coherent montage from a folder of clips.")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--orientation", choices=["vertical", "horizontal", "any"], default="vertical")
    parser.add_argument("--media", choices=["videos", "images", "mixed"], default="videos")
    parser.add_argument("--audio", choices=["keep", "remove"], default="remove")
    parser.add_argument("--image-duration", type=float, default=3.0, help="Seconds per image in image slideshow mode.")
    parser.add_argument("--max-duration", type=float, default=None, help="Maximum output duration in seconds.")
    parser.add_argument("--target", type=Path, default=None, help="Reference image/video used to reject off-theme media.")
    parser.add_argument("--target-threshold", type=float, default=0.35, help="Minimum visual similarity to --target.")
    parser.add_argument("--output", type=Path, default=None, help="Default: <input_dir>/clipweave_<media>_<orientation>.mp4")
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
    parser.add_argument("--smart-editing", action="store_true", help="Trim or drop clips whose sampled sequence is mostly already covered.")
    parser.add_argument("--smart-sample-rate", type=float, default=1.0, help="Frames per second to sample for smart editing.")
    parser.add_argument("--smart-threshold", type=float, default=0.94, help="Frame similarity threshold for smart editing.")
    parser.add_argument(
        "--smart-max-known-ratio",
        type=float,
        default=0.55,
        help="Trim a clip when more than this share of sampled frames is already known.",
    )
    parser.add_argument(
        "--smart-min-segment-duration",
        type=float,
        default=2.0,
        help="Minimum salvaged segment length when smart editing trims repeated clips.",
    )
    parser.add_argument(
        "--no-smart-reorder-segments",
        action="store_false",
        dest="smart_reorder_segments",
        help="Keep smart-edited segments in their original clip order instead of reordering them visually.",
    )
    parser.add_argument(
        "--no-smart-dedupe-segments",
        action="store_false",
        dest="smart_dedupe_segments",
        help="Skip the post-trim visual duplicate pass over smart-edited segments.",
    )
    return parser.parse_args()


def options_from_args(args: argparse.Namespace) -> BuildOptions:
    """Convert parsed CLI arguments into the typed pipeline configuration."""
    return BuildOptions(
        input_dir=args.input_dir,
        output=args.output,
        orientation=args.orientation,
        media=args.media,
        audio=args.audio,
        image_duration=args.image_duration,
        max_duration=args.max_duration,
        target=args.target,
        target_threshold=args.target_threshold,
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
        smart_editing=args.smart_editing,
        smart_sample_rate=args.smart_sample_rate,
        smart_threshold=args.smart_threshold,
        smart_max_known_ratio=args.smart_max_known_ratio,
        smart_min_segment_duration=args.smart_min_segment_duration,
        smart_reorder_segments=args.smart_reorder_segments,
        smart_dedupe_segments=args.smart_dedupe_segments,
    )


def main() -> None:
    """CLI entrypoint: build the video and print the manifest."""
    manifest = build_video(options_from_args(parse_args()))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
