"""Single Sandbox entrypoint: raw uploads -> config + donors -> runner NDJSON.

Usage: python build_job.py <job_dir>

``<job_dir>/uploads/`` holds the raw fonts the browser dropped. This script:

  1. lists the uploads and calls ``config_gen.generate_config``;
  2. on ``ConfigGenError`` prints ``{"type":"error","code","message"}`` and exits 1;
  3. otherwise writes ``<job_dir>/stv.config.json`` and copies each donor to
     ``<job_dir>/donors/<id>.ttf``;
  4. emits ``{"type":"detected","fonts":[{id,name,weight}...],"axis":{...}}``;
  5. runs ``runner.py <job_dir>`` as a subprocess (via ``sys.executable``) and
     forwards its stdout NDJSON line-by-line to this script's own stdout.

stdout stays pure NDJSON so the API can tail it and re-emit each line as SSE.
Reuses config_gen + runner; never reimplements the engine.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from config_gen import ConfigGenError, generate_config

# Progress events go to the real stdout as pure NDJSON; runner's own chatter is
# already redirected to build.log, and its subprocess stderr is captured below.
_STDOUT = sys.stdout


def _emit(event: dict) -> None:
    _STDOUT.write(json.dumps(event) + "\n")
    _STDOUT.flush()


def main() -> int:
    job_dir = Path(sys.argv[1]).resolve()
    uploads = job_dir / "uploads"
    font_paths = sorted(p for p in uploads.iterdir() if p.is_file() and not p.name.startswith("."))

    # Optional per-upload weight overrides from the editable weight table, keyed
    # by the upload's filename (path.name). Absent means use the detected weights.
    overrides_file = job_dir / "overrides.json"
    overrides = json.loads(overrides_file.read_text()) if overrides_file.exists() else None

    try:
        config, id_to_path = generate_config(font_paths, overrides)
    except ConfigGenError as exc:
        _emit({"type": "error", "code": exc.code, "message": str(exc)})
        return 1

    donors_dir = job_dir / "donors"
    donors_dir.mkdir(parents=True, exist_ok=True)
    for donor_id, src in id_to_path.items():
        shutil.copyfile(src, donors_dir / f"{donor_id}.ttf")

    (job_dir / "stv.config.json").write_text(json.dumps(config, indent=2))

    # Detected summary for the UI: the per-donor weights plus the wght axis span.
    style = next(iter(config["styles"].values()))
    axis = config["axes"][0]
    _emit(
        {
            "type": "detected",
            "fonts": [
                {"id": d["id"], "name": d["name"], "weight": d["location"]["wght"]}
                for d in style["donors"]
            ],
            "axis": {
                "tag": axis["tag"],
                "min": axis["minimum"],
                "def": axis["default"],
                "max": axis["maximum"],
            },
        }
    )

    # Run the pipeline in a separate process the API can hard-kill; forward its
    # NDJSON stdout verbatim, and keep its stderr out of our event stream.
    runner = Path(__file__).resolve().parent / "runner.py"
    err_log = (job_dir / "build_job.stderr.log").open("w")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(runner), str(job_dir)],
            stdout=subprocess.PIPE,
            stderr=err_log,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _STDOUT.write(line)
            _STDOUT.flush()
        return proc.wait()
    finally:
        err_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
