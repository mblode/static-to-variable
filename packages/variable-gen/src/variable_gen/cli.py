from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analyze import (
    build_compatibility_report,
    write_compatibility_markdown,
    write_compatibility_report,
)
from .config import ConfigError, load_config
from .discover import build_inventory_report, write_inventory_report
from .manifest import ManifestError, load_manifest
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

    inventory_parser = subparsers.add_parser(
        "inventory",
        help="Inspect static donor fonts from a manifest without mutating sources.",
    )
    inventory_parser.add_argument("--manifest", required=True)
    inventory_parser.add_argument("--family", default="all")
    inventory_parser.add_argument("--output")

    compatibility_parser = subparsers.add_parser(
        "compatibility",
        help="Run raw donor interpolatability analysis from a manifest.",
    )
    compatibility_parser.add_argument("--manifest", required=True)
    compatibility_parser.add_argument("--family", default="all")
    compatibility_parser.add_argument("--stage", default="raw")
    compatibility_parser.add_argument("--output")
    compatibility_parser.add_argument("--markdown")

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

    for name, help_text in _PIPELINE_COMMANDS.items():
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--config", required=True, help="path to stv.config.json")
        sub.add_argument("--style", default="all", help="style key, or 'all'")
        if name == "build":
            sub.add_argument("--check-only", action="store_true")

    args = parser.parse_args(argv)

    try:
        if args.command == "inventory":
            return _inventory(args)
        if args.command == "compatibility":
            return _compatibility(args)
        if args.command == "pipeline-status":
            return _pipeline_status(args)
        if args.command in _PIPELINE_COMMANDS:
            return _pipeline_command(args)
    except (ManifestError, ConfigError, ValueError) as exc:
        parser.exit(2, f"variable-gen: {exc}\n")

    parser.error(f"unknown command {args.command!r}")
    return 2


def _resolve_style_keys(config, style: str) -> list[str]:
    if style != "all" and style not in config.styles:
        raise ConfigError(f"unknown style {style!r}; have {sorted(config.styles)}")
    return list(config.styles) if style == "all" else [style]


def _pipeline_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    keys = _resolve_style_keys(config, args.style)

    if args.command == "bootstrap":
        from .bootstrap import bootstrap_style

        for key in keys:
            stats = bootstrap_style(config, key)
            if stats["skipped"]:
                print(f"[{key}] source exists at {stats['source']} — skipped")
            else:
                print(
                    f"[{key}] bootstrapped {stats['glyphs']} glyphs "
                    f"({stats['unmapped']} unmapped) -> {stats['source']}"
                )
        return 0

    if args.command == "rebuild":
        from .rebuild import rebuild_style

        report = {}
        for key in keys:
            stats = rebuild_style(config, key)
            report[key] = stats
            plan = config.styles[key].masters
            print(
                f"[{key}] {len(plan)} masters | donor={stats['donor']} "
                f"reconstructed={stats['reconstructed']} "
                f"ai-pending={len(stats['ai_pending'])} "
                f"sampled(non-donor)={stats['sampled']} frozen={stats['frozen']}"
            )
            if stats["ai_pending"]:
                print(f"   ai-pending (topology change -> freeze): {stats['ai_pending']}")
        out = config.repo_root / "packages/variable-gen/reports/reconstruction-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        print(f"reconstruction report -> {out}")
        return 0

    if args.command == "normalize":
        from .normalize import normalize_style

        for key in keys:
            r = normalize_style(config, key)
            if r.get("skipped"):
                print(f"[{key}] height normalization disabled (normalize.heights=false)")
            else:
                print(
                    f"[{key}] vertical-normalized {r['vertical_normalized']} glyphs "
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
        from .build import build_style, check_fidelity

        for key in keys:
            if not args.check_only:
                build_style(config, key)
            fails = check_fidelity(config, key)
            worst = sorted(fails, key=lambda f: f[2])[:12]
            print(
                f"[{key}] underweight (<0.92x mapped donor) at any named "
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


def _inventory(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest))
    report = build_inventory_report(manifest, family_filter=args.family)

    if args.output:
        output_path = write_inventory_report(report, Path(args.output))
        print(
            "Wrote donor inventory: "
            f"{output_path} "
            f"({report['summary']['family_count']} families, "
            f"{report['summary']['donor_count']} donors, "
            f"{report['summary']['warning_count']} warnings)"
        )
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    return 0


def _compatibility(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest))
    report = build_compatibility_report(
        manifest,
        family_filter=args.family,
        stage=args.stage,
    )

    if args.output:
        output_path = write_compatibility_report(report, Path(args.output))
        print(
            "Wrote compatibility report: "
            f"{output_path} "
            f"({report['summary']['family_count']} families, "
            f"{report['summary']['problem_glyph_count']} problem glyphs, "
            f"{report['summary']['issue_count']} issues, "
            f"gate={report['hard_gates']['status']})"
        )
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    if args.markdown:
        markdown_path = write_compatibility_markdown(report, Path(args.markdown))
        print(f"Wrote compatibility markdown: {markdown_path}")

    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
