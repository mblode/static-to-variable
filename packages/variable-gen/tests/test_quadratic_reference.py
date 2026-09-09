from __future__ import annotations

from pathlib import Path

import pytest
import ufo2ft
import ufoLib2
from fontTools.cu2qu.ufo import fonts_to_quadratic
from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.ttLib.tables import otTables
from fontTools.pens.transformPen import TransformPen
from fontTools.varLib.varStore import OnlineVarStoreBuilder
from fontTools.varLib.instancer import instantiateVariableFont

from variable_gen.authorship import OPTICAL_AUTHORSHIP_KEY
from variable_gen.build import _optimize_unmarked_variations, _preserved_authored_variations
from variable_gen.common import PipelineError
from variable_gen.quadratic_reference import (
    _fixed_quadratic_spline,
    _recording,
    _same_filled_path,
    preserve_quadratic_reference,
)
import variable_gen.quadratic_reference as quadratic_reference

PROVENANCE = "manual:" + "a" * 64


def _reference_font(path: Path, *, units_per_em: int = 1000) -> None:
    builder = FontBuilder(units_per_em, isTTF=True)
    builder.setupGlyphOrder([".notdef", "curve", "unmarked"])
    empty = TTGlyphPen(None)
    curve = TTGlyphPen(None)
    curve.moveTo((0, 0))
    curve.lineTo((100, 0))
    curve.qCurveTo((50, 150), (0, 0))
    curve.closePath()
    unmarked = TTGlyphPen(None)
    unmarked.moveTo((150, 0))
    unmarked.lineTo((250, 0))
    unmarked.qCurveTo((200, 120), (150, 0))
    unmarked.closePath()
    builder.setupGlyf(
        {
            ".notdef": empty.glyph(),
            "curve": curve.glyph(),
            "unmarked": unmarked.glyph(),
        }
    )
    builder.setupHorizontalMetrics({".notdef": (500, 0), "curve": (500, 0), "unmarked": (500, 150)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupCharacterMap({0x61: "curve", 0x62: "unmarked"})
    builder.setupNameTable(
        {
            "familyName": "Quadratic Reference Fixture",
            "styleName": "Regular",
            "uniqueFontIdentifier": "QuadraticReferenceFixture-Regular",
            "fullName": "Quadratic Reference Fixture Regular",
            "psName": "QuadraticReferenceFixture-Regular",
            "version": "Version 1.000",
        }
    )
    builder.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)


def _source_font(
    *, height: float, width: float, marked: bool, units_per_em: int = 1000
) -> ufoLib2.Font:
    font = ufoLib2.Font()
    font.info.familyName = "Quadratic Reference Fixture"
    font.info.styleName = f"Height {height:g}"
    font.info.unitsPerEm = units_per_em
    font.info.ascender = 800
    font.info.descender = -200
    font.newGlyph(".notdef").width = 500

    curve = font.newGlyph("curve")
    pen = curve.getPen()
    pen.moveTo((0, 0))
    pen.curveTo((0, height), (100, height), (100, 0))
    pen.closePath()
    curve.width = width
    if marked:
        curve.lib[OPTICAL_AUTHORSHIP_KEY] = PROVENANCE

    unmarked = font.newGlyph("unmarked")
    pen = unmarked.getPen()
    pen.moveTo((150, 0))
    pen.curveTo((150, 180), (250, 180), (250, 0))
    pen.closePath()
    unmarked.width = 500
    return font


def _source_set() -> list[ufoLib2.Font]:
    return [
        _source_font(height=220, width=520, marked=True),
        _source_font(height=200, width=500, marked=False),
        _source_font(height=200, width=500, marked=False),
    ]


def _exact_reference_source(*, marked: bool) -> ufoLib2.Font:
    font = _source_font(height=100, width=500, marked=marked)
    glyph = font["curve"]
    glyph.clearContours()
    pen = glyph.getPen()
    pen.moveTo((0, 0))
    # Degree elevation of the protected quadratic from (100, 0), via
    # (50, 150), to (0, 0), expressed in the source's opposite direction.
    pen.curveTo(((100 / 3), 99.5), ((200 / 3), 99.5), (100, 0))
    pen.closePath()
    return font


def _signature(glyph) -> tuple[tuple[str, int], ...]:
    recording = _recording(glyph)
    return tuple((operation, len(points)) for operation, points in recording.value)


def _compile_variable(fonts: list[ufoLib2.Font], *, optimize_gvar: bool = True) -> TTFont:
    document = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.name = "Optical size"
    axis.tag = "opsz"
    axis.minimum = 12
    axis.default = 16
    axis.maximum = 28
    document.addAxis(axis)
    for index, (font, optical_size) in enumerate(zip(fonts, (12, 16, 28), strict=True)):
        source = SourceDescriptor()
        source.name = f"master-{index}"
        source.familyName = font.info.familyName
        source.styleName = font.info.styleName
        source.location = {axis.name: optical_size}
        source.font = font
        document.addSource(source)
    return ufo2ft.compileVariableTTF(document, useProductionNames=False, optimizeGvar=optimize_gvar)


def test_selective_compression_keeps_authored_deltas_and_normal_unmarked_output() -> None:
    def sources():
        fonts = _source_set()
        for font in fonts:
            font["unmarked"].clearContours()
            _recording(font["curve"]).replay(font["unmarked"].getPen())
        return fonts

    explicit = _compile_variable(sources(), optimize_gvar=False)
    standard = _compile_variable(sources())
    before = [(v.axes, list(v.coordinates)) for v in explicit["gvar"].variations["curve"]]
    _optimize_unmarked_variations(explicit, frozenset({"curve"}))
    assert [(v.axes, list(v.coordinates)) for v in explicit["gvar"].variations["curve"]] == before
    actual = explicit["gvar"].variations["unmarked"]
    expected = standard["gvar"].variations["unmarked"]
    assert any(delta is None for variation in actual for delta in variation.coordinates)
    assert [(v.axes, list(v.coordinates)) for v in actual] == [
        (v.axes, list(v.coordinates)) for v in expected
    ]


@pytest.mark.parametrize("scale", (16, 32))
def test_authored_high_precision_carrier_is_excluded_from_iup_optimization(scale: int) -> None:
    fonts = _source_set()
    carrier = f"curve.stv-semantic{scale}x"
    for font in fonts:
        font["unmarked"].clearContours()
        _recording(font["curve"]).replay(font["unmarked"].getPen())
        glyph = font.newGlyph(carrier)
        _recording(font["unmarked"]).replay(glyph.getPen())

    explicit = _compile_variable(fonts, optimize_gvar=False)
    before = [
        (variation.axes, list(variation.coordinates))
        for variation in explicit["gvar"].variations[carrier]
    ]
    preserved = _preserved_authored_variations(explicit, frozenset({"curve"}))
    _optimize_unmarked_variations(explicit, preserved)

    assert preserved == frozenset({"curve", carrier})
    assert [
        (variation.axes, list(variation.coordinates))
        for variation in explicit["gvar"].variations[carrier]
    ] == before
    assert any(
        delta is None
        for variation in explicit["gvar"].variations["unmarked"]
        for delta in variation.coordinates
    )


def test_display_weight_row_is_preserved_with_text_as_the_default(tmp_path: Path) -> None:
    path = tmp_path / "reference.ttf"
    _reference_font(path)
    reference = TTFont(path)
    FontBuilder(font=reference).setupFvar(
        [("wght", 100, 400, 900, "Weight"), ("opsz", 14, 14, 32, "Optical size")], []
    )
    reference["gvar"] = newTable("gvar")
    reference["gvar"].variations = {name: [] for name in reference.getGlyphOrder()}
    coordinates, _, _ = reference["glyf"]["curve"].getCoordinates(reference["glyf"])
    for support, height_delta, advance_delta in [((-1, -1, 0), -24, -20), ((0, 1, 1), 30, 40)]:
        deltas = [(0, height_delta if y else 0) for _, y in coordinates] + [(0, 0)] * 4
        deltas[len(coordinates) + 1] = (advance_delta, 0)
        reference["gvar"].variations["curve"].append(TupleVariation({"wght": support}, deltas))
    store = OnlineVarStoreBuilder(["wght", "opsz"])
    store.setSupports([{"wght": (-1, -1, 0)}, {"wght": (0, 1, 1)}])
    indices = {
        name: store.storeDeltas([-20, 40] if name == "curve" else [0, 0])
        for name in reference.getGlyphOrder()
    }
    reference["HVAR"] = newTable("HVAR")
    hvar = reference["HVAR"].table = otTables.HVAR()
    hvar.Version = 0x10000
    hvar.VarStore = store.finish()
    hvar.AdvWidthMap = otTables.VarIdxMap()
    hvar.AdvWidthMap.mapping = indices
    hvar.LsbMap = hvar.RsbMap = None
    reference.save(path)

    fonts = [_source_font(height=220 + i * 20, width=520 + i * 20, marked=True) for i in range(3)]
    for scale, width in [(0.84, 480), (1, 500), (1.2, 540)]:
        font = _exact_reference_source(marked=False)
        old = _recording(font["curve"])
        font["curve"].clearContours()
        old.replay(TransformPen(font["curve"].getPen(), (1, 0, 0, scale, 0, 0)))
        font["curve"].width = width
        fonts.append(font)
    preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=path,
        reference_location={},
        protected_locations={
            3 + i: {"wght": weight, "opsz": 32} for i, weight in enumerate((100, 400, 900))
        },
    )
    document = DesignSpaceDocument()
    for name, tag, minimum, default, maximum in [
        ("Weight", "wght", 100, 400, 900),
        ("Optical size", "opsz", 14, 14, 32),
    ]:
        axis = AxisDescriptor()
        axis.name, axis.tag = name, tag
        axis.minimum, axis.default, axis.maximum = minimum, default, maximum
        document.addAxis(axis)
    locations = [(weight, opsz) for opsz in (14, 32) for weight in (100, 400, 900)]
    for index, (font, (weight, opsz)) in enumerate(zip(fonts, locations, strict=True)):
        source = SourceDescriptor()
        source.name = f"master-{index}"
        source.font = font
        source.familyName, source.styleName = font.info.familyName, font.info.styleName
        source.location = {"Weight": weight, "Optical size": opsz}
        document.addSource(source)
    variable = ufo2ft.compileVariableTTF(document, useProductionNames=False, optimizeGvar=False)
    assert {axis.axisTag: axis.defaultValue for axis in variable["fvar"].axes} == {
        "wght": 400,
        "opsz": 14,
    }
    for weight in (100, 237, 400, 625, 900):
        expected = reference.getGlyphSet(location={"wght": weight, "opsz": 32})["curve"]
        actual = variable.getGlyphSet(location={"wght": weight, "opsz": 32})["curve"]
        assert _same_filled_path(_recording(actual), _recording(expected))
        assert actual.width == pytest.approx(expected.width, abs=1e-9)
    text = variable.getGlyphSet()["curve"]
    assert text.width == 540
    assert not _same_filled_path(_recording(text), _recording(reference.getGlyphSet()["curve"]))


@pytest.mark.parametrize("locations", [{}, {3: {}}, {True: {}}])
def test_protected_master_indices_fail_before_source_mutation(tmp_path, locations) -> None:
    path = tmp_path / "reference.ttf"
    _reference_font(path)
    fonts = _source_set()
    before = [_recording(font["curve"]).value for font in fonts]
    with pytest.raises(ValueError, match="existing source masters"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=path,
            reference_location={},
            protected_locations=locations,
        )
    assert [_recording(font["curve"]).value for font in fonts] == before


def _cubic_point(curve: tuple[complex, complex, complex, complex], t: float) -> complex:
    p0, p1, p2, p3 = curve
    u = 1 - t
    return u**3 * p0 + 3 * u**2 * t * p1 + 3 * u * t**2 * p2 + t**3 * p3


def _quadratic_point(start: complex, control: complex, end: complex, t: float) -> complex:
    u = 1 - t
    return u**2 * start + 2 * u * t * control + t**2 * end


def test_reference_geometry_survives_compatible_closed_variable_build(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()

    report = preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        max_error=1,
    )

    assert report.glyphs == 1
    assert report.converted_glyphs == 1
    assert report.exact_default_glyphs == 0
    assert report.expanded_operations == 3
    assert report.maximum_segments == 4
    signatures = {_signature(font["curve"]) for font in fonts}
    assert signatures == {
        (
            ("moveTo", 1),
            ("lineTo", 1),
            ("qCurveTo", 2),
            ("qCurveTo", 2),
            ("qCurveTo", 2),
            ("qCurveTo", 2),
            ("closePath", 0),
        )
    }

    reference = TTFont(reference_path).getGlyphSet()["curve"]
    assert _same_filled_path(_recording(fonts[1]["curve"]), _recording(reference))
    assert _same_filled_path(_recording(fonts[2]["curve"]), _recording(reference))
    assert fonts[1]["curve"].width == fonts[2]["curve"].width == 500
    assert fonts[0]["curve"].width == 520

    variable = _compile_variable(fonts)
    ui = instantiateVariableFont(variable, {"opsz": 16}, inplace=False)
    display = instantiateVariableFont(variable, {"opsz": 28}, inplace=False)
    text = instantiateVariableFont(variable, {"opsz": 12}, inplace=False)
    assert _same_filled_path(_recording(ui.getGlyphSet()["curve"]), _recording(reference))
    assert _same_filled_path(_recording(display.getGlyphSet()["curve"]), _recording(reference))
    assert ui["hmtx"].metrics["curve"][0] == 500
    assert display["hmtx"].metrics["curve"][0] == 500
    assert text["hmtx"].metrics["curve"][0] == 520


@pytest.mark.parametrize("metadata", [False, True])
def test_piecewise_authored_source_compiles_with_exact_protected_masters(
    tmp_path: Path, metadata
) -> None:
    from fontTools.misc.bezierTools import splitCubicAtT

    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    glyph = fonts[0]["curve"]
    glyph.clearContours()
    pen = glyph.getPen()
    pen.moveTo((0, 0))
    for curve in splitCubicAtT((0, 0), (0, 220), (100, 220), (100, 0), 0.5):
        pen.curveTo(*curve[1:])
    pen.closePath()
    untouched = _source_set()
    fonts_to_quadratic(untouched, max_err=1, reverse_direction=True, remember_curve_type=False)
    groups = (((1, 1, 2, 1),), ((1, 1, 1, 1),), ((1, 1, 1, 1),))
    if metadata:
        for font, contours in zip(fonts, groups, strict=True):
            font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = contours
    preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        protected_locations={1: {}, 2: {}},
        source_groups=None if metadata else {"curve": groups},
    )
    assert len({_signature(font["curve"]) for font in fonts}) == 1
    for actual, expected in zip(fonts, untouched, strict=True):
        assert _recording(actual["unmarked"]).value == _recording(expected["unmarked"]).value
    variable = _compile_variable(fonts, optimize_gvar=False)
    reference = TTFont(reference_path).getGlyphSet()["curve"]
    for optical_size in (16, 28):
        instance = instantiateVariableFont(variable, {"opsz": optical_size}, inplace=False)
        glyphs = instance.getGlyphSet()
        recording = DecomposingRecordingPen(glyphs)
        glyphs["curve"].draw(recording)
        assert _same_filled_path(recording, _recording(reference))
        assert instance["hmtx"].metrics["curve"][0] == 500


def test_incomplete_piecewise_contract_fails_before_any_source_mutation(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    before = [[_recording(font[name]).value for name in font.keys()] for font in fonts]
    with pytest.raises(PipelineError, match="every source master"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            source_groups={"curve": (((1, 1, 1, 1),),)},
        )
    assert before == [[_recording(font[name]).value for name in font.keys()] for font in fonts]


@pytest.mark.parametrize("failure", ["missing", "unmarked", "conflict"])
def test_source_group_metadata_cannot_be_partial_unmarked_or_overridden(tmp_path, failure):
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    for font in fonts:
        font["curve"].lib[OPTICAL_AUTHORSHIP_KEY] = PROVENANCE
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = ((1, 1, 1, 1),)
    if failure == "missing":
        del fonts[1]["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY]
    elif failure == "unmarked":
        for font in fonts:
            del font["curve"].lib[OPTICAL_AUTHORSHIP_KEY]
    before = [[_recording(font[name]).value for name in font.keys()] for font in fonts]
    with pytest.raises(PipelineError):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            source_groups={} if failure == "conflict" else None,
        )
    assert before == [[_recording(font[name]).value for name in font.keys()] for font in fonts]


@pytest.mark.parametrize(
    "mode",
    [
        quadratic_reference.BALANCED_ENDPOINTS,
        quadratic_reference.REFERENCE_COUNT,
        quadratic_reference.REFERENCE_COUNT_LINES,
        quadratic_reference.NATIVE_IUP_TRANSPORT,
    ],
)
def test_balanced_padding_metadata_compiles_with_exact_protected_masters(
    tmp_path: Path, mode: str
) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    groups = ((1, 1, 1, 1),)
    for index, font in enumerate(fonts):
        if mode in {
            quadratic_reference.REFERENCE_COUNT,
            quadratic_reference.REFERENCE_COUNT_LINES,
            quadratic_reference.NATIVE_IUP_TRANSPORT,
        }:
            glyph = font["curve"]
            glyph.clearContours()
            pen = glyph.getPen()
            pen.moveTo((0, 0))
            pen.curveTo((100 / 3, 100), (200 / 3, 100), (100, 0))
            if mode == quadratic_reference.REFERENCE_COUNT_LINES and index == 0:
                pen.lineTo((130, 0))
            pen.closePath()
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = (
            ((1, 1, 2, 1),)
            if mode == quadratic_reference.REFERENCE_COUNT_LINES and index == 0
            else groups
        )
        font["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = mode
        if mode == quadratic_reference.NATIVE_IUP_TRANSPORT:
            font["curve"].lib[quadratic_reference.NATIVE_IUP_TRANSPORT_KEY] = {
                "schemaVersion": 1,
                "placement": quadratic_reference.NATIVE_IUP_TRANSPORT,
                "glyph": "curve",
                "glyphRowsSha256": "a" * 64,
                "referenceSha256": "b" * 64,
                "nativeFramePoints": [0],
                "textAdjustmentPoints": [1],
                "textLocations": [{"opsz": 14, "wght": 100}],
                "protectedLocation": {"opsz": 32, "wght": 400},
                "maxNativeFrameResidual": 1,
            }

    preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        protected_locations={1: {}, 2: {}},
    )

    assert len({_signature(font["curve"]) for font in fonts}) == 1
    reference = TTFont(reference_path).getGlyphSet()["curve"]
    assert _same_filled_path(_recording(fonts[1]["curve"]), _recording(reference))
    assert _same_filled_path(_recording(fonts[2]["curve"]), _recording(reference))
    variable = _compile_variable(fonts, optimize_gvar=False)
    for optical_size in (16, 28):
        instance = instantiateVariableFont(variable, {"opsz": optical_size}, inplace=False)
        assert _same_filled_path(_recording(instance.getGlyphSet()["curve"]), _recording(reference))


def test_native_iup_transport_requires_recipe_in_every_master(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    for font in fonts:
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = ((1, 1, 1, 1),)
        font["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = (
            quadratic_reference.NATIVE_IUP_TRANSPORT
        )
    before = [[_recording(font[name]).value for name in font.keys()] for font in fonts]
    with pytest.raises(PipelineError, match="placement and recipe must agree"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
        )
    assert before == [[_recording(font[name]).value for name in font.keys()] for font in fonts]


@pytest.mark.parametrize(
    ("mode", "scale"),
    [
        (quadratic_reference.CONTINUOUS_CHAIN, 16),
        (quadratic_reference.CONTINUOUS_CHAIN_FULL, 32),
    ],
)
def test_continuous_chain_uses_explicit_scaled_carrier_and_preserves_reference(
    tmp_path: Path, mode: str, scale: int
) -> None:
    from fontTools.misc.bezierTools import splitCubicAtT

    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    source = fonts[0]["curve"]
    source.clearContours()
    pen = source.getPen()
    pen.moveTo((0, 0))
    for curve in splitCubicAtT((0, 0), (0, 220), (100, 220), (100, 0), 0.5):
        pen.curveTo(*curve[1:])
    pen.closePath()
    groups = (((1, 1, 2, 1),), ((1, 1, 1, 1),), ((1, 1, 1, 1),))
    for font, contours in zip(fonts, groups, strict=True):
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = contours
        font["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = mode

    report = preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        protected_locations={1: {}, 2: {}},
        glyph_max_error={"curve": 20},
    )

    helper_name = f"curve.stv-semantic{scale}x"
    assert report.carrier_glyphs == (helper_name,)
    for font in fonts:
        assert helper_name in font
        assert font[helper_name].lib[OPTICAL_AUTHORSHIP_KEY] == PROVENANCE
        assert len(font["curve"].components) == 1
        assert font["curve"].components[0].baseGlyph == helper_name
        assert font["curve"].components[0].transformation == pytest.approx(
            (1 / scale, 0, 0, 1 / scale, 0, 0)
        )
    variable = _compile_variable(fonts, optimize_gvar=False)
    cmap = variable.getBestCmap()
    assert cmap is None or helper_name not in cmap.values()
    assert variable["head"].yMax > TTFont(reference_path)["head"].yMax
    reference = TTFont(reference_path).getGlyphSet()["curve"]
    for optical_size in (16, 28):
        instance = instantiateVariableFont(variable, {"opsz": optical_size}, inplace=False)
        glyphs = instance.getGlyphSet()
        recording = DecomposingRecordingPen(glyphs)
        glyphs["curve"].draw(recording)
        assert _same_filled_path(recording, _recording(reference))


def test_continuous_chain_full_distributes_exact_collapsed_reference_capacity() -> None:
    operation = ("qCurveTo", ((50, 100), (100, 0)))
    operations = quadratic_reference._subdivide_reference_chain_full((0, 0), operation)

    assert len(operations) == 16
    assert all(kind == "qCurveTo" and len(points) == 2 for kind, points in operations)
    assert all(
        value * 16 == round(value * 16)
        for _, points in operations
        for point in points
        for value in point
    )
    for index in range(0, len(operations), 4):
        endpoint = operations[index][1][-1]
        assert operations[index + 1 : index + 4] == [("qCurveTo", (endpoint, endpoint))] * 3
    assert sum(points[0] == points[1] for _, points in operations[:8]) == 6

    original = RecordingPen()
    original.moveTo((0, 0))
    original.qCurveTo(*operation[1])
    original.closePath()
    expanded = RecordingPen()
    expanded.moveTo((0, 0))
    for kind, points in operations:
        getattr(expanded, kind)(*points)
    expanded.closePath()
    assert quadratic_reference._same_filled_path(original, expanded)


def test_adaptive_piecewise_uses_reviewed_allocations_and_explicit_deltas(
    tmp_path: Path,
) -> None:
    from fontTools.misc.bezierTools import splitCubicAtT

    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    source = fonts[0]["curve"]
    source.clearContours()
    pen = source.getPen()
    pen.moveTo((0, 0))
    for curve in splitCubicAtT((0, 0), (0, 220), (100, 220), (100, 0), 0.25, 0.5):
        pen.curveTo(*curve[1:])
    pen.closePath()
    groups = (((1, 1, 3, 1),), ((1, 1, 1, 1),), ((1, 1, 1, 1),))
    recipe = {
        "schemaVersion": 1,
        "placement": quadratic_reference.ADAPTIVE_PIECEWISE,
        "glyph": "curve",
        "glyphRowsSha256": "a" * 64,
        "subdivisions": 4,
        "allocations": {"0:1": [1, 1, 2]},
    }
    for font, contours in zip(fonts, groups, strict=True):
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = contours
        font["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = (
            quadratic_reference.ADAPTIVE_PIECEWISE
        )
        font["curve"].lib[quadratic_reference.ADAPTIVE_PIECEWISE_KEY] = recipe

    report = preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        protected_locations={1: {}, 2: {}},
        glyph_max_error={"curve": 20},
    )

    assert report.carrier_glyphs == ("curve.stv-semantic16x",)
    assert len({_signature(font["curve.stv-semantic16x"]) for font in fonts}) == 1
    assert _signature(fonts[0]["curve.stv-semantic16x"])[1:5] == (
        ("lineTo", 1),
        ("qCurveTo", 2),
        ("qCurveTo", 2),
        ("qCurveTo", 3),
    )
    reference = TTFont(reference_path).getGlyphSet()["curve"]
    for index in (1, 2):
        recording = DecomposingRecordingPen(fonts[index])
        fonts[index]["curve"].draw(recording)
        assert _same_filled_path(recording, _recording(reference))
    variable = _compile_variable(fonts, optimize_gvar=False)
    variations = variable["gvar"].variations["curve.stv-semantic16x"]
    assert all(delta is not None for variation in variations for delta in variation.coordinates)
    for optical_size in (16, 28):
        instance = instantiateVariableFont(variable, {"opsz": optical_size}, inplace=False)
        recording = DecomposingRecordingPen(instance.getGlyphSet())
        instance.getGlyphSet()["curve"].draw(recording)
        assert _same_filled_path(recording, _recording(reference))


@pytest.mark.parametrize(
    ("recipe_change", "message"),
    [
        ({"allocations": {}}, "needs an explicit allocation"),
        ({"allocations": {"0:1": [1, 1, 1]}}, "totals 3, expected 4"),
    ],
)
def test_adaptive_piecewise_rejects_missing_or_incomplete_multi_curve_allocation(
    tmp_path: Path, recipe_change: dict, message: str
) -> None:
    from fontTools.misc.bezierTools import splitCubicAtT

    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    source = fonts[0]["curve"]
    source.clearContours()
    pen = source.getPen()
    pen.moveTo((0, 0))
    for curve in splitCubicAtT((0, 0), (0, 220), (100, 220), (100, 0), 0.5):
        pen.curveTo(*curve[1:])
    pen.closePath()
    groups = (((1, 1, 2, 1),), ((1, 1, 1, 1),), ((1, 1, 1, 1),))
    recipe = {
        "schemaVersion": 1,
        "placement": quadratic_reference.ADAPTIVE_PIECEWISE,
        "glyph": "curve",
        "glyphRowsSha256": "a" * 64,
        "subdivisions": 4,
        "allocations": {"0:1": [2, 2]},
    }
    recipe.update(recipe_change)
    for font, contours in zip(fonts, groups, strict=True):
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = contours
        font["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = (
            quadratic_reference.ADAPTIVE_PIECEWISE
        )
        font["curve"].lib[quadratic_reference.ADAPTIVE_PIECEWISE_KEY] = recipe
    before = [_recording(font["curve"]).value for font in fonts]

    with pytest.raises(PipelineError, match=message):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            protected_locations={1: {}, 2: {}},
            glyph_max_error={"curve": 20},
        )
    assert [_recording(font["curve"]).value for font in fonts] == before


@pytest.mark.parametrize("version", [1, 3])
def test_semantic_partition_uses_source_bound_recipe_and_exact_carrier(
    tmp_path: Path,
    version: int,
) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    recipe = {
        "schemaVersion": 1,
        "placement": quadratic_reference.SEMANTIC_PARTITION,
        "glyph": "curve",
        "glyphRowsSha256": "a" * 64,
        "defaultSubdivisions": 2,
        "subdivisionOverrides": {},
        "semanticSlots": [],
        "straightExtensionWeights": [],
    }
    if version == 3:
        recipe.update(schemaVersion=3, defaultSubdivisions=1, endpointSpans={"1": 8})
    for font in fonts:
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = ((1, 1, 1, 1),)
        font["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = (
            quadratic_reference.SEMANTIC_PARTITION
        )
        font["curve"].lib[quadratic_reference.SEMANTIC_PARTITION_KEY] = recipe

    report = preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        protected_locations={1: {}, 2: {}},
        glyph_max_error={"curve": 20},
    )

    assert report.carrier_glyphs == ("curve.stv-semantic16x",)
    assert len({_signature(font["curve"]) for font in fonts}) == 1
    reference = TTFont(reference_path).getGlyphSet()["curve"]
    for index in (1, 2):
        recording = DecomposingRecordingPen(fonts[index])
        fonts[index]["curve"].draw(recording)
        assert _same_filled_path(recording, _recording(reference))


@pytest.mark.parametrize(
    "change",
    [
        {"endpointSpans": {}},
        {"endpointSpans": {"01": 8}},
        {"endpointSpans": {"1": True}},
        {"endpointSpans": {"1": 65}},
        {"defaultSubdivisions": 2},
        {"semanticSlots": [1]},
        {"schemaVersion": True},
        {"pairedOperations": []},
    ],
)
def test_endpoint_metadata_rejects_unbounded_or_subdivided_protected_paths(change: dict) -> None:
    fonts = _source_set()
    recipe = {
        "schemaVersion": 3,
        "placement": quadratic_reference.SEMANTIC_PARTITION,
        "glyph": "curve",
        "glyphRowsSha256": "a" * 64,
        "defaultSubdivisions": 1,
        "subdivisionOverrides": {},
        "semanticSlots": [],
        "straightExtensionWeights": [],
        "endpointSpans": {"1": 8},
    }
    recipe.update(change)
    for font in fonts:
        font["curve"].lib[quadratic_reference.SEMANTIC_PARTITION_KEY] = recipe
    with pytest.raises(PipelineError, match="semantic partition metadata"):
        quadratic_reference._semantic_partition_metadata(
            fonts, {"curve": quadratic_reference.SEMANTIC_PARTITION}
        )


def test_semantic_partition_fails_without_recipe_before_mutating_sources(
    tmp_path: Path,
) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    for font in fonts:
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = ((1, 1, 1, 1),)
        font["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = (
            quadratic_reference.SEMANTIC_PARTITION
        )
    before = [_recording(font["curve"]).value for font in fonts]
    with pytest.raises(PipelineError, match="semantic partition recipe mismatch"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
        )
    assert [_recording(font["curve"]).value for font in fonts] == before


@pytest.mark.parametrize("endpoint_spans", [False, True, "leading"])
def test_semantic_partition_indexes_operations_after_move_sentinel(endpoint_spans) -> None:
    def recording(*operations):
        pen = RecordingPen()
        pen.value = list(operations)
        return pen

    ordinary = recording(
        ("moveTo", ((0, 0),)),
        ("lineTo", ((100, 0),)),
        ("curveTo", ((100, 80), (0, 80), (0, 0))),
        ("closePath", ()),
    )
    extended = recording(
        ("moveTo", ((0, 0),)),
        ("lineTo", ((100, 0),)),
        ("lineTo", ((100, 10),)),
        ("curveTo", ((100, 80), (0, 80), (0, 0))),
        ("closePath", ()),
    )
    protected = recording(
        ("moveTo", ((0, 0),)),
        ("lineTo", ((100, 0),)),
        ("qCurveTo", ((50, 120), (0, 0))),
        ("closePath", ()),
    )
    contours, _, _ = quadratic_reference._piecewise_contours(
        "curve",
        [extended, ordinary, ordinary],
        (((1, 1, 2, 1),), ((1, 1, 1, 1),), ((1, 1, 1, 1),)),
        {1: protected, 2: protected},
        1,
        40,
        quadratic_reference.SEMANTIC_PARTITION,
        {
            "defaultSubdivisions": 2,
            "subdivisionOverrides": {},
            "semanticSlots": [] if endpoint_spans is True else [1],
            **({"endpointSpans": {"1": 8}} if endpoint_spans else {}),
            **({"splitFraction": 0.25} if endpoint_spans == "leading" else {}),
        },
    )
    assert len({tuple((op, len(points)) for op, points in value[0]) for value in contours}) == 1
    if endpoint_spans:
        for index in (1, 2):
            offset = int(endpoint_spans == "leading")
            assert contours[index][0][2 + offset] == protected.value[2]
            assert contours[index][0][3 + offset] == ("qCurveTo", ((0, 0),) * 9)
            if offset:
                assert contours[index][0][2] == ("qCurveTo", ((100, 0),) * 2)


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"splitFraction": 0},
        {"splitFraction": 1},
        {"splitFraction": True},
        {"splitFraction": float("nan")},
        {"splitFraction": "0.25"},
        {"semanticSlots": [0]},
        {"schemaVersion": 3},
        {"extra": 1},
    ],
)
def test_endpoint_v4_metadata_accepts_only_bounded_explicit_recipe(change):
    fonts = _source_set()
    recipe = {
        "schemaVersion": 4,
        "placement": quadratic_reference.SEMANTIC_PARTITION,
        "glyph": "curve",
        "glyphRowsSha256": "a" * 64,
        "defaultSubdivisions": 1,
        "subdivisionOverrides": {},
        "semanticSlots": [1],
        "straightExtensionWeights": [400],
        "endpointSpans": {"1": 8},
        "splitFraction": 0.25,
    }
    recipe.update(change)
    for font in fonts:
        font["curve"].lib[quadratic_reference.SEMANTIC_PARTITION_KEY] = recipe
    if change:
        with pytest.raises(PipelineError, match="semantic partition metadata"):
            quadratic_reference._semantic_partition_metadata(
                fonts, {"curve": quadratic_reference.SEMANTIC_PARTITION}
            )
    else:
        assert quadratic_reference._semantic_partition_metadata(
            fonts, {"curve": quadratic_reference.SEMANTIC_PARTITION}
        ) == {"curve": recipe}


def test_semantic_partition_pairs_adjacent_operations_with_protected_seam_ratio() -> None:
    def recording(*operations):
        pen = RecordingPen()
        pen.value = list(operations)
        return pen

    authored = recording(
        ("moveTo", ((0, 0),)),
        ("curveTo", ((50 / 3, 100 / 3), (100 / 3, 50), (50, 50))),
        ("curveTo", ((200 / 3, 50), (250 / 3, 100 / 3), (100, 0))),
        ("closePath", ()),
    )
    protected = recording(
        ("moveTo", ((0, 0),)),
        ("qCurveTo", ((25, 50), (50, 50))),
        ("qCurveTo", ((75, 50), (100, 0))),
        ("closePath", ()),
    )
    contours, _, maximum = quadratic_reference._piecewise_contours(
        "curve",
        [authored, authored, authored],
        (((1, 1, 1, 1),),) * 3,
        {1: protected, 2: protected},
        1,
        1,
        quadratic_reference.SEMANTIC_PARTITION,
        {
            "defaultSubdivisions": 4,
            "subdivisionOverrides": {},
            "semanticSlots": [],
            "pairedOperations": [[0, 1]],
            "protectedMatchAxes": ["Weight"],
        },
        ({"Weight": 100}, {"Weight": 100}, {"Weight": 400}),
    )
    assert maximum == 4
    assert [kind for kind, _ in contours[0][0]] == [
        "moveTo",
        "qCurveTo",
        "qCurveTo",
        "closePath",
    ]
    first, second = contours[0][0][1:3]
    seam = complex(*first[1][-1])
    incoming = seam - complex(*first[1][-2])
    outgoing = complex(*second[1][0]) - seam
    assert abs(incoming.real * outgoing.imag - incoming.imag * outgoing.real) < 1e-12
    assert incoming.real * outgoing.real + incoming.imag * outgoing.imag > 0
    assert abs(outgoing) / abs(incoming) == pytest.approx(1)


def test_semantic_partition_rejects_nonadjacent_paired_operations(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    recipe = {
        "schemaVersion": 2,
        "placement": quadratic_reference.SEMANTIC_PARTITION,
        "glyph": "curve",
        "glyphRowsSha256": "a" * 64,
        "defaultSubdivisions": 4,
        "subdivisionOverrides": {},
        "semanticSlots": [],
        "straightExtensionWeights": [],
        "pairedOperations": [[0, 2]],
        "protectedMatchAxes": ["Weight"],
    }
    for font in fonts:
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = ((1, 1, 1, 1),)
        font["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = (
            quadratic_reference.SEMANTIC_PARTITION
        )
        font["curve"].lib[quadratic_reference.SEMANTIC_PARTITION_KEY] = recipe
    with pytest.raises(PipelineError, match="semantic partition metadata is invalid"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
        )


@pytest.mark.parametrize("failure", ["missing", "mismatch", "nonscalar", "ungrouped"])
def test_balanced_padding_metadata_fails_closed_before_source_mutation(
    tmp_path: Path, failure: str
) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    groups = ((1, 1, 1, 1),)
    for font in fonts:
        font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY] = groups
        font["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = (
            quadratic_reference.BALANCED_ENDPOINTS
        )
    if failure == "missing":
        del fonts[1]["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY]
    elif failure == "mismatch":
        fonts[1]["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = "unknown"
    elif failure == "nonscalar":
        fonts[1]["curve"].lib[quadratic_reference.PADDING_PLACEMENT_KEY] = {
            "mode": quadratic_reference.BALANCED_ENDPOINTS
        }
    else:
        for font in fonts:
            del font["curve"].lib[quadratic_reference.SOURCE_GROUPS_KEY]

    before = [_recording(font["curve"]).value for font in fonts]
    with pytest.raises(PipelineError, match="padding placement"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
        )
    assert [_recording(font["curve"]).value for font in fonts] == before


def test_reference_count_contracts_a_conservative_preliminary_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = [
        _exact_reference_source(marked=True),
        _exact_reference_source(marked=False),
        _exact_reference_source(marked=False),
    ]

    def conservative_conversion(fonts, **_kwargs) -> None:
        for font in fonts:
            glyph = font["curve"]
            glyph.clearContours()
            pen = glyph.getPen()
            pen.moveTo((0, 0))
            # The same quadratic split at t=.5: deliberately compatible and
            # geometrically exact, but more segmented than the authority.
            pen.lineTo((100, 0))
            pen.qCurveTo((75, 74.625), (25, 74.625), (0, 0))
            pen.closePath()

    monkeypatch.setattr(quadratic_reference, "fonts_to_quadratic", conservative_conversion)
    report = preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        max_error=1,
    )

    assert report.expanded_operations == 0
    assert report.maximum_segments == 1
    assert {_signature(font["curve"]) for font in fonts} == {
        (
            ("moveTo", 1),
            ("lineTo", 1),
            ("qCurveTo", 2),
            ("closePath", 0),
        )
    }


def test_authored_cubic_fit_stays_within_one_unit() -> None:
    points = ((0, 0), (0, 220), (100, 220), (100, 0))
    spline = _fixed_quadratic_spline(points, 4, 1)

    assert spline is not None
    cubic = tuple(complex(*point) for point in points)
    controls = [complex(*point) for point in spline[1:-1]]
    endpoints = [complex(*spline[0])]
    endpoints.extend(
        (left + right) / 2 for left, right in zip(controls, controls[1:], strict=False)
    )
    endpoints.append(complex(*spline[-1]))
    maximum_error = max(
        abs(
            _quadratic_point(endpoints[index], control, endpoints[index + 1], step / 1000)
            - _cubic_point(cubic, (index + step / 1000) / len(controls))
        )
        for index, control in enumerate(controls)
        for step in range(1001)
    )

    assert 0 < maximum_error <= 1


def test_per_glyph_precision_preserves_unmarked_conversion_and_reference(tmp_path):
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    ordinary, precise = _source_set(), _source_set()
    preserve_quadratic_reference(
        ordinary, default_index=1, reference_path=reference_path, reference_location={}
    )
    preserve_quadratic_reference(
        precise,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        glyph_max_error={"curve": 0.1},
    )
    assert _recording(ordinary[0]["curve"]).value != _recording(precise[0]["curve"]).value
    assert [_recording(font["unmarked"]).value for font in ordinary] == [
        _recording(font["unmarked"]).value for font in precise
    ]
    with TTFont(reference_path) as reference:
        assert _same_filled_path(
            _recording(precise[1]["curve"]), _recording(reference.getGlyphSet()["curve"])
        )


def test_unmarked_precision_override_fails_before_conversion(tmp_path):
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    before = [_recording(font["curve"]).value for font in fonts]
    with pytest.raises(PipelineError, match="requires authored glyphs"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            glyph_max_error={"unmarked": 0.25},
        )
    assert [_recording(font["curve"]).value for font in fonts] == before


def test_topology_contract_binds_every_authored_master_before_cu2qu(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = [
        _source_font(height=220, width=520, marked=True),
        _source_font(height=200, width=500, marked=True),
        _source_font(height=180, width=480, marked=True),
    ]
    contract = {
        "curve": ((("moveTo", 1), ("curveTo", 3), ("closePath", 0)),),
    }

    report = preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        max_error=1,
        topology_contract=contract,
        topology_contract_master_names=("text", "ui", "display"),
        source_master_names=("text", "ui", "display"),
    )

    assert report.glyphs == 1


def test_topology_contract_fails_closed_for_unmarked_or_drifted_master(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = [
        _source_font(height=220, width=520, marked=True),
        _source_font(height=200, width=500, marked=False),
        _source_font(height=180, width=480, marked=True),
    ]
    contract = {
        "curve": ((("moveTo", 1), ("curveTo", 3), ("closePath", 0)),),
    }

    with pytest.raises(PipelineError, match="requires authored provenance in master 1"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            topology_contract=contract,
            topology_contract_master_names=("text", "ui", "display"),
            source_master_names=("text", "ui", "display"),
        )

    fonts[1] = _source_font(height=200, width=500, marked=True)
    pen = fonts[1]["curve"].getPen()
    fonts[1]["curve"].clearContours()
    pen.moveTo((0, 0))
    pen.lineTo((100, 0))
    pen.closePath()
    with pytest.raises(PipelineError, match="topology contract mismatch in master 1"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            topology_contract=contract,
            topology_contract_master_names=("text", "ui", "display"),
            source_master_names=("text", "ui", "display"),
        )


def test_topology_contract_rejects_a_partial_or_reordered_master_set(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = [_source_font(height=220, width=520, marked=True)]
    with pytest.raises(PipelineError, match="master inputs differ"):
        preserve_quadratic_reference(
            fonts,
            default_index=0,
            reference_path=reference_path,
            reference_location={},
            topology_contract={
                "curve": ((("moveTo", 1), ("curveTo", 3), ("closePath", 0)),),
            },
            topology_contract_master_names=("text", "ui", "display"),
            source_master_names=("text",),
        )


def test_reference_reconciliation_is_provenance_scoped_and_deterministic(
    tmp_path: Path,
) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    first = _source_set()
    second = _source_set()
    normal = _source_set()
    fonts_to_quadratic(
        normal,
        max_err=1,
        reverse_direction=True,
        remember_curve_type=False,
    )

    first_report = preserve_quadratic_reference(
        first,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        max_error=1,
    )
    second_report = preserve_quadratic_reference(
        second,
        default_index=1,
        reference_path=reference_path,
        reference_location={},
        max_error=1,
    )

    assert first_report == second_report
    for first_font, second_font, normal_font in zip(first, second, normal, strict=True):
        assert _recording(first_font["curve"]).value == _recording(second_font["curve"]).value
        assert _recording(first_font["unmarked"]).value == _recording(normal_font["unmarked"]).value


def test_reference_validation_fails_before_mutating_sources(tmp_path: Path) -> None:
    reference_path = tmp_path / "wrong-upem.ttf"
    _reference_font(reference_path, units_per_em=2048)
    fonts = _source_set()
    before = [_recording(font["curve"]).value for font in fonts]

    with pytest.raises(PipelineError, match="unitsPerEm must match every source"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            max_error=1,
        )

    assert [_recording(font["curve"]).value for font in fonts] == before


def test_open_authored_contour_fails_before_quadratic_conversion(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.ttf"
    _reference_font(reference_path)
    fonts = _source_set()
    glyph = fonts[0]["curve"]
    glyph.clearContours()
    pen = glyph.getPen()
    pen.moveTo((0, 0))
    pen.curveTo((0, 220), (100, 220), (100, 0))
    pen.endPath()
    before = [_recording(font["curve"]).value for font in fonts]

    with pytest.raises(PipelineError, match="requires closed contours"):
        preserve_quadratic_reference(
            fonts,
            default_index=1,
            reference_path=reference_path,
            reference_location={},
            max_error=1,
        )

    assert [_recording(font["curve"]).value for font in fonts] == before
