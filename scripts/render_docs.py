#!/usr/bin/env python3
"""Render README assets: reader screenshots of a built book and the repository social preview.

    scripts/render_docs.py --out docs                       # newest collector's edition in output/
    scripts/render_docs.py --epub output/tyk-collectors-20260907.epub

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
  .text {{ position:absolute; left:72px; top:88px; width:452px; z-index:3; }}
  .name {{ font-family:"Bebas Neue","Barlow Condensed",sans-serif; font-size:118px; line-height:.9; letter-spacing:2px; }}
  .name em {{ font-style:normal; color:#2EC4B6; }}
  .tag {{ font-size:27px; line-height:1.3; margin-top:22px; color:#dfe7f0; }}
  .tag b {{ color:#FFB703; font-weight:600; }}
  .chips {{ margin-top:34px; display:flex; gap:12px; flex-wrap:wrap; }}
  .chip {{ font-family:"Barlow Condensed",sans-serif; font-weight:700; font-size:20px; letter-spacing:2px; text-transform:uppercase; padding:8px 16px; border:2px solid #2EC4B6; border-radius:6px; color:#2EC4B6; }}
  /* Fanned, not laid side by side: three covers abreast would run under the text. */
  .covers {{ position:absolute; right:44px; top:128px; display:flex; }}
  .covers img {{ height:366px; border-radius:6px; box-shadow:0 26px 56px rgba(0,0,0,.65); }}
  .covers img.b {{ transform:rotate(-7deg) translateY(18px); }}
  .covers img.c {{ margin-left:-112px; transform:rotate(0deg) translateY(-8px); z-index:2; }}
  .covers img.a {{ margin-left:-112px; transform:rotate(7deg) translateY(18px); }}
</style></head><body>
<div class="grid"></div><div class="glow"></div>
<div class="text">
  <div class="name">blog<em>2</em>epub</div>
  <div class="tag">Point it at the blogs you read. Get <b>navigable EPUB books</b> and monthly digests for your e-reader, kept current by a weekly sync and a monthly release.</div>
  <div class="chips"><span class="chip">WordPress · RSS · Sitemap</span><span class="chip">Readability</span><span class="chip">Volumes under 200 MB</span><span class="chip">EPUB 3 · epubcheck clean</span></div>
</div>
<div class="covers"><img class="b" src="{cover_a}"><img class="c" src="{cover_b}"><img class="a" src="{cover_c}"></div>
</body></html>"""


def _die(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


def _newest_book(out: Path) -> Path:
    """The newest EPUB in `out`, preferring a collector's edition.

    Naming it outright stopped working when books were cut into volumes and every file gained an
    issue date. A collector's edition is the better subject anyway: its contents page spans every
    year, which is what the screenshot is there to show.
    """
    books = sorted(out.glob("*.epub"), key=lambda p: p.stat().st_mtime, reverse=True)
    collectors = [b for b in books if "-collectors-" in b.name]
    return (collectors or books or [out / "nothing-built.epub"])[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--epub", type=Path, default=None, help="default: newest book in output/")
    ap.add_argument("--out", type=Path, default=ROOT / "docs")
    args = ap.parse_args()
    if args.epub is None:
        args.epub = _newest_book(args.out.parent / "output" if args.out.name == "docs" else ROOT / "output")
        print("using", args.epub)
    if not args.epub.exists():
        return _die(f"{args.epub} does not exist; build a book first, or pass --epub")

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
                # three of the eight, chosen to show the range of palettes rather than the newest
                cover_a=(ROOT / "covers/mulesoft.jpg").resolve().as_uri(),
                cover_b=(ROOT / "covers/tyk.jpg").resolve().as_uri(),
                cover_c=(ROOT / "covers/api-management.jpg").resolve().as_uri(),
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
