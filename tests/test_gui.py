from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QScrollArea

    from clipweave.gui import MainWindow, resource_path
except (ImportError, ModuleNotFoundError):  # pragma: no cover - exercised only without optional UI deps.
    QApplication = None
    MainWindow = None
    resource_path = None


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Create a single QApplication for all widget tests."""
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        """Create a fresh window for each GUI behavior check."""
        self.window = MainWindow()

    def tearDown(self) -> None:
        """Close widgets so tests do not leak top-level windows."""
        self.window.close()

    def test_initial_status_does_not_say_ready(self) -> None:
        """The UI should not display Ready before a build has run."""
        self.assertNotIn("Ready", self.window.status_label.text())
        self.assertIn("start a build", self.window.status_label.text())

    def test_images_mode_forces_silent_output(self) -> None:
        """Image slideshow mode cannot keep source audio."""
        self.window.keep_audio_check.setChecked(True)
        self.window.media_combo.setCurrentText("images")

        self.assertFalse(self.window.keep_audio_check.isChecked())
        self.assertFalse(self.window.keep_audio_check.isEnabled())

    def test_keep_audio_disables_fade_checkbox(self) -> None:
        """Keeping audio uses hard cuts to avoid transition audio artifacts."""
        self.window.keep_audio_check.setChecked(True)

        self.assertFalse(self.window.fade_transition_check.isChecked())
        self.assertFalse(self.window.fade_transition_check.isEnabled())

    def test_boolean_options_are_checkboxes_below_other_options(self) -> None:
        """Binary options are checkboxes placed below the main option controls."""
        keep_audio_row, _, _, _ = self.window.option_grid.getItemPosition(
            self.window.option_grid.indexOf(self.window.keep_audio_check.parentWidget())
        )
        fade_row, _, _, _ = self.window.option_grid.getItemPosition(
            self.window.option_grid.indexOf(self.window.fade_transition_check.parentWidget())
        )
        temp_row, _, _, _ = self.window.option_grid.getItemPosition(
            self.window.option_grid.indexOf(self.window.keep_work_check.parentWidget())
        )

        self.assertGreaterEqual(keep_audio_row, 5)
        self.assertGreaterEqual(fade_row, 5)
        self.assertGreaterEqual(temp_row, 6)

    def test_build_options_reads_current_fields(self) -> None:
        """Form controls are converted into BuildOptions for the pipeline."""
        self.window.input_edit.setText("D:/clips")
        self.window.target_edit.setText("D:/target.jpg")
        self.window.output_edit.setText("D:/out.mp4")
        self.window.media_combo.setCurrentText("mixed")
        self.window.orientation_combo.setCurrentText("horizontal")
        self.window.keep_audio_check.setChecked(True)
        self.window.max_duration_spin.setValue(12.5)

        options = self.window.build_options()

        self.assertEqual(options.input_dir, Path("D:/clips"))
        self.assertEqual(options.target, Path("D:/target.jpg"))
        self.assertEqual(options.output, Path("D:/out.mp4"))
        self.assertEqual(options.media, "mixed")
        self.assertEqual(options.orientation, "horizontal")
        self.assertEqual(options.audio, "keep")
        self.assertEqual(options.transition, "cut")
        self.assertEqual(options.max_duration, 12.5)

    def test_assets_resolve_for_source_tree(self) -> None:
        """GUI assets are available from the source checkout."""
        self.assertTrue(resource_path("assets/clipweave-banner.png").exists())
        self.assertTrue(resource_path("assets/clipweave-app-banner.png").exists())
        self.assertTrue(resource_path("assets/clipweave-icon.png").exists())
        self.assertFalse(self.window.windowIcon().isNull())

    def test_options_are_roomy_enough(self) -> None:
        """Main controls should not collapse into thin rows."""
        self.assertGreaterEqual(self.window.minimumWidth(), 1180)
        self.assertGreaterEqual(self.window.options_group.minimumHeight(), 590)
        self.assertGreaterEqual(self.window.media_combo.minimumHeight(), 30)
        self.assertEqual(self.window.media_combo.height(), 30)
        self.assertGreaterEqual(self.window.image_duration_spin.minimumHeight(), 30)
        self.assertEqual(self.window.image_duration_spin.height(), 30)

    def test_crf_spin_uses_same_numeric_field_style(self) -> None:
        """CRF should look like the other numeric option fields."""
        self.assertEqual(self.window.crf_spin.minimumHeight(), self.window.image_duration_spin.minimumHeight())
        self.assertEqual(self.window.crf_spin.height(), self.window.image_duration_spin.height())
        self.assertEqual(self.window.crf_spin.styleSheet(), self.window.image_duration_spin.styleSheet())

    def test_layout_can_scroll_instead_of_overlapping(self) -> None:
        """The main form should scroll when it cannot fit vertically."""
        self.assertIsInstance(self.window.centralWidget(), QScrollArea)
        self.assertEqual(self.window.banner_label.height(), 120)


if __name__ == "__main__":
    unittest.main()
