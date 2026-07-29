from __future__ import annotations

import json
import shutil
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
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
    QSizePolicy,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import BuildOptions
from .pipeline import build_video

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resource_path(relative_path: str) -> Path:
    """Resolve a bundled asset path for source and PyInstaller builds."""
    base = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    return base / relative_path


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
        self.setMinimumSize(1180, 860)
        icon_path = resource_path("assets/clipweave-icon.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self._build_ui()
        self._set_idle_state("Choose input media, then start a build.")

    def _build_ui(self) -> None:
        """Create controls and layout for the main window."""
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setSpacing(10)

        self.banner_label = QLabel()
        self.banner_label.setFixedHeight(120)
        self.banner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_label.setStyleSheet("background: #15191d; border-radius: 6px;")
        self.banner_pixmap = QPixmap(str(resource_path("assets/clipweave-app-banner.png")))
        self._apply_banner_pixmap()
        layout.addWidget(self.banner_label)

        paths = QGroupBox("Paths")
        path_grid = QGridLayout(paths)
        path_grid.setColumnStretch(1, 1)
        self.input_edit = QLineEdit()
        self.target_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self._style_field(self.input_edit)
        self._style_field(self.target_edit)
        self._style_field(self.output_edit)
        path_grid.addWidget(self._label_with_hint("Input folder", "Folder with source videos, images, or mixed media."), 0, 0)
        path_grid.addWidget(self.input_edit, 0, 1)
        path_grid.addWidget(self._browse_button(self.choose_input), 0, 2)
        path_grid.addWidget(self._label_with_hint("Target", "Optional reference file used to reject visually distant media."), 1, 0)
        path_grid.addWidget(self.target_edit, 1, 1)
        target_actions = QHBoxLayout()
        target_actions.addWidget(self._browse_button(self.choose_target))
        target_actions.addWidget(self._small_button("Clear", self.target_edit.clear))
        path_grid.addLayout(target_actions, 1, 2)
        path_grid.addWidget(self._label_with_hint("Output", "Optional MP4 path. Empty means output goes into the input folder."), 2, 0)
        path_grid.addWidget(self.output_edit, 2, 1)
        output_actions = QHBoxLayout()
        output_actions.addWidget(self._browse_button(self.choose_output))
        output_actions.addWidget(self._small_button("Clear", self.output_edit.clear))
        path_grid.addLayout(output_actions, 2, 2)
        layout.addWidget(paths)

        self.options_group = QGroupBox("Options")
        self.options_group.setMinimumHeight(590)
        option_grid = QGridLayout(self.options_group)
        option_grid.setHorizontalSpacing(24)
        option_grid.setVerticalSpacing(18)
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
        self._style_field(self.crf_spin, height=44, fixed=True)
        self.crf_spin.setStyleSheet("QSpinBox { padding: 6px 10px; }")
        self.preset_combo = self._combo(["ultrafast", "veryfast", "medium", "slow"])
        self.preset_combo.setCurrentText("slow")
        self.keep_work_check = QCheckBox("Keep temporary files")
        self._style_field(self.keep_work_check, height=44, fixed=True)

        self._add_option(option_grid, 0, "Media", self.media_combo, "Choose videos, image slideshow, or both.")
        self._add_option(option_grid, 1, "Orientation", self.orientation_combo, "Filter vertical, horizontal, or all formats.")
        self._add_option(option_grid, 2, "Audio", self.audio_combo, "Keep source audio or render a silent montage.")
        self._add_option(option_grid, 3, "Transition", self.transition_combo, "Use visual fades or hard cuts between clips.")
        self._add_option(option_grid, 4, "Order", self.order_combo, "Sort by visual continuity, filename, or duration.")
        self._add_option(option_grid, 5, "Image duration, sec", self.image_duration_spin, "How long each still image stays on screen.")
        self._add_option(option_grid, 6, "Max duration, sec", self.max_duration_spin, "Upper limit for selected media. 0 means no limit.")
        self._add_option(option_grid, 7, "Target threshold", self.target_threshold_spin, "Higher values keep only media closer to the target.")
        self._add_option(option_grid, 8, "Duplicate threshold", self.duplicate_threshold_spin, "Higher values remove only very close visual duplicates.")
        self._add_option(option_grid, 9, "CRF", self.crf_spin, "Encoding quality. Lower is larger and cleaner.")
        self._add_option(option_grid, 10, "Preset", self.preset_combo, "Encoding speed preset. Slow favors compression quality.")
        self._add_option(option_grid, 11, "Temporary files", self.keep_work_check, "Keep intermediate render files for debugging.")
        layout.addWidget(self.options_group)

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
        self.log.setPlaceholderText("Build manifest and errors will appear here.")
        self.log.setMinimumHeight(180)
        layout.addWidget(self.status_label)
        layout.addWidget(self.log, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

    def resizeEvent(self, event) -> None:
        """Keep the banner crisp when the window changes size."""
        super().resizeEvent(event)
        self._apply_banner_pixmap()

    def _apply_banner_pixmap(self) -> None:
        """Scale the README banner into the GUI header."""
        if not hasattr(self, "banner_label") or not hasattr(self, "banner_pixmap"):
            return
        if self.banner_pixmap.isNull():
            self.banner_label.setText("Clipweave")
            self.banner_label.setStyleSheet("font-size: 28px; font-weight: 700;")
            return
        size = self.banner_label.size()
        if size.width() <= 1:
            size.setWidth(1140)
        size.setHeight(120)
        scaled = self.banner_pixmap.scaled(
            size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.banner_label.setPixmap(scaled)

    def _label_with_hint(self, title: str, hint: str) -> QWidget:
        """Create a field label with a visible short explanation."""
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(title)
        label.setStyleSheet("font-weight: 600;")
        help_label = QLabel(hint)
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #7d8b98; font-size: 11px;")
        layout.addWidget(label)
        layout.addWidget(help_label)
        return box

    def _add_option(self, grid: QGridLayout, index: int, title: str, widget: QWidget, hint: str) -> None:
        """Place one explained option into the two-column options grid."""
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._label_with_hint(title, hint))
        layout.addWidget(widget)
        row = index // 2
        column = index % 2
        cell.setMinimumHeight(82)
        grid.addWidget(cell, row, column)
        grid.setRowMinimumHeight(row, 92)
        grid.setColumnStretch(column, 1)
        grid.setColumnMinimumWidth(column, 540)

    def _style_field(self, widget: QWidget, height: int = 38, fixed: bool = False) -> None:
        """Apply common sizing to input controls so they remain easy to use."""
        widget.setMinimumHeight(height)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if fixed:
            widget.setFixedHeight(height)

    def _browse_button(self, callback) -> QPushButton:
        """Create a compact browse button wired to a file/folder picker callback."""
        button = QPushButton("Browse")
        button.clicked.connect(callback)
        button.setMinimumHeight(38)
        return button

    def _small_button(self, text: str, callback) -> QPushButton:
        """Create a compact utility button."""
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setMinimumHeight(38)
        return button

    def _combo(self, values: list[str]) -> QComboBox:
        """Create a combo box from a list of string values."""
        combo = QComboBox()
        combo.addItems(values)
        self._style_field(combo, height=44, fixed=True)
        combo.setStyleSheet("QComboBox { padding: 6px 10px; }")
        return combo

    def _double_spin(self, minimum: float, maximum: float, value: float, decimals: int) -> QDoubleSpinBox:
        """Create a numeric control for float-valued options."""
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        self._style_field(spin, height=44, fixed=True)
        spin.setStyleSheet("QDoubleSpinBox { padding: 6px 10px; }")
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
