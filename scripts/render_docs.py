#!/usr/bin/env python3
"""Render README assets: reader screenshots of a built book and the repository social preview.

    scripts/render_docs.py --epub output/tyk.epub --out docs

Screenshots use a 6-inch e-reader viewport (600x800 CSS px at 2x). The social preview is the
1280x640 image GitHub shows when the repository is shared.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SOCIAL = """<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="{fonts}">
<style>
  body {{ margin:0; width:1280px; height:640px; background:#0B1622; color:#F6F4EF; font-family:"Barlow","Liberation Sans",Arial,sans-serif; position:relative; overflow:hidden; }}
  .grid {{ position:absolute; inset:0; opacity:.14; background-image:linear-gradient(rgba(159,179,200,.5) 1px,transparent 1px),linear-gradient(90deg,rgba(159,179,200,.5) 1px,transparent 1px); background-size:64px 64px; }}
  .glow {{ position:absolute; width:900px; height:900px; border-radius:50%; right:-250px; top:-300px; background:radial-gradient(circle, rgba(132,56,250,.35) 0%, transparent 65%); }}
  .text {{ position:absolute; left:72px; top:92px; width:470px; }}
  .name {{ font-family:"Bebas Neue","Barlow Condensed",sans-serif; font-size:118px; line-height:.9; letter-spacing:2px; }}
  .name em {{ font-style:normal; color:#2EC4B6; }}
  .tag {{ font-size:27px; line-height:1.3; margin-top:22px; color:#dfe7f0; }}
  .tag b {{ color:#FFB703; font-weight:600; }}
  .chips {{ margin-top:34px; display:flex; gap:12px; flex-wrap:wrap; }}
  .chip {{ font-family:"Barlow Condensed",sans-serif; font-weight:700; font-size:20px; letter-spacing:2px; text-transform:uppercase; padding:8px 16px; border:2px solid #2EC4B6; border-radius:6px; color:#2EC4B6; }}
  .covers {{ position:absolute; right:48px; top:112px; display:flex; gap:22px; }}
  .covers img {{ height:400px; border-radius:6px; box-shadow:0 30px 60px rgba(0,0,0,.6); }}
  .covers img.b {{ transform:rotate(-4deg) translateY(10px); }}
  .covers img.a {{ transform:rotate(4deg); }}
</style></head><body>
<div class="grid"></div><div class="glow"></div>
<div class="text">
  <div class="name">blog<em>2</em>epub</div>
  <div class="tag">Point it at the blogs you read. Get <b>navigable EPUB books</b> and monthly digests for your e-reader, kept current by a weekly workflow.</div>
  <div class="chips"><span class="chip">WordPress · RSS · Sitemap</span><span class="chip">Readability</span><span class="chip">EPUB 3 · epubcheck clean</span></div>
</div>
<div class="covers"><img class="b" src="{cover_a}"><img class="a" src="{cover_b}"></div>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--epub", type=Path, default=ROOT / "output" / "tyk.epub")
    ap.add_argument("--out", type=Path, default=ROOT / "docs")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright  # noqa: PLC0415  (optional dependency)

    executable = os.environ.get("CHROMIUM_PATH") or (
        "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None
    )
    shots = args.out / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        book = Path(tmp) / "book"
        zipfile.ZipFile(args.epub).extractall(book)
        oebps = book / "OEBPS"
        texts = sorted(p.name for p in (oebps / "Text").iterdir())
        # newest year and month pages: the most populated, and what a reader sees first
        part = [n for n in texts if n.startswith("part-")][-1]
        sections = [n for n in texts if n.startswith("sec-")]
        # the busiest month page shows the layout best
        section = (
            max(sections, key=lambda n: (oebps / "Text" / n).read_text(encoding="utf-8").count("<li>"))
            if sections
            else part
        )
        # a chapter with an image, so the screenshot shows one
        chapter = next(
            (
                n
                for n in texts
                if n.startswith("ch-") and "<img" in (oebps / "Text" / n).read_text(encoding="utf-8")
            ),
            next(n for n in texts if n.startswith("ch-")),
        )
        pages = {
            "contents.png": oebps / "nav.xhtml",
            "part.png": oebps / "Text" / part,
            "month.png": oebps / "Text" / section,
            "chapter.png": oebps / "Text" / chapter,
        }
        browser = pw.chromium.launch(executable_path=executable, args=["--allow-file-access-from-files"])
        page = browser.new_page(viewport={"width": 600, "height": 800}, device_scale_factor=2)
        for name, path in pages.items():
            page.goto(path.resolve().as_uri())
            page.add_style_tag(
                content="body{padding:28px 32px !important;background:#fff;} nav[hidden]{display:none}"
            )
            page.wait_for_timeout(200)
            page.screenshot(path=str(shots / name), full_page=False)
            print("wrote", shots / name)

        html = Path(tmp) / "social.html"
        html.write_text(
            SOCIAL.format(
                fonts=(ROOT / "covers/fonts/fonts.css").resolve().as_uri(),
                cover_a=(ROOT / "covers/tyk.jpg").resolve().as_uri(),
                cover_b=(ROOT / "covers/api-management.jpg").resolve().as_uri(),
            ),
            encoding="utf-8",
        )
        page = browser.new_page(viewport={"width": 1280, "height": 640}, device_scale_factor=1)
        page.goto(html.resolve().as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(300)
        page.screenshot(path=str(args.out / "social-preview.png"))
        print("wrote", args.out / "social-preview.png")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
