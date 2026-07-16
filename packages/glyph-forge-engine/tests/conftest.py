"""Make the flat-module engine importable from tests.

The engine modules under ``python/`` import each other by bare name
(``import shared`` etc.), so tests add that directory to ``sys.path`` —
the same pattern packages/variable-gen/tests uses for its package src.
"""

import sys
from pathlib import Path

ENGINE_PYTHON_DIR = Path(__file__).resolve().parents[1] / "python"

if str(ENGINE_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_PYTHON_DIR))
