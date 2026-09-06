"""Covers: a static image, a downloaded one, or a magazine cover rendered from an HTML template.

A template is a string.Template with placeholders filled from the posts that go into the book
(or the volume, when the book is split): $count, $first_year, $last_year, $years ("2015 - 2026" with an
en dash, or "2015" for a single year), $years_prose ("2015 to 2026"), $issue (e.g.
"September 2026"), $issue_number (e.g. "20260905.1"), $volume, $volumes, $volume_label ("Vol. 2
of 3", empty for a single volume), $month, $year, $url, $title, $blog_count, $blog_list, and cover
lines $kicker1/$title1 ... $kicker6/$title6 from the newest posts. For a multi-blog book the
kicker is the blog's title. Rendering uses the Chromium bundled with Playwright (the `covers`
extra); fonts under covers/fonts/ resolve relative to the template.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from .config import BlogConfig, BookConfig, Settings
from .http import HttpClient
from .images import fetch_image
from .store import BlogStore

if TYPE_CHECKING:
    from .epub import Entry

log = logging.getLogger(__name__)

KICKERS = [
    (r"\b(mcp|agent|ai|llm)\b", "AI & MCP"),
    (r"\bopen[ -]?source\b", "OPEN SOURCE"),
    (r"\b(bank|financ|fintech|open finance|payments?)\b", "FINANCIAL SERVICES"),
    (r"\b(kubernetes|k8s|cloud|deploy|scal)", "PLATFORM"),
    (r"\b(secur|auth|oauth|jwt|token|revoke)", "SECURITY"),
    (r"\b(graphql|rest|grpc|openapi|schema)\b", "API DESIGN"),
]
COVER_LINES = 6
COVER_WIDTH, COVER_HEIGHT, COVER_QUALITY = 1600, 2133, 90


def resolve_cover(cover: str | None, settings: Settings, client: HttpClient | None = None) -> Path | None:
    """Return the local file behind `cover`: a jpg/png, an .html template, or a URL downloaded
    into cache/_covers once. None when there is nothing usable (the build then generates one)."""
    if not cover:
        return None
    if urlsplit(cover).scheme in ("http", "https"):
        store = BlogStore(settings.cache_dir, "_covers")
        path = store.image_path(cover)
        if path is None and client is not None:
            if fetch_image(client, store, cover, 20_000_000):
                path = store.image_path(cover)
            store.save()
        if path is None:
            log.warning("cover %s is not available, using a generated cover", cover)
        return path
    path = settings.config_path.parent / cover
    if not path.exists():
        log.warning("cover file %s not found, using a generated cover", path)
        return None
    return path


def is_template(cover: Path | None) -> bool:
    return cover is not None and cover.suffix.lower() in (".html", ".htm")


def static_fallback(template: Path) -> Path | None:
    """The last rendered image next to a template, for builds that cannot run Chromium."""
    for ext in (".jpg", ".jpeg", ".png"):
        candidate = template.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401, PLC0415  (optional dependency: the `covers` extra)
    except ImportError:
        return False
    return True


def kicker_for(title: str, categories: list[str]) -> str:
    for cat in categories:
        if cat and cat.lower() != "uncategorized":
            return cat.upper()
    for pattern, label in KICKERS:
        if re.search(pattern, title, re.I):
            return label
    return "OPINION"


def cover_lines(entries: list[Entry], n: int, by_blog: bool) -> list[tuple[str, str]]:
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


def _span(dates: list[datetime], joiner: str) -> str:
    if not dates:
        return ""
    first, last = dates[0].year, dates[-1].year
    return str(first) if first == last else f"{first}{joiner}{last}"


def volume_label(volume: int, volumes: int) -> str:
    return f"Vol. {volume} of {volumes}" if volumes > 1 else ""


def cover_values(
    book: BookConfig,
    entries: list[Entry],
    *,
    now: datetime | None = None,
    issue: str | None = None,
    volume: int = 1,
    volumes: int = 1,
    label: str | None = None,
    lines: int = COVER_LINES,
) -> dict[str, str]:
    """Placeholder values for one volume's cover, computed from the posts that are in it.

    `label` is what the volume is called on the cover: "2024" for a year split, "Vol. 2 of 3"
    for a size split (the default when None), empty for a book that is one volume.
    """
    now = now or datetime.now(timezone.utc)
    issue = issue or f"{now:%Y%m%d}"
    newest = sorted(
        entries, key=lambda e: e.post.date_obj or datetime.min.replace(tzinfo=timezone.utc), reverse=True
    )
    dates = sorted(e.post.date_obj for e in entries if e.post.date_obj)
    blogs: list[BlogConfig] = list({e.blog.id: e.blog for e in entries}.values())
    values = {
        "count": str(len(entries)),
        "first_year": str(dates[0].year) if dates else "",
        "last_year": str(dates[-1].year) if dates else "",
        # a one-year volume says "2015", not "2015 - 2015"
        "years": _span(dates, " \u2013 "),
        "years_prose": _span(dates, " to "),
        "issue": f"{now:%B %Y}",
        "issue_number": f"{issue}.{volume}",
        "volume": str(volume),
        "volumes": str(volumes),
        "volume_label": volume_label(volume, volumes) if label is None else label,
        "month": f"{now:%B}",
        "year": f"{now:%Y}",
        "url": blogs[0].url.removeprefix("https://").removeprefix("http://") if len(blogs) == 1 else "",
        "title": book.title,
        "blog_count": str(len(blogs)),
        "blog_list": " · ".join(b.title for b in blogs),
    }
    for i, (kicker, title) in enumerate(cover_lines(newest, lines, by_blog=len(book.blogs) > 1), start=1):
        values[f"kicker{i}"] = kicker
        values[f"title{i}"] = title
    return values


def render_cover_template(
    template: Path,
    out: Path,
    values: dict[str, str],
    *,
    width: int = COVER_WIDTH,
    height: int = COVER_HEIGHT,
    quality: int = COVER_QUALITY,
) -> list[str]:
    """Fill the template and screenshot it with Chromium. Returns the fonts that failed to load.

    Raises ImportError when Playwright is not installed; callers decide what to fall back to.
    """
    from playwright.sync_api import sync_playwright  # noqa: PLC0415  (optional dependency)

    html = Template(template.read_text(encoding="utf-8")).safe_substitute(values)
    # Render from a file next to the template so relative assets (fonts/, images) resolve.
    rendered = template.with_name(f".{template.stem}.render.html")
    rendered.write_text(html, encoding="utf-8")
    # Use an existing Chromium when one is provided (CI images, `playwright install` otherwise).
    executable = os.environ.get("CHROMIUM_PATH") or (
        "/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None
    )
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=executable, args=["--allow-file-access-from-files"])
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.goto(rendered.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(300)
            fonts = page.evaluate(
                "Array.from(document.fonts).map(f => f.family + ':' + f.weight + ':' + f.status)"
            )
            kind = "jpeg" if out.suffix.lower() in (".jpg", ".jpeg") else "png"
            shot: dict[str, Any] = {"path": str(out), "type": kind, "full_page": False}
            if kind == "jpeg":
                shot["quality"] = quality
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(**shot)
            browser.close()
    finally:
        rendered.unlink(missing_ok=True)
    # "unloaded" just means no element used that weight; only "error" is a real failure.
    return [f for f in fonts if f.endswith(":error")]
