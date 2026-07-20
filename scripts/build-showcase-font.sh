#!/usr/bin/env bash
# Thin wrapper around build-showcase-font.py that runs it through the repo's
# uv-managed env (where the variable_gen engine and fontTools live). All args are
# forwarded. See build-showcase-font.py for the full option list.
#
# Example:
#   scripts/build-showcase-font.sh \
#     --id barlow --family Barlow --ofl barlow \
#     --master Thin=100 --master Regular=400 --master Black=900 \
#     --default 400 --out apps/web/public/fonts
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run --project "$repo_root" python "$repo_root/scripts/build-showcase-font.py" "$@"
