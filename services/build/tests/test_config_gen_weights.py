from __future__ import annotations

import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

import pytest  # noqa: E402
from config_gen import _infer_weight, generate_config, inspect_font  # noqa: E402
from fontTools.fontBuilder import FontBuilder  # noqa: E402
from fontTools.pens.ttGlyphPen import TTGlyphPen  # noqa: E402


def _static(tmp_path: Path, filename: str, *, us_weight: int, family: str, style: str) -> Path:
    """A minimal but real TTF carrying the name/OS2 fields inspect_font reads."""
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef"])
    builder.setupCharacterMap({})
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph()})
    builder.setupHorizontalMetrics({".notdef": (500, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable(
        {
            "familyName": family,
            "styleName": "Regular",
            "typographicFamily": family,
            "typographicSubfamily": style,
            "psName": f"{family}-{style}".replace(" ", ""),
        }
    )
    builder.setupOS2(usWeightClass=us_weight, fsSelection=0)
    builder.setupPost()
    path = tmp_path / filename
    builder.save(str(path))
    return path


def test_named_weight_overrides_a_wrong_us_weight_class(tmp_path: Path) -> None:
    # Google's shipped Inter statics declare usWeightClass=250 for BOTH Thin and
    # ExtraLight. Trusting OS/2 collapsed them onto one weight and the upload was
    # rejected with duplicate_weight, so the whole family was unbuildable.
    thin = _static(tmp_path, "Thin.ttf", us_weight=250, family="Inter 18pt", style="Thin")
    extralight = _static(
        tmp_path, "ExtraLight.ttf", us_weight=250, family="Inter 18pt", style="ExtraLight"
    )

    assert inspect_font(thin)["weight"] == 100
    assert inspect_font(extralight)["weight"] == 200


def test_named_weight_overrides_a_generic_400(tmp_path: Path) -> None:
    # Operator Mono Bold ships usWeightClass=400 despite a "Bold" style name.
    bold = _static(tmp_path, "Bold.ttf", us_weight=400, family="Operator Mono", style="Bold")

    assert inspect_font(bold)["weight"] == 700


def test_us_weight_class_wins_when_the_name_says_nothing(tmp_path: Path) -> None:
    # A "Book" or "Text" cut names no standard weight, so OS/2 is the only signal
    # and a non-standard value like 350 must survive rather than snap to 400.
    book = _static(tmp_path, "Book.ttf", us_weight=350, family="Some Serif", style="Book")

    assert inspect_font(book)["weight"] == 350


def test_weight_read_from_the_family_name(tmp_path: Path) -> None:
    # Common layout: the weight lives in the family name and the style is
    # "Regular". Inferring from the style alone would call this glyph set 400.
    font = _static(tmp_path, "Thin.ttf", us_weight=250, family="Foo Thin", style="Regular")

    assert inspect_font(font)["weight"] == 100


def test_infer_weight_reports_no_opinion_rather_than_defaulting() -> None:
    assert _infer_weight("Bold") == 700
    assert _infer_weight("ExtraLight") == 200
    assert _infer_weight("Book") is None
    assert _infer_weight("") is None


def test_the_full_inter_weight_run_builds_a_config(tmp_path: Path) -> None:
    styles = [
        ("Thin", 250, 100),
        ("ExtraLight", 250, 200),
        ("Light", 300, 300),
        ("Regular", 400, 400),
        ("Medium", 500, 500),
        ("SemiBold", 600, 600),
        ("Bold", 700, 700),
        ("ExtraBold", 800, 800),
        ("Black", 900, 900),
    ]
    paths = [
        _static(tmp_path, f"{s}.ttf", us_weight=us, family="Inter 18pt", style=s)
        for s, us, _ in styles
    ]

    config, id_to_path = generate_config(paths)

    axis = config["axes"][0]
    assert axis["minimum"] == 100
    assert axis["maximum"] == 900
    assert axis["default"] == 400
    assert len(id_to_path) == len(styles)
    assert sorted(int(w) for w in axis["namedInstances"]) == [w for _, _, w in styles]


def test_genuinely_duplicated_weights_still_report_a_clear_error(tmp_path: Path) -> None:
    a = _static(tmp_path, "a.ttf", us_weight=700, family="Foo", style="Bold")
    b = _static(tmp_path, "b.ttf", us_weight=700, family="Foo", style="Bold")

    with pytest.raises(Exception) as excinfo:
        generate_config([a, b])
    assert getattr(excinfo.value, "code", None) == "duplicate_weight"
