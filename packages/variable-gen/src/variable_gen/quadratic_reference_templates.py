"""Exact, explicitly selected reference representations before grouped conversion.

Templates may elevate straight lines, add stationary spans and rotate contour
starts. They must retain the same ordered quadratic spans and winding. This does
not waive source, compiled, or downstream variation-preservation gates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from fontTools.pens.basePen import BasePen
from fontTools.pens.recordingPen import RecordingPen, replayRecording

from variable_gen.common import PipelineError

REFERENCE_TEMPLATES_KEY = "com.mblode.stv.quadraticReferenceTemplates"
REFERENCE_TEMPLATE = "reference-template"


def recording_sha256(recording) -> str:
    normalized = [
        (op, [None if p is None else [float(v) for v in p] for p in points])
        for op, points in recording
    ]
    return hashlib.sha256(
        json.dumps(normalized, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _same(a, b):
    return len(a) == len(b) and all(
        math.isclose(x, y, abs_tol=1e-9, rel_tol=0) for x, y in zip(a, b, strict=True)
    )


class _Spans(BasePen):
    def __init__(self):
        super().__init__(None)
        self.contours = []
        self.current = []
        self.start = None
        self.point = None

    def _moveTo(self, point):
        if self.start is not None:
            raise ValueError("unclosed reference contour")
        self.start = self.point = point

    def _lineTo(self, point):
        if self.point is None:
            raise ValueError("reference line has no start")
        self.current.append(("line", self.point, point))
        self.point = point

    def _qCurveToOne(self, control, point):
        if self.point is None:
            raise ValueError("quadratic reference has no start")
        midpoint = tuple((a + b) / 2 for a, b in zip(self.point, point, strict=True))
        if _same(control, midpoint):
            self._lineTo(point)
        else:
            self.current.append(("quadratic", self.point, control, point))
            self.point = point

    def _curveToOne(self, *points):
        raise ValueError("reference templates must be quadratic")

    def _closePath(self):
        if self.point is None or self.start is None:
            raise ValueError("reference close has no start")
        if not _same(self.point, self.start):
            self._lineTo(self.start)
        self.contours.append(self.current)
        self.current = []
        self.start = self.point = None

    def _endPath(self):
        raise ValueError("reference templates must be closed")


def _merge(a, b):
    if a[0] != "line" or b[0] != "line" or not _same(a[-1], b[1]):
        return None
    start, joint, end = a[1], a[-1], b[-1]
    direction = (end[0] - start[0], end[1] - start[1])
    cross = (joint[0] - start[0]) * direction[1] - (joint[1] - start[1]) * direction[0]
    if abs(cross) > 1e-9 or any(
        not min(x, z) - 1e-9 <= y <= max(x, z) + 1e-9
        for x, y, z in zip(start, joint, end, strict=True)
    ):
        return None
    return ("line", start, end)


def _canonical(recording):
    pen = _Spans()
    for op, points in recording:
        if op not in {"moveTo", "lineTo", "qCurveTo", "closePath"}:
            raise ValueError("unsupported reference-template operation")
        if (
            (op in {"moveTo", "lineTo"} and len(points) != 1)
            or (op == "closePath" and points)
            or (op == "qCurveTo" and len(points) < 2)
            or any(point is None for point in points)
        ):
            raise ValueError("invalid reference-template operation arguments")
        for point in points:
            if point is not None and (len(point) != 2 or not all(map(math.isfinite, point))):
                raise ValueError("reference template has nonfinite coordinates")
    replayRecording(recording, pen)
    if pen.start is not None or not pen.contours:
        raise ValueError("reference template has an open or empty outline")
    contours = []
    for spans in pen.contours:
        kept = [s for s in spans if not all(_same(s[1], p) for p in s[2:])]
        if not kept:
            raise ValueError("reference template has an empty contour")
        changed = True
        while changed and len(kept) > 1:
            changed = False
            for i in range(len(kept)):
                j = (i + 1) % len(kept)
                merged = _merge(kept[i], kept[j])
                if merged is not None:
                    if j == 0:
                        kept = [merged, *kept[1:i]]
                    else:
                        kept[i : j + 1] = [merged]
                    changed = True
                    break
        contours.append(kept)
    return contours


def exact_reference_template(original, template) -> bool:
    """Compare exact cyclic span programs, never reversed contours or sampled ink."""
    left, right = _canonical(original), _canonical(template)
    if len(left) != len(right):
        return False
    for a, b in zip(left, right, strict=True):
        if len(a) != len(b):
            return False
        if not any(
            all(
                x[0] == y[0]
                and len(x) == len(y)
                and all(_same(p, q) for p, q in zip(x[1:], y[1:], strict=True))
                for x, y in zip(a, b[k:] + b[:k], strict=True)
            )
            for k in range(len(b))
        ):
            return False
    return True


def _resolve_native_roundoff(original, template):
    # Cubic degree elevation followed by algebraic recovery can leave ~1e-14
    # noise. Resolve only to an existing original native point or exact line
    # midpoint; never quantize the reference to an invented precision grid.
    spans = _Spans()
    replayRecording(original, spans)
    points: set[tuple[float, ...]] = set()
    for contour in spans.contours:
        for span in contour:
            points.update(tuple(p) for p in span[1:])
            if span[0] == "line":
                points.add(tuple((a + b) / 2 for a, b in zip(span[1], span[2], strict=True)))
    normalized = []
    for operation, coordinates in template:
        resolved: list[tuple[float, ...] | None] = []
        for point in coordinates:
            if point is None:
                resolved.append(None)
                continue
            matches = [p for p in points if _same(p, point)]
            if len(matches) > 1:
                raise ValueError("reference point has ambiguous native roundoff correspondence")
            resolved.append(matches[0] if matches else tuple(point))
        normalized.append((operation, tuple(resolved)))
    return normalized


def load_reference_templates(fonts, placements, originals, reference_path: Path, locations):
    """Validate every protected location and return authenticated pen recordings."""
    names = {
        name for font in fonts for name in font.keys() if REFERENCE_TEMPLATES_KEY in font[name].lib
    }
    expected = {name for name, mode in placements.items() if mode == REFERENCE_TEMPLATE}
    if names != expected:
        raise PipelineError("reference-template mode and metadata must agree")
    result = {}
    reference_hash = hashlib.sha256(reference_path.read_bytes()).hexdigest() if names else None
    for name in sorted(names):
        try:
            values = [font[name].lib[REFERENCE_TEMPLATES_KEY] for font in fonts]
            if any(value != values[0] for value in values[1:]):
                raise ValueError("metadata differs across masters")
            recipe = values[0]
            if (
                not isinstance(recipe, dict)
                or set(recipe)
                != {"schemaVersion", "glyph", "glyphRowsSha256", "referenceSha256", "templates"}
                or type(recipe["schemaVersion"]) is not int
                or recipe["schemaVersion"] != 1
            ):
                raise ValueError("invalid recipe schema")
            if recipe["glyph"] != name or recipe["referenceSha256"] != reference_hash:
                raise ValueError("reference source binding changed")
            if (
                not isinstance(recipe["glyphRowsSha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", recipe["glyphRowsSha256"]) is None
            ):
                raise ValueError("invalid authored row binding")
            templates = recipe["templates"]
            if not isinstance(templates, (list, tuple)) or len(templates) != len(locations):
                raise ValueError("templates must bind every protected location")
            resolved = {}
            for item in templates:
                if not isinstance(item, dict) or set(item) != {
                    "location",
                    "originalRecordingSha256",
                    "recordingSha256",
                    "recording",
                }:
                    raise ValueError("invalid template schema")
                matching = [i for i, loc in locations.items() if loc == item["location"]]
                if len(matching) != 1 or matching[0] in resolved:
                    raise ValueError("template location is missing or repeated")
                index = matching[0]
                original = originals[name][index].value
                template = item["recording"]
                if (
                    recording_sha256(original) != item["originalRecordingSha256"]
                    or recording_sha256(template) != item["recordingSha256"]
                ):
                    raise ValueError("template recording hash changed")
                if not exact_reference_template(original, template):
                    raise ValueError("template changes exact protected geometry or winding")
                template = _resolve_native_roundoff(original, template)
                if not exact_reference_template(original, template):
                    raise ValueError("native roundoff resolution changed reference geometry")
                pen = RecordingPen()
                pen.value = [
                    (op, tuple(None if p is None else tuple(p) for p in points))
                    for op, points in template
                ]
                resolved[index] = pen
            result[name] = resolved
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
            raise PipelineError(f"{name}: invalid reference template: {error}") from error
    return result
