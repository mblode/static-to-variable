#!/usr/bin/env python3
"""Safe auto-converge loop for the glyph_forge "automatic decisions" gate.

The gate flags every glyph where the recommender's suggested strategy is more
rigorous than the manifest's current strategy. Naively applying all suggestions
(`auto-stage` + `apply`) converges the gate to zero but can REGRESS glyphs —
e.g. pushing `italic:perthousand` to `interpolatable=2` or freezing `.ss08`
glyphs. So "apply everything the recommender suggests" is unsafe.

This loop applies only suggestions that are gain-positive (enforced by
`bulk_stage --min-gain`) AND do not regress `blocker_residuals`. After each batch
it rebuilds and compares the residual failure set against the accepted baseline;
any glyph that newly fails is reverted to its prior manifest entry and added to a
permanent exclusion set, so the loop always makes progress and terminates.

The cheap inner check is repair + residual (~2 min). The expensive
audit + forge:build (~4 min) only runs when the gate's candidate set must be
recomputed for the next round.

Run from the repo root via:
    npm --workspace @static-to-variable/glyph-forge-engine run converge
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
VENV_PY = REPO_ROOT / ".venv/bin/python"

MANIFEST = REPO_ROOT / "packages/variable-gen/manifests/circular-triage.json"
RESIDUAL_JSON = REPO_ROOT / "packages/variable-gen/reports/repair/blocker-residual-validation.json"
PENDING = PACKAGE_ROOT / "manifests/pending-triage-edits.json"

# variable_gen.pipeline gate logic is the single source of truth for candidates.
sys.path.insert(0, str(REPO_ROOT / "packages/variable-gen/src"))
from variable_gen import pipeline as P  # noqa: E402

FAILURE_RE = re.compile(r"^(roman|italic):([^:]+):")


def run(cmd: list[str], *, label: str) -> None:
    print(f"  $ {label}", flush=True)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0 and "residual" not in label:
        # residual:blockers exits 1 when failures remain — that's expected here.
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        raise SystemExit(f"command failed: {label}")


def repair() -> None:
    run(
        [
            str(VENV_PY),
            "-m",
            "variable_gen.cli",
            "rebuild",
            "--config",
            "examples/glide/stv.config.json",
            "--style",
            "all",
        ],
        label="rebuild",
    )


def residual() -> None:
    subprocess.run(
        [
            str(VENV_PY),
            "packages/variable-gen/scripts/validate_residual_glyphs.py",
            "--family",
            "all",
            "--min-priority",
            "blocker",
            "--output",
            "packages/variable-gen/reports/repair/blocker-residual-validation.md",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def forge_audit() -> None:
    run(
        [str(VENV_PY), "packages/variable-gen/scripts/audit_variable_font.py", "--style", "all"],
        label="audit",
    )
    run(["npm", "run", "forge:build"], label="forge:build")


def failing_set() -> set[tuple[str, str]]:
    data = json.loads(RESIDUAL_JSON.read_text())
    out: set[tuple[str, str]] = set()
    for f in data.get("failures", []):
        m = FAILURE_RE.match(f)
        if m:
            out.add((m.group(1), m.group(2)))
    return out


def gate_candidates() -> set[tuple[str, str]]:
    base = PACKAGE_ROOT / "manifests"
    broken = json.loads((base / "broken-glyphs.json").read_text())
    sugg = json.loads((base / "strategy-suggestions.json").read_text())
    solv = json.loads((base / "solver-results.json").read_text())
    out: set[tuple[str, str]] = set()
    for item in broken:
        if P._automatic_decision_kind(item, solv, sugg):
            fam, name = item.get("family"), item.get("name")
            if fam and name:
                out.add((fam, name))
    return out


def stage_and_apply(names: set[tuple[str, str]], min_gain: float) -> None:
    # bulk_stage --names matches BARE glyph names and disambiguates families via
    # --family, so stage one family at a time with bare names.
    PENDING.write_text("[]\n")  # start each batch from an empty pending queue
    names_file = PENDING.parent / "converge-names.txt"
    for fam in ("roman", "italic"):
        fam_names = sorted(n for f, n in names if f == fam)
        if not fam_names:
            continue
        names_file.write_text("\n".join(fam_names) + "\n")
        run(
            [
                str(VENV_PY),
                "packages/glyph-forge-engine/python/bulk_stage.py",
                "--family",
                fam,
                "--strategy-source",
                "suggestion",
                "--no-downgrade",
                "--min-gain",
                str(min_gain),
                "--names",
                str(names_file),
            ],
            label=f"bulk_stage {fam} {len(fam_names)} names",
        )
    run([str(VENV_PY), "packages/glyph-forge-engine/python/apply_pending_triage.py"], label="apply")


def manifest_entry(data: dict, fam: str, name: str):
    return data.get(fam, {}).get("glyphs", {}).get(name)


def revert_glyphs(bad: set[tuple[str, str]], backup: dict) -> None:
    cur = json.loads(MANIFEST.read_text())
    for fam, name in bad:
        prior = manifest_entry(backup, fam, name)
        glyphs = cur.setdefault(fam, {}).setdefault("glyphs", {})
        if prior is None:
            glyphs.pop(name, None)
        else:
            glyphs[name] = prior
    MANIFEST.write_text(json.dumps(cur, indent=2) + "\n")


def changed_keys(before: dict, after: dict) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for fam in ("roman", "italic"):
        b = before.get(fam, {}).get("glyphs", {})
        a = after.get(fam, {}).get("glyphs", {})
        for name in set(a) | set(b):
            if a.get(name) != b.get(name):
                out.add((fam, name))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-rounds", type=int, default=6)
    ap.add_argument("--min-gain", type=float, default=0.1)
    args = ap.parse_args()

    print("== converge: establishing coherent baseline ==", flush=True)
    # All sub-commands run with cwd=REPO_ROOT using repo-root-relative paths; the
    # forge scripts resolve their own data dirs from PACKAGE_ROOT internally.
    repair()
    residual()
    forge_audit()
    baseline = failing_set()
    print(f"baseline residual failures: {len(baseline)} glyphs", flush=True)

    excluded: set[tuple[str, str]] = set()
    applied: set[tuple[str, str]] = set()

    for rnd in range(1, args.max_rounds + 1):
        candidates = gate_candidates() - excluded
        print(
            f"\n== round {rnd}: {len(candidates)} candidate(s), {len(excluded)} excluded ==",
            flush=True,
        )
        if not candidates:
            print("converged: no remaining safe automatic candidates.", flush=True)
            break

        backup = json.loads(MANIFEST.read_text())
        stage_and_apply(candidates, args.min_gain)
        after = json.loads(MANIFEST.read_text())
        changed = changed_keys(backup, after)

        repair()
        residual()
        now = failing_set()
        regressions = now - baseline
        if regressions:
            bad = (regressions & changed) or set(candidates)
            print(f"  regression: {sorted(regressions)} -> excluding {sorted(bad)}", flush=True)
            revert_glyphs(bad, backup)
            excluded |= bad
            repair()
            residual()
            now = failing_set()

        applied |= changed - excluded
        baseline = now
        print(
            f"  residual failures now: {len(now)} glyphs; applied total: {len(applied)}", flush=True
        )
        forge_audit()

    print("\n== converge complete ==", flush=True)
    print(f"applied: {len(applied)} glyphs | excluded (would regress): {len(excluded)}")
    print(f"final residual failures: {len(failing_set())} glyphs")
    print(f"final gate candidates: {len(gate_candidates() - excluded)}")
    if excluded:
        print("excluded glyphs (need manual handling):")
        for fam, name in sorted(excluded):
            print(f"  - {fam}/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
