#!/usr/bin/env bash
#
# Provision the static-to-variable build engine into a uv venv.
#
# Run from the repo root (the Vercel Sandbox and the container fallback both do):
#
#     ./services/build/setup.sh [venv_dir]
#
# The venv dir is taken from $1, then $STV_VENV, then defaults to /tmp/stv-venv.
# Idempotent: re-running reuses an existing venv and reinstalls the engine, so a
# warm Sandbox or rebuilt layer skips the native-wheel download.
#
# On success it prints the resolved fontmake path and the exact line to export.
# STV_FONTMAKE is load-bearing: build.py::_fontmake honours it, and job dirs have
# no local .venv to fall back to, so the caller MUST export it before running the
# pipeline:
#
#     export STV_FONTMAKE=<venv>/bin/fontmake
#
set -euo pipefail

# Resolve the repo root from this script's location so it works regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

VENV_DIR="${1:-${STV_VENV:-/tmp/stv-venv}}"

# The Vercel Sandbox's raw python3.13 runtime ships pip but not uv, so bootstrap
# uv from pip when it's missing (the container image already has it on PATH).
if ! command -v uv >/dev/null 2>&1; then
  echo "stv: installing uv" >&2
  python3 -m pip install --quiet --disable-pip-version-check --user uv \
    || python3 -m pip install --quiet uv
  # pip may drop the console script in --user or the interpreter's scripts dir.
  export PATH="${HOME}/.local/bin:$(python3 -c 'import sysconfig; print(sysconfig.get_path("scripts"))' 2>/dev/null):${PATH}"
fi
command -v uv >/dev/null 2>&1 || {
  echo "stv: ERROR — uv not on PATH after install" >&2
  exit 1
}

echo "stv: provisioning engine into ${VENV_DIR}" >&2

# --allow-existing reuses a venv already present (warm Sandbox / cached layer)
# instead of erroring, and unlike --clear it keeps the installed native wheels.
# No --python pin: use the ambient interpreter (3.13 in the Sandbox, 3.11 in the
# container) — both satisfy the engine's requires-python >=3.11.
uv venv --allow-existing "${VENV_DIR}"

# Install the engine (fonttools, glyphsLib, fontmake, ufoLib2, Pillow, Brotli,
# zopfli, skia-pathops, numpy, scipy) from the workspace member.
uv pip install --python "${VENV_DIR}" "${REPO_ROOT}/packages/variable-gen"

FONTMAKE="${VENV_DIR}/bin/fontmake"
if [ ! -x "${FONTMAKE}" ]; then
  echo "stv: ERROR — fontmake not found at ${FONTMAKE} after install" >&2
  exit 1
fi

echo "stv: engine ready" >&2
echo "stv: fontmake -> ${FONTMAKE}" >&2
echo "stv: export the following before running the pipeline:" >&2
# The one line callers grep for / eval — printed to stdout, not stderr.
echo "export STV_FONTMAKE=${FONTMAKE}"
