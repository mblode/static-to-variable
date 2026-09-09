from copy import deepcopy
from io import BytesIO

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.roundTools import otRound
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.varLib.iup import iup_delta

from variable_gen.common import PipelineError
from variable_gen.variation_reference import NativeIupTransport
from variable_gen.variation_reference import restore_reference_inference
from variable_gen.variation_reference import restore_reference_true_default
from variable_gen.variation_reference import restore_reference_with_prefixes
from variable_gen.variation_reference import restore_endpoint_iup_default


def fonts():
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "curve"])
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((100, 0))
    pen.qCurveTo((50, 149), (0, 0))
    pen.closePath()
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "curve": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (200, 0), "curve": (200, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupCharacterMap({99: "curve"})
    builder.setupNameTable({"familyName": "Inference", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    builder.setupFvar([("wght", 100, 400, 950, "Weight"), ("opsz", 14, 14, 32, "Optical size")], [])
    reference = builder.font
    reference["gvar"] = newTable("gvar")
    reference["gvar"].variations = {
        ".notdef": [],
        "curve": [TupleVariation({"wght": (0, 1, 1)}, [(0, 0), (1, 0), None] + [(0, 0)] * 4)],
    }
    candidate = deepcopy(reference)
    coords, controls = reference["glyf"]._getCoordinatesAndControls(
        "curve", reference["hmtx"].metrics
    )
    expanded = iup_delta(
        reference["gvar"].variations["curve"][0].coordinates, coords, controls.endPts
    )
    candidate["gvar"].variations["curve"][0].coordinates = [
        tuple(otRound(value) for value in point) for point in expanded
    ]
    candidate["glyf"]["curve"].coordinates.translate((0, 46))
    candidate["gvar"].variations["curve"].append(
        TupleVariation({"opsz": (0, 1, 1)}, [(0, -46)] * 3 + [(0, 0)] * 4)
    )
    return reference, candidate


def recording(font, weight, optical):
    pen = RecordingPen()
    font.getGlyphSet(location={"wght": weight, "opsz": optical})["curve"].draw(pen)
    return pen.value


def endpoint_fonts():
    reference, _ = fonts()
    high = reference["gvar"].variations["curve"][0]
    reference["gvar"].variations["curve"].insert(
        0, TupleVariation({"wght": (-1.0, -1.0, 0.0)}, [(0, 0)] * 7)
    )
    candidate = deepcopy(reference)
    helper_name = "curve.stv-semantic16x"
    pen = TTGlyphPen(None)
    pen.moveTo((0, 736))
    pen.qCurveTo((800, 3120), (1600, 736))
    pen.qCurveTo((1600, 736), (1600, 736))
    pen.closePath()
    candidate["glyf"][helper_name] = pen.glyph()
    candidate["hmtx"].metrics[helper_name] = (3200, 0)
    candidate.setGlyphOrder([".notdef", "curve", helper_name])
    pen = TTGlyphPen(candidate.getGlyphSet())
    pen.addComponent(helper_name, (0.0625, 0, 0, 0.0625, 0, 0))
    candidate["glyf"]["curve"] = pen.glyph()
    candidate["gvar"].variations["curve"] = []
    candidate["gvar"].variations[helper_name] = [
        TupleVariation(high.axes, [(0, 0), (8, 0), (16, 0), (16, 0), (16, 0)] + [(0, 0)] * 4),
        TupleVariation({"opsz": (0.0, 1.0, 1.0)}, [(0, -736)] * 5 + [(0, 0)] * 4),
    ]
    return reference, candidate, helper_name


@pytest.mark.parametrize("preserve_direction", [False, True])
def test_endpoint_transport_keeps_text_default_and_serialized_native_display(preserve_direction):
    import pathops
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    from variable_gen.quadratic_reference import _filled_path

    reference, candidate, helper = endpoint_fonts()
    if preserve_direction:
        glyph = candidate["glyf"][helper]
        order = [0, *range(len(glyph.coordinates) - 1, 0, -1)]
        glyph.coordinates = type(glyph.coordinates)([glyph.coordinates[i] for i in order])
        glyph.flags = type(glyph.flags)("B", [glyph.flags[i] for i in order])
        for variation in candidate["gvar"].variations[helper]:
            variation.coordinates = [
                variation.coordinates[i] for i in order
            ] + variation.coordinates[-4:]
    before = deepcopy(candidate["glyf"][helper].coordinates)
    report = restore_endpoint_iup_default(
        reference, candidate, "curve", helper, endpoint_points=frozenset({1}), fixed_coordinates={}
    )
    assert report["endpointPoints"] == 2
    assert candidate["glyf"][helper].coordinates == before
    stream = BytesIO()
    candidate.save(stream)
    stream.seek(0)
    candidate = TTFont(stream)
    for weight in (100, 400, 537.25, 949.75, 950):
        ref_pen, actual_pen = (
            RecordingPen(),
            DecomposingRecordingPen(candidate.getGlyphSet(location={"wght": weight, "opsz": 32})),
        )
        reference.getGlyphSet(location={"wght": weight, "opsz": 32})["curve"].draw(ref_pen)
        actual_pen.glyphSet["curve"].draw(actual_pen)
        assert (
            pathops.op(_filled_path(ref_pen), _filled_path(actual_pen), pathops.PathOp.XOR).area
            == 0
        )


def endpoint_recipe():
    return {
        "schemaVersion": 2,
        "placement": "semantic-partition",
        "glyph": "curve",
        "glyphRowsSha256": "a" * 64,
        "referenceSha256": "b" * 64,
        "nativeEndpointPoints": [1],
        "flatTextY": 46,
        "coordinateScale": 16,
        "maxCoordinateMove": 1000,
    }


@pytest.mark.parametrize("changed_reference", [False, True])
def test_ordinary_build_restores_serialized_endpoints_before_fidelity(
    tmp_path, monkeypatch, changed_reference
):
    import hashlib
    from types import SimpleNamespace
    from fontTools.designspaceLib import DesignSpaceDocument
    from variable_gen import build
    from variable_gen.variation_reference import ENDPOINT_TRANSPORTS_KEY

    reference, candidate, helper = endpoint_fonts()
    ref_path, out_path = tmp_path / "native.ttf", tmp_path / "built.ttf"
    reference.save(ref_path)
    candidate.save(out_path)
    original_bytes = out_path.read_bytes()
    recipe = endpoint_recipe()
    recipe["referenceSha256"] = hashlib.sha256(ref_path.read_bytes()).hexdigest()
    if changed_reference:
        recipe["referenceSha256"] = "0" * 64
    ds = DesignSpaceDocument()
    ds.lib[ENDPOINT_TRANSPORTS_KEY] = {"curve": recipe}
    ds_path = tmp_path / "fixture.designspace"
    ds.write(ds_path)
    style = SimpleNamespace(
        source=ref_path,
        output=out_path,
        optimize_gvar=False,
        preserve_authored_deltas=False,
        quadratic_reference=SimpleNamespace(path=ref_path),
    )
    config = SimpleNamespace(styles={"roman": style}, repo_root=tmp_path)
    monkeypatch.setattr(
        build, "inspect_authored_source", lambda *_: SimpleNamespace(glyphs=frozenset())
    )
    monkeypatch.setattr(build, "fontmake_command", lambda *_: "unused")
    monkeypatch.setattr(build, "export_designspace", lambda *_: ds_path)
    # The claim starts with an already-compiled font; no donor rebuild is needed.
    monkeypatch.setattr(build, "_run", lambda *_: SimpleNamespace(returncode=0))

    class ReachedFidelity(Exception):
        pass

    def inspect_compiled(*_):
        with TTFont(out_path) as actual:
            assert len(actual["gvar"].variations[helper]) == 6
            assert actual["glyf"][helper].coordinates == candidate["glyf"][helper].coordinates
        raise ReachedFidelity

    monkeypatch.setattr(build, "_collapse_findings", inspect_compiled)
    if changed_reference:
        with pytest.raises(PipelineError, match="reference changed after source export"):
            build.build_style(config, "roman")
        assert out_path.read_bytes() == original_bytes
    else:
        with pytest.raises(ReachedFidelity):
            build.build_style(config, "roman")


@pytest.mark.parametrize(
    "failure", [None, "late-recipe", "caps", "boolean", "bound", "missing-helper"]
)
def test_endpoint_batch_matches_direct_transport_or_leaves_candidate_untouched(failure):
    from variable_gen.variation_reference import apply_endpoint_transports

    reference, candidate, helper = endpoint_fonts()
    original = deepcopy(candidate)
    recipe = endpoint_recipe()
    recipes = {"curve": recipe}
    if failure == "late-recipe":
        recipes["zmissing"] = {**recipe, "glyph": "zmissing"}
    elif failure == "caps":
        recipe["flatTextY"] = 47
    elif failure == "boolean":
        recipe["schemaVersion"] = True
    elif failure == "bound":
        recipe["maxCoordinateMove"] = float("nan")
    elif failure == "missing-helper":
        recipes = {"missing": {**recipe, "glyph": "missing"}}
    if failure:
        with pytest.raises(PipelineError):
            apply_endpoint_transports(reference, candidate, recipes)
        assert candidate["glyf"][helper].coordinates == original["glyf"][helper].coordinates
        assert candidate["gvar"].variations == original["gvar"].variations
        return
    report = apply_endpoint_transports(reference, candidate, recipes)
    restore_endpoint_iup_default(
        reference,
        original,
        "curve",
        helper,
        endpoint_points=frozenset({1}),
        fixed_coordinates={
            (i, 1): 736 for i, p in enumerate(original["glyf"][helper].coordinates) if p[1] == 736
        },
    )
    assert report["curve"]["endpointPoints"] == 2
    for tag in ("glyf", "gvar"):
        assert candidate[tag].compile(candidate) == original[tag].compile(original)


@pytest.mark.parametrize("failure", [None, "missing", "mismatch", "semantic", "placement"])
def test_endpoint_metadata_must_bind_every_source_and_its_semantic_recipe(failure):
    import ufoLib2
    from variable_gen.quadratic_reference import (
        NATIVE_IUP_TRANSPORT_KEY,
        SEMANTIC_PARTITION_KEY,
        _native_iup_transport_metadata,
    )

    recipe = endpoint_recipe()
    fonts = [ufoLib2.Font(), ufoLib2.Font()]
    for font in fonts:
        glyph = font.newGlyph("curve")
        glyph.lib[NATIVE_IUP_TRANSPORT_KEY] = deepcopy(recipe)
        glyph.lib[SEMANTIC_PARTITION_KEY] = {"schemaVersion": 3, "glyphRowsSha256": "a" * 64}
    placement = {"curve": "semantic-partition"}
    if failure == "missing":
        del fonts[1]["curve"].lib[NATIVE_IUP_TRANSPORT_KEY]
    elif failure == "mismatch":
        fonts[1]["curve"].lib[NATIVE_IUP_TRANSPORT_KEY]["flatTextY"] = 47
    elif failure == "semantic":
        fonts[1]["curve"].lib[SEMANTIC_PARTITION_KEY]["glyphRowsSha256"] = "c" * 64
    elif failure == "placement":
        placement["curve"] = "native-iup-transport"
    if failure:
        with pytest.raises(PipelineError):
            _native_iup_transport_metadata(fonts, placement)
    else:
        assert _native_iup_transport_metadata(fonts, placement) == {"curve": recipe}


@pytest.mark.parametrize(
    "failure", ["low-sparse", "endpoints", "transform", "moving", "native-point"]
)
def test_endpoint_transport_rejects_unsupported_inputs_before_mutation(failure):
    reference, candidate, helper = endpoint_fonts()
    endpoints = frozenset({1})
    if failure == "low-sparse":
        reference["gvar"].variations["curve"][0].coordinates[0] = None
    elif failure == "endpoints":
        endpoints = frozenset({2})
    elif failure == "transform":
        candidate["glyf"]["curve"].components[0].x = 1
    elif failure == "moving":
        candidate["gvar"].variations["curve"] = [
            TupleVariation({"wght": (0.0, 1.0, 1.0)}, [(1, 0)] + [(0, 0)] * 4)
        ]
    else:
        candidate["glyf"][helper].coordinates[0] = (1, 736)
    before_coords = deepcopy(candidate["glyf"][helper].coordinates)
    before_variations = deepcopy(candidate["gvar"].variations)
    with pytest.raises(PipelineError):
        restore_endpoint_iup_default(
            reference, candidate, "curve", helper, endpoint_points=endpoints, fixed_coordinates={}
        )
    assert candidate["glyf"][helper].coordinates == before_coords
    assert candidate["gvar"].variations == before_variations


def test_fractional_reference_survives_serialization_and_keeps_text_default():
    reference, candidate = fonts()
    assert recording(reference, 950, 32) != recording(candidate, 950, 32)
    untouched = deepcopy(candidate["glyf"]["curve"].coordinates)
    assert restore_reference_inference(reference, candidate, frozenset({"curve"})) == {"curve": 1}
    binary = BytesIO()
    candidate.save(binary)
    binary.seek(0)
    candidate = TTFont(binary)
    for weight in (100, 400, 537.25, 625, 949.99, 950):
        assert recording(reference, weight, 32) == recording(candidate, weight, 32)
    assert candidate["glyf"]["curve"].coordinates == untouched
    assert candidate["fvar"].axes[1].defaultValue == 14
    assert recording(reference, 400, 14) != recording(candidate, 400, 14)


@pytest.mark.parametrize("failure", ["axis", "topology", "compressed"])
def test_incompatible_inference_fails_before_mutation(failure):
    reference, candidate = fonts()
    if failure == "axis":
        candidate["fvar"].axes[0].maxValue = 900
    elif failure == "topology":
        candidate["glyf"]["curve"].flags[1] = 0
    else:
        candidate["gvar"].variations["curve"][0].coordinates[0] = None
    before = deepcopy(candidate["gvar"].variations)
    with pytest.raises(PipelineError):
        restore_reference_inference(reference, candidate, frozenset({"curve"}))
    assert candidate["gvar"].variations == before


def prefixed_fonts():
    reference, candidate = fonts()
    pen = TTGlyphPen(None)
    pen.moveTo((0, 46))
    pen.lineTo((100, 46))
    pen.qCurveTo((115, 52), (110, 54))
    pen.qCurveTo((67, 195), (0, 46))
    pen.closePath()
    candidate["glyf"]["curve"] = pen.glyph()
    mapping = (0, 1, 1, 1, 2, 3, 4, 5, 6)
    for variation in candidate["gvar"].variations["curve"]:
        variation.coordinates = [variation.coordinates[index] for index in mapping]
    optical = candidate["gvar"].variations["curve"][1]
    optical.coordinates[2:5] = [(-15, -52), (-10, -54), (-17, -46)]
    return reference, candidate


def without_stationary_prefixes(value):
    result, current = [], None
    for op, points in value:
        if not (op == "qCurveTo" and points and all(point == current for point in points)):
            result.append((op, points))
        if points:
            current = points[-1]
    return result


def test_native_frame_and_constant_tuple_keep_text_and_fractional_display_after_save():
    reference, candidate = prefixed_fonts()
    before = recording(candidate, 400, 14)
    assert restore_reference_with_prefixes(
        reference, candidate, frozenset({"curve"}), {"wght": 400, "opsz": 32}
    ) == {"curve": 1}
    binary = BytesIO()
    candidate.save(binary)
    binary.seek(0)
    candidate = TTFont(binary)
    assert recording(candidate, 400, 14) == before
    # The intermediate region must survive serialization even with a zero peak.
    # Empty support passed numerical checks but glitched in the macOS browser.
    assert candidate["gvar"].variations["curve"][0].axes == {"wght": (-1, 0, 1)}
    assert candidate["fvar"].axes[1].defaultValue == 14
    for weight in (*range(100, 951), 537.25, 949.99):
        actual = without_stationary_prefixes(recording(candidate, weight, 32))
        expected = recording(reference, weight, 32)
        for (op, points), (other_op, other_points) in zip(actual, expected, strict=True):
            assert op == other_op
            for point, other_point in zip(points, other_points, strict=True):
                assert point == pytest.approx(other_point, abs=1e-12, rel=0)


def test_prefix_mapping_rejects_a_moved_protected_point_before_mutation():
    reference, candidate = prefixed_fonts()
    candidate["glyf"]["curve"].coordinates[2] = (116, 52)
    before_glyph = deepcopy(candidate["glyf"]["curve"].coordinates)
    before_variations = deepcopy(candidate["gvar"].variations)
    with pytest.raises(PipelineError, match="exact native prefix"):
        restore_reference_with_prefixes(
            reference, candidate, frozenset({"curve"}), {"wght": 400, "opsz": 32}
        )
    assert before_glyph == candidate["glyf"]["curve"].coordinates
    assert before_variations == candidate["gvar"].variations


def true_default_fonts():
    reference, candidate = fonts()
    # Keep the candidate within the recipe's explicit one-unit approximation
    # budget while making its ordinary default distinct from the native frame.
    candidate["glyf"]["curve"].coordinates.translate((0, -45))
    endpoint = candidate["gvar"].variations["curve"][0]
    endpoint.coordinates[4] = (5, 0)
    candidate["gvar"].variations["curve"].append(
        TupleVariation(
            {"wght": (0, 1, 1), "opsz": (0, 1, 1)},
            [(0, 0)] * len(endpoint.coordinates),
        )
    )
    return reference, candidate


def true_default_recipe(**changes):
    values = {
        "native_frame_points": frozenset({0, 1, 2}),
        "text_adjustment_points": frozenset({3, 4, 5, 6}),
        "text_locations": ((("wght", 950), ("opsz", 14)),),
        "max_native_frame_residual": 1,
    }
    values.update(changes)
    return NativeIupTransport(**values)


def test_true_default_transport_preserves_native_display_without_default_tuple():
    reference, candidate = true_default_fonts()
    report = restore_reference_true_default(
        reference,
        candidate,
        {"curve": true_default_recipe()},
        {"wght": 400, "opsz": 32},
    )
    assert report == {
        "curve": {
            "nativeSparseRows": 1,
            "maximumRatioError": 0,
            "maximumNativeFrameResidual": 1,
        }
    }
    binary = BytesIO()
    candidate.save(binary)
    binary.seek(0)
    candidate = TTFont(binary)
    assert all(variation.axes for variation in candidate["gvar"].variations["curve"])
    for weight in (400, 537.25, 950):
        assert recording(reference, weight, 32) == recording(candidate, weight, 32)


@pytest.mark.parametrize("failure", ["ratio", "roles", "residual", "support"])
def test_true_default_transport_rejects_before_mutation(failure):
    reference, candidate = true_default_fonts()
    recipe = true_default_recipe()
    if failure == "ratio":
        x, y = candidate["glyf"]["curve"].coordinates[0]
        candidate["glyf"]["curve"].coordinates[0] = (x + 10, y)
        recipe = true_default_recipe(
            native_frame_points=frozenset({2}),
            text_adjustment_points=frozenset({0, 1, 3, 4, 5, 6}),
        )
    elif failure == "roles":
        recipe = true_default_recipe(text_adjustment_points=frozenset({4, 5, 6}))
    elif failure == "residual":
        recipe = true_default_recipe(max_native_frame_residual=0.5)
    else:
        candidate["gvar"].variations["curve"].append(
            deepcopy(candidate["gvar"].variations["curve"][0])
        )
    before_glyph = deepcopy(candidate["glyf"]["curve"].coordinates)
    before_variations = deepcopy(candidate["gvar"].variations)
    with pytest.raises(PipelineError):
        restore_reference_true_default(
            reference,
            candidate,
            {"curve": recipe},
            {"wght": 400, "opsz": 32},
        )
    assert before_glyph == candidate["glyf"]["curve"].coordinates
    assert before_variations == candidate["gvar"].variations
