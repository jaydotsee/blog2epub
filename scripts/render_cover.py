#!/usr/bin/env python3
"""Render a magazine-style cover for a blog from an HTML template.

    scripts/render_cover.py --blog tyk --template covers/tyk.html --out covers/tyk.jpg

The template is a string.Template with placeholders filled from the blog's cache:
$count, $first_year, $last_year, $issue (e.g. "September 2026"), $issue_number (e.g.
"2026.09.05", the date the cover was rendered), $url, and three
cover lines ($kicker1/$title1 ... $kicker3/$title3) taken from the newest posts.
Rendering uses the Chromium bundled with Playwright; fonts come from Google Fonts
when the network allows and fall back to system fonts otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from blog2epub.config import load_config  # noqa: E402
from blog2epub.models import parse_date  # noqa: E402
from blog2epub.store import BlogStore  # noqa: E402

KICKERS = [
    (r"\b(mcp|agent|ai|llm)\b", "AI & MCP"),
    (r"\bopen[ -]?source\b", "OPEN SOURCE"),
    (r"\b(bank|financ|fintech|open finance|payments?)\b", "FINANCIAL SERVICES"),
    (r"\b(kubernetes|k8s|cloud|deploy|scal)", "PLATFORM"),
    (r"\b(secur|auth|oauth|jwt|token|revoke)", "SECURITY"),
    (r"\b(graphql|rest|grpc|openapi|schema)\b", "API DESIGN"),
]


def kicker_for(title: str, categories: list[str]) -> str:
    for cat in categories:
        if cat and cat.lower() != "uncategorized":
            return cat.upper()
    for pattern, label in KICKERS:
        if re.search(pattern, title, re.I):
            return label
    return "OPINION"


def cover_lines(store: BlogStore, n: int = 3) -> list[tuple[str, str]]:
    posts = sorted(
        store.iter_posts(),
        key=lambda p: p.date_obj or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    lines: list[tuple[str, str]] = []
    used: set[str] = set()
    for p in posts:
        k = kicker_for(p.title, p.categories)
        if k in used or len(p.title) > 70:
            continue
        used.add(k)
        lines.append((k, p.title))
        if len(lines) == n:
            break
    while len(lines) < n:
        lines.append(("FEATURE", posts[len(lines)].title if len(posts) > len(lines) else ""))
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blog", required=True, help="blog id from blogs.yaml")
    ap.add_argument("--template", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path, help=".jpg or .png")
    ap.add_argument("-c", "--config", default=str(ROOT / "blogs.yaml"))
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=2133)
    ap.add_argument("--quality", type=int, default=90)
    args = ap.parse_args()

    settings = load_config(args.config)
    blog = settings.blog(args.blog)
    store = BlogStore(settings.cache_dir, blog.id)
    dates = sorted(d for d in (parse_date(v.get("date")) for v in store.post_index.values()) if d)
    now = datetime.now(timezone.utc)
    lines = cover_lines(store)
    values = {
        "count": str(len(store.post_index)),
        "first_year": str(dates[0].year) if dates else "",
        "last_year": str(dates[-1].year) if dates else "",
        "issue": f"{now:%B %Y}",
        "issue_number": f"{now:%Y.%m.%d}",
        "url": blog.url.removeprefix("https://").removeprefix("http://"),
        "title": blog.title,
    }
    for i, (kicker, title) in enumerate(lines, start=1):
        values[f"kicker{i}"] = kicker
        values[f"title{i}"] = title
    html = Template(args.template.read_text(encoding="utf-8")).safe_substitute(values)
    html = html.replace("$count", values["count"])  # in case of nested use
    # Render from a temporary file next to the template so relative assets (fonts/, images) resolve.
    rendered = args.template.with_name(f".{args.template.stem}.render.html")
    rendered.write_text(html, encoding="utf-8")

    from playwright.sync_api import sync_playwright  # noqa: PLC0415  (optional dependency)

    # Use an existing Chromium when one is provided (CI images, `playwright install` otherwise).
    executable = os.environ.get("CHROMIUM_PATH") or (
        "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable, args=["--allow-file-access-from-files"])
        page = browser.new_page(viewport={"width": args.width, "height": args.height}, device_scale_factor=1)
        page.goto(rendered.resolve().as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(300)
        fonts = page.evaluate(
            "Array.from(document.fonts).map(f => f.family + ':' + f.weight + ':' + f.status)"
        )
        missing = [f for f in fonts if not f.endswith(":loaded")]
        if missing:
            print(f"warning: fonts not loaded: {missing}", file=sys.stderr)
        kind = "jpeg" if args.out.suffix.lower() in (".jpg", ".jpeg") else "png"
        shot = {"path": str(args.out), "type": kind, "full_page": False}
        if kind == "jpeg":
            shot["quality"] = args.quality
        page.screenshot(**shot)
        browser.close()
    rendered.unlink(missing_ok=True)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB) with cover lines: {json.dumps(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
