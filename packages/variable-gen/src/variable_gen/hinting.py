"""Give the built variable font a rasterizer baseline.

Donor statics ship ``fpgm``/``prep``/``cvt ``/``gasp``. This pipeline redraws
every outline, so the donors' glyph-level instructions are stale and dropping
them is correct — but shipping with *no* ``gasp`` and no dropout control is not.
Legacy Windows rasterizers then get no smoothing directive at all, and thin
strokes at small sizes can drop out entirely.

So the output gets the baseline Google Fonts prescribes for variable fonts
(their ``fix-nonhinting`` step): grayscale + symmetric smoothing at every size,
and a ``prep`` that turns on dropout control. Actual glyph hinting stays out —
GF's own guidance is that autohinted variable fonts frequently render worse than
unhinted ones, and hints only apply to the default instance anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import ttProgram

HintingMode = Literal["smooth", "none"]
HINTING_MODES: tuple[HintingMode, ...] = ("smooth", "none")

# Gridfit | DoGray | SymmetricGridfit | SymmetricSmoothing, at every ppem.
_GASP_RANGES = {0xFFFF: 0x000F}

# SCANCTRL 511: dropout control on under all conditions, at every size.
# SCANTYPE 4: the smart-dropout rule the OpenType spec recommends.
_PREP_ASSEMBLY = ["PUSHW[]", "511", "SCANCTRL[]", "PUSHB[]", "4", "SCANTYPE[]"]

# Our prep never pushes more than one value at a time; leave a little headroom.
_MIN_STACK_ELEMENTS = 2


@dataclass(frozen=True)
class HintingReport:
    mode: str
    gasp: bool = False
    prep: bool = False
    note: str = ""

    def summary(self) -> str:
        if self.mode == "none":
            return "hinting: none"
        parts = [tag for tag, present in (("gasp", self.gasp), ("prep", self.prep)) if present]
        extra = f", {self.note}" if self.note else ""
        return f"hinting: {self.mode} ({', '.join(parts) or 'nothing added'}{extra})"


def apply_hinting(varfont: TTFont, mode: HintingMode = "smooth") -> HintingReport:
    """Add the smoothing/dropout baseline to ``varfont`` in place.

    Idempotent, and it never overwrites real hinting: a font that already has a
    ``prep`` keeps it, because that program came from somewhere that knows more
    about this typeface than we do.
    """
    if mode == "none":
        return HintingReport(mode="none")
    if mode != "smooth":
        raise ValueError(f"unknown hinting mode {mode!r}")

    added_gasp = "gasp" not in varfont
    if added_gasp:
        gasp = newTable("gasp")
        gasp.gaspRange = dict(_GASP_RANGES)
        varfont["gasp"] = gasp

    note = ""
    added_prep = "prep" not in varfont
    if added_prep:
        prep = newTable("prep")
        prep.program = ttProgram.Program()
        prep.program.fromAssembly(_PREP_ASSEMBLY)
        varfont["prep"] = prep
        _widen_maxp(varfont)
    else:
        note = "kept the existing prep"

    return HintingReport(mode="smooth", gasp="gasp" in varfont, prep="prep" in varfont, note=note)


def _widen_maxp(varfont: TTFont) -> None:
    """Declare the (tiny) interpreter budget our ``prep`` needs.

    fontmake emits an unhinted font, so these come out at zero; a rasterizer that
    trusts ``maxp`` would then refuse to run the program we just added.
    """
    if "maxp" not in varfont:
        return
    maxp = varfont["maxp"]
    maxp.maxZones = max(getattr(maxp, "maxZones", 0), 1)
    maxp.maxStackElements = max(getattr(maxp, "maxStackElements", 0), _MIN_STACK_ELEMENTS)
