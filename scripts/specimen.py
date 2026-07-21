#!/usr/bin/env python3
"""Serve a specimen sheet for visually spot-checking every showcase variable font.

Reads each ``.ttf`` in ``apps/web/public/fonts`` for its real ``wght`` range and
family name, then serves one page that renders all of them. A single normalized
weight slider drives every font at once (drag once, watch the whole set morph),
so freezes and mid-axis wobble stand out; a sweep toggle instead stacks each
font at fixed steps across its own range for static side-by-side comparison.
The sample text and size are editable and apply to every font.

  uv run scripts/specimen.py            # serve on the first free port from 8770
  uv run scripts/specimen.py --port 9000
  uv run scripts/specimen.py --open     # also open the browser (macOS)

Nothing is written into the repo; the HTML is generated in memory and the font
files are streamed from apps/web/public/fonts.
"""

from __future__ import annotations

# This file embeds an HTML/CSS/JS template as string literals, where long lines
# read better unwrapped than broken across continuations.
# ruff: noqa: E501
import argparse
import html
import http.server
import json
import socketserver
import subprocess
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "apps/web/public/fonts"


def collect_fonts() -> list[dict]:
    fonts = []
    for ttf in sorted(FONTS_DIR.glob("*.ttf")):
        fid = ttf.stem
        woff2 = ttf.with_suffix(".woff2")
        src = f"{fid}.woff2" if woff2.exists() else f"{fid}.ttf"
        try:
            f = TTFont(str(ttf))
            wght = next((a for a in f["fvar"].axes if a.axisTag == "wght"), None)
            name = f["name"].getBestFamilyName() or fid
        except Exception as exc:  # noqa: BLE001
            print(f"skip {fid}: {exc}", file=sys.stderr)
            continue
        if wght is None:
            continue
        fonts.append(
            {
                "id": fid,
                "name": name,
                "src": src,
                "min": int(wght.minValue),
                "def": int(wght.defaultValue),
                "max": int(wght.maxValue),
            }
        )
    return fonts


SAMPLE = (
    "One file, every weight in between. “vwx” AWGKkpq4 & @ ?!\n"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789\n"
    "àáâãäåæçèéêë"
    "ìíîïñòóôõöøü "
    ".,;:!?“”‘’()[]&@#$%½¾⁄"
)


def build_html(fonts: list[dict]) -> str:
    faces = "\n".join(
        f"@font-face{{font-family:'sv-{f['id']}';src:url('/fonts/{f['src']}');"
        f"font-weight:{f['min']} {f['max']};font-display:swap;}}"
        for f in fonts
    )
    data = json.dumps(fonts)
    sample = html.escape(SAMPLE)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Variable font specimen</title>
<style>
{faces}
:root{{color-scheme:dark;}}
*{{box-sizing:border-box;}}
body{{margin:0;background:#0d0d0d;color:#f4f4f4;font-family:ui-sans-serif,system-ui,sans-serif;}}
header{{position:sticky;top:0;z-index:5;background:#141414;border-bottom:1px solid #262626;
  padding:14px 20px;display:flex;flex-wrap:wrap;gap:18px 26px;align-items:center;}}
header label{{font-size:12px;color:#9a9a9a;display:flex;flex-direction:column;gap:6px;}}
header .row{{display:flex;align-items:center;gap:10px;}}
input[type=range]{{width:260px;accent-color:#f4f4f4;}}
#wval,#sval{{font-variant-numeric:tabular-nums;color:#f4f4f4;min-width:44px;}}
textarea{{width:min(560px,60vw);height:52px;background:#1c1c1c;color:#f4f4f4;border:1px solid #333;
  border-radius:8px;padding:8px 10px;font-family:ui-monospace,monospace;font-size:12px;resize:vertical;}}
button,select{{background:#1c1c1c;color:#f4f4f4;border:1px solid #333;border-radius:8px;padding:7px 12px;font-size:12px;cursor:pointer;}}
.font{{padding:18px 20px;border-bottom:1px solid #1c1c1c;}}
.font h2{{margin:0 0 2px;font-size:12px;font-weight:600;color:#c9c9c9;letter-spacing:.02em;
  display:flex;gap:10px;align-items:baseline;}}
.font h2 .meta{{font-weight:400;color:#6f6f6f;font-variant-numeric:tabular-nums;}}
.sample{{line-height:1.28;letter-spacing:0;white-space:pre-wrap;word-break:break-word;}}
.sweep .sample{{margin-top:6px;}}
.sweep .wt{{font-size:10px;color:#5a5a5a;font-variant-numeric:tabular-nums;}}
</style></head>
<body>
<header>
  <label>Weight (normalized)
    <div class="row"><input id="w" type="range" min="0" max="100" value="50"><span id="wval">50%</span></div>
  </label>
  <label>Size
    <div class="row"><input id="s" type="range" min="20" max="140" value="58"><span id="sval">58</span></div>
  </label>
  <label>Sample text
    <textarea id="t">{sample}</textarea>
  </label>
  <label>&nbsp;
    <div class="row">
      <button id="mode">Sweep mode</button>
    </div>
  </label>
</header>
<main id="main"></main>
<script>
const FONTS = {data};
const main = document.getElementById('main');
const w = document.getElementById('w'), s = document.getElementById('s'), t = document.getElementById('t');
const wval = document.getElementById('wval'), sval = document.getElementById('sval'), modeBtn = document.getElementById('mode');
let sweep = false;
const wghtAt = (f, pct) => Math.round(f.min + (f.max - f.min) * pct / 100);
function render() {{
  const pct = +w.value, size = +s.value, text = t.value;
  wval.textContent = pct + '%'; sval.textContent = size;
  document.body.classList.toggle('sweep', sweep);
  main.innerHTML = '';
  for (const f of FONTS) {{
    const el = document.createElement('section');
    el.className = 'font';
    const h = document.createElement('h2');
    if (sweep) {{
      h.innerHTML = `${{f.name}} <span class="meta">${{f.min}}–${{f.max}}</span>`;
      el.appendChild(h);
      const steps = 6;
      for (let i = 0; i < steps; i++) {{
        const wt = Math.round(f.min + (f.max - f.min) * i / (steps - 1));
        const tag = document.createElement('div'); tag.className = 'wt'; tag.textContent = wt;
        const p = document.createElement('div'); p.className = 'sample'; p.textContent = text;
        p.style.fontFamily = `'sv-${{f.id}}'`; p.style.fontSize = size + 'px';
        p.style.fontVariationSettings = `"wght" ${{wt}}`;
        el.appendChild(tag); el.appendChild(p);
      }}
    }} else {{
      const wt = wghtAt(f, pct);
      h.innerHTML = `${{f.name}} <span class="meta">${{f.min}}–${{f.max}} · wght ${{wt}}</span>`;
      const p = document.createElement('div'); p.className = 'sample'; p.textContent = text;
      p.style.fontFamily = `'sv-${{f.id}}'`; p.style.fontSize = size + 'px';
      p.style.fontVariationSettings = `"wght" ${{wt}}`;
      el.appendChild(h); el.appendChild(p);
    }}
    main.appendChild(el);
  }}
}}
w.oninput = s.oninput = t.oninput = render;
modeBtn.onclick = () => {{ sweep = !sweep; modeBtn.textContent = sweep ? 'Slider mode' : 'Sweep mode'; render(); }};
render();
</script>
</body></html>"""


def serve(fonts: list[dict], port: int, do_open: bool) -> None:
    page = build_html(fonts).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(page, "text/html; charset=utf-8")
                return
            if path.startswith("/fonts/"):
                fp = (FONTS_DIR / path[len("/fonts/") :]).resolve()
                if FONTS_DIR in fp.parents and fp.exists() and fp.suffix in (".woff2", ".ttf"):
                    ctype = "font/woff2" if fp.suffix == ".woff2" else "font/ttf"
                    self._send(fp.read_bytes(), ctype)
                    return
            self.send_error(404)

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence per-request logging
            pass

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    while True:
        try:
            httpd = Server(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
            if port > 8800:
                raise
    url = f"http://127.0.0.1:{port}/"
    print(f"specimen: {len(fonts)} fonts at {url}", flush=True)
    if do_open:
        subprocess.run(["open", url], check=False)  # noqa: S603, S607 (macOS)
    httpd.serve_forever()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--open", action="store_true", help="open the browser (macOS)")
    args = ap.parse_args(argv)
    fonts = collect_fonts()
    if not fonts:
        print(f"no fonts found in {FONTS_DIR}", file=sys.stderr)
        return 1
    serve(fonts, args.port, args.open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
