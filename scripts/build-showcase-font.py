#!/usr/bin/env python3
"""Build one gap-family showcase variable font from Google Fonts static masters.

A "gap family" ships on Google Fonts as independent static weights with no
variable version. Those static masters are drawn independently, so they disagree
on contour count / order / start point / node count. A naive ``fontTools.varLib``
merge therefore freezes 40-65% of glyphs (they stop responding to the weight
axis) or fails outright on incompatible GSUB/GPOS tables.

This builder drives the repo's own reconstruction engine
(``variable_gen.reconstruct_compatible``) to reconcile every glyph's outlines
across the chosen weights into one shared point structure, then merges the
reconciled masters into a single ``wght``-axis variable font. It strips the
per-master OpenType layout tables (which cannot be merged and are not needed for
a weight-only showcase font), finalises names / instances / STAT, and writes:

  <out>/<id>.ttf     full variable font (all glyphs)
  <out>/<id>.woff2   web font (full font re-flavored, or Latin+Latin-1 subset)

Masters are fetched from
``raw.githubusercontent.com/google/fonts/main/ofl/<ofl>/<Family>-<Style>.ttf``
and cached under a scratch dir, or pass ``--masters-dir`` to use local .ttf files
named ``<Family>-<Style>.ttf``.

Example (Barlow, Thin/Regular/Black across the full weight axis):

  scripts/build-showcase-font.py \
      --id barlow --family Barlow --ofl barlow \
      --master Thin=100 --master Regular=400 --master Black=900 \
      --default 400 --out apps/web/public/fonts

Run it through the uv-managed env so the engine and fontTools are importable:

  uv run scripts/build-showcase-font.py ...
  # or: .venv/bin/python scripts/build-showcase-font.py ...
"""

from __future__ import annotations

import argparse
import logging
import time
import urllib.request
from pathlib import Path

from fontTools.designspaceLib import (
    AxisDescriptor,
    DesignSpaceDocument,
    InstanceDescriptor,
    SourceDescriptor,
)
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.subset import Options as SubsetOptions
from fontTools.subset import Subsetter
from fontTools.ttLib import TTFont
from fontTools.varLib import build as varlib_build
from variable_gen.outlines import donor_outline
from variable_gen.reconstruct_compatible import reconstruct

# Tables dropped from every master before the merge. OpenType layout (GSUB/GPOS/
# ...) cannot be merged across independently-drawn statics and is not needed for a
# weight-only showcase font. TrueType hinting (fpgm/prep/cvt/gasp) is dropped too:
# every glyph is redrawn here, so the default master's instructions are stale and
# would otherwise leave orphaned cvar/hinting tables in the output.
DROP_TABLES = (
    "GSUB",
    "GPOS",
    "GDEF",
    "BASE",
    "JSTF",
    "kern",
    "MATH",
    "fpgm",
    "prep",
    "cvt ",
    "gasp",
)

# Tables varLib may synthesise that the showcase fonts do not ship.
DROP_AFTER_BUILD = ("MVAR", "cvar")

RAW_BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl"

# Web subset: Basic Latin + Latin-1 Supplement + Latin Extended-A (accents), plus
# the punctuation/symbols a preview needs so it never renders tofu (curly quotes,
# dashes, ellipsis, euro, trademark, common ligatures).
SUBSET_CODEPOINTS = set(range(0x0000, 0x0180)) | {
    0x2013,
    0x2014,
    0x2018,
    0x2019,
    0x201C,
    0x201D,
    0x2020,
    0x2021,
    0x2022,
    0x2026,
    0x2030,
    0x2039,
    0x203A,
    0x20AC,
    0x2122,
    0x2212,
    0xFB01,
    0xFB02,
}

log = logging.getLogger("build-showcase-font")


class Master:
    """One weight of the family: its axis position, source .ttf, and outlines."""

    def __init__(self, style: str, wght: float, path: Path):
        self.style = style
        self.wght = wght
        self.path = path
        self.font = TTFont(str(path))
        # Outlines are read from a pristine second load, never from self.font:
        # reconcile() rewrites glyphs into self.font as it goes, and a live
        # glyphset over it would decompose later composites (gcircumflex = g +
        # circumflex) against already-rewritten bases, which then fail the
        # quality gate and freeze even though the donor outlines reconstruct.
        self.glyphset = TTFont(str(path)).getGlyphSet()

    def outline(self, name: str):
        """Decomposed donor contours for ``name`` (or None if undrawable)."""
        got = donor_outline(self.glyphset, name)
        return None if got is None else got  # (contours, width)


def parse_master(spec: str) -> tuple[str, float]:
    style, _, wght = spec.partition("=")
    if not style or not wght:
        raise argparse.ArgumentTypeError(f"master must be Style=wght, got {spec!r}")
    return style, float(wght)


def resolve_masters(
    family: str,
    ofl: str,
    specs: list[tuple[str, float]],
    masters_dir: Path | None,
    cache: Path,
) -> list[Master]:
    masters: list[Master] = []
    for style, wght in specs:
        filename = f"{family.replace(' ', '')}-{style}.ttf"
        if masters_dir is not None:
            path = masters_dir / filename
            if not path.exists():
                raise SystemExit(f"missing local master: {path}")
        else:
            path = cache / filename
            if not path.exists():
                url = f"{RAW_BASE}/{ofl}/{filename}"
                log.info("fetch %s", url)
                cache.mkdir(parents=True, exist_ok=True)
                try:
                    urllib.request.urlretrieve(url, path)  # noqa: S310 (fixed host)
                except Exception as exc:  # noqa: BLE001
                    raise SystemExit(f"failed to fetch {url}: {exc}") from exc
        masters.append(Master(style, wght, path))
    return masters


def draw_glyph(contours) -> object:
    """Draw reconstructed donor contours into a fresh TrueType glyf glyph."""
    pen = TTGlyphPen(None)
    for contour in contours:
        for op, pts in contour:
            if op == "moveTo":
                pen.moveTo(pts[0])
            elif op == "lineTo":
                pen.lineTo(pts[0])
            elif op == "qCurveTo":
                pen.qCurveTo(*pts)
            elif op == "curveTo":  # cubic: should not occur from glyf sources
                pen.curveTo(*pts)
            elif op == "closePath":
                pen.closePath()
            elif op == "endPath":
                pen.endPath()
    return pen.glyph()


def set_glyph(font: TTFont, name: str, contours, width: float) -> None:
    glyf = font["glyf"]
    glyph = draw_glyph(contours)
    glyf[name] = glyph
    glyph.recalcBounds(glyf)
    lsb = glyph.xMin if getattr(glyph, "numberOfContours", 0) else 0
    font["hmtx"].metrics[name] = (int(round(width)), int(lsb))


class BuildStats:
    def __init__(self) -> None:
        self.native = 0  # already interpolation-compatible
        self.reconstructed = 0  # reconciled by the engine
        self.frozen: list[str] = []  # left static at the default master shape
        self.total = 0


def reconcile(masters: list[Master], default_wght: float, stats: BuildStats) -> None:
    """Reconcile every glyph across masters, writing shared-structure outlines
    back into each master. Glyphs that cannot be reconciled are frozen: every
    master is given the default master's outline so they carry no weight delta."""
    default = next(m for m in masters if m.wght == default_wght)
    order = default.font.getGlyphOrder()
    stats.total = len(order)

    for name in order:
        default_outline = default.outline(name)
        if default_outline is None:  # e.g. empty .notdef edge cases; leave as-is
            continue
        d_contours, d_width = default_outline

        outlines = {}
        drawable = True
        for m in masters:
            got = m.outline(name)
            if got is None:
                drawable = False
                break
            outlines[m.wght] = got[0]

        result = None
        if drawable:
            try:
                result, info = reconstruct(outlines, reference_pos=default_wght)
            except Exception as exc:  # noqa: BLE001 (engine edge cases -> freeze)
                log.debug("reconstruct raised for %s: %s", name, exc)
                result = None
                info = {"stage": None}

        if result is None:
            # Freeze: give every master the default outline (zero weight delta).
            stats.frozen.append(name)
            for m in masters:
                set_glyph(m.font, name, d_contours, d_width)
            continue

        if info.get("stage") == "compatible":
            stats.native += 1
        else:
            stats.reconstructed += 1
        for m in masters:
            width = m.outline(name)[1]
            set_glyph(m.font, name, result[m.wght], width)


def prepare_masters(masters: list[Master], default_wght: float) -> None:
    """Drop unmergeable tables and force every master onto the default glyph
    order so varLib sees one consistent, layout-free master set."""
    default = next(m for m in masters if m.wght == default_wght)
    order = default.font.getGlyphOrder()
    for m in masters:
        for tag in DROP_TABLES:
            if tag in m.font:
                del m.font[tag]
        m.font.setGlyphOrder(order)


def build_variable(
    masters: list[Master],
    axis_name: str,
    default_wght: float,
) -> TTFont:
    lo = min(m.wght for m in masters)
    hi = max(m.wght for m in masters)

    doc = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.tag, axis.name = "wght", axis_name
    axis.minimum, axis.default, axis.maximum = lo, default_wght, hi
    doc.addAxis(axis)

    for m in masters:
        source = SourceDescriptor()
        source.font = m.font
        source.location = {axis_name: m.wght}
        source.styleName = m.style
        if m.wght == default_wght:
            source.copyInfo = True
        doc.addSource(source)

    for m in masters:
        inst = InstanceDescriptor()
        inst.location = {axis_name: m.wght}
        inst.styleName = m.style
        doc.addInstance(inst)

    varfont, _, _ = varlib_build(doc)
    for tag in DROP_AFTER_BUILD:
        if tag in varfont:
            del varfont[tag]
    return varfont


def _set_name(font: TTFont, value: str, name_id: int) -> None:
    font["name"].setName(value, name_id, 3, 1, 0x409)  # Windows Unicode English
    font["name"].setName(value, name_id, 1, 0, 0)  # Mac Roman English


def finalize(font: TTFont, family: str, version: str, default_wght: float) -> None:
    ps_family = family.replace(" ", "")
    _set_name(font, family, 1)  # family
    _set_name(font, "Regular", 2)  # subfamily
    _set_name(font, family, 4)  # full name
    _set_name(font, f"{ps_family}-Regular", 6)  # PostScript name
    _set_name(font, f"Version {version}", 5)
    _set_name(font, family, 16)  # typographic family
    _set_name(font, "Regular", 17)  # typographic subfamily

    os2 = font["OS/2"]
    os2.usWeightClass = int(default_wght)
    os2.fsSelection = (os2.fsSelection | 0x040) & ~0x001  # REGULAR, not ITALIC
    font["head"].macStyle &= ~0x3


def write_woff2(font: TTFont, out: Path, subset_latin: bool) -> Path:
    woff2 = out.with_suffix(".woff2")
    if subset_latin:
        opts = SubsetOptions()
        opts.flavor = "woff2"  # brotli
        opts.name_IDs = ["*"]
        opts.recalc_bounds = True
        opts.retain_gids = False
        subsetter = Subsetter(options=opts)
        subsetter.populate(unicodes=SUBSET_CODEPOINTS)
        subsetter.subset(font)
        font.save(str(woff2))
    else:
        font.flavor = "woff2"  # full font, brotli-compressed
        font.save(str(woff2))
    return woff2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build one gap-family showcase variable font.")
    ap.add_argument("--id", required=True, help="output file stem, e.g. 'barlow'")
    ap.add_argument("--family", required=True, help="family name, e.g. 'Barlow'")
    ap.add_argument("--ofl", help="google/fonts ofl dir (default: id)")
    ap.add_argument(
        "--master",
        action="append",
        required=True,
        type=parse_master,
        metavar="Style=wght",
        help="a static master, e.g. Thin=100 (repeat, 2+ required)",
    )
    ap.add_argument("--default", type=float, required=True, help="default axis position")
    ap.add_argument("--out", required=True, type=Path, help="output directory")
    ap.add_argument("--version", default="1.000", help="font version string")
    ap.add_argument("--axis-name", default="Weight")
    ap.add_argument("--masters-dir", type=Path, help="use local masters instead of fetching")
    ap.add_argument(
        "--cache",
        type=Path,
        default=Path("/tmp/stv-showcase-masters"),
        help="download cache for fetched masters",
    )
    ap.add_argument(
        "--woff2-subset",
        action="store_true",
        help="subset the woff2 to Latin (Basic+Latin-1+Extended-A+web punctuation); "
        "default: full font re-flavored",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Silence varLib's per-glyph "incompatible masters" chatter; freezing is
    # handled explicitly here and reported in the summary.
    logging.getLogger("fontTools.varLib").setLevel(logging.ERROR)

    if len(args.master) < 2:
        raise SystemExit("need at least 2 masters")
    if args.default not in {w for _, w in args.master}:
        raise SystemExit(f"--default {args.default} is not one of the masters")

    started = time.time()
    masters = resolve_masters(
        args.family, args.ofl or args.id, args.master, args.masters_dir, args.cache
    )

    stats = BuildStats()
    reconcile(masters, args.default, stats)
    prepare_masters(masters, args.default)
    varfont = build_variable(masters, args.axis_name, args.default)
    finalize(varfont, args.family, args.version, args.default)

    args.out.mkdir(parents=True, exist_ok=True)
    ttf = args.out / f"{args.id}.ttf"
    varfont.save(str(ttf))
    # Re-open for woff2 so subsetting never mutates the saved TTF in place.
    woff2 = write_woff2(TTFont(str(ttf)), ttf, args.woff2_subset)

    elapsed = time.time() - started
    fvar = TTFont(str(ttf))["fvar"]
    axis = fvar.axes[0]
    print("")
    print(f"built {args.family}  ({elapsed:.1f}s)")
    print(f"  axis:   {axis.axisTag} {axis.minValue} / {axis.defaultValue} / {axis.maxValue}")
    print(
        f"  glyphs: {stats.total}  varying: {stats.native + stats.reconstructed}"
        f"  (native {stats.native}, reconstructed {stats.reconstructed})"
    )
    print(f"  frozen: {len(stats.frozen)}" + (f"  {stats.frozen}" if stats.frozen else ""))
    print(f"  ttf:    {ttf}  ({ttf.stat().st_size / 1024:.0f} KB)")
    label = "Latin+Latin-1 subset" if args.woff2_subset else "full"
    print(f"  woff2:  {woff2}  ({woff2.stat().st_size / 1024:.0f} KB, {label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
