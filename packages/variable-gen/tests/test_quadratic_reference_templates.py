import copy
import hashlib
from types import SimpleNamespace

import pytest
import ufo2ft
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from variable_gen.common import PipelineError
from variable_gen.quadratic_reference_templates import (
    REFERENCE_TEMPLATE,
    REFERENCE_TEMPLATES_KEY,
    exact_reference_template,
    load_reference_templates,
    recording_sha256,
)
from variable_gen import quadratic_reference as q
from test_quadratic_reference import _reference_font, _source_set, _compile_variable

ORIGINAL = [
    ("moveTo", ((0, 0),)),
    ("lineTo", ((100, 0),)),
    ("qCurveTo", ((50, 150), (0, 0))),
    ("closePath", ()),
]
TEMPLATE = [
    ("moveTo", ((100, 0),)),
    ("qCurveTo", ((100, 0), (100, 0))),
    ("qCurveTo", ((50, 150), (0, 0))),
    ("qCurveTo", ((50, 0), (100, 0))),
    ("closePath", ()),
]


def test_exact_midpoint_elevation_stationary_capacity_and_cyclic_start():
    assert exact_reference_template(ORIGINAL, TEMPLATE)


@pytest.mark.parametrize("change", ["bend", "reverse", "retrace", "move"])
def test_changed_shape_winding_or_nonstationary_retrace_is_rejected(change):
    bad = copy.deepcopy(TEMPLATE)
    if change == "bend":
        bad[3] = ("qCurveTo", ((50, 0.001), (100, 0)))
    elif change == "move":
        bad[2] = ("qCurveTo", ((50, 150.001), (0, 0)))
    elif change == "reverse":
        bad = [
            ("moveTo", ((0, 0),)),
            ("qCurveTo", ((50, 150), (100, 0))),
            ("lineTo", ((0, 0),)),
            ("closePath", ()),
        ]
    else:
        bad[1] = ("qCurveTo", ((110, 0), (100, 0)))
    assert not exact_reference_template(ORIGINAL, bad)


def recipe(path, template=TEMPLATE):
    return dict(
        schemaVersion=1,
        glyph="curve",
        glyphRowsSha256="a" * 64,
        referenceSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        templates=[
            dict(
                location={},
                originalRecordingSha256=recording_sha256(ORIGINAL),
                recordingSha256=recording_sha256(template),
                recording=template,
            )
        ],
    )


def test_metadata_requires_complete_matching_bound_recipe(tmp_path):
    path = tmp_path / "ref"
    path.write_bytes(b"reference")
    r = recipe(path)
    fonts = [{"curve": SimpleNamespace(lib={REFERENCE_TEMPLATES_KEY: r})} for _ in range(2)]
    pen = RecordingPen()
    pen.value = ORIGINAL
    result = load_reference_templates(
        fonts, {"curve": REFERENCE_TEMPLATE}, {"curve": {1: pen}}, path, {1: {}}
    )
    assert result["curve"][1].value == TEMPLATE
    path.write_bytes(b"changed")
    with pytest.raises(PipelineError, match="binding changed"):
        load_reference_templates(
            fonts, {"curve": REFERENCE_TEMPLATE}, {"curve": {1: pen}}, path, {1: {}}
        )


def test_template_is_consumed_before_fontmake_and_compiled_master_is_exact(tmp_path, monkeypatch):
    path = tmp_path / "reference.ttf"
    _reference_font(path)
    fonts = _source_set()
    # Existing source direction reverses to move,line,curve,close. Elevate the
    # protected line without changing the source operation grouping.
    template = [ORIGINAL[0], ("qCurveTo", ((50, 0), (100, 0))), *ORIGINAL[2:]]
    r = recipe(path, template)
    for font in fonts:
        lib = font["curve"].lib
        lib[q.SOURCE_GROUPS_KEY] = ((1, 1, 1, 1),)
        lib[q.PADDING_PLACEMENT_KEY] = REFERENCE_TEMPLATE
        lib[REFERENCE_TEMPLATES_KEY] = r
    report = q.preserve_quadratic_reference(
        fonts,
        default_index=1,
        reference_path=path,
        reference_location={},
        protected_locations={1: {}},
        max_error=0.03125,
    )
    assert report.carrier_glyphs == ("curve.stv-semantic16x",)
    compile_variable = ufo2ft.compileVariableTTF
    monkeypatch.setattr(
        ufo2ft,
        "compileVariableTTF",
        lambda *args, **kwargs: compile_variable(*args, reverseDirection=False, **kwargs),
    )
    variable = _compile_variable(fonts, optimize_gvar=False)
    protected = instantiateVariableFont(variable, {"opsz": 16}, inplace=False).getGlyphSet()
    from fontTools.pens.recordingPen import DecomposingRecordingPen

    actual = DecomposingRecordingPen(protected)
    protected["curve"].draw(actual)
    expected = q._recording(TTFont(path).getGlyphSet()["curve"])
    assert exact_reference_template(expected.value, actual.value)
    assert q._same_filled_path(expected, actual)


@pytest.mark.parametrize(
    "bad",
    [
        [("moveTo", ())],
        [("lineTo", ((0, 0),))],
        [("closePath", ())],
        [("moveTo", ((0, 0),)), ("moveTo", ((1, 1),))],
        [("moveTo", ((0, 0),)), ("qCurveTo", ((1, 1),))],
        [("moveTo", ((0, 0),)), ("qCurveTo", ((1, 1), None))],
        [("moveTo", ((0, 0),)), ("closePath", ((1, 1),))],
    ],
)
def test_malformed_operation_program_rejects_with_value_error(bad):
    with pytest.raises(ValueError):
        exact_reference_template(ORIGINAL, bad)


@pytest.mark.parametrize("control", [(50, 150), (100, 0)])
def test_exact_quarter_subdivision_and_cyclic_start(control):
    from fontTools.misc.bezierTools import splitQuadraticAtT

    original = [ORIGINAL[0], ORIGINAL[1], ("qCurveTo", (control, (0, 0))), ORIGINAL[-1]]
    pieces = splitQuadraticAtT((100, 0), control, (0, 0), 0.25, 0.5, 0.75)
    template = [("moveTo", ((100, 0),))]
    template.extend(("qCurveTo", tuple(piece[1:])) for piece in pieces)
    template.extend([("lineTo", ((100, 0),)), ("closePath", ())])
    assert exact_reference_template(original, template)
    bad = copy.deepcopy(template)
    point = bad[2][1][0]
    bad[2] = ("qCurveTo", ((point[0] + 0.000001, point[1]), bad[2][1][1]))
    assert not exact_reference_template(original, bad)


def test_partial_quadratic_subdivision_cannot_drop_a_span():
    from fontTools.misc.bezierTools import splitQuadraticAtT

    pieces = splitQuadraticAtT((100, 0), (50, 150), (0, 0), 0.25, 0.5, 0.75)
    template = [ORIGINAL[0], ORIGINAL[1]]
    template.extend(("qCurveTo", tuple(piece[1:])) for piece in pieces[:-1])
    template.append(("closePath", ()))
    assert not exact_reference_template(ORIGINAL, template)
