from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml
from lxml.cssselect import CSSSelector, SelectorError

from .models import resolve_date


class ConfigError(Exception):
    pass


_ID_RE = re.compile(r"[A-Za-z0-9._-]+")


def _check_date(owner: str, attr: str, value: str | None) -> None:
    if value is not None and resolve_date(value) is None:
        raise ConfigError(
            f"{owner}: `{attr}` must be a date like 2025-01-01 or a window like 7d, 2w, 3m, 1y, not {value!r}"
        )


def _check_selectors(owner: str, attr: str, selectors: list[str]) -> None:
    for sel in selectors:
        try:
            CSSSelector(sel)
        except SelectorError as exc:
            raise ConfigError(f"{owner}: `{attr}` has an invalid CSS selector {sel!r}: {exc}") from exc


def _check_choice(owner: str, attr: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise ConfigError(f"{owner}: `{attr}` must be one of {sorted(allowed)}, not {value!r}")


@dataclass
class BookConfig:
    """One EPUB (or one EPUB per year when split) built from one or more blogs."""

    id: str
    blogs: list[str]
    title: str = ""
    author: str = ""
    description: str = ""
    publisher: str = ""
    language: str = "en"
    since: str | None = None
    until: str | None = None
    max_posts: int | None = None  # keep only the N most recent posts across all blogs
    cover: str | None = None  # path (relative to blogs.yaml) or URL of a jpg/png
    images: bool = True
    group_by: str = "year"  # year | year-month | month | blog | none  -> the "part" level of the TOC
    order: str = "asc"  # asc = oldest first (book), desc = newest first (magazine)
    split: str = "none"  # none | year
    demote_headings: bool = True
    readability: str = "auto"  # auto | always | never
    excerpts: bool = True  # show excerpts on the part/contents pages
    featured_images: bool = True  # lead each chapter with the post's featured image
    extra_css: str = ""  # appended to the book's stylesheet
    svg_images: str = "raster"  # raster | keep | drop  (Kindle's converter mishandles SVG)
    optimize_images: bool = True  # downscale and re-encode images to max_image_width
    image_quality: int = 82  # JPEG quality used when re-encoding

    def __post_init__(self) -> None:
        if not self.id or not _ID_RE.fullmatch(self.id):
            raise ConfigError(f"book id {self.id!r} may only contain letters, digits, '.', '_' and '-'")
        if not self.blogs:
            raise ConfigError(f"book {self.id!r} needs a non-empty `blogs` list")
        if not self.title:
            self.title = self.id
        _check_choice(
            f"book {self.id!r}", "group_by", self.group_by, {"year", "year-month", "month", "blog", "none"}
        )
        _check_choice(f"book {self.id!r}", "order", self.order, {"asc", "desc"})
        _check_choice(f"book {self.id!r}", "split", self.split, {"none", "year"})
        _check_choice(f"book {self.id!r}", "readability", self.readability, {"auto", "always", "never"})
        _check_choice(f"book {self.id!r}", "svg_images", self.svg_images, {"raster", "keep", "drop"})
        _check_date(f"book {self.id!r}", "since", self.since)
        _check_date(f"book {self.id!r}", "until", self.until)


# Book-level keys a blog may also carry; they configure the blog's own standalone book.
_BOOK_OPTS = (
    "author",
    "description",
    "publisher",
    "language",
    "since",
    "until",
    "max_posts",
    "cover",
    "group_by",
    "order",
    "split",
    "demote_headings",
    "readability",
    "excerpts",
    "featured_images",
    "svg_images",
    "optimize_images",
    "image_quality",
)


@dataclass
class BlogConfig:
    id: str
    url: str
    title: str = ""
    source: str = "auto"  # auto | wordpress | feed | sitemap
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    standalone: bool = True  # also build this blog's own EPUB
    images: bool = True  # download images at sync time
    max_image_width: int = 1200
    max_image_bytes: int = 8_000_000
    fetch_full: bool = True  # feed source: fetch the page when the feed body is missing/short
    # Some sites answer 200 with an error page for URLs that no longer exist (Google Cloud's
    # blog does). Posts whose body is shorter than this are skipped and named in the log.
    min_chars: int = 150
    keep: list[str] = field(default_factory=list)  # CSS selectors: the article container(s)
    remove: list[str] = field(default_factory=list)  # CSS selectors: clutter to drop from every post
    extra_css: str = ""  # appended to the stylesheet of every book containing this blog
    request_delay: float | None = None
    wordpress: dict[str, Any] = field(default_factory=dict)
    feed: dict[str, Any] = field(default_factory=dict)
    sitemap: dict[str, Any] = field(default_factory=dict)
    # standalone-book options (see _BOOK_OPTS)
    author: str = ""
    description: str = ""
    publisher: str = ""
    language: str = "en"
    since: str | None = None
    until: str | None = None
    max_posts: int | None = None
    cover: str | None = None
    group_by: str = "year"
    order: str = "asc"
    split: str = "none"
    demote_headings: bool = True
    readability: str = "auto"
    excerpts: bool = True
    featured_images: bool = True
    svg_images: str = "raster"
    optimize_images: bool = True
    image_quality: int = 82

    def __post_init__(self) -> None:
        if not self.id or not _ID_RE.fullmatch(self.id):
            raise ConfigError(f"blog id {self.id!r} may only contain letters, digits, '.', '_' and '-'")
        if not self.url:
            raise ConfigError(f"blog {self.id!r} needs a `url`")
        if not self.title:
            self.title = self.id
        _check_choice(f"blog {self.id!r}", "source", self.source, {"auto", "wordpress", "feed", "sitemap"})
        for pattern in self.include + self.exclude:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"blog {self.id!r}: invalid regex {pattern!r}: {exc}") from exc
        for pattern in self.sitemap.get("include", []):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(
                    f"blog {self.id!r}: invalid sitemap.include regex {pattern!r}: {exc}"
                ) from exc
        _check_selectors(f"blog {self.id!r}", "keep", self.keep)
        _check_selectors(f"blog {self.id!r}", "remove", self.remove)
        _check_date(f"blog {self.id!r}", "since", self.since)
        _check_date(f"blog {self.id!r}", "until", self.until)
        self.as_book()  # validates the book-level choices

    def as_book(self) -> BookConfig:
        """The implicit one-blog book this blog builds when `standalone` is true."""
        return BookConfig(
            id=self.id, title=self.title, blogs=[self.id], **{k: getattr(self, k) for k in _BOOK_OPTS}
        )

    @property
    def include_re(self) -> list[re.Pattern[str]]:
        return [re.compile(p) for p in self.include]

    @property
    def exclude_re(self) -> list[re.Pattern[str]]:
        return [re.compile(p) for p in self.exclude]

    def accepts_url(self, url: str) -> bool:
        if self.include_re and not any(p.search(url) for p in self.include_re):
            return False
        return not any(p.search(url) for p in self.exclude_re)


@dataclass
class Settings:
    config_path: Path
    output_dir: Path
    cache_dir: Path
    user_agent: str = "blog2epub/0.1"
    request_delay: float = 0.5
    timeout: int = 30
    blogs: list[BlogConfig] = field(default_factory=list)
    books: list[BookConfig] = field(default_factory=list)

    def blog(self, blog_id: str) -> BlogConfig:
        for b in self.blogs:
            if b.id == blog_id:
                return b
        raise ConfigError(f"unknown blog {blog_id!r}; configured: {[b.id for b in self.blogs]}")

    def all_books(self) -> list[BookConfig]:
        """Standalone blog books first, then the combined books."""
        return [b.as_book() for b in self.blogs if b.standalone] + list(self.books)

    def book(self, book_id: str) -> BookConfig:
        for b in self.all_books():
            if b.id == book_id:
                return b
        raise ConfigError(f"unknown book {book_id!r}; configured: {[b.id for b in self.all_books()]}")


_SETTINGS_KEYS = {"output_dir", "cache_dir", "user_agent", "request_delay", "timeout"}
_BLOG_KEYS = {f.name for f in fields(BlogConfig)}
_BOOK_KEYS = {f.name for f in fields(BookConfig)}


def load_config(path: str | Path) -> Settings:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")

    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("`defaults` must be a mapping")
    base = path.parent

    settings = Settings(
        config_path=path,
        output_dir=base / str(defaults.get("output_dir", "output")),
        cache_dir=base / str(defaults.get("cache_dir", "cache")),
        user_agent=str(defaults.get("user_agent", Settings.user_agent)),
        request_delay=float(defaults.get("request_delay", Settings.request_delay)),
        timeout=int(defaults.get("timeout", Settings.timeout)),
    )

    unknown = set(defaults) - _SETTINGS_KEYS - _BLOG_KEYS - _BOOK_KEYS
    if unknown:
        raise ConfigError(f"unknown keys in `defaults`: {sorted(unknown)}")
    blog_defaults = {k: v for k, v in defaults.items() if k in _BLOG_KEYS}
    book_defaults = {k: v for k, v in defaults.items() if k in _BOOK_KEYS}

    for entry in _list(raw, "blogs"):
        unknown = set(entry) - _BLOG_KEYS
        if unknown:
            raise ConfigError(f"blog {entry.get('id')!r}: unknown keys {sorted(unknown)}")
        merged: dict[str, Any] = {**blog_defaults, **entry}
        _require(merged, entry, "id", "url")
        _stringify_dates(merged)
        blog = BlogConfig(**merged)
        if any(b.id == blog.id for b in settings.blogs):
            raise ConfigError(f"duplicate blog id {blog.id!r}")
        settings.blogs.append(blog)

    for entry in _list(raw, "books"):
        unknown = set(entry) - _BOOK_KEYS
        if unknown:
            raise ConfigError(f"book {entry.get('id')!r}: unknown keys {sorted(unknown)}")
        merged = {**book_defaults, **entry}
        _require(merged, entry, "id", "blogs")
        _stringify_dates(merged)
        book = BookConfig(**merged)
        for blog_id in book.blogs:
            settings.blog(blog_id)  # raises for unknown ids
        if any(b.id == book.id for b in settings.all_books()):
            raise ConfigError(f"book id {book.id!r} clashes with another book or a blog id")
        settings.books.append(book)
    return settings


def _list(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = raw.get(key) or []
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ConfigError(f"`{key}` must be a list of mappings")
    return items


def _require(merged: dict[str, Any], entry: dict[str, Any], *keys: str) -> None:
    for key in keys:
        if not merged.get(key):
            raise ConfigError(f"entry {entry.get('id') or entry!r} is missing `{key}`")


def _stringify_dates(merged: dict[str, Any]) -> None:
    for key in ("since", "until"):
        if merged.get(key) is not None:
            merged[key] = str(merged[key])
