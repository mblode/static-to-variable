#!/usr/bin/env python3
"""Config-driven variable-font build + per-weight fidelity check.

Exports the designspace (via :mod:`variable_gen.designspace`), runs fontmake, and repeats a
freeze loop that pins any cu2qu-incompatible or interpolation-collapsing glyph to
the default master's donor before rebuilding, then verifies that every named
weight matches its mapped donor. Every input (masters, donor paths, output paths)
comes from a v3 ``ProjectConfig`` instead of the hardcoded ``PLANS``/``BUILD``
literals.

The generated-outline freeze behaviour is preserved exactly (parity depends on
it): the loop detects glyphs that collapse at master-pair midpoints in the BUILT
VF, freezes them to the default-master donor (constant -> can't collapse), and
rebuilds. Explicitly marked authored rows are never destructive-repair targets;
incomplete provenance, incompatibility, collapse, or compiled-source drift is a
named hard error instead.

Run:  uv run python -m variable_gen.cli build --config <path> --style all
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import glyphsLib
import pathops
from fontTools.designspaceLib import DesignSpaceDocument
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from variable_gen.authorship import AuthoredSource, inspect_authored_source
from variable_gen.common import PipelineError, fontmake_command, merge_style_report
from variable_gen.config import ProjectConfig, Style, default_donor_path
from variable_gen.designspace import export_designspace
from variable_gen.outlines import donor_outline, draw_into
from variable_gen.quadratic_prefix import install as _install_opsz_prefix

_install_opsz_prefix()

UNDERWEIGHT_RATIO = 0.92
AUTHORED_FIDELITY_RATIO = 0.98
SEMANTIC_CARRIER_SUFFIX = re.compile(r"^(?P<owner>.+)\.stv-semantic\d+x$")


def _semantic_carrier_owner(name: str) -> str | None:
    matched = SEMANTIC_CARRIER_SUFFIX.fullmatch(name)
    return matched.group("owner") if matched else None
