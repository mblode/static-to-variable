"""Pure outline helpers shared by the rebuild/build/bootstrap pipeline.

These read donor CFF/glyf outlines and write them into glyphsLib layers,
preserving cubic segment structure. Kept dependency-light (fontTools only) and
inside the package so the installed engine has them without the scripts/ dir.
"""

from __future__ import annotations

from fontTools.pens.recordingPen import DecomposingRecordingPen

# One drawing op: ("moveTo", [pt]) / ("curveTo", [c1, c2, end]) / ("closePath", []).
# A qCurveTo point may be None: the implied on-curve endpoint of an all-off-curve
# TrueType contour, which round-trips straight back through the pen.
Segment = tuple[str, list[tuple[float, ...] | None]]
Contour = list[Segment]


def donor_outline(glyphset, name):
    """Return (contours, width) or None if the glyph can't be drawn.

    contours: list of contours, each a list of (op, [pt,...]) preserving the
    cubic segment structure straight from the donor CFF outline.
    """
    if name not in glyphset:
        return None
    pen = DecomposingRecordingPen(glyphset)
    try:
        glyphset[name].draw(pen)
    except Exception:  # noqa: BLE001
        return None
    contours: list[Contour] = []
    cur: Contour = []
    for op, args in pen.value:
        if op == "moveTo":
            cur = [("moveTo", [tuple(args[0])])]
        elif op == "lineTo":
            cur.append(("lineTo", [tuple(args[0])]))
        elif op == "curveTo":
            cur.append(("curveTo", [tuple(p) for p in args]))
        elif op == "qCurveTo":
            # An all-off-curve TrueType contour ends with an implied on-curve
            # point the pen reports as None; keep it so draw_into round-trips it.
            cur.append(("qCurveTo", [tuple(p) if p is not None else None for p in args]))
        elif op in ("closePath", "endPath"):
            cur.append((op, []))
            contours.append(cur)
            cur = []
    return contours, glyphset[name].width


def _winding(points):
    if len(points) < 3:
        return 0
    s = sum(
        points[i][0] * points[(i + 1) % len(points)][1]
        - points[(i + 1) % len(points)][0] * points[i][1]
        for i in range(len(points))
    )
    return 1 if s > 0 else (-1 if s < 0 else 0)


def signature(contours):
    """(op-sequence, winding) per contour — a cheap pre-filter for direct copy.

    A few glyphs pass this yet still interpolate incompatibly (a contour starts
    at a different node across weights, e.g. dollar). Those are caught after the
    fact by the interpolatable pass rather than guessed at here.
    """
    sig = []
    for con in contours:
        ops = tuple(op for op, _ in con if op in ("moveTo", "lineTo", "curveTo", "qCurveTo"))
        # Skip an all-off-curve contour's implied (None) endpoint in the winding poly.
        pts = [p[-1] for op, p in con if p and p[-1] is not None]
        sig.append((ops, _winding(pts)))
    return tuple(sig)


def draw_into(layer, contours):
    layer.paths = []
    layer.components = []
    pen = layer.getPen()
    for con in contours:
        for op, pts in con:
            if op == "moveTo":
                pen.moveTo(pts[0])
            elif op == "lineTo":
                pen.lineTo(pts[0])
            elif op == "curveTo":
                pen.curveTo(*pts)
            elif op == "qCurveTo":
                pen.qCurveTo(*pts)
            elif op == "closePath":
                pen.closePath()
            elif op == "endPath":
                pen.endPath()
