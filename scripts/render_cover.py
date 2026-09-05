#!/usr/bin/env python3
"""Render a magazine-style cover for a blog or a book from an HTML template.

    scripts/render_cover.py --blog tyk --template covers/tyk.html --out covers/tyk.jpg
    scripts/render_cover.py --book api-management --template covers/api-management.html --out covers/api-management.jpg

The template is a string.Template with placeholders filled from the cache:
$count (posts in the book's window), $first_year, $last_year, $issue (e.g. "September 2026"),
$issue_number (e.g. "2026.09.05", the date the cover was rendered), $month, $year, $url, $title, $blog_count,
$blog_list (blog titles joined with " · ") and cover lines ($kicker1/$title1 ... up to
$kicker6/$title6) taken from the newest posts. For a book the kicker is the blog's title.
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

from blog2epub.config import BookConfig, load_config  # noqa: E402
from blog2epub.epub import select_entries  # noqa: E402
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


def cover_lines(entries: list, n: int, by_blog: bool) -> list[tuple[str, str]]:
    """Newest posts as (kicker, title) pairs; one per kicker so the lines stay varied."""
    lines: list[tuple[str, str]] = []
    used: set[str] = set()
    for e in entries:
        p = e.post
        k = e.blog.title.upper() if by_blog else kicker_for(p.title, p.categories)
        if k in used or len(p.title) > 80:
            continue
        used.add(k)
        lines.append((k, p.title))
        if len(lines) == n:
            break
    for e in entries:  # top up with whatever is left
        if len(lines) == n:
            break
        if (e.post.title not in {t for _, t in lines}) and len(e.post.title) <= 80:
            lines.append((e.blog.title.upper() if by_blog else "FEATURE", e.post.title))
    while len(lines) < n:
        lines.append(("", ""))
    return lines


def render_all(settings, args) -> int:
    """Render every covers/<id>.html whose id names a configured blog or book."""
    known = {b.id for b in settings.all_books()} | {b.id for b in settings.blogs}
    templates = sorted(p for p in (ROOT / "covers").glob("*.html") if p.stem in known)
    if not templates:
        print("no cover templates match a configured blog or book", file=sys.stderr)
        return 1
    rc = 0
    for template in templates:
        argv = [
            "--book" if any(b.id == template.stem for b in settings.all_books()) else "--blog",
            template.stem,
            "--template",
            str(template),
            "--out",
            str(template.with_suffix(".jpg")),
            "-c",
            args.config,
            "--width",
            str(args.width),
            "--height",
            str(args.height),
            "--quality",
            str(args.quality),
            "--lines",
            str(args.lines),
        ]
        rc |= main(argv)
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--blog", help="blog id from blogs.yaml (its standalone book)")
    target.add_argument("--book", help="book id from blogs.yaml")
    target.add_argument(
        "--all",
        action="store_true",
        help="render every covers/<id>.html whose id is a configured blog or book",
    )
    ap.add_argument("--template", type=Path, help="cover template (required unless --all)")
    ap.add_argument("--out", type=Path, help=".jpg or .png (required unless --all)")
    ap.add_argument("-c", "--config", default=str(ROOT / "blogs.yaml"))
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=2133)
    ap.add_argument("--quality", type=int, default=90)
    ap.add_argument("--lines", type=int, default=6, help="how many cover lines to fill")
    args = ap.parse_args(argv)

    settings = load_config(args.config)
    if args.all:
        return render_all(settings, args)
    if not args.template or not args.out:
        ap.error("--template and --out are required unless --all is given")
    book: BookConfig = settings.blog(args.blog).as_book() if args.blog else settings.book(args.book)
    sources = {bid: (settings.blog(bid), BlogStore(settings.cache_dir, bid)) for bid in book.blogs}
    entries = select_entries(book, sources)
    entries.sort(key=lambda e: e.post.date_obj or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    dates = sorted(e.post.date_obj for e in entries if e.post.date_obj)
    now = datetime.now(timezone.utc)
    blogs = [settings.blog(bid) for bid in book.blogs]
    lines = cover_lines(entries, args.lines, by_blog=len(book.blogs) > 1)
    values = {
        "count": str(len(entries)),
        "first_year": str(dates[0].year) if dates else "",
        "last_year": str(dates[-1].year) if dates else "",
        "issue": f"{now:%B %Y}",
        "issue_number": f"{now:%Y.%m.%d}",
        "month": f"{now:%B}",
        "year": f"{now:%Y}",
        "url": blogs[0].url.removeprefix("https://").removeprefix("http://") if len(blogs) == 1 else "",
        "title": book.title,
        "blog_count": str(len(blogs)),
        "blog_list": " \u00b7 ".join(b.title for b in blogs),
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
        # "unloaded" just means no element used that weight; only "error" is a real failure.
        missing = [f for f in fonts if f.endswith(":error")]
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
