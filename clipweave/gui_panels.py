from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLineEdit, QWidget

from .gui_widgets import (
    add_option,
    browse_button,
    combo,
    double_spin,
    int_spin,
    label_with_hint,
    small_button,
    style_checkbox,
    style_field,
)


class PathsPanel(QGroupBox):
    """Input, target, and output path controls."""

    def __init__(
        self,
        choose_input: Callable[[], None],
        choose_target: Callable[[], None],
        choose_output: Callable[[], None],
    ) -> None:
        super().__init__("Paths")
        path_grid = QGridLayout(self)
        path_grid.setColumnStretch(1, 1)

        self.input_edit = QLineEdit()
        self.target_edit = QLineEdit()
        self.output_edit = QLineEdit()
        style_field(self.input_edit)
        style_field(self.target_edit)
        style_field(self.output_edit)

        path_grid.addWidget(label_with_hint("Input folder", "Folder with source videos, images, or mixed media."), 0, 0)
        path_grid.addWidget(self.input_edit, 0, 1)
        path_grid.addWidget(browse_button(choose_input), 0, 2)

        path_grid.addWidget(label_with_hint("Target", "Optional reference file used to reject visually distant media."), 1, 0)
        path_grid.addWidget(self.target_edit, 1, 1)
        target_actions = QHBoxLayout()
        target_actions.addWidget(browse_button(choose_target))
        target_actions.addWidget(small_button("Clear", self.target_edit.clear))
        path_grid.addLayout(target_actions, 1, 2)

        path_grid.addWidget(label_with_hint("Output", "Optional MP4 path. Empty means output goes into the input folder."), 2, 0)
        path_grid.addWidget(self.output_edit, 2, 1)
        output_actions = QHBoxLayout()
        output_actions.addWidget(browse_button(choose_output))
        output_actions.addWidget(small_button("Clear", self.output_edit.clear))
        path_grid.addLayout(output_actions, 2, 2)


class OptionsPanel(QGroupBox):
    """Montage selection and rendering option controls."""

    def __init__(self) -> None:
        super().__init__("Options")
        self.setMinimumHeight(590)
        self.option_grid = QGridLayout(self)
        self.option_grid.setHorizontalSpacing(24)
        self.option_grid.setVerticalSpacing(15)

        self.media_combo = combo(["videos", "images", "mixed"])
        self.orientation_combo = combo(["vertical", "horizontal", "any"])
        self.order_combo = combo(["visual", "name", "duration"])
        self.image_duration_spin = double_spin(0.1, 60.0, 3.0, 1)
        self.max_duration_spin = double_spin(0.0, 24 * 60 * 60, 0.0, 1)
        self.target_threshold_spin = double_spin(-1.0, 1.0, 0.35, 2)
        self.duplicate_threshold_spin = double_spin(-1.0, 1.0, 0.965, 3)
        self.smart_max_known_ratio_spin = double_spin(0.0, 1.0, 0.55, 2)
        self.smart_min_segment_duration_spin = double_spin(0.1, 60.0, 2.0, 1)
        self.crf_spin = int_spin(0, 35, 16)
        self.preset_combo = combo(["ultrafast", "veryfast", "medium", "slow"])
        self.preset_combo.setCurrentText("slow")

        self.keep_audio_check = QCheckBox("Keep source audio")
        self.fade_transition_check = QCheckBox("Use fade transitions")
        self.fade_transition_check.setChecked(True)
        self.smart_editing_check = QCheckBox("Smart editing")
        self.smart_dedupe_segments_check = QCheckBox("Dedupe smart segments")
        self.smart_dedupe_segments_check.setChecked(True)
        self.smart_reorder_segments_check = QCheckBox("Reorder smart segments")
        self.smart_reorder_segments_check.setChecked(True)
        self.keep_work_check = QCheckBox("Keep temporary files")
        style_checkbox(self.keep_audio_check)
        style_checkbox(self.fade_transition_check)
        style_checkbox(self.smart_editing_check)
        style_checkbox(self.smart_dedupe_segments_check)
        style_checkbox(self.smart_reorder_segments_check)
        style_checkbox(self.keep_work_check)

        self.media_combo.currentTextChanged.connect(self.apply_media_rules)
        self.keep_audio_check.toggled.connect(self.apply_audio_rules)
        self.smart_editing_check.toggled.connect(self.apply_smart_rules)
        self.option_cells: dict[str, QWidget] = {}
        self._populate()
        self.apply_media_rules(self.media_combo.currentText())

    @property
    def audio_value(self) -> str:
        """Return CLI-compatible audio option value."""
        return "keep" if self.keep_audio_check.isChecked() else "remove"

    @property
    def transition_value(self) -> str:
        """Return CLI-compatible transition option value."""
        return "fade" if self.fade_transition_check.isChecked() else "cut"

    def apply_media_rules(self, media: str) -> None:
        """Enable only controls that apply to the selected media mode."""
        images_possible = media in {"images", "mixed"}
        audio_possible = media == "videos"

        self._set_option_enabled("image_duration", images_possible)
        self._set_option_enabled("keep_audio", audio_possible)
        self._set_option_enabled("smart_max_known_ratio", self.smart_editing_check.isChecked())
        self._set_option_enabled("smart_min_segment_duration", self.smart_editing_check.isChecked())
        self._set_option_enabled("smart_dedupe_segments", self.smart_editing_check.isChecked())
        self._set_option_enabled("smart_reorder_segments", self.smart_editing_check.isChecked())

        if not audio_possible:
            self.keep_audio_check.setChecked(False)
        self.apply_audio_rules(self.keep_audio_check.isChecked())

    def apply_audio_rules(self, keep_audio: bool) -> None:
        """Disable fades when source audio is preserved."""
        fade_available = not keep_audio
        if not fade_available:
            self.fade_transition_check.setChecked(False)
        self._set_option_enabled("fade_transition", fade_available)
        self._set_option_enabled("smart_max_known_ratio", self.smart_editing_check.isChecked())
        self._set_option_enabled("smart_min_segment_duration", self.smart_editing_check.isChecked())
        self._set_option_enabled("smart_dedupe_segments", self.smart_editing_check.isChecked())
        self._set_option_enabled("smart_reorder_segments", self.smart_editing_check.isChecked())

    def apply_smart_rules(self, enabled: bool) -> None:
        """Disable smart editing details until smart editing is active."""
        self._set_option_enabled("smart_max_known_ratio", enabled)
        self._set_option_enabled("smart_min_segment_duration", enabled)
        self._set_option_enabled("smart_dedupe_segments", enabled)
        self._set_option_enabled("smart_reorder_segments", enabled)

    def _set_option_enabled(self, key: str, enabled: bool) -> None:
        """Enable or disable a whole option cell when the setting is not applicable."""
        cell = self.option_cells.get(key)
        if cell is not None:
            cell.setEnabled(enabled)

    def _populate(self) -> None:
        """Add option controls in visual order."""
        self.option_cells["media"] = add_option(self.option_grid, 0, "Media", self.media_combo, "Choose videos, image slideshow, or both.")
        self.option_cells["orientation"] = add_option(self.option_grid, 1, "Orientation", self.orientation_combo, "Filter vertical, horizontal, or all formats.")
        self.option_cells["order"] = add_option(self.option_grid, 2, "Order", self.order_combo, "Sort by visual continuity, filename, or duration.")
        self.option_cells["image_duration"] = add_option(self.option_grid, 3, "Image duration, sec", self.image_duration_spin, "How long each still image stays on screen.")
        self.option_cells["max_duration"] = add_option(self.option_grid, 4, "Max duration, sec", self.max_duration_spin, "Upper limit for selected media. 0 means no limit.")
        self.option_cells["target_threshold"] = add_option(self.option_grid, 5, "Target threshold", self.target_threshold_spin, "Higher values keep only media closer to the target.")
        self.option_cells["duplicate_threshold"] = add_option(self.option_grid, 6, "Duplicate threshold", self.duplicate_threshold_spin, "Higher values remove only very close visual duplicates.")
        self.option_cells["smart_max_known_ratio"] = add_option(self.option_grid, 7, "Smart max known ratio", self.smart_max_known_ratio_spin, "Drop clips above this already-seen frame ratio.")
        self.option_cells["smart_min_segment_duration"] = add_option(self.option_grid, 8, "Smart min segment, sec", self.smart_min_segment_duration_spin, "Shortest repeated-clip segment worth keeping.")
        self.option_cells["crf"] = add_option(self.option_grid, 9, "CRF", self.crf_spin, "Encoding quality. Lower is larger and cleaner.")
        self.option_cells["preset"] = add_option(self.option_grid, 10, "Preset", self.preset_combo, "Encoding speed preset. Slow favors compression quality.")
        self.option_cells["keep_audio"] = add_option(self.option_grid, 11, "Keep audio", self.keep_audio_check, "Use source audio instead of rendering a silent montage.")
        self.option_cells["fade_transition"] = add_option(self.option_grid, 12, "Fade transitions", self.fade_transition_check, "Blend clips visually. Disabled automatically when audio is kept.")
        self.option_cells["smart_editing"] = add_option(self.option_grid, 13, "Smart editing", self.smart_editing_check, "Trim or skip clips that mostly repeat earlier sampled frames.")
        self.option_cells["smart_dedupe_segments"] = add_option(self.option_grid, 14, "Dedupe smart segments", self.smart_dedupe_segments_check, "Run a second visual duplicate pass after trimming.")
        self.option_cells["smart_reorder_segments"] = add_option(self.option_grid, 15, "Reorder smart segments", self.smart_reorder_segments_check, "Sort salvaged segments visually after smart editing.")
        self.option_cells["keep_work"] = add_option(self.option_grid, 16, "Temporary files", self.keep_work_check, "Keep intermediate render files for debugging.")
