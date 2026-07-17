"""AI escape hatch: redraw interpolation-incompatible glyphs via the Vercel AI Gateway.

When :func:`reconstruct_compatible.reconstruct` cannot reconcile a glyph's static
masters, the pipeline freezes it (pins it to the default master, so it can't vary
in weight). This is the opt-in alternative: hand the incompatible per-master
outlines to an LLM (through ``@static-to-variable/glyph-forge-engine``'s
``ai-redraw`` command) which re-expresses every master onto one shared point
structure, so the glyph interpolates instead of freezing.

It is best-effort and never fatal: any glyph the model can't redraw (or the whole
batch, if the gateway is unreachable) simply stays frozen. Enable by setting
``STV_AI_REDRAW=1``; requires ``AI_GATEWAY_API_KEY`` in the environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

# A contour is variable-gen's ``[(op, [pt, ...]), ...]`` form; a glyph outline is
# ``{axis_pos: [contour, ...]}``.
Contour = list
Outline = dict


def enabled() -> bool:
    return os.environ.get("STV_AI_REDRAW", "").lower() in ("1", "true", "yes")


def _has_none_points(outlines: Outline) -> bool:
    """All-off-curve TrueType contours carry an implied (None) point that can't be
    round-tripped as coordinates; such glyphs are left frozen rather than redrawn."""
    return any(
        p is None
        for contours in outlines.values()
        for contour in contours
        for _op, pts in contour
        for p in pts
    )


def _contour_to_json(contour: Contour) -> dict:
    return {
        "segments": [
            {"op": op, "points": [[float(p[0]), float(p[1])] for p in pts]} for op, pts in contour
        ]
    }


def _contour_from_json(payload: dict) -> Contour:
    return [(seg["op"], [tuple(p) for p in seg["points"]]) for seg in payload["segments"]]


def _engine_dir(repo_root: Path) -> Path:
    # ``STV_FORGE_DIR`` wins (standalone installs point it at the bundled engine).
    # Otherwise find ``packages/glyph-forge-engine`` by walking up from this
    # module — the config's ``repo_root`` is the user's project, not the monorepo.
    override = os.environ.get("STV_FORGE_DIR")
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages/glyph-forge-engine"
        if candidate.exists():
            return candidate
    return repo_root / "packages/glyph-forge-engine"


def redraw_glyphs(
    jobs: list[dict],
    repo_root: Path,
    units_per_em: float,
) -> dict[str, Outline]:
    """Redraw a batch of incompatible glyphs.

    ``jobs`` items are ``{"glyph": str, "reference_pos": float,
    "outlines": {pos: [contour, ...]}}``. Returns ``{glyph: {pos: [contour, ...]}}``
    for the glyphs the model successfully made compatible; glyphs it couldn't
    (and every glyph, if the call fails) are simply absent, so callers keep the
    frozen fallback for those.
    """
    jobs = [job for job in jobs if not _has_none_points(job["outlines"])]
    if not jobs:
        return {}

    payload = {
        "jobs": [
            {
                "glyph": job["glyph"],
                "unitsPerEm": units_per_em,
                "referencePos": job["reference_pos"],
                "masters": [
                    {"pos": pos, "contours": [_contour_to_json(c) for c in contours]}
                    for pos, contours in sorted(job["outlines"].items())
                ],
            }
            for job in jobs
        ]
    }

    engine = _engine_dir(repo_root)
    with tempfile.TemporaryDirectory() as tmp:
        job_path = Path(tmp) / "jobs.json"
        out_path = Path(tmp) / "out.json"
        job_path.write_text(json.dumps(payload))
        try:
            proc = subprocess.run(
                ["npm", "run", "--silent", "ai-redraw", "--", str(job_path), str(out_path)],
                cwd=engine,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"[ai-redraw] skipped — could not run engine: {exc}")
            return {}
        if proc.returncode != 0:
            print(f"[ai-redraw] skipped — {proc.stderr.strip().splitlines()[-1:] or ['failed']}")
            return {}
        if not out_path.exists():
            return {}
        results = json.loads(out_path.read_text()).get("results", [])

    out: dict[str, Outline] = {}
    for res in results:
        if not res.get("ok"):
            continue
        out[res["glyph"]] = {
            master["pos"]: [_contour_from_json(c) for c in master["contours"]]
            for master in res["masters"]
        }
    return out
