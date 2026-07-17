"""Run the from-scratch pipeline for one job directory, emitting NDJSON progress.

Usage: python runner.py <job_dir>

The job dir must already contain ``stv.config.json`` and ``donors/<id>.ttf`` (as
written by config_gen). Each line of stdout is one JSON event the API tails and
re-emits to the browser as SSE:

  {"type":"stage","id":"rebuild","status":"running"}
  {"type":"stage","id":"rebuild","status":"succeeded"}
  {"type":"result","files":[{"name","format","bytes","path"}], "frozen":[...]}
  {"type":"error","code":"build_failed","message":"..."}

Imports the engine directly (never reimplements it); native crashes / non-convergence
are isolated because the API runs this as a separate subprocess it can hard-kill.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

from variable_gen.bootstrap import bootstrap_style
from variable_gen.build import build_style, check_fidelity
from variable_gen.config import load_config
from variable_gen.normalize import normalize_style
from variable_gen.rebuild import rebuild_style
from variable_gen.release import _release_dir, release_style

STAGES = [
    ("bootstrap", "Bootstrap source"),
    ("rebuild", "Rebuild masters"),
    ("normalize", "Normalize metrics"),
    ("build", "Build & check"),
    ("release", "Package TTF + WOFF2"),
]


# Progress events go to the real stdout as pure NDJSON; the pipeline's own chatty
# prints are redirected to build.log so they never corrupt the event stream.
_STDOUT = sys.stdout


def _emit(event: dict) -> None:
    _STDOUT.write(json.dumps(event) + "\n")
    _STDOUT.flush()


def main() -> int:
    job_dir = Path(sys.argv[1]).resolve()
    config = load_config(job_dir / "stv.config.json")
    key = next(iter(config.styles))

    _emit({"type": "stages", "stages": [{"id": sid, "title": t} for sid, t in STAGES]})

    frozen: list[str] = []
    current = STAGES[0][0]
    log = (job_dir / "build.log").open("w")
    try:
        with contextlib.redirect_stdout(log):
            for sid, _title in STAGES:
                current = sid
                _emit({"type": "stage", "id": sid, "status": "running"})
                if sid == "bootstrap":
                    bootstrap_style(config, key)
                elif sid == "rebuild":
                    rebuild_style(config, key)
                elif sid == "normalize":
                    normalize_style(config, key)
                elif sid == "build":
                    frozen = build_style(config, key)
                    check_fidelity(config, key)
                elif sid == "release":
                    release_style(config, key)
                _emit({"type": "stage", "id": sid, "status": "succeeded"})
    except SystemExit as exc:
        # build_style raises SystemExit on a failed/non-converging fontmake run.
        _emit({"type": "stage", "id": current, "status": "failed"})
        _emit({"type": "error", "code": "build_failed", "message": str(exc) or "build failed"})
        return 1
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "stage", "id": current, "status": "failed"})
        _emit({"type": "error", "code": "build_failed", "message": str(exc)})
        return 1
    finally:
        log.close()

    release_dir = _release_dir(config)
    files = [
        {"name": f.name, "format": f.suffix.lstrip("."), "bytes": f.stat().st_size, "path": str(f)}
        for f in sorted(release_dir.glob("*"))
        if f.suffix in (".ttf", ".woff2")
    ]
    _emit({"type": "result", "files": files, "frozen": frozen})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
