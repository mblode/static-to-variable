"""Heuristic strategy recommender.

Consumes cell-scores.json + glyph-scores.json + circular-triage.json.
Emits manifests/strategy-suggestions.json with per-glyph suggestion + reason.

The rules are intentionally simple — this is a starting point, not a solver.
They are also transparent, so a human can override any recommendation.

Decision rules (first match wins):

1. Irregularity catastrophically low at any weight (< 0.4) → donor_copy
   The glide outline is lumpy/kinked. Replace topology wholesale from donor.

2. Void catastrophically low at any weight (< 0.3) → structural_fallback
   Interpolated shape lands in the wrong pixels. Full replace + rebuild.

3. Drift low (< 0.4) but others OK → inherit_base_contours
   Overall shape is right but vertices drift. Pin to a stable base glyph.

4. All worst scores < 0.3 → structural_fallback
   Try the most comprehensive automatic repair before requiring a human.

5. avg > 0.7 and worst > 0.5 → weighted_fallback
   Close to acceptable; nudge the interpolation toward the donor.

6. Else → structural_fallback
   Ambiguous glyphs still get an automatic whole-glyph repair. Human review is
   reserved for solver-classified reconstruction cases.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from shared import MANIFEST_PATH, PACKAGE_ROOT, TRIAGE_MANIFEST

CELL_SCORES_PATH = PACKAGE_ROOT / "manifests" / "cell-scores.json"
GLYPH_SCORES_PATH = PACKAGE_ROOT / "manifests" / "glyph-scores.json"
SUGGESTIONS_PATH = PACKAGE_ROOT / "manifests" / "strategy-suggestions.json"


@dataclass
class Suggestion:
    strategy: str
    confidence: float  # 0 (uncertain) - 1 (certain)
    reason: str
    matchesExisting: bool | None = None  # vs circular-triage current value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _min_score(cells: dict[str, float], key: str) -> float:
    vals = [c[key] for c in cells.values()]
    return min(vals) if vals else 1.0


def _avg_score(cells: dict[str, float], key: str) -> float:
    vals = [c[key] for c in cells.values()]
    return sum(vals) / len(vals) if vals else 1.0


def recommend_for_glyph(
    family: str,
    name: str,
    cell_scores: dict,
    glyph_scores: dict,
) -> Suggestion:
    key = f"{family}/{name}"
    agg = glyph_scores.get(key)
    if agg is None or agg["worstComposite"] is None:
        return Suggestion(
            strategy="reference_fallback",
            confidence=0.35,
            reason=(
                "No donor comparison scores are available for this glyph name. "
                "Freeze the current compatible reference outline automatically; "
                "do not send this to human review unless the solver flags whole-glyph reconstruction."
            ),
        )

    cells = {k: v for k, v in cell_scores.items() if k.startswith(f"{key}/")}
    if not cells:
        return Suggestion(
            strategy="reference_fallback",
            confidence=0.35,
            reason=(
                "No per-weight score cells were found for this glyph. Freeze the current "
                "compatible reference outline automatically; reconstruction review is decided "
                "by solver reconstruction flags."
            ),
        )

    min_void = _min_score(cells, "void")
    min_irreg = _min_score(cells, "irregularity")
    min_drift = _min_score(cells, "drift")
    avg_comp = agg["avgComposite"] or 0.0
    worst_comp = agg["worstComposite"] or 0.0
    worst_wght = agg["worstWght"]

    # Rule 1
    if min_irreg < 0.4:
        return Suggestion(
            strategy="donor_copy",
            confidence=0.85,
            reason=(
                f"Irregularity bottoms at {min_irreg:.2f} — the glide outline has lumpy "
                f"curves or self-intersections at some weights. Copying the donor outlines "
                f"for all masters replaces the bad topology."
            ),
        )

    # Rule 2
    if min_void < 0.3:
        return Suggestion(
            strategy="structural_fallback",
            confidence=0.8,
            reason=(
                f"Void score bottoms at {min_void:.2f} at weight {worst_wght} — "
                f"the interpolated glyph lands in the wrong pixels (large pixel mismatch "
                f"vs donor). A structural fallback rebuilds the glyph from donor masters."
            ),
        )

    # Rule 3
    if min_drift < 0.4 and min_void > 0.6 and min_irreg > 0.7:
        return Suggestion(
            strategy="inherit_base_contours",
            confidence=0.7,
            reason=(
                f"Drift dips to {min_drift:.2f} but shape (void {min_void:.2f}) and "
                f"smoothness (irregularity {min_irreg:.2f}) are both OK. Vertices drift "
                f"from the donor at some weights — pin this glyph's base contours to a "
                f"stable reference glyph."
            ),
        )

    # Rule 4
    if worst_comp < 0.3:
        return Suggestion(
            strategy="structural_fallback",
            confidence=0.65,
            reason=(
                f"All three metrics are catastrophically low at weight {worst_wght} "
                f"(composite {worst_comp:.2f}). Use the most comprehensive automatic "
                f"whole-glyph fallback before escalating to reconstruction review."
            ),
        )

    # Rule 5
    if avg_comp > 0.7 and worst_comp > 0.5:
        return Suggestion(
            strategy="weighted_fallback",
            confidence=0.6,
            reason=(
                f"Avg composite {avg_comp:.2f} with worst {worst_comp:.2f} at weight "
                f"{worst_wght}. Close to acceptable — nudge the interpolation toward the "
                f"donor master at the weak weight(s) to smooth out the dip."
            ),
        )

    # Rule 6 fallback
    return Suggestion(
        strategy="structural_fallback",
        confidence=0.45,
        reason=(
            f"Scores don't fit a clean heuristic bucket "
            f"(avg {avg_comp:.2f}, worst {worst_comp:.2f} @ {worst_wght}, "
            f"void {min_void:.2f}, irr {min_irreg:.2f}, drift {min_drift:.2f}). "
            f"Defaulting to automatic whole-glyph structural fallback; solver "
            f"reconstruction flags decide whether a human is required."
        ),
    )


def _load(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open() as f:
        return json.load(f)


def load_triage_strategies() -> dict[str, str]:
    """Flatten circular-triage.json into {family/glyph: strategy}."""
    raw = _load(TRIAGE_MANIFEST)
    if raw is None:
        return {}
    out = {}
    for family, cfg in raw.items():
        if family not in ("roman", "italic"):
            continue
        for name, gcfg in (cfg.get("glyphs") or {}).items():
            if "strategy" in gcfg:
                out[f"{family}/{name}"] = gcfg["strategy"]
    return out


def build() -> int:
    manifest = _load(MANIFEST_PATH)
    cell_scores = _load(CELL_SCORES_PATH)
    glyph_scores = _load(GLYPH_SCORES_PATH)
    if manifest is None:
        print("error: broken-glyphs.json missing", file=sys.stderr)
        return 1
    if cell_scores is None or glyph_scores is None:
        print(
            "error: cell-scores.json or glyph-scores.json missing — run build_scores.py first",
            file=sys.stderr,
        )
        return 1
    existing = load_triage_strategies()

    suggestions: dict[str, dict] = {}
    counts: dict[str, int] = {}
    changes = 0
    for entry in manifest:
        key = f"{entry['family']}/{entry['name']}"
        s = recommend_for_glyph(entry["family"], entry["name"], cell_scores, glyph_scores)
        if key in existing:
            s.matchesExisting = existing[key] == s.strategy
            if not s.matchesExisting:
                changes += 1
        suggestions[key] = s.to_dict()
        counts[s.strategy] = counts.get(s.strategy, 0) + 1

    SUGGESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUGGESTIONS_PATH.open("w", encoding="utf-8") as f:
        json.dump(suggestions, f, indent=0, ensure_ascii=False)

    print(f"wrote suggestions for {len(suggestions)} glyphs")
    for strat, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {strat}: {n}")
    print(
        f"of the {len(existing)} glyphs in circular-triage.json, "
        f"{changes} have a suggestion that differs from the current strategy."
    )
    return 0


if __name__ == "__main__":
    sys.exit(build())
