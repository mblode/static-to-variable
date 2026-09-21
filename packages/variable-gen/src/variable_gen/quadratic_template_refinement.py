"""Explicit exact refinement of protected templates and their source groups."""

import json
from copy import deepcopy

from variable_gen.quadratic_reference_templates import exact_reference_template, recording_sha256


def serialize_template_recipe(recipe):
    """Retain exact template coordinates through Glyphs numeric userData rounding."""
    result = deepcopy(recipe)
    if result.get("carrierScale") == 64:
        for template in result["templates"]:
            if not isinstance(template["recording"], str):
                template["recording"] = json.dumps(
                    template["recording"], separators=(",", ":"), allow_nan=False
                )
    return result


def refine_template_groups(recipe, master_groups, *, coalesce=False, subdivisions=1):
    """Rejoin common implied midpoints and optionally halve every quadratic.

    Source curves are untouched. Their group counts are joined in the same
    order as the protected operations. Every resulting protected recording is
    independently checked for exact geometric equivalence before returning.
    """
    if type(coalesce) is not bool or type(subdivisions) is not int or subdivisions not in (1, 2):
        raise ValueError("template refinement requires explicit coalescing and one or two parts")
    result = deepcopy(recipe)
    originals = []
    for template in result["templates"]:
        contours, current = [], []
        for op, points in template["recording"]:
            current.append((op, tuple(tuple(p) for p in points)))
            if op == "closePath":
                contours.append(current)
                current = []
        if current or not contours:
            raise ValueError("template refinement requires closed contours")
        originals.append(contours)
    if not originals or any(
        [len(c) for c in contours] != [len(c) for c in originals[0]] for contours in originals
    ):
        raise ValueError("template refinement requires common protected operation counts")
    if not master_groups or any(
        len(groups) != len(originals[0])
        or any(
            len(counts) != len(contour) or any(type(n) is not int or n < 1 for n in counts)
            for counts, contour in zip(groups, originals[0], strict=True)
        )
        for groups in master_groups
    ):
        raise ValueError("template source groups do not cover every protected operation")
    grouped: list[list[tuple[int, ...]]] = [[] for _ in master_groups]
    recordings: list[list[tuple]] = [[] for _ in originals]
    for ci, contour in enumerate(originals[0]):
        blocks: list[list[int]] = []
        for oi, (op, _) in enumerate(contour):
            merge = coalesce and oi > 0 and op == "qCurveTo" and contour[oi - 1][0] == op
            if merge:
                for contours in originals:
                    previous, following = contours[ci][oi - 1][1], contours[ci][oi][1]
                    if (
                        len(previous) < 2
                        or len(following) < 2
                        or previous[-1]
                        != tuple(
                            (a + b) / 2 for a, b in zip(previous[-2], following[0], strict=True)
                        )
                    ):
                        merge = False
                        break
            if merge:
                blocks[-1].append(oi)
            else:
                blocks.append([oi])
        for mi, groups in enumerate(master_groups):
            grouped[mi].append(tuple(sum(groups[ci][i] for i in block) for block in blocks))
        for ti, contours in enumerate(originals):
            point = None
            for block in blocks:
                op, points = contours[ci][block[0]]
                for oi in block[1:]:
                    points = (*points[:-1], *contours[ci][oi][1])
                if op == "qCurveTo" and subdivisions == 2:
                    controls: list[tuple[float, ...]] = []
                    for i, control in enumerate(points[:-1]):
                        end = (
                            points[-1]
                            if i == len(points) - 2
                            else tuple(
                                (a + b) / 2 for a, b in zip(control, points[i + 1], strict=True)
                            )
                        )
                        if point is None:
                            raise ValueError("quadratic refinement lacks an initial point")
                        controls.extend(
                            [
                                tuple((a + b) / 2 for a, b in zip(point, control, strict=True)),
                                tuple((a + b) / 2 for a, b in zip(control, end, strict=True)),
                            ]
                        )
                        point = end
                    points = (*controls, points[-1])
                recordings[ti].append((op, points))
                if points:
                    point = points[-1]
    for template, recording in zip(result["templates"], recordings, strict=True):
        if not exact_reference_template(template["recording"], recording):
            raise ValueError("template refinement changed protected geometry")
        template["recording"] = [[op, [list(p) for p in points]] for op, points in recording]
        template["recordingSha256"] = recording_sha256(recording)
    return result, tuple(tuple(groups) for groups in grouped)
