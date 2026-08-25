"""Generic contour I/O for cubic outlines.

This module reads glyphs into contours, flattens them for scanline work, and
draws them back through a segment pen. It knows nothing about glyph
classification, donor files, font metadata, or CLI policy.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from fontTools.pens.recordingPen import RecordingPen

Point = tuple[float, float]
SegmentKind = Literal["l", "c"]
Segment = tuple[SegmentKind, tuple[Point, ...]]
Contour = list[Segment]
Contours = list[Contour]
LineSegment = tuple[Point, Point]


class DrawableGlyph(Protocol):
    def draw(self, pen: Any) -> None: ...


class GlyphSet(Protocol):
    def __getitem__(self, name: str) -> DrawableGlyph: ...


class SegmentPen(Protocol):
    def moveTo(self, point: Point) -> None: ...

    def lineTo(self, point: Point) -> None: ...

    def curveTo(self, *points: Point) -> None: ...

    def closePath(self) -> None: ...


__all__ = [
    "Contour",
    "Contours",
    "LineSegment",
    "Point",
    "Segment",
    "SegmentKind",
    "contours_of",
    "draw_contours",
    "flatten_contours",
    "runs_at",
    "widest_run",
]


def contours_of(glyph_set: GlyphSet, name: str) -> Contours:
    """Draw a glyph into a list of contours, each a list of ``(kind, points)``.

    ``kind`` is ``"l"`` for a line or ``"c"`` for a cubic; points always end at
    the on-curve point, so a contour is a closed ring of segments.
    """
    recording = RecordingPen()
    glyph_set[name].draw(recording)
    contours: Contours = []
    current: Contour = []
    start: Point | None = None
    here: Point | None = None
    for op, args in recording.value:
        if op == "moveTo":
            if current:
                contours.append(current)
            current, start = [], args[0]
            here = start
        elif op == "lineTo":
            if here is None:
                raise RuntimeError(f"{name}: line before moveTo")
            current.append(("l", (here, args[0])))
            here = args[0]
        elif op == "curveTo":
            if here is None:
                raise RuntimeError(f"{name}: curve before moveTo")
            current.append(("c", (here, *args)))
            here = args[-1]
        elif op == "qCurveTo":
            raise RuntimeError(f"{name}: quadratic outlines are not supported")
        elif op == "closePath" and here is not None and start is not None:
            if here != start:
                current.append(("l", (here, start)))
            here = start
        elif op == "addComponent":
            raise RuntimeError(f"{name}: unexpected component in a CFF glyph set")
    if current:
        contours.append(current)
    return contours


def _contour_is_ccw(contour):
    """Signed area test, to know which way the normal points out of the ink."""
    area = 0.0
    for _, pts in contour:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
            area += x0 * y1 - x1 * y0
    return area > 0


def flatten_contours(contours: Contours, steps: int = 12) -> list[LineSegment]:
    """Contours as line segments, for scanline work only."""
    segments = []
    for contour in contours:
        for kind, pts in contour:
            if kind == "l":
                segments.append((pts[0], pts[1]))
            else:
                p0, p1, p2, p3 = pts
                prev = p0
                for i in range(1, steps + 1):
                    t, u = i / steps, 1 - i / steps
                    point = (
                        u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
                        u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
                    )
                    segments.append((prev, point))
                    prev = point
    return segments


def runs_at(segments: list[LineSegment], y: float) -> list[tuple[float, float]]:
    """Ink intervals where a horizontal line at ``y`` crosses the outline.

    Uses the nonzero winding rule, matching how the outline is actually filled.
    """
    crossings = []
    for (x0, y0), (x1, y1) in segments:
        if (y0 <= y < y1) or (y1 <= y < y0):
            crossings.append((x0 + (y - y0) * (x1 - x0) / (y1 - y0), 1 if y1 > y0 else -1))
    if not crossings:
        return []
    crossings.sort()
    runs, winding, start = [], 0, None
    for x, direction in crossings:
        was_inside = winding != 0
        winding += direction
        if not was_inside and winding != 0:
            start = x
        elif was_inside and winding == 0 and start is not None:
            runs.append((start, x))
    return runs


def widest_run(segments: list[LineSegment], y: float) -> float:
    runs = runs_at(segments, y)
    return max((b - a for a, b in runs), default=0.0)


def draw_contours(contours: Contours, pen: SegmentPen) -> None:
    for contour in contours:
        if not contour:
            continue
        pen.moveTo(contour[0][1][0])
        for kind, pts in contour:
            if kind == "l":
                pen.lineTo(pts[1])
            else:
                pen.curveTo(pts[1], pts[2], pts[3])
        pen.closePath()
