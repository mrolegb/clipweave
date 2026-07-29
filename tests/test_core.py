from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from clipweave.cli import options_from_args
from clipweave.config import BuildOptions
from clipweave.models import Clip, Transition, VideoMeta
from clipweave.pipeline import build_manifest, discover_clips, read_target
from clipweave.render import fade_duration
from clipweave.selection import (
    apply_duration_limit,
    choose_dimensions,
    filter_by_target,
    is_extension_duplicate,
    order_clips,
    orientation_ok,
    select_unique,
    target_similarity,
)


def vector(values: list[float]) -> np.ndarray:
    """Build a normalized test vector."""
    array = np.array(values, dtype="float32")
    return array / np.linalg.norm(array)


V1 = vector([1, 0, 0])
V2 = vector([0, 1, 0])
V3 = vector([0, 0, 1])
VMIX = vector([0.9, 0.1, 0])
VFADE = vector([0.85, 0.52, 0])


def clip(
    name: str,
    *,
    width: int = 1080,
    height: int = 1920,
    duration: float = 10.0,
    file_hash: str | None = None,
    start: np.ndarray = V1,
    mid: np.ndarray = V1,
    end: np.ndarray = V1,
    brightness: float = 100.0,
    media_type: str = "video",
) -> Clip:
    """Create a small Clip fixture without reading media files."""
    return Clip(
        path=Path(name),
        meta=VideoMeta(width=width, height=height, duration=duration),
        file_hash=file_hash or name,
        start=start,
        mid=mid,
        end=end,
        brightness=brightness,
        media_type=media_type,
    )


class ConfigTests(unittest.TestCase):
    def test_default_output_path_and_audio_flags(self) -> None:
        """BuildOptions derives output path and fade/audio behavior."""
        options = BuildOptions(input_dir=Path("."), output=None)

        self.assertTrue(str(options.output_path).endswith("clipweave_videos_vertical.mp4"))
        self.assertFalse(options.keep_audio)
        self.assertTrue(options.use_fades)

        with_audio = BuildOptions(input_dir=Path("."), output=None, audio="keep")
        self.assertTrue(with_audio.keep_audio)
        self.assertFalse(with_audio.use_fades)

    def test_options_from_args_maps_all_public_flags(self) -> None:
        """CLI namespace values are carried into BuildOptions."""
        args = Namespace(
            input_dir=Path("in"),
            output=Path("out.mp4"),
            orientation="horizontal",
            media="mixed",
            audio="keep",
            image_duration=2.5,
            max_duration=30.0,
            target=Path("target.jpg"),
            target_threshold=0.5,
            work_dir=Path("work"),
            keep_work=True,
            transition="cut",
            min_fade=0.1,
            max_fade=0.4,
            duplicate_threshold=0.9,
            aspect_tolerance=0.02,
            order="name",
            crf=18,
            preset="medium",
        )

        options = options_from_args(args)

        self.assertEqual(options.orientation, "horizontal")
        self.assertEqual(options.media, "mixed")
        self.assertEqual(options.audio, "keep")
        self.assertEqual(options.image_duration, 2.5)
        self.assertEqual(options.target_threshold, 0.5)
        self.assertEqual(options.crf, 18)
        self.assertEqual(options.preset, "medium")


class SelectionTests(unittest.TestCase):
    def test_orientation_filter(self) -> None:
        """Orientation matching accepts vertical, horizontal, or any."""
        vertical = clip("v.mp4", width=720, height=1280)
        horizontal = clip("h.mp4", width=1280, height=720)

        self.assertTrue(orientation_ok(vertical, "vertical"))
        self.assertFalse(orientation_ok(horizontal, "vertical"))
        self.assertTrue(orientation_ok(horizontal, "horizontal"))
        self.assertTrue(orientation_ok(vertical, "any"))

    def test_choose_dimensions_prefers_common_exact_size(self) -> None:
        """Three exact matches win over aspect-ratio grouping."""
        clips = [
            clip("a.mp4", width=1080, height=1920),
            clip("b.mp4", width=1080, height=1920),
            clip("c.mp4", width=1080, height=1920),
            clip("d.mp4", width=720, height=1280),
        ]

        self.assertEqual(choose_dimensions(clips, 0.04), (1080, 1920))

    def test_choose_dimensions_falls_back_to_common_aspect_ratio(self) -> None:
        """When no exact size dominates, aspect ratio chooses the target pool."""
        clips = [
            clip("a.mp4", width=1080, height=1920),
            clip("b.mp4", width=720, height=1280),
            clip("c.mp4", width=1280, height=720),
        ]

        self.assertEqual(choose_dimensions(clips, 0.04), (1080, 1920))

    def test_select_unique_removes_hash_and_visual_duplicates(self) -> None:
        """Dedupe keeps longer clips and skips near-identical middles."""
        clips = [
            clip("short.mp4", duration=5, file_hash="same", mid=V1),
            clip("long.mp4", duration=15, file_hash="same", mid=V1),
            clip("visual-copy.mp4", duration=4, file_hash="other", mid=V1),
            clip("different.mp4", duration=3, file_hash="third", mid=V2),
        ]

        names = [item.path.name for item in select_unique(clips, 0.95)]

        self.assertEqual(names, ["long.mp4", "different.mp4"])

    def test_extension_duplicate_prefers_long_grok_style_clip(self) -> None:
        """Short repeats are treated as duplicates of long extension clips."""
        short = clip("short.mp4", duration=20, start=V1, mid=V2, end=V3)
        long = clip("long.mp4", duration=30, start=V1, mid=V2, end=V3)

        self.assertTrue(is_extension_duplicate(short, long, 0.95))
        self.assertFalse(is_extension_duplicate(long, short, 0.95))

    def test_target_filtering_and_score(self) -> None:
        """Target filtering keeps visually related clips only."""
        target = clip("target.jpg", start=V1, mid=V1, end=V1, media_type="image")
        related = clip("related.mp4", start=V2, mid=VMIX, end=V3)
        unrelated = clip("unrelated.mp4", start=V2, mid=V2, end=V3)

        self.assertGreater(target_similarity(related, target), 0.9)
        self.assertEqual(filter_by_target([related, unrelated], target, 0.9), [related])
        self.assertEqual(filter_by_target([related], None, 0.9), [related])

    def test_order_modes(self) -> None:
        """Order mode supports deterministic filename, duration, and visual ordering."""
        a = clip("b.mp4", duration=1, brightness=20, end=V2)
        b = clip("a.mp4", duration=3, brightness=10, start=V2, end=V3)
        c = clip("c.mp4", duration=2, brightness=30, start=V3)

        self.assertEqual([item.path.name for item in order_clips([a, b, c], "name")], ["a.mp4", "b.mp4", "c.mp4"])
        self.assertEqual([item.path.name for item in order_clips([a, b, c], "duration")], ["a.mp4", "c.mp4", "b.mp4"])
        self.assertEqual([item.path.name for item in order_clips([a, b, c], "visual")], ["a.mp4", "c.mp4", "b.mp4"])

    def test_duration_limit_keeps_whole_clips(self) -> None:
        """Duration limits skip clips that would exceed the cap after the first."""
        clips = [clip("a.mp4", duration=7), clip("b.mp4", duration=5), clip("c.mp4", duration=3)]

        self.assertEqual([item.path.name for item in apply_duration_limit(clips, 10)], ["a.mp4", "c.mp4"])
        self.assertEqual(apply_duration_limit(clips, None), clips)


class RenderTests(unittest.TestCase):
    def test_fade_duration_shortens_similar_boundaries(self) -> None:
        """Fade length follows visual similarity thresholds."""
        prev = clip("prev.mp4", end=V1)

        self.assertEqual(fade_duration(prev, clip("same.mp4", start=V1), 0.08, 0.45), 0.08)
        self.assertEqual(fade_duration(prev, clip("mixed.mp4", start=VFADE), 0.08, 0.45), 0.15)
        self.assertEqual(fade_duration(prev, clip("different.mp4", start=V2), 0.08, 0.45), 0.45)


class PipelineTests(unittest.TestCase):
    def test_discover_clips_skips_outputs_and_filters_by_media(self) -> None:
        """Discovery ignores generated outputs and only reads enabled media types."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "a.mp4"
            image_path = root / "b.jpg"
            output_path = root / "clipweave_videos_vertical.mp4"
            video_path.write_text("video", encoding="utf-8")
            image_path.write_text("image", encoding="utf-8")
            output_path.write_text("output", encoding="utf-8")

            with (
                patch("clipweave.pipeline.read_clip", return_value=clip("a.mp4")),
                patch("clipweave.pipeline.read_image_clip", return_value=clip("b.jpg", media_type="image")),
            ):
                clips = discover_clips(root, BuildOptions(input_dir=root, output=None, media="mixed"))

        self.assertEqual([item.path.name for item in clips], ["a.mp4", "b.jpg"])

    def test_read_target_rejects_unknown_extension(self) -> None:
        """Unsupported target file types fail before selection."""
        options = BuildOptions(input_dir=Path("."), output=None, target=Path("target.txt"))

        with self.assertRaisesRegex(RuntimeError, "Unsupported target file type"):
            read_target(options)

    def test_build_manifest_serializes_selection(self) -> None:
        """Manifest includes options, counts, clips, and transition records."""
        options = BuildOptions(input_dir=Path("."), output=Path("out.mp4"), target=Path("target.jpg"))
        selected = [clip("a.mp4", duration=1.2345)]
        target = clip("target.jpg", media_type="image")
        transition = Transition("a.mp4", "b.mp4", 0.98765, 0.12345)

        manifest = build_manifest(
            options,
            selected,
            (1080, 1920),
            {"after_size_filter": 2, "after_orientation": 3, "after_target_filter": 2},
            [transition],
            target,
        )

        self.assertEqual(manifest["output"], "out.mp4")
        self.assertEqual(manifest["dimensions"], {"width": 1080, "height": 1920})
        self.assertEqual(manifest["selected_clips"][0]["duration"], 1.234)
        self.assertEqual(manifest["selected_clips"][0]["target_similarity"], 1.0)
        self.assertEqual(manifest["transitions"][0]["fade_seconds"], 0.123)


if __name__ == "__main__":
    unittest.main()
