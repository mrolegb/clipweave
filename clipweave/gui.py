from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .config import BuildOptions
from .gui_assets import resource_path
from .gui_panels import OptionsPanel, PathsPanel
from .gui_worker import BuildWorker, ffmpeg_available


class MainWindow(QMainWindow):
    """Desktop UI for configuring and launching Clipweave builds."""

    def __init__(self) -> None:
        super().__init__()
        self.thread: QThread | None = None
        self.worker: BuildWorker | None = None

        self.setWindowTitle("Clipweave")
        self.setMinimumSize(1180, 860)
        icon_path = resource_path("assets/clipweave-icon.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()
        self._set_idle_state("Choose input media, then start a build.")

    def _build_ui(self) -> None:
        """Create the top-level layout and compose the reusable panels."""
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setSpacing(10)

        self.paths_panel = PathsPanel(self.choose_input, self.choose_target, self.choose_output)
        self.input_edit = self.paths_panel.input_edit
        self.target_edit = self.paths_panel.target_edit
        self.output_edit = self.paths_panel.output_edit
        layout.addWidget(self.paths_panel)

        self.options_group = OptionsPanel()
        self._expose_option_controls(self.options_group)
        layout.addWidget(self.options_group)

        layout.addLayout(self._build_actions())
        layout.addWidget(self._separator())

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Build manifest and errors will appear here.")
        self.log.setMinimumHeight(180)
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        layout.addWidget(self.log, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

    def _expose_option_controls(self, panel: OptionsPanel) -> None:
        """Expose panel controls on the window for simple tests and event handlers."""
        self.option_grid = panel.option_grid
        self.media_combo = panel.media_combo
        self.orientation_combo = panel.orientation_combo
        self.order_combo = panel.order_combo
        self.structure_combo = panel.structure_combo
        self.image_duration_spin = panel.image_duration_spin
        self.max_duration_spin = panel.max_duration_spin
        self.target_threshold_spin = panel.target_threshold_spin
        self.duplicate_threshold_spin = panel.duplicate_threshold_spin
        self.smart_max_known_ratio_spin = panel.smart_max_known_ratio_spin
        self.smart_min_segment_duration_spin = panel.smart_min_segment_duration_spin
        self.smart_scene_threshold_spin = panel.smart_scene_threshold_spin
        self.crf_spin = panel.crf_spin
        self.preset_combo = panel.preset_combo
        self.keep_audio_check = panel.keep_audio_check
        self.fade_transition_check = panel.fade_transition_check
        self.split_aspects_check = panel.split_aspects_check
        self.auto_grade_check = panel.auto_grade_check
        self.smart_editing_check = panel.smart_editing_check
        self.smart_dedupe_segments_check = panel.smart_dedupe_segments_check
        self.smart_reorder_segments_check = panel.smart_reorder_segments_check
        self.save_manifest_check = panel.save_manifest_check
        self.save_contact_sheet_check = panel.save_contact_sheet_check
        self.keep_work_check = panel.keep_work_check

    def _build_actions(self) -> QHBoxLayout:
        """Create action buttons shown below the options panel."""
        actions = QHBoxLayout()
        self.build_button = QPushButton("Build")
        self.build_button.clicked.connect(self.start_build)
        self.open_output_button = QPushButton("Open Output Folder")
        self.open_output_button.clicked.connect(self.open_output_folder)
        actions.addWidget(self.build_button)
        actions.addWidget(self.open_output_button)
        actions.addStretch(1)
        return actions

    def _separator(self) -> QFrame:
        """Create a horizontal separator between controls and log output."""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        return line

    def choose_input(self) -> None:
        """Prompt for the source media directory."""
        path = QFileDialog.getExistingDirectory(self, "Choose input folder", self.input_edit.text())
        if path:
            self.input_edit.setText(path)

    def choose_target(self) -> None:
        """Prompt for an optional target image or video."""
        path, _ = QFileDialog.getOpenFileName(self, "Choose target media", self.input_edit.text())
        if path:
            self.target_edit.setText(path)

    def choose_output(self) -> None:
        """Prompt for the output MP4 path."""
        path, _ = QFileDialog.getSaveFileName(self, "Choose output file", self.input_edit.text(), "MP4 video (*.mp4)")
        if path:
            self.output_edit.setText(path)

    def on_media_changed(self, media: str) -> None:
        """Compatibility wrapper for tests and signal handlers."""
        self.options_group.apply_media_rules(media)

    def on_keep_audio_changed(self, keep_audio: bool) -> None:
        """Compatibility wrapper for tests and signal handlers."""
        self.options_group.apply_audio_rules(keep_audio)

    def build_options(self) -> BuildOptions:
        """Read current UI state into BuildOptions."""
        input_dir = Path(self.input_edit.text().strip())
        output_text = self.output_edit.text().strip()
        target_text = self.target_edit.text().strip()
        max_duration = self.max_duration_spin.value() or None
        return BuildOptions(
            input_dir=input_dir,
            output=Path(output_text) if output_text else None,
            orientation=self.orientation_combo.currentText(),
            media=self.media_combo.currentText(),
            audio=self.options_group.audio_value,
            image_duration=self.image_duration_spin.value(),
            max_duration=max_duration,
            target=Path(target_text) if target_text else None,
            target_threshold=self.target_threshold_spin.value(),
            keep_work=self.keep_work_check.isChecked(),
            transition=self.options_group.transition_value,
            duplicate_threshold=self.duplicate_threshold_spin.value(),
            order=self.order_combo.currentText(),
            structure=self.structure_combo.currentText(),
            split_aspects=self.split_aspects_check.isChecked(),
            auto_grade=self.auto_grade_check.isChecked(),
            crf=self.crf_spin.value(),
            preset=self.preset_combo.currentText(),
            save_manifest=self.save_manifest_check.isChecked(),
            save_contact_sheet=self.save_contact_sheet_check.isChecked(),
            smart_editing=self.smart_editing_check.isChecked(),
            smart_max_known_ratio=self.smart_max_known_ratio_spin.value(),
            smart_min_segment_duration=self.smart_min_segment_duration_spin.value(),
            smart_scene_threshold=self.smart_scene_threshold_spin.value(),
            smart_dedupe_segments=self.smart_dedupe_segments_check.isChecked(),
            smart_reorder_segments=self.smart_reorder_segments_check.isChecked(),
        )

    def validate_options(self, options: BuildOptions) -> bool:
        """Show friendly validation errors before starting a build."""
        if not options.input_dir.exists() or not options.input_dir.is_dir():
            QMessageBox.warning(self, "Input folder missing", "Choose an existing input folder.")
            return False
        if options.target and not options.target.exists():
            QMessageBox.warning(self, "Target missing", "The target file does not exist.")
            return False
        if not ffmpeg_available():
            QMessageBox.warning(self, "FFmpeg missing", "ffmpeg and ffprobe must be available in PATH.")
            return False
        return True

    def start_build(self) -> None:
        """Start a background build with the current settings."""
        options = self.build_options()
        if not self.validate_options(options):
            return

        self._set_busy_state()
        self.log.setPlainText("Building...\n")
        self.thread = QThread()
        self.worker = BuildWorker(options)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_build_finished)
        self.worker.failed.connect(self.on_build_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def on_build_finished(self, manifest: dict) -> None:
        """Display the successful build manifest."""
        self._set_idle_state()
        self.log.setPlainText(json.dumps(manifest, ensure_ascii=False, indent=2))
        self.status_label.setText(f"Done: {manifest.get('output')}")
        self.worker = None
        self.thread = None

    def on_build_failed(self, error: str) -> None:
        """Display a traceback from the worker thread."""
        self._set_idle_state()
        self.log.setPlainText(error)
        self.status_label.setText("Build failed.")
        self.worker = None
        self.thread = None

    def open_output_folder(self) -> None:
        """Open the configured or default output folder in the OS file manager."""
        output = self.build_options().output_path
        folder = output.parent if output.parent.exists() else self.build_options().resolved_input_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _set_busy_state(self) -> None:
        """Disable build controls while a worker is active."""
        self.build_button.setEnabled(False)
        self.status_label.setText("Building...")

    def _set_idle_state(self, message: str = "") -> None:
        """Restore controls when no build is active."""
        self.build_button.setEnabled(True)
        self.status_label.setText(message)


def main() -> None:
    """Launch the Clipweave desktop UI."""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
