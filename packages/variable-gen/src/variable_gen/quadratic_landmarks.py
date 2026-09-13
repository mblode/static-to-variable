"""Inactive preparation of an authenticated shared semantic quadratic basis.

This pure seam does not change build defaults or Display acceptance. Protected
masters retain their exact spans; intermediate interpolation uses a new basis.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

import numpy as np
from fontTools.pens.areaPen import AreaPen


@dataclass(frozen=True)
class LandmarkMaster:
    curves: tuple
    landmarks: tuple[tuple[str, int], ...]
    recording_sha256: str
    protected: bool = False
    corner_roles: frozenset[str] = frozenset()


@dataclass(frozen=True)
class LandmarkBasis:
    sources: tuple
    groups: tuple
    protected: dict
    slots: tuple[int, ...]


def curves_sha256(curves) -> str:
    return hashlib.sha256(
        json.dumps(
            np.asarray(curves, dtype=float).tolist(), separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _record(curves):
    return (
        [("moveTo", (tuple(curves[0][0]),))]
        + [("curveTo", tuple(map(tuple, c[1:]))) for c in curves]
        + [("closePath", ())]
    )


def _area(curves):
    pen = AreaPen(None)
    for op, points in _record(curves):
        getattr(pen, op)(*points)
    return pen.value


def _section(c, start, end):
    def split(c, t):
        a, b, d = (1 - t) * c[:-1] + t * c[1:]
        e, f = (1 - t) * a + t * b, (1 - t) * b + t * d
        g = (1 - t) * e + t * f
        return np.array([c[0], a, e, g]), np.array([g, f, d, c[-1]])

    if start == 0:
        return split(c, end)[0]
    return split(split(c, start)[1], (end - start) / (1 - start))[0]


def _length(c):
    ts = np.linspace(0, 1, 65)[:, None]
    ps = (
        (1 - ts) ** 3 * c[0]
        + 3 * (1 - ts) ** 2 * ts * c[1]
        + 3 * (1 - ts) * ts**2 * c[2]
        + ts**3 * c[3]
    )
    return float(np.linalg.norm(np.diff(ps, axis=0), axis=1).sum())


def _validate(master, roles, winding):
    curves = np.asarray(master.curves, dtype=float)
    if curves.ndim != 3 or curves.shape[1:] != (4, 2) or not np.isfinite(curves).all():
        raise ValueError("landmark masters require finite cubic contours")
    if curves_sha256(curves) != master.recording_sha256:
        raise ValueError("landmark master recording hash mismatch")
    if any(
        np.linalg.norm(a[-1] - b[0]) > 1e-9
        for a, b in zip(curves, np.roll(curves, -1, axis=0), strict=True)
    ):
        raise ValueError("landmark master must be a continuous closed contour")
    if _area(curves) * winding <= 0:
        raise ValueError("landmark master winding mismatch")
    names = tuple(name for name, _ in master.landmarks)
    indices = [index for _, index in master.landmarks]
    if names != roles or len(set(names)) != len(names):
        raise ValueError("landmark roles must be identical and ordered in every master")
    if (
        len(indices) < 2
        or indices[0] != 0
        or indices[-1] != len(curves)
        or any(type(i) is not int for i in indices)
        or any(a >= b for a, b in zip(indices, indices[1:], strict=False))
    ):
        raise ValueError("landmarks must strictly partition the complete contour")
    lookup = dict(master.landmarks)
    for role in master.corner_roles:
        if role not in lookup or lookup[role] == len(curves):
            raise ValueError("required corner role is missing")
        i = lookup[role]
        a, b = curves[i][0] - curves[i - 1][-2], curves[i][1] - curves[i][0]
        denominator = np.linalg.norm(a) * np.linalg.norm(b)
        if denominator < 1e-12 or np.dot(a, b) / denominator >= math.sqrt(0.5):
            raise ValueError("required corner role does not identify a sharp corner")
    return curves


def _native_slots(curves, count):
    lengths = [_length(c) for c in curves]
    total = sum(lengths)
    if total <= 0:
        raise ValueError("landmark sections must have positive length")
    positions, prior, distance = [], -1, 0.0
    for i, length in enumerate(lengths):
        slot = max(prior + 1, min(count - (len(curves) - i), round(distance / total * count)))
        positions.append(slot)
        prior, distance = slot, distance + length
    result, index, point = [], 0, curves[0][0]
    for slot in range(count):
        if index < len(curves) and positions[index] == slot:
            result.append(curves[index])
            point = curves[index][-1]
            index += 1
        else:
            result.append(np.array([point] * 4))
    return result


def _dyadic_slots(curves, count):
    """Fill capacity with exact halves/quarters before stationary end slots."""
    parts = [(curve, 0) for curve in curves]
    while len(parts) < count:
        choices = [i for i, (_, depth) in enumerate(parts) if depth < 2]
        if not choices:
            parts.append((np.array([parts[-1][0][-1]] * 4), 2))
            continue
        index = max(choices, key=lambda i: _length(parts[i][0]))
        curve, depth = parts[index]
        parts[index : index + 1] = [
            (_section(curve, 0, 0.5), depth + 1),
            (_section(curve, 0.5, 1), depth + 1),
        ]
    return [curve for curve, _ in parts]


def _authored_slots(curves, count):
    lengths = np.array([_length(c) for c in curves])
    if np.any(lengths <= 0):
        raise ValueError("authored sections require nonstationary source curves")
    cum = np.cumsum([0, *lengths])
    knots = [0.0]
    for distance in np.linspace(0, cum[-1], count + 1)[1:]:
        i = min(len(curves) - 1, np.searchsorted(cum, distance, side="right") - 1)
        knots.append(i + (distance - cum[i]) / lengths[i])
    knots[-1] = float(len(curves))
    pieces, groups = [], []
    for start, end in zip(knots, knots[1:], strict=False):
        part = [
            _section(c, max(start, i) - i, min(end, i + 1) - i)
            for i, c in enumerate(curves)
            if min(end, i + 1) - max(start, i) > 1e-10
        ]
        if not part:
            raise ValueError("authored landmark slot has no curve")
        pieces.extend(part)
        groups.append(len(part))
    return pieces, groups


def prepare_landmark_basis(masters, *, native_partition="stationary") -> LandmarkBasis:
    """Return grouped exact source subdivisions and protected quadratic slots.

    By default additional native slots collapse at an endpoint. The explicit
    quarters mode instead subdivides each protected span exactly four times;
    it requires matching native span counts in every semantic region. Dyadic
    mode balances differing counts with exact halves/quarters, then stationary
    end capacity if necessary. Native spans are never fitted or moved. Named
    roles bind the entire master set.
    """
    if native_partition not in ("stationary", "quarters", "dyadic"):
        raise ValueError("unknown native landmark partition")
    if (
        len(masters) < 2
        or not any(m.protected for m in masters)
        or all(m.protected for m in masters)
    ):
        raise ValueError("landmark basis requires authored and protected masters")
    authored_corners = {m.corner_roles for m in masters if not m.protected}
    if len(authored_corners) != 1:
        raise ValueError("authored masters must bind the same required corner roles")
    roles = tuple(name for name, _ in masters[0].landmarks)
    if not masters[0].curves:
        raise ValueError("landmark masters require finite cubic contours")
    winding = _area(masters[0].curves)
    curves = [_validate(m, roles, winding) for m in masters]
    native_counts = [
        [m.landmarks[j + 1][1] - m.landmarks[j][1] for m in masters if m.protected]
        for j in range(len(roles) - 1)
    ]
    if native_partition == "quarters" and any(len(set(counts)) != 1 for counts in native_counts):
        raise ValueError("quarter partition requires matching protected landmark span counts")
    multiplier = {"quarters": 4, "stationary": 2, "dyadic": 1}[native_partition]
    slots = tuple(multiplier * max(counts) for counts in native_counts)
    sources, groups, protected = [], [], {}
    for mi, master in enumerate(masters):
        output: list[np.ndarray] = []
        grouping = [1]
        for j, count in enumerate(slots):
            region = curves[mi][master.landmarks[j][1] : master.landmarks[j + 1][1]]
            if master.protected:
                pieces = (
                    [_section(c, j / 4, (j + 1) / 4) for c in region for j in range(4)]
                    if native_partition == "quarters"
                    else _dyadic_slots(region, count)
                    if native_partition == "dyadic"
                    else _native_slots(region, count)
                )
                counts = [1] * count
            else:
                pieces, counts = _authored_slots(region, count)
            output.extend(pieces)
            grouping.extend(counts)
        sources.append(_record(output))
        groups.append([*grouping, 1])
        if master.protected:
            operations: list[tuple[str, tuple]] = [("moveTo", (tuple(output[0][0]),))]
            for c in output:
                a, b = (3 * c[1] - c[0]) / 2, (3 * c[2] - c[3]) / 2
                if np.linalg.norm(a - b) > 1e-8:
                    raise ValueError("protected landmark source is not an exact quadratic")
                operations.append(("qCurveTo", (tuple((a + b) / 2), tuple(c[-1]))))
            operations.append(("closePath", ()))
            protected[mi] = operations
    return LandmarkBasis(tuple(sources), tuple(groups), protected, slots)
