from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .common import PipelineError
from .config import ConfigError, load_config, resolve_style_keys
from .pipeline import (
    build_pipeline_status,
    write_pipeline_markdown,
    write_pipeline_status,
)

# Config-driven pipeline commands: rebuild -> normalize -> designspace -> build
# -> release. Each takes --config (a v3 stv.config.json) and --style.
_PIPELINE_COMMANDS = {
    "bootstrap": "Synthesize a minimal .glyphs source from each style's default donor.",
    "rebuild": "Rebuild each style's masters from its donors (config-driven).",
    "normalize": "Normalize donor-inherited glyph height defects.",
    "designspace": "Export UFOs + a corrected .designspace from each source.",
    "build": "Build the variable font(s) with fontmake + fidelity check.",
    "release": "Finalize metadata and emit release TTF + WOFF2.",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="variable-gen",
        description="Config-driven static-to-variable font pipeline utilities.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pipeline_parser = subparsers.add_parser(
        "pipeline-status",
        help="Summarize static-to-variable pipeline artifacts and promotion gates.",
    )
    pipeline_parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[4]),
    )
    pipeline_parser.add_argument("--output")
    pipeline_parser.add_argument("--markdown")

    split_parser = subparsers.add_parser(
        "split",
        help="Split a variable font into static weight files (the reverse of build).",
    )
    split_parser.add_argument("--input", required=True, help="path to a variable .ttf/.otf")
    split_parser.add_argument("--output", default="static", help="output directory")
    split_parser.add_argument(
        "--step", type=int, default=100, help="weight step along the wght axis"
    )
    split_parser.add_argument("--json", action="store_true", help="emit a JSON summary")

    for name, help_text in _PIPELINE_COMMANDS.items():
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--config", required=True, help="path to stv.config.json")
        sub.add_argument("--style", default="all", help="style key, or 'all'")
        if name == "build":
            sub.add_argument("--check-only", action="store_true")
        if name == "bootstrap":
            sub.add_argument("--force", action="store_true", help="overwrite an existing source")

    args = parser.parse_args(argv)

    try:
        if args.command == "pipeline-status":
            return _pipeline_status(args)
        if args.command == "split":
            return _split(args)
        if args.command in _PIPELINE_COMMANDS:
            return _pipeline_command(args)
    except (ConfigError, ValueError) as exc:
        parser.exit(2, f"variable-gen: {exc}\n")
    except PipelineError as exc:
        print(f"variable-gen: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command {args.command!r}")
    return 2


def run_command(command: str, argv: list[str] | None = None) -> int:
    """Run one subcommand with its own argv. Module mains delegate here so
    ``python -m variable_gen.<command>`` and ``variable-gen <command>`` share a
    single implementation."""
    args = sys.argv[1:] if argv is None else argv
    return main([command, *args])


def _merge_style_report(
    path: Path, updates: dict[str, Any], style_order: list[str]
) -> dict[str, Any]:
    """Merge per-style report entries into whatever ``path`` already holds,
    ordering configured styles first. An unreadable existing file is replaced."""
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text())
            if isinstance(payload, dict):
                existing = payload
        except json.JSONDecodeError:
            existing = {}
    merged = {**existing, **updates}
    ordered = {key: merged[key] for key in style_order if key in merged}
    ordered.update({key: value for key, value in merged.items() if key not in ordered})
    return ordered


def _pipeline_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    keys = resolve_style_keys(config, args.style)

    if args.command == "bootstrap":
        from .bootstrap import bootstrap_style

        for key in keys:
            boot = bootstrap_style(config, key, force=args.force)
            if boot.skipped:
                print(
                    f"[{key}] source exists at {boot.source} — skipped (use --force to overwrite)"
                )
            else:
                print(
                    f"[{key}] bootstrapped {boot.glyphs} glyphs "
                    f"({boot.unmapped} unmapped) -> {boot.source}"
                )
        return 0

    if args.command == "rebuild":
        from .rebuild import rebuild_style

        report = {}
        for key in keys:
            stats = rebuild_style(config, key)
            report[key] = asdict(stats)
            plan = config.styles[key].masters
            print(
                f"[{key}] {len(plan)} masters | donor={stats.donor} "
                f"reconstructed={stats.reconstructed} "
                f"frozen-incompatible={len(stats.frozen_incompatible)} "
                f"sampled(non-donor)={stats.sampled} frozen={stats.frozen}"
            )
            if stats.frozen_incompatible:
                print(
                    "   frozen-incompatible (topology change -> freeze): "
                    f"{stats.frozen_incompatible}"
                )
        out = config.repo_root / "packages/variable-gen/reports/reconstruction-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        # Merge single-style runs into the existing report so `--style roman`
        # cannot erase the italic entry (the promotion gate reads every style).
        merged = _merge_style_report(out, report, list(config.styles))
        out.write_text(json.dumps(merged, indent=2))
        print(f"reconstruction report -> {out}")
        return 0

    if args.command == "normalize":
        from .normalize import normalize_style

        for key in keys:
            norm = normalize_style(config, key)
            if norm.skipped:
                print(f"[{key}] height normalization disabled (normalize.heights=false)")
            else:
                print(
                    f"[{key}] vertical-normalized {norm.vertical_normalized} glyphs "
                    f"(aligned to the default master's box)"
                )
        return 0

    if args.command == "designspace":
        from .designspace import export_designspace

        for key in keys:
            ds_path = export_designspace(config, key)
            print(f"[{key}] -> {ds_path}")
        return 0

    if args.command == "build":
        from .build import UNDERWEIGHT_RATIO, build_style, check_fidelity

        for key in keys:
            if not args.check_only:
                build_style(config, key)
            fails = check_fidelity(config, key)
            worst = sorted(fails, key=lambda f: f[2])[:12]
            print(
                f"[{key}] underweight (<{UNDERWEIGHT_RATIO}x mapped donor) at any named "
                f"weight: {len(fails)} glyph-weights"
            )
            if worst:
                print("   worst:", worst)
        return 0

    if args.command == "release":
        from .release import _release_dir, release_style

        for key in keys:
            out = release_style(config, key)
            print(f"[{key}] -> {out.name} + .woff2")
        print(f"release staged in {_release_dir(config)}")
        return 0

    raise ConfigError(f"unhandled pipeline command {args.command!r}")


def _pipeline_status(args: argparse.Namespace) -> int:
    report = build_pipeline_status(Path(args.repo_root))

    if args.output:
        output_path = write_pipeline_status(report, Path(args.output))
        print(
            "Wrote pipeline status: "
            f"{output_path} "
            f"(verdict={report['verdict']}, "
            f"blocking_failures={report['summary']['blocking_failure_count']})"
        )
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    if args.markdown:
        markdown_path = write_pipeline_markdown(report, Path(args.markdown))
        print(f"Wrote pipeline markdown: {markdown_path}")

    return 0


def _split(args: argparse.Namespace) -> int:
    from .split import split_variable_font

    output_dir = Path(args.output)
    results = split_variable_font(Path(args.input), output_dir, step=args.step)

    if args.json:
        print(
            json.dumps(
                {
                    "input": str(args.input),
                    "output": str(output_dir),
                    "count": len(results),
                    "weights": results,
                },
                indent=2,
            )
        )
    else:
        for entry in results:
            names = ", ".join(Path(f).name for f in entry["files"])
            print(f"[wght {entry['weight']}] {entry['name']} -> {names}")
        print(f"Wrote {len(results)} static weights to {output_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
