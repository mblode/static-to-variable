"""Give every curve an on-curve node where it turns, before cu2qu sees it.

A cubic that reaches its leftmost or topmost point in the middle of a segment
has an extremum with no node on it. Nothing is wrong with the curve -- it is the
shape the donor was drawn with -- but every downstream stage that has to
approximate it does so worst exactly there, and the quadratic conversion has no
node to anchor the turn to. Measured on the 4.0.4 roman, 3076 of 14654 source
segments hide an extremum, across 414 of 754 glyphs.

Splitting a cubic at a parameter is exact: de Casteljau reproduces the same
curve, so this pass changes no shape at all. It only changes where the nodes
are, and it does that while the sources are still float, upstream of the single
rounding cu2qu performs on every point it emits anyway.

THE CROSS-MASTER RULE. gvar requires every master of a glyph to have identical
point structure, so a split cannot be taken per master: master A's `o` finding a
root at 0.51 and master B's at 0.49 would produce the same node count by luck
and a different one wherever a master's curve is flat enough to have no root at
all. Instead the roots of every master are pooled per segment, clustered, and
each cluster becomes one split in EVERY master -- at that master's own root
where it has one, and at the cluster's centre where it does not. Splitting a
segment that did not need it is harmless precisely because the split is exact.

This is the cubic twin of ``insert_extrema`` in the Glide repo's
``scripts/repair-glide-curve-quality.py``, which does the same thing to
quadratics after the build. That one has to round its new nodes to the em grid
and pays for it; this one runs before cu2qu, which was the reason to expect it
to be cheaper.

MEASURED, AND PARKED. It is cheaper and still not free. Built end to end and
audited at wght 400 / opsz 16, roman, against the same build with the pass off:

    missing extrema     2443 -> 9        (what the pass is for)
    curvature sign flips 1126 -> 1470
    roughness p50/p90   8.21/46.37 -> 11.48/67.36
    flagged by is_rough  352 -> 373 of 743

Italic behaves the same way (missing extrema 2496 -> 0, p90 30.24 -> 52.24).
Raising EXTREMUM_EPSILON trades the two off smoothly and never wins: at 20 units
it is 989 missing extrema for 1243 flips and p90 53.52. Roughly one extremum
removed costs a seventh of a sign flip, at every setting tried.

The reason is that cu2qu still has to round the new node, and an extremum is by
definition where the curve is locally flattest, so half a unit of grid error
there is a large *relative* curvature change. Splitting puts a rounding-sensitive
join on precisely the flattest stretch of every curve. Being upstream of the
rounding does not help, because it is the same single rounding either way.

A FINER GRID DOES NOT RESCUE IT EITHER. If the cost is the em grid, a bigger em
should buy it back. Measured by re-rounding the same insertions to finer grids,
4.0.4 release roman at wght 400 / opsz 16:

    grid    ~upem   flagged of 776   sign flips
    float       -       359              1139
    0.125    8000       374              1346
    0.25     4096       383              1418
    0.5      2048       383              1535
    1.0      1000       402              1651

Doubling the em to 2048 recovers about half the cost. Eight times finer still
does not reach float, and the curve is flattening well short of it. So there is
no em Glide could ship at that makes on-curve extrema free; a finer grid only
makes the tension cheaper, never absent.

So this is off by default and no config turns it on. Turning it on is a decision
to value on-curve extrema above measured curve quality; the numbers above are
what that costs. Deleting the module is a reasonable alternative to keeping it.

For Glide specifically the decision looks settled the other way: in review the
defects a human actually marks on these outlines are smoothness complaints --
"the inner loop is not smooth", "where the bowl meets the stem is not perfect"
-- and not one of them is a missing extremum. Trading measured smoothness for
nodes nobody is asking for is the wrong side of this trade for a UI face.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fontTools.misc.bezierTools import solveQuadratic, splitCubicAtT
from fontTools.pens.pointPen import SegmentToPointPen
from fontTools.pens.recordingPen import RecordingPen

Point = tuple[float, float]
Segment = tuple[Any, ...]

#: Roots this close to an endpoint are that endpoint, in parameter space.
PARAMETER_EPSILON = 1e-3

#: An extremum this close to a node it already has, in font units, is that node.
#: Splitting there would add a zero-length segment for no gain.
EXTREMUM_EPSILON = 1.0

#: Roots this close in parameter space are one extremum seen from different
#: masters, and must become one shared split rather than one per master.
CLUSTER_TOLERANCE = 0.12


@dataclass
class ExtremaStats:
    glyphs: int = 0
    segments_split: int = 0
    splits: int = 0
    skipped_incompatible: int = 0
    skipped_non_cubic: int = 0

    def __str__(self) -> str:
        return (
            f"{self.splits} extrema inserted in {self.segments_split} segment(s) "
            f"across {self.glyphs} glyph(s)"
            + (
                f"; {self.skipped_incompatible} glyph(s) skipped as incompatible"
                if self.skipped_incompatible
                else ""
            )
            + (f"; {self.skipped_non_cubic} skipped as non-cubic" if self.skipped_non_cubic else "")
        )


def cubic_extrema(segment: Segment) -> list[float]:
    """Parameters strictly inside a cubic where it turns in x or in y.

    B'(t)/3 = t^2 (u - 2v + w) + t (2v - 2u) + u, for u = P1-P0, v = P2-P1 and
    w = P3-P2, so each axis contributes the roots of one quadratic.
    """
    if segment[0] != "c":
        return []
    _, p0, p1, p2, p3 = segment
    found: list[float] = []
    for axis in (0, 1):
        u = p1[axis] - p0[axis]
        v = p2[axis] - p1[axis]
        w = p3[axis] - p2[axis]
        for t in solveQuadratic(u - 2 * v + w, 2 * (v - u), u):
            if PARAMETER_EPSILON < t < 1 - PARAMETER_EPSILON:
                found.append(t)
    return found


def _point_at(segment: Segment, t: float) -> Point:
    _, p0, p1, p2, p3 = segment
    m = 1 - t
    return (
        m * m * m * p0[0] + 3 * m * m * t * p1[0] + 3 * m * t * t * p2[0] + t * t * t * p3[0],
        m * m * m * p0[1] + 3 * m * m * t * p1[1] + 3 * m * t * t * p2[1] + t * t * t * p3[1],
    )


def needed_splits(segment: Segment) -> list[float]:
    """Split parameters worth taking: a real turn, not a hair from a node."""
    splits = []
    for t in cubic_extrema(segment):
        point = _point_at(segment, t)
        if (
            math.dist(point, segment[1]) > EXTREMUM_EPSILON
            and math.dist(point, segment[4]) > EXTREMUM_EPSILON
        ):
            splits.append(t)
    return sorted(splits)


def cluster_parameters(values: Sequence[float]) -> list[list[float]]:
    clusters: list[list[float]] = []
    for value in sorted(values):
        if clusters and value - clusters[-1][-1] <= CLUSTER_TOLERANCE:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return clusters


def parameters_for_master(clusters: Sequence[Sequence[float]], own: Sequence[float]) -> list[float]:
    """One split per cluster, at this master's own root where it has one.

    Every master gets the same number of splits, which is what keeps the point
    structure identical for gvar, but each lands on its own turning point rather
    than on some other master's.
    """
    chosen: list[float] = []
    for cluster in clusters:
        centre = sum(cluster) / len(cluster)
        candidates = [t for t in own if abs(t - centre) <= CLUSTER_TOLERANCE]
        chosen.append(min(candidates, key=lambda t: abs(t - centre)) if candidates else centre)
    return sorted(chosen)


def split_segment(segment: Segment, parameters: Sequence[float]) -> list[Segment]:
    """Split one cubic at several parameters, exactly."""
    if not parameters or segment[0] != "c":
        return [segment]
    pieces = splitCubicAtT(segment[1], segment[2], segment[3], segment[4], *parameters)
    return [("c", *piece) for piece in pieces]


def _contour_segments(contour) -> list[Segment] | None:
    """One contour as a list of segments, or None if it is not all cubic.

    Read through a pen rather than off the point list so that the closing
    segment of a closed contour is already present as a segment, whatever point
    types the source used.
    """
    pen = RecordingPen()
    contour.draw(pen)
    segments: list[Segment] = []
    here: Point | None = None
    for op, args in pen.value:
        if op == "moveTo":
            here = args[0]
        elif op == "lineTo":
            segments.append(("l", here, args[0]))
            here = args[0]
        elif op == "curveTo":
            if len(args) != 3:
                return None  # a super-cubic, which splitCubicAtT cannot take
            segments.append(("c", here, *args))
            here = args[-1]
        elif op == "qCurveTo":
            return None
    return segments


def _draw_segments(pen, segments: Sequence[Segment]) -> None:
    pen.moveTo(segments[0][1])
    for segment in segments:
        if segment[0] == "l":
            pen.lineTo(segment[2])
        else:
            pen.curveTo(segment[2], segment[3], segment[4])
    pen.closePath()


def _structure(segments: Sequence[Segment]) -> tuple[str, ...]:
    return tuple(segment[0] for segment in segments)


def insert_extrema(fonts: Sequence[Any]) -> ExtremaStats:
    """Add an on-curve node at every extremum, in every master at once.

    ``fonts`` are the masters of one designspace, as font objects supporting
    ``__contains__``/``__getitem__`` by glyph name -- ufoLib2 fonts, as
    glyphsLib hands them over. They are mutated in place.
    """
    stats = ExtremaStats()
    if not fonts:
        return stats

    for name in sorted(fonts[0].keys()):
        if any(name not in font for font in fonts):
            continue
        glyphs = [font[name] for font in fonts]
        if not any(len(glyph.contours) for glyph in glyphs):
            continue

        per_master = [[_contour_segments(c) for c in glyph.contours] for glyph in glyphs]
        if any(segments is None for master in per_master for segments in master):
            stats.skipped_non_cubic += 1
            continue

        reference = per_master[0]
        if any(len(master) != len(reference) for master in per_master) or any(
            _structure(master[i]) != _structure(reference[i])
            for master in per_master
            for i in range(len(reference))
        ):
            # Masters that do not already agree on point structure are not this
            # pass's to repair, and splitting them would only make the mismatch
            # harder to read.
            stats.skipped_incompatible += 1
            continue

        rebuilt: list[list[list[Segment]]] = [[] for _ in per_master]
        touched = False
        for contour_index in range(len(reference)):
            own = [master[contour_index] for master in per_master]
            out: list[list[Segment]] = [[] for _ in own]
            for segment_index in range(len(reference[contour_index])):
                roots = [needed_splits(master[segment_index]) for master in own]
                clusters = cluster_parameters([t for master in roots for t in master])
                if clusters:
                    touched = True
                    stats.segments_split += 1
                    stats.splits += len(clusters)
                for index, master in enumerate(own):
                    parameters = parameters_for_master(clusters, roots[index]) if clusters else []
                    out[index].extend(split_segment(master[segment_index], parameters))
            for index in range(len(own)):
                rebuilt[index].append(out[index])

        if not touched:
            continue
        stats.glyphs += 1
        for glyph, contours in zip(glyphs, rebuilt, strict=True):
            glyph.clearContours()
            pen = SegmentToPointPen(glyph.getPointPen())
            for segments in contours:
                _draw_segments(pen, segments)

    return stats
