#!/usr/bin/env python3
"""Render a magazine-style cover for a blog or a book from an HTML template.

    scripts/render_cover.py --blog tyk --template covers/tyk.html --out covers/tyk.jpg
    scripts/render_cover.py --book api-management --template covers/api-management.html --out covers/api-management.jpg
    scripts/render_cover.py --all          # every covers/<id>.html that names a configured blog or book

This renders the whole book onto one cover, for previews and the README. `blog2epub build`
renders the same template itself, once per volume, with that volume's post count, year span,
issue number and cover lines — see blog2epub.covers for the placeholders.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from blog2epub.config import BookConfig, load_config  # noqa: E402
from blog2epub.covers import (  # noqa: E402  # noqa: E402
    COVER_HEIGHT,
    COVER_LINES,
    COVER_QUALITY,
    COVER_WIDTH,
    cover_values,
    render_cover_template,
)
from blog2epub.epub import select_entries  # noqa: E402
from blog2epub.store import BlogStore  # noqa: E402


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
    ap.add_argument("--width", type=int, default=COVER_WIDTH)
    ap.add_argument("--height", type=int, default=COVER_HEIGHT)
    ap.add_argument("--quality", type=int, default=COVER_QUALITY)
    ap.add_argument("--lines", type=int, default=COVER_LINES, help="how many cover lines to fill")
    args = ap.parse_args(argv)

    settings = load_config(args.config)
    if args.all:
        return render_all(settings, args)
    if not args.template or not args.out:
        ap.error("--template and --out are required unless --all is given")
    book: BookConfig = settings.blog(args.blog).as_book() if args.blog else settings.book(args.book)
    sources = {bid: (settings.blog(bid), BlogStore(settings.cache_dir, bid)) for bid in book.blogs}
    entries = select_entries(book, sources)
    values = cover_values(book, entries, lines=args.lines)
    missing = render_cover_template(
        args.template, args.out, values, width=args.width, height=args.height, quality=args.quality
    )
    if missing:
        print(f"warning: fonts not loaded: {missing}", file=sys.stderr)
    lines = [[values[f"kicker{i}"], values[f"title{i}"]] for i in range(1, args.lines + 1)]
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB) with cover lines: {json.dumps(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
