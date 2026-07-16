"""Pure decision-logic tests for ingest severity mapping and strategy
recommendations — dict fixtures only, no fonts or reports on disk."""

from ingest_audit_reports import VERDICT_ORDER, _more_severe, severity_to_verdict
from recommend_strategy import recommend_for_glyph


def test_verdict_order_is_monotonic():
    assert VERDICT_ORDER[0] == "unknown"
    assert VERDICT_ORDER[-1] == "tracked"


def test_more_severe_picks_the_higher_verdict():
    assert _more_severe("low", "blocker") == "blocker"
    assert _more_severe("high", "medium") == "high"
    assert _more_severe("unknown", "low") == "low"


def test_severity_to_verdict_thresholds():
    assert severity_to_verdict(None) == "unknown"
    # Monotonic: a higher severity score never yields a milder verdict.
    scores = [0, 1, 3, 6, 10, 100]
    verdicts = [severity_to_verdict(score) for score in scores]
    ranks = [VERDICT_ORDER.index(verdict) for verdict in verdicts]
    assert ranks == sorted(ranks)


def cell(void=1.0, irregularity=1.0, drift=1.0):
    return {"void": void, "irregularity": irregularity, "drift": drift}


def scores(avg=0.9, worst=0.8, wght=400):
    return {"avgComposite": avg, "worstComposite": worst, "worstWght": wght}


def test_missing_scores_fall_back_to_reference():
    suggestion = recommend_for_glyph("roman", "at", {}, {})
    assert suggestion.strategy == "reference_fallback"
    assert suggestion.confidence < 0.5


def test_lumpy_curves_recommend_donor_copy():
    suggestion = recommend_for_glyph(
        "roman",
        "at",
        {"roman/at/100": cell(irregularity=0.2)},
        {"roman/at": scores()},
    )
    assert suggestion.strategy == "donor_copy"


def test_large_void_recommends_structural_fallback():
    suggestion = recommend_for_glyph(
        "roman",
        "at",
        {"roman/at/100": cell(void=0.1)},
        {"roman/at": scores()},
    )
    assert suggestion.strategy == "structural_fallback"


def test_pure_drift_recommends_inheriting_base_contours():
    suggestion = recommend_for_glyph(
        "roman",
        "at",
        {"roman/at/100": cell(void=0.9, irregularity=0.9, drift=0.2)},
        {"roman/at": scores()},
    )
    assert suggestion.strategy == "inherit_base_contours"


def test_near_acceptable_recommends_weighted_fallback():
    suggestion = recommend_for_glyph(
        "roman",
        "at",
        {"roman/at/100": cell(void=0.8, irregularity=0.9, drift=0.9)},
        {"roman/at": scores(avg=0.85, worst=0.6)},
    )
    assert suggestion.strategy == "weighted_fallback"
