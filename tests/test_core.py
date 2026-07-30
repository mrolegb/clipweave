from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from clipweave.analysis import motion_score
from clipweave.cli import options_from_args
from clipweave.config import BuildOptions
from clipweave.contact_sheet import LABEL_HEIGHT, PADDING, THUMB_HEIGHT, THUMB_WIDTH, fit_thumbnail, save_contact_sheet
from clipweave.models import Clip, Transition, VideoMeta
from clipweave.pipeline import build_manifest, build_video, discover_clips, order_and_smart_edit, read_target, render_video
from clipweave.render import fade_duration, grade_filter, normalize_clip, normalize_image
from clipweave.selection import (
    apply_duration_limit,
    choose_dimensions,
    filter_by_target,
    is_extension_duplicate,
    known_frame_ratio,
    order_clips,
    orientation_ok,
    select_unique,
    select_unique_segments,
    select_smart_sequences,
    target_similarity,
    transition_similarity,
)


def vector(values: list[float]) -> np.ndarray:
    """Build a normalized test vector."""
    array = np.array(values, dtype="float32")
    return array / np.linalg.norm(array)


V1 = vector([1, 0, 0])
V2 = vector([0, 1, 0])
V3 = vector([0, 0, 1])
V4 = vector([0.5, 0.5, 0.707])
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
    motion_score: float = 0.0,
    media_type: str = "video",
    sequence: tuple[np.ndarray, ...] | None = None,
    sequence_times: tuple[float, ...] | None = None,
    source_start: float = 0.0,
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
        motion_score=motion_score,
        media_type=media_type,
        sequence=sequence or (start, mid, end),
        sequence_times=sequence_times or (0.0, duration / 2, duration),
        source_start=source_start,
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

    def test_explicit_output_path_gets_fixed_prefix(self) -> None:
        """Generated output filenames always use the fixed Clipweave prefix."""
        options = BuildOptions(input_dir=Path("."), output=Path("out.mp4"))
        already_prefixed = BuildOptions(input_dir=Path("."), output=Path("clipweave_out.mp4"))

        self.assertEqual(options.output_path.name, "clipweave_out.mp4")
        self.assertEqual(already_prefixed.output_path.name, "clipweave_out.mp4")

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
            structure="arc",
            auto_grade=True,
            crf=18,
            preset="medium",
            save_manifest=True,
            save_contact_sheet=True,
            smart_editing=True,
            smart_sample_rate=2.0,
            smart_threshold=0.93,
            smart_max_known_ratio=0.4,
            smart_min_segment_duration=3.0,
            smart_scene_threshold=0.6,
            smart_reorder_segments=False,
            smart_dedupe_segments=False,
        )

        options = options_from_args(args)

        self.assertEqual(options.orientation, "horizontal")
        self.assertEqual(options.media, "mixed")
        self.assertEqual(options.audio, "keep")
        self.assertEqual(options.image_duration, 2.5)
        self.assertEqual(options.target_threshold, 0.5)
        self.assertEqual(options.structure, "arc")
        self.assertTrue(options.auto_grade)
        self.assertEqual(options.crf, 18)
        self.assertEqual(options.preset, "medium")
        self.assertTrue(options.save_manifest)
        self.assertTrue(options.save_contact_sheet)
        self.assertTrue(options.smart_editing)
        self.assertEqual(options.smart_sample_rate, 2.0)
        self.assertEqual(options.smart_threshold, 0.93)
        self.assertEqual(options.smart_max_known_ratio, 0.4)
        self.assertEqual(options.smart_min_segment_duration, 3.0)
        self.assertEqual(options.smart_scene_threshold, 0.6)
        self.assertFalse(options.smart_reorder_segments)
        self.assertFalse(options.smart_dedupe_segments)


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

    def test_visual_order_keeps_same_source_segments_chronological(self) -> None:
        """Visual ordering treats trimmed segments from one source as a chronological run."""
        later = clip("source.mp4", start=V3, end=V2, source_start=5.0, sequence=(V3, V2))
        earlier = clip("source.mp4", start=V2, end=V1, source_start=1.0, sequence=(V2, V1))
        bridge = clip("bridge.mp4", start=V1, end=V3, source_start=0.0, sequence=(V1, V3))

        ordered = order_clips([later, bridge, earlier], "visual")

        self.assertEqual(
            [(item.path.name, item.source_start) for item in ordered],
            [("source.mp4", 1.0), ("source.mp4", 5.0), ("bridge.mp4", 0.0)],
        )

    def test_motion_score_tracks_sampled_frame_change(self) -> None:
        """Motion score increases when adjacent sampled frames are less alike."""
        still = motion_score((V1, V1, V1))
        changing = motion_score((V1, V2, V3))

        self.assertEqual(still, 0.0)
        self.assertGreater(changing, still)

    def test_visual_structure_can_prefer_variety(self) -> None:
        """Variety structure favors a stronger motion change when similarity is close."""
        start = clip("start.mp4", brightness=10, end=V1, motion_score=0.0)
        low_motion = clip("low.mp4", brightness=20, start=VFADE, motion_score=0.05)
        high_motion = clip("high.mp4", brightness=20, start=VFADE, motion_score=0.9)

        ordered = order_clips([start, low_motion, high_motion], "visual", "variety")

        self.assertEqual([item.path.name for item in ordered], ["start.mp4", "high.mp4", "low.mp4"])

    def test_visual_structure_arc_prefers_peak_motion_near_middle(self) -> None:
        """Arc structure can choose higher-motion material after the opening clip."""
        start = clip("start.mp4", brightness=10, end=V1, motion_score=0.0)
        calm = clip("calm.mp4", brightness=20, start=VFADE, motion_score=0.1)
        energetic = clip("energetic.mp4", brightness=20, start=VFADE, motion_score=0.8)

        ordered = order_clips([start, calm, energetic], "visual", "arc")

        self.assertEqual([item.path.name for item in ordered], ["start.mp4", "energetic.mp4", "calm.mp4"])

    def test_transition_similarity_uses_more_than_boundary_frames(self) -> None:
        """Visual ordering should not trust a single matching edge frame alone."""
        previous = clip("previous.mp4", end=V1, sequence=(V2, V2, V1))
        boundary_only = clip("boundary.mp4", start=V1, sequence=(V1, V3, V3))
        sequence_match = clip("sequence.mp4", start=VFADE, sequence=(VFADE, V2, V2))

        self.assertGreater(transition_similarity(previous, sequence_match), transition_similarity(previous, boundary_only))

    def test_duration_limit_keeps_whole_clips(self) -> None:
        """Duration limits skip clips that would exceed the cap after the first."""
        clips = [clip("a.mp4", duration=7), clip("b.mp4", duration=5), clip("c.mp4", duration=3)]

        self.assertEqual([item.path.name for item in apply_duration_limit(clips, 10)], ["a.mp4", "c.mp4"])
        self.assertEqual(apply_duration_limit(clips, None), clips)

    def test_smart_sequence_dedupe_drops_mostly_known_clips(self) -> None:
        """Smart editing skips clips whose sampled frames are mostly already present."""
        first = clip("first.mp4", sequence=(V1, V2, V3))
        repeated = clip("repeated.mp4", sequence=(V1, V2, VMIX))
        fresh = clip("fresh.mp4", sequence=(VFADE, VFADE, VFADE))

        self.assertEqual(known_frame_ratio(repeated, list(first.sequence), 0.94), 1.0)
        selected = select_smart_sequences([first, repeated, fresh], threshold=0.94, max_known_ratio=0.55, scene_threshold=-1.0)

        self.assertEqual([item.path.name for item in selected], ["first.mp4", "fresh.mp4"])
        self.assertEqual(selected[0].known_frame_ratio, 0.0)

    def test_smart_sequence_dedupe_salvages_novel_segments(self) -> None:
        """Smart editing can trim repeated clips down to still-new sequences."""
        first = clip("first.mp4", sequence=(V1, V2, V3))
        repeated_with_new_end = clip(
            "mixed.mp4",
            sequence=(V1, V2, V3, VFADE, VFADE),
            sequence_times=(0.0, 2.0, 4.0, 6.0, 8.0),
            duration=10.0,
        )

        selected = select_smart_sequences(
            [first, repeated_with_new_end],
            threshold=0.94,
            max_known_ratio=0.55,
            min_segment_duration=2.0,
            scene_threshold=-1.0,
        )

        self.assertEqual([item.path.name for item in selected], ["first.mp4", "mixed.mp4"])
        self.assertEqual(selected[1].source_start, 5.0)
        self.assertEqual(selected[1].duration, 4.0)
        self.assertEqual(len(selected[1].sequence), 2)
        self.assertEqual(selected[1].motion_score, 0.0)

    def test_smart_sequence_splits_fresh_clips_on_scene_changes(self) -> None:
        """Smart editing splits even fresh clips when sampled frames jump sharply."""
        fresh = clip(
            "fresh.mp4",
            sequence=(V1, V1, V2, V2),
            sequence_times=(0.0, 2.0, 4.0, 6.0),
            duration=8.0,
        )

        selected = select_smart_sequences([fresh], threshold=0.94, max_known_ratio=0.55, scene_threshold=0.5)

        self.assertEqual([item.path.name for item in selected], ["fresh.mp4", "fresh.mp4"])
        self.assertEqual(selected[0].source_start, 0.0)
        self.assertEqual(selected[1].source_start, 3.0)

    def test_smart_segments_are_reordered_after_salvage(self) -> None:
        """Smart editing can run a second visual ordering pass over salvaged segments."""
        base = clip("base.mp4", start=V1, end=V1, brightness=10, sequence=(V1, V2, V3))
        repeated = clip(
            "repeated.mp4",
            brightness=100,
            sequence=(V1, V2, V3, VFADE, VFADE),
            sequence_times=(0.0, 2.0, 4.0, 6.0, 8.0),
            duration=10.0,
        )
        fresh = clip("fresh.mp4", start=VFADE, end=V2, brightness=10, sequence=(V4, V4, V4))
        options = BuildOptions(input_dir=Path("."), output=None, smart_editing=True, smart_scene_threshold=-1.0)

        selected, counts = order_and_smart_edit([base, repeated, fresh], options)

        self.assertEqual([item.path.name for item in selected], ["base.mp4", "fresh.mp4", "repeated.mp4"])
        self.assertEqual(counts["after_smart_trim"], 3)
        self.assertEqual(counts["after_smart_dedupe"], 3)

    def test_post_trim_segment_dedupe_ignores_file_hash(self) -> None:
        """Post-trim dedupe removes visual repeats without dropping every segment from one source."""
        first = clip("same.mp4", sequence=(V1, V1, V1), duration=3.0)
        repeated = clip("same.mp4", sequence=(V1, VMIX, V1), duration=3.0)
        fresh_same_file = clip("same.mp4", sequence=(V2, V2, V2), duration=3.0)

        selected = select_unique_segments([first, repeated, fresh_same_file], threshold=0.94, max_known_ratio=0.55)

        self.assertEqual([item.sequence[0].tolist() for item in selected], [V1.tolist(), V2.tolist()])


class RenderTests(unittest.TestCase):
    def test_fade_duration_shortens_similar_boundaries(self) -> None:
        """Fade length follows visual similarity thresholds."""
        prev = clip("prev.mp4", end=V1)

        self.assertEqual(fade_duration(prev, clip("same.mp4", start=V1), 0.08, 0.45), 0.08)
        self.assertEqual(fade_duration(prev, clip("mixed.mp4", start=VFADE), 0.08, 0.45), 0.15)
        self.assertEqual(fade_duration(prev, clip("different.mp4", start=V2), 0.08, 0.45), 0.45)

    def test_grade_filter_is_opt_in(self) -> None:
        """Auto grading only adds an FFmpeg eq filter when requested."""
        self.assertEqual(grade_filter(120, False), "")
        self.assertIn("eq=brightness=", grade_filter(90, True))

    def test_normalize_clip_command_includes_trim_audio_and_grade(self) -> None:
        """Video normalization should forward trim, audio, and auto-grade settings to FFmpeg."""
        with patch("clipweave.render.run") as run:
            normalize_clip(Path("in.mp4"), Path("out.mp4"), (720, 1280), True, 18, "medium", 1.25, 2.5, True, 90)

        command = run.call_args.args[0]
        self.assertIn("-ss", command)
        self.assertIn("1.250", command)
        self.assertIn("-t", command)
        self.assertIn("2.500", command)
        self.assertIn("-c:a", command)
        self.assertTrue(any("eq=brightness=" in value for value in command))

    def test_normalize_image_command_is_silent_and_can_grade(self) -> None:
        """Image slideshow segments loop a still frame, remove audio, and support grading."""
        with patch("clipweave.render.run") as run:
            normalize_image(Path("in.jpg"), Path("out.mp4"), (720, 1280), 3.0, 18, "medium", True, 200)

        command = run.call_args.args[0]
        self.assertIn("-loop", command)
        self.assertIn("-an", command)
        self.assertTrue(any("eq=brightness=" in value for value in command))


class ContactSheetTests(unittest.TestCase):
    def test_fit_thumbnail_letterboxes_to_fixed_cell_size(self) -> None:
        """Contact-sheet thumbnails keep stable dimensions regardless of source aspect."""
        frame = np.full((40, 10, 3), 255, dtype=np.uint8)

        thumb = fit_thumbnail(frame)

        self.assertEqual(thumb.shape, (THUMB_HEIGHT, THUMB_WIDTH, 3))

    def test_save_contact_sheet_rejects_empty_selection(self) -> None:
        """A contact sheet without selected clips is a caller error."""
        with self.assertRaisesRegex(RuntimeError, "without selected clips"):
            save_contact_sheet([], Path("out.mp4"))

    def test_save_contact_sheet_writes_expected_grid(self) -> None:
        """Contact sheet rendering should write a deterministic grid image."""
        clips = [clip("a.mp4"), clip("b.mp4"), clip("c.mp4")]
        frame = np.full((40, 20, 3), 255, dtype=np.uint8)

        with (
            patch("clipweave.contact_sheet.representative_frame", return_value=frame),
            patch("clipweave.contact_sheet.cv2.imwrite", return_value=True) as imwrite,
        ):
            path = save_contact_sheet(clips, Path("out.mp4"), columns=2)

        written = imwrite.call_args.args[1]
        self.assertEqual(path, Path("out.contact.jpg"))
        self.assertEqual(written.shape[1], 2 * (THUMB_WIDTH + PADDING) + PADDING)
        self.assertEqual(written.shape[0], 2 * (THUMB_HEIGHT + LABEL_HEIGHT + PADDING) + PADDING)


class PipelineTests(unittest.TestCase):
    def test_discover_clips_skips_outputs_and_filters_by_media(self) -> None:
        """Discovery ignores generated outputs and only reads enabled media types."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "a.mp4"
            image_path = root / "b.jpg"
            output_path = root / "clipweave_videos_vertical.mp4"
            prefixed_output_path = root / "clipweave_custom.mp4"
            video_path.write_text("video", encoding="utf-8")
            image_path.write_text("image", encoding="utf-8")
            output_path.write_text("output", encoding="utf-8")
            prefixed_output_path.write_text("output", encoding="utf-8")

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

        self.assertEqual(manifest["output"], "clipweave_out.mp4")
        self.assertEqual(manifest["dimensions"], {"width": 1080, "height": 1920})
        self.assertEqual(manifest["auto_grade"], False)
        self.assertEqual(manifest["structure"], "smooth")
        self.assertEqual(manifest["selected_clips"][0]["duration"], 1.234)
        self.assertEqual(manifest["selected_clips"][0]["motion_score"], 0.0)
        self.assertEqual(manifest["selected_clips"][0]["target_similarity"], 1.0)
        self.assertEqual(manifest["transitions"][0]["fade_seconds"], 0.123)

    def test_build_video_writes_manifest_only_when_requested(self) -> None:
        """Manifest JSON is opt-in even though build_video still returns manifest data."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.mp4"
            selected = [clip("a.mp4", duration=1.0)]
            counts = {
                "after_size_filter": 1,
                "after_orientation": 1,
                "after_target_filter": 1,
                "after_smart_filter": 1,
                "after_smart_trim": None,
                "after_smart_dedupe": None,
            }
            with (
                patch("clipweave.pipeline.select_clips", return_value=(selected, (1080, 1920), counts, None)),
                patch("clipweave.pipeline.render_video", return_value=[]),
            ):
                build_video(BuildOptions(input_dir=Path(tmp), output=output))
                self.assertFalse(output.with_name("clipweave_out.manifest.json").exists())

                build_video(BuildOptions(input_dir=Path(tmp), output=output, save_manifest=True))
                self.assertTrue(output.with_name("clipweave_out.manifest.json").exists())

    def test_build_video_writes_contact_sheet_only_when_requested(self) -> None:
        """Contact sheet debug output is opt-in."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.mp4"
            selected = [clip("a.mp4", duration=1.0)]
            counts = {
                "after_size_filter": 1,
                "after_orientation": 1,
                "after_target_filter": 1,
                "after_smart_filter": 1,
                "after_smart_trim": None,
                "after_smart_dedupe": None,
            }
            with (
                patch("clipweave.pipeline.select_clips", return_value=(selected, (1080, 1920), counts, None)),
                patch("clipweave.pipeline.render_video", return_value=[]),
                patch("clipweave.pipeline.save_contact_sheet", return_value=output.with_suffix(".contact.jpg")) as contact_sheet,
            ):
                manifest = build_video(BuildOptions(input_dir=Path(tmp), output=output))
                contact_sheet.assert_not_called()
                self.assertNotIn("contact_sheet", manifest)

                manifest = build_video(BuildOptions(input_dir=Path(tmp), output=output, save_contact_sheet=True))
                contact_sheet.assert_called_once()
                self.assertEqual(manifest["contact_sheet"], str(output.with_suffix(".contact.jpg")))

    def test_render_video_passes_auto_grade_to_normalization(self) -> None:
        """Pipeline rendering should forward auto-grade to every normalized source."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.mp4"
            selected = [clip("a.mp4", duration=1.0), clip("b.mp4", duration=1.0)]
            options = BuildOptions(input_dir=Path(tmp), output=output, transition="cut", auto_grade=True)

            with (
                patch("clipweave.pipeline.normalize_source") as normalize,
                patch("clipweave.pipeline.concat_plain", return_value=[]),
            ):
                render_video(selected, (1080, 1920), output, options)

        self.assertEqual(normalize.call_count, 2)
        self.assertTrue(all(call.args[6] is True for call in normalize.call_args_list))


if __name__ == "__main__":
    unittest.main()
