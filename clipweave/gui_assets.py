from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resource_path(relative_path: str) -> Path:
    """Resolve a bundled asset path for source and PyInstaller builds."""
    base = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    return base / relative_path
