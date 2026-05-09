"""
CityMind — Urban Intelligence System

Run from the project root:

  python main.py

Imports use top-level packages `core`, `ui`, `simulation`, etc.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.app import CityMindApp


def main() -> None:
    CityMindApp().run()


if __name__ == "__main__":
    main()
