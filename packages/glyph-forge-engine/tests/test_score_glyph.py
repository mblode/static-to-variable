"""Geometry-scoring unit tests, including the duplicate-point regression."""

import math

import numpy as np
import pytest
from score_glyph import (
    _flatten_ops,
    composite,
    drift_score,
    irregularity_score,
    void_score,
)


def test_flatten_line_ops():
    ops = [("moveTo", [(0.0, 0.0)]), ("lineTo", [(10.0, 0.0)]), ("closePath", [])]
    pts = _flatten_ops(ops)
    assert pts[0] == (0.0, 0.0)
    assert (10.0, 0.0) in pts
    # closePath returns to the subpath start.
    assert pts[-1] == (0.0, 0.0)


def test_flatten_cubic_ends_on_curve_endpoint():
    ops = [
        ("moveTo", [(0.0, 0.0)]),
        ("curveTo", [(0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]),
    ]
    pts = _flatten_ops(ops, steps=8)
    assert pts[-1] == (10.0, 0.0)


def test_flatten_quad_chain_with_duplicate_points():
    # The end point duplicates the start point (a closed quadratic loop). The
    # old implementation located segment positions with list.index(), which
    # finds the FIRST occurrence — here it mistook the final on-curve point for
    # an interior one and ended the curve at an implied midpoint instead of the
    # real end point.
    ops = [("moveTo", [(0.0, 0.0)]), ("qCurveTo", [(5.0, 5.0), (0.0, 0.0)])]
    pts = _flatten_ops(ops, steps=6)
    assert pts[-1] == (0.0, 0.0)


def test_flatten_quad_chain_implied_oncurves():
    # Two off-curves imply an on-curve midpoint between them; the chain still
    # ends exactly at the explicit end point.
    ops = [("moveTo", [(0.0, 0.0)]), ("qCurveTo", [(2.0, 4.0), (6.0, 4.0), (8.0, 0.0)])]
    pts = _flatten_ops(ops, steps=6)
    assert pts[-1] == (8.0, 0.0)


def test_void_score_identical_masks_is_one():
    mask = np.zeros((8, 8), dtype=bool)
    mask[2:6, 2:6] = True
    assert void_score(mask, mask) == 1.0


def test_void_score_disjoint_masks_is_zero():
    donor = np.zeros((8, 8), dtype=bool)
    donor[0:2, 0:2] = True
    glide = np.zeros((8, 8), dtype=bool)
    glide[6:8, 6:8] = True
    assert void_score(donor, glide) == 0.0


def test_void_score_empty_donor():
    empty = np.zeros((8, 8), dtype=bool)
    inked = np.ones((8, 8), dtype=bool)
    assert void_score(empty, empty) == 1.0
    assert void_score(empty, inked) == 0.0


def ngon(n=24, radius=100.0, spikes=()):
    """A closed regular n-gon; indices in `spikes` bulge outward (kinks)."""
    ops = []
    for k in range(n):
        angle = 2 * math.pi * k / n
        r = radius * (1.8 if k in spikes else 1.0)
        pt = (math.cos(angle) * r, math.sin(angle) * r)
        ops.append(("moveTo" if k == 0 else "lineTo", [pt]))
    ops.append(("closePath", []))
    return ops


def test_irregularity_measures_turning_angle_variance():
    # The metric is the VARIANCE of turning angles: an outline that turns
    # uniformly (a regular polygon — a flattened circle) is perfectly regular,
    # while injected kinks on an otherwise-smooth outline drag the score down.
    assert irregularity_score(ngon()) == 1.0
    assert irregularity_score(ngon(spikes=(3, 11, 17))) < 0.7


def test_drift_score_identical_outlines_is_one():
    pytest.importorskip("scipy")
    ops = [
        ("moveTo", [(0.0, 0.0)]),
        ("lineTo", [(100.0, 0.0)]),
        ("lineTo", [(100.0, 100.0)]),
        ("lineTo", [(0.0, 100.0)]),
        ("closePath", []),
    ]
    assert drift_score(ops, ops, font_units=1000) == 1.0


def test_composite_is_geometric_mean():
    assert composite(1.0, 1.0, 1.0) == pytest.approx(1.0)
    assert composite(0.8, 0.8, 0.8) == pytest.approx(0.8)
    # One catastrophic component drags the whole score down.
    assert composite(1.0, 1.0, 0.001) < 0.15
