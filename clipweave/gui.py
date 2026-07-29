from __future__ import annotations

import json
import shutil
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import BuildOptions
from .pipeline import build_video


def ffmpeg_available() -> bool:
    """Check that the external FFmpeg tools required by the renderer are available."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class BuildWorker(QObject):
    """Run Clipweave in a background thread so the UI stays responsive."""

    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, options: BuildOptions) -> None:
        super().__init__()
        self.options = options

    def run(self) -> None:
        """Build the video and notify the UI with either a manifest or traceback."""
        try:
            self.finished.emit(build_video(self.options))
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    """Small desktop UI for configuring and launching Clipweave builds."""

    def __init__(self) -> None:
        super().__init__()
        self.thread: QThread | None = None
        self.worker: BuildWorker | None = None
        self.setWindowTitle("Clipweave")
        self.setMinimumSize(820, 720)
        self._build_ui()
        self._set_idle_state()

    def _build_ui(self) -> None:
        """Create controls and layout for the main window."""
        root = QWidget()
        layout = QVBoxLayout(root)

        title = QLabel("Clipweave")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        subtitle = QLabel("Build local video montages and image slideshows with visual ordering.")
        subtitle.setStyleSheet("color: #53606b;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        paths = QGroupBox("Paths")
        path_grid = QGridLayout(paths)
        self.input_edit = QLineEdit()
        self.target_edit = QLineEdit()
        self.output_edit = QLineEdit()
        path_grid.addWidget(QLabel("Input folder"), 0, 0)
        path_grid.addWidget(self.input_edit, 0, 1)
        path_grid.addWidget(self._browse_button(self.choose_input), 0, 2)
        path_grid.addWidget(QLabel("Target"), 1, 0)
        path_grid.addWidget(self.target_edit, 1, 1)
        target_actions = QHBoxLayout()
        target_actions.addWidget(self._browse_button(self.choose_target))
        target_actions.addWidget(self._small_button("Clear", self.target_edit.clear))
        path_grid.addLayout(target_actions, 1, 2)
        path_grid.addWidget(QLabel("Output"), 2, 0)
        path_grid.addWidget(self.output_edit, 2, 1)
        output_actions = QHBoxLayout()
        output_actions.addWidget(self._browse_button(self.choose_output))
        output_actions.addWidget(self._small_button("Clear", self.output_edit.clear))
        path_grid.addLayout(output_actions, 2, 2)
        layout.addWidget(paths)

        options = QGroupBox("Options")
        form = QFormLayout(options)
        self.media_combo = self._combo(["videos", "images", "mixed"])
        self.media_combo.currentTextChanged.connect(self.on_media_changed)
        self.orientation_combo = self._combo(["vertical", "horizontal", "any"])
        self.audio_combo = self._combo(["remove", "keep"])
        self.transition_combo = self._combo(["fade", "cut"])
        self.order_combo = self._combo(["visual", "name", "duration"])
        self.image_duration_spin = self._double_spin(0.1, 60.0, 3.0, 1)
        self.max_duration_spin = self._double_spin(0.0, 24 * 60 * 60, 0.0, 1)
        self.target_threshold_spin = self._double_spin(-1.0, 1.0, 0.35, 2)
        self.duplicate_threshold_spin = self._double_spin(-1.0, 1.0, 0.965, 3)
        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(0, 35)
        self.crf_spin.setValue(16)
        self.preset_combo = self._combo(["ultrafast", "veryfast", "medium", "slow"])
        self.preset_combo.setCurrentText("slow")
        self.keep_work_check = QCheckBox("Keep temporary files")

        form.addRow("Media", self.media_combo)
        form.addRow("Orientation", self.orientation_combo)
        form.addRow("Audio", self.audio_combo)
        form.addRow("Transition", self.transition_combo)
        form.addRow("Order", self.order_combo)
        form.addRow("Image duration, sec", self.image_duration_spin)
        form.addRow("Max duration, sec (0 = no limit)", self.max_duration_spin)
        form.addRow("Target threshold", self.target_threshold_spin)
        form.addRow("Duplicate threshold", self.duplicate_threshold_spin)
        form.addRow("CRF", self.crf_spin)
        form.addRow("Preset", self.preset_combo)
        form.addRow("", self.keep_work_check)
        layout.addWidget(options)

        actions = QHBoxLayout()
        self.build_button = QPushButton("Build")
        self.build_button.clicked.connect(self.start_build)
        self.open_output_button = QPushButton("Open Output Folder")
        self.open_output_button.clicked.connect(self.open_output_folder)
        actions.addWidget(self.build_button)
        actions.addWidget(self.open_output_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)

        self.status_label = QLabel()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(180)
        layout.addWidget(self.status_label)
        layout.addWidget(self.log, 1)
        self.setCentralWidget(root)

    def _browse_button(self, callback) -> QPushButton:
        """Create a compact browse button wired to a file/folder picker callback."""
        button = QPushButton("Browse")
        button.clicked.connect(callback)
        return button

    def _small_button(self, text: str, callback) -> QPushButton:
        """Create a compact utility button."""
        button = QPushButton(text)
        button.clicked.connect(callback)
        return button

    def _combo(self, values: list[str]) -> QComboBox:
        """Create a combo box from a list of string values."""
        combo = QComboBox()
        combo.addItems(values)
        return combo

    def _double_spin(self, minimum: float, maximum: float, value: float, decimals: int) -> QDoubleSpinBox:
        """Create a numeric control for float-valued options."""
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        return spin

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
        """Keep option combinations valid when switching media modes."""
        if media == "images":
            self.audio_combo.setCurrentText("remove")
            self.audio_combo.setEnabled(False)
        else:
            self.audio_combo.setEnabled(True)

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
            audio=self.audio_combo.currentText(),
            image_duration=self.image_duration_spin.value(),
            max_duration=max_duration,
            target=Path(target_text) if target_text else None,
            target_threshold=self.target_threshold_spin.value(),
            keep_work=self.keep_work_check.isChecked(),
            transition=self.transition_combo.currentText(),
            duplicate_threshold=self.duplicate_threshold_spin.value(),
            order=self.order_combo.currentText(),
            crf=self.crf_spin.value(),
            preset=self.preset_combo.currentText(),
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
        self.status_label.setText("Working...")

    def _set_idle_state(self) -> None:
        """Restore controls when no build is active."""
        self.build_button.setEnabled(True)
        self.status_label.setText("Ready.")


def main() -> None:
    """Launch the Clipweave desktop UI."""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
