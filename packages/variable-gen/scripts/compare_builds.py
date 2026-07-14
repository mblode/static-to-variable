#!/usr/bin/env python3
"""Glide parity gate: diff a freshly-built variable font against a baseline.

Used as a regression gate during the toolchain/engine refactor. A rebuild from
the same sources must produce a byte-identical VF *except* for volatile stamps
(build timestamps, version/unique-id strings). This dumps both fonts to TTX,
masks those volatile fields, and diffs the tables that actually carry the
outlines, interpolation, and metadata:

    glyf gvar fvar avar name OS/2 STAT hmtx cmap

Masked before diffing (so a timestamp-only rebuild still passes):
  - head.created / head.modified           -> normalized to a constant
  - name records nameID 3 (unique id) and 5 (version) -> normalized
  - any date-like "YYYY-MM-DD[ T]HH..." substring inside a name record

Exit 0 if every compared table is identical after masking (and, when report
paths are given, the reconstruction reports match); exit 1 otherwise.

Run (baseline vs a fresh build):
  .venv/bin/python packages/variable-gen/scripts/compare_builds.py \\
      --baseline .baseline-snapshot/parity/glide-variable-vf.ttf \\
      --candidate packages/variable-gen/build/roman/glide-variable-vf.ttf
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont

# Tables that carry outlines, interpolation deltas, axes, and metadata. A
# same-source rebuild must reproduce these exactly (post-masking).
TABLES = ["glyf", "gvar", "fvar", "avar", "name", "OS/2", "STAT", "hmtx", "cmap"]

MAX_DIFF_LINES = 80  # very long diffs are truncated to this many lines

# --- masking ---------------------------------------------------------------
# head timestamps: <created value="..."/> and <modified value="..."/>
_HEAD_STAMP = re.compile(r'(<(?:created|modified) value=")[^"]*(")')
# a full name record block; group 1 = opening tag, 2 = body, 3 = closing tag
_NAMEREC = re.compile(r'(<namerecord nameID="(\d+)"[^>]*>)(.*?)(</namerecord>)', re.DOTALL)
# a date/time stamp that may appear inside a version or build string
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?")
# the ttLibVersion attribute in the per-table TTX header (defensive; both runs
# use the same fontTools, but a version bump shouldn't be read as a real diff)
_TTLIB = re.compile(r'(ttLibVersion=")[^"]*(")')

# nameIDs whose whole value is volatile: 3 = unique font id, 5 = version string
_VOLATILE_NAME_IDS = {"3", "5"}


def _mask_name(text: str) -> str:
    def repl(m: re.Match) -> str:
        open_tag, name_id, body, close_tag = m.group(1), m.group(2), m.group(3), m.group(4)
        if name_id in _VOLATILE_NAME_IDS:
            body = "\n      MASKED\n    "
        else:
            body = _DATE.sub("MASKED", body)
        return open_tag + body + close_tag

    return _NAMEREC.sub(repl, text)


def mask(table: str, text: str) -> str:
    text = _TTLIB.sub(r"\1MASKED\2", text)
    if table == "name":
        text = _mask_name(text)
    if table == "head":  # not diffed directly, but kept for completeness
        text = _HEAD_STAMP.sub(r"\1MASKED\2", text)
    return text


# --- ttx dumping -----------------------------------------------------------
def dump_table(font: TTFont, table: str, tmp: Path) -> str | None:
    """Return the masked TTX for one table, or None if the font lacks it."""
    if table not in font:
        return None
    out = tmp / f"{table.replace('/', '_')}.ttx"
    font.saveXML(str(out), tables=[table])
    return mask(table, out.read_text(encoding="utf-8"))


def diff_tables(baseline: Path, candidate: Path) -> tuple[bool, list[str]]:
    """Diff every table for one font pair. Returns (ok, report_lines)."""
    bf, cf = TTFont(str(baseline)), TTFont(str(candidate))
    lines: list[str] = []
    ok = True
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        b_tmp, c_tmp = tmp / "b", tmp / "c"
        b_tmp.mkdir()
        c_tmp.mkdir()
        for table in TABLES:
            b = dump_table(bf, table, b_tmp)
            c = dump_table(cf, table, c_tmp)
            if b is None and c is None:
                lines.append(f"  {table:6s} ABSENT in both (skipped)")
                continue
            if b is None or c is None:
                ok = False
                where = "candidate" if b is None else "baseline"
                lines.append(f"  {table:6s} MISMATCH — missing in {where}")
                continue
            if b == c:
                lines.append(f"  {table:6s} IDENTICAL")
                continue
            ok = False
            udiff = list(
                difflib.unified_diff(
                    b.splitlines(),
                    c.splitlines(),
                    fromfile=f"baseline/{table}",
                    tofile=f"candidate/{table}",
                    lineterm="",
                )
            )
            lines.append(f"  {table:6s} DIFFERS ({len(udiff)} diff lines):")
            shown = udiff[:MAX_DIFF_LINES]
            lines.extend("    " + ln for ln in shown)
            if len(udiff) > MAX_DIFF_LINES:
                lines.append(f"    ... ({len(udiff) - MAX_DIFF_LINES} more lines truncated)")
    return ok, lines


# --- report comparison -----------------------------------------------------
def compare_reports(baseline: Path, candidate: Path) -> tuple[bool, list[str]]:
    """Compare two reconstruction-report.json files field by field.

    List fields (e.g. ai_pending glyph names) are compared as sorted sets and
    reported as added/removed; scalar fields (donor/reconstructed/frozen
    counts) are compared for equality."""
    import json

    b = json.loads(baseline.read_text(encoding="utf-8"))
    c = json.loads(candidate.read_text(encoding="utf-8"))
    lines: list[str] = []
    ok = True
    for fam in sorted(set(b) | set(c)):
        lines.append(f"  [{fam}]")
        if fam not in b or fam not in c:
            ok = False
            lines.append(f"    family only in {'baseline' if fam in b else 'candidate'}")
            continue
        bd, cd = b[fam], c[fam]
        for key in sorted(set(bd) | set(cd)):
            bv, cv = bd.get(key), cd.get(key)
            if isinstance(bv, list) or isinstance(cv, list):
                bs, cs = set(bv or []), set(cv or [])
                if bs == cs:
                    lines.append(f"    {key}: IDENTICAL ({len(bs)} names)")
                else:
                    ok = False
                    added = sorted(cs - bs)
                    removed = sorted(bs - cs)
                    lines.append(f"    {key}: DIFFERS  added={added}  removed={removed}")
            elif bv == cv:
                lines.append(f"    {key}: {bv}")
            else:
                ok = False
                lines.append(f"    {key}: DIFFERS  baseline={bv}  candidate={cv}")
    return ok, lines


# --- pairing ---------------------------------------------------------------
def resolve_pairs(args) -> list[tuple[Path, Path]]:
    if args.baseline_dir or args.candidate_dir:
        if not (args.baseline_dir and args.candidate_dir):
            sys.exit("--baseline-dir and --candidate-dir must be given together")
        bdir, cdir = Path(args.baseline_dir), Path(args.candidate_dir)
        pairs = []
        for bpath in sorted(bdir.glob("*.ttf")):
            cpath = cdir / bpath.name
            if not cpath.exists():
                sys.exit(f"no candidate for {bpath.name} in {cdir}")
            pairs.append((bpath, cpath))
        if not pairs:
            sys.exit(f"no *.ttf found in {bdir}")
        return pairs
    if not args.baseline or not args.candidate:
        sys.exit("give --baseline/--candidate (repeatable) or --baseline-dir/--candidate-dir")
    if len(args.baseline) != len(args.candidate):
        sys.exit("--baseline and --candidate counts differ")
    return [(Path(b), Path(c)) for b, c in zip(args.baseline, args.candidate, strict=False)]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--baseline", action="append", help="baseline VF (repeatable)")
    ap.add_argument("--candidate", action="append", help="candidate VF (repeatable)")
    ap.add_argument("--baseline-dir", help="dir of baseline *.ttf (matched by name)")
    ap.add_argument("--candidate-dir", help="dir of candidate *.ttf (matched by name)")
    ap.add_argument("--report-baseline", help="baseline reconstruction-report.json")
    ap.add_argument("--report-candidate", help="candidate reconstruction-report.json")
    args = ap.parse_args()

    pairs = resolve_pairs(args)
    all_ok = True
    for baseline, candidate in pairs:
        print(f"\n=== {baseline.name}  vs  {candidate.name} ===")
        ok, lines = diff_tables(baseline, candidate)
        print("\n".join(lines))
        all_ok = all_ok and ok

    if args.report_baseline and args.report_candidate:
        print("\n=== reconstruction report ===")
        ok, lines = compare_reports(Path(args.report_baseline), Path(args.report_candidate))
        print("\n".join(lines))
        all_ok = all_ok and ok

    verdict = (
        "PARITY OK — all compared tables identical"
        if all_ok
        else "PARITY FAILED — differences above"
    )
    print(f"\n{verdict}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
