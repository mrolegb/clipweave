from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

OPTION_FIELD_HEIGHT = 30
PATH_FIELD_HEIGHT = 30
OPTION_CELL_HEIGHT = 45
OPTION_COLUMN_WIDTH = 540
INPUT_HORIZONTAL_PADDING = 10
SPIN_INNER_STYLE = "QLineEdit { border: none; background: transparent; padding: 0px; }"
INPUT_STYLE = f"""
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: #2b2b2b;
    border: 1px solid #3f3f3f;
    border-radius: 4px;
    color: #ffffff;
    padding-top: 0px;
    padding-bottom: 0px;
    padding-left: {INPUT_HORIZONTAL_PADDING}px;
    padding-right: {INPUT_HORIZONTAL_PADDING}px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid #b15cc6;
}}
QComboBox {{
    padding-right: 28px;
}}
QComboBox::drop-down {{
    border-left: 1px solid #3f3f3f;
    width: 24px;
}}
QSpinBox, QDoubleSpinBox {{
    padding: 0px;
}}
"""


def label_with_hint(title: str, hint: str) -> QWidget:
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


def style_field(widget: QWidget, height: int = PATH_FIELD_HEIGHT, fixed: bool = False) -> None:
    """Apply common sizing to text, combo, and numeric controls."""
    widget.setMinimumHeight(height)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    widget.setStyleSheet(INPUT_STYLE)
    if isinstance(widget, QLineEdit):
        widget.setTextMargins(INPUT_HORIZONTAL_PADDING, 0, INPUT_HORIZONTAL_PADDING, 0)
    if fixed:
        widget.setFixedHeight(height)


def style_checkbox(checkbox: QCheckBox) -> None:
    """Apply common sizing to boolean option controls."""
    checkbox.setMinimumHeight(OPTION_FIELD_HEIGHT)
    checkbox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def browse_button(callback: Callable[[], None]) -> QPushButton:
    """Create a compact browse button wired to a file/folder picker callback."""
    button = QPushButton("Browse")
    button.clicked.connect(callback)
    button.setMinimumHeight(PATH_FIELD_HEIGHT)
    return button


def small_button(text: str, callback: Callable[[], None]) -> QPushButton:
    """Create a compact utility button."""
    button = QPushButton(text)
    button.clicked.connect(callback)
    button.setMinimumHeight(PATH_FIELD_HEIGHT)
    return button


def combo(values: list[str]) -> QComboBox:
    """Create a combo box from a list of string values."""
    control = QComboBox()
    control.addItems(values)
    style_field(control, height=OPTION_FIELD_HEIGHT, fixed=True)
    return control


def double_spin(minimum: float, maximum: float, value: float, decimals: int) -> QDoubleSpinBox:
    """Create a numeric control for float-valued options."""
    control = QDoubleSpinBox()
    control.setRange(minimum, maximum)
    control.setDecimals(decimals)
    control.setValue(value)
    style_spin(control)
    return control


def int_spin(minimum: int, maximum: int, value: int) -> QSpinBox:
    """Create a numeric control for integer-valued options."""
    control = QSpinBox()
    control.setRange(minimum, maximum)
    control.setValue(value)
    style_spin(control)
    return control


def style_spin(control: QSpinBox | QDoubleSpinBox) -> None:
    """Apply the same sizing and padding to all numeric option controls."""
    control.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    style_field(control, height=OPTION_FIELD_HEIGHT, fixed=True)
    control.lineEdit().setFrame(False)
    control.lineEdit().setStyleSheet(SPIN_INNER_STYLE)
    control.lineEdit().setTextMargins(INPUT_HORIZONTAL_PADDING, 0, INPUT_HORIZONTAL_PADDING, 0)


def add_option(grid: QGridLayout, index: int, title: str, widget: QWidget, hint: str) -> None:
    """Place one explained option into the two-column options grid."""
    cell = QWidget()
    layout = QVBoxLayout(cell)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(1)
    layout.addWidget(label_with_hint(title, hint))
    layout.addWidget(widget)
    row = index // 2
    column = index % 2
    cell.setMinimumHeight(OPTION_CELL_HEIGHT)
    grid.addWidget(cell, row, column)
    grid.setRowMinimumHeight(row, OPTION_CELL_HEIGHT)
    grid.setColumnStretch(column, 1)
    grid.setColumnMinimumWidth(column, OPTION_COLUMN_WIDTH)
