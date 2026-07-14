from __future__ import annotations

import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PACKAGE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from variable_gen.pipeline import _automatic_decision_kind


def _item(**kw):
    base = {"family": "italic", "name": "perthousand", "existingStrategy": "weighted_fallback"}
    base.update(kw)
    return base


class GlyphForgeGateTests(unittest.TestCase):
    """The automatic-decision gate must only flag actionable upgrades.

    A more-rigorous suggestion with no projected solver gain is a treadmill, not
    a decision — flagging it blocks promotion forever even though applying it
    wouldn't help.
    """

    def test_zero_gain_upgrade_not_flagged(self) -> None:
        suggestions = {"italic/perthousand": {"strategy": "structural_fallback"}}
        solver = {"italic/perthousand": {"gain": 0.0, "requiresReconstruction": False}}
        self.assertIsNone(_automatic_decision_kind(_item(), solver, suggestions))

    def test_negative_gain_upgrade_not_flagged(self) -> None:
        suggestions = {"italic/perthousand": {"strategy": "structural_fallback"}}
        solver = {"italic/perthousand": {"gain": -0.3, "requiresReconstruction": False}}
        self.assertIsNone(_automatic_decision_kind(_item(), solver, suggestions))

    def test_positive_gain_upgrade_flagged(self) -> None:
        suggestions = {"italic/perthousand": {"strategy": "structural_fallback"}}
        solver = {"italic/perthousand": {"gain": 0.3, "requiresReconstruction": False}}
        self.assertEqual(_automatic_decision_kind(_item(), solver, suggestions), "upgrade")

    def test_allow_static_outline_skips(self) -> None:
        suggestions = {"italic/perthousand": {"strategy": "structural_fallback"}}
        solver = {"italic/perthousand": {"gain": 0.9, "requiresReconstruction": False}}
        self.assertIsNone(
            _automatic_decision_kind(_item(allowStaticOutline=True), solver, suggestions)
        )

    def test_reconstruction_required_skips(self) -> None:
        suggestions = {"italic/perthousand": {"strategy": "structural_fallback"}}
        solver = {"italic/perthousand": {"gain": 0.9, "requiresReconstruction": True}}
        self.assertIsNone(_automatic_decision_kind(_item(), solver, suggestions))


if __name__ == "__main__":
    unittest.main()
