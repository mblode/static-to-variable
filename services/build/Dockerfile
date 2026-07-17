# Container fallback for the static-to-variable build engine.
#
# This is the fallback path; the primary runtime is a Vercel Sandbox that runs
# services/build/setup.sh directly. Build and run this ONLY for linux/amd64:
# skia-pathops ships manylinux (glibc) x86_64 wheels — there is no musl wheel
# (so no Alpine) and the arm64 story is unreliable — hence debian-slim, not
# alpine, and amd64, not arm64:
#
#     docker build --platform linux/amd64 -f services/build/Dockerfile -t stv-build .
#
FROM --platform=linux/amd64 python:3.11-slim-bookworm

# uv provides the venv + resolver; copy the static binary from its published image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create the engine venv up front so it lands in its own layer.
RUN uv venv --python 3.11 /app/.venv

# Install the engine BEFORE copying the service code so the native-wheel layer
# (skia-pathops, numpy, scipy, Pillow, Brotli, zopfli) is cached and does not
# reinstall when only runner.py / config_gen.py change.
COPY packages/variable-gen /app/packages/variable-gen
RUN uv pip install --python /app/.venv /app/packages/variable-gen

# App code changes most often; keep it in the last layer.
COPY services/build /app/services/build

# STV_FONTMAKE is load-bearing: build.py::_fontmake reads it, and job dirs have no
# local .venv to fall back to. PATH exposes the venv tools for ad-hoc use.
ENV STV_FONTMAKE=/app/.venv/bin/fontmake \
    PATH=/app/.venv/bin:$PATH

# Jobs run against a mounted/ephemeral job dir under /work.
WORKDIR /work
