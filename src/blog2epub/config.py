from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    pass


@dataclass
class BlogConfig:
    id: str
    url: str
    title: str = ""
    author: str = ""
    description: str = ""
    publisher: str = ""
    language: str = "en"
    source: str = "auto"                 # auto | wordpress | feed | sitemap
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    since: str | None = None
    until: str | None = None
    max_posts: int | None = None
    cover: str | None = None             # path or URL to a jpg/png cover image
    images: bool = True
    max_image_width: int = 1200
    max_image_bytes: int = 8_000_000
    group_by: str = "year"               # year | month | none
    order: str = "asc"                   # asc | desc
    split: str = "none"                  # none | year
    demote_headings: bool = True
    fetch_full: bool = True              # feed source: fetch the page when the feed body is missing/short
    request_delay: float | None = None
    wordpress: dict[str, Any] = field(default_factory=dict)
    feed: dict[str, Any] = field(default_factory=dict)
    sitemap: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ConfigError("every blog needs an `id`")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", self.id):
            raise ConfigError(f"blog id {self.id!r} may only contain letters, digits, '.', '_' and '-'")
        if not self.url:
            raise ConfigError(f"blog {self.id!r} needs a `url`")
        if not self.title:
            self.title = self.id
        for attr, allowed in (
            ("source", {"auto", "wordpress", "feed", "sitemap"}),
            ("group_by", {"year", "month", "none"}),
            ("order", {"asc", "desc"}),
            ("split", {"none", "year"}),
        ):
            if getattr(self, attr) not in allowed:
                raise ConfigError(f"blog {self.id!r}: `{attr}` must be one of {sorted(allowed)}")
        for pattern in self.include + self.exclude:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"blog {self.id!r}: invalid regex {pattern!r}: {exc}") from exc

    @property
    def include_re(self) -> list[re.Pattern[str]]:
        return [re.compile(p) for p in self.include]

    @property
    def exclude_re(self) -> list[re.Pattern[str]]:
        return [re.compile(p) for p in self.exclude]

    def accepts_url(self, url: str) -> bool:
        if self.include_re and not any(p.search(url) for p in self.include_re):
            return False
        if any(p.search(url) for p in self.exclude_re):
            return False
        return True


@dataclass
class Settings:
    config_path: Path
    output_dir: Path
    cache_dir: Path
    user_agent: str = "blog2epub/0.1"
    request_delay: float = 0.5
    timeout: int = 30
    blogs: list[BlogConfig] = field(default_factory=list)

    def blog(self, blog_id: str) -> BlogConfig:
        for b in self.blogs:
            if b.id == blog_id:
                return b
        raise ConfigError(f"unknown blog {blog_id!r}; configured: {[b.id for b in self.blogs]}")


_SETTINGS_KEYS = {"output_dir", "cache_dir", "user_agent", "request_delay", "timeout"}
_BLOG_KEYS = {f.name for f in fields(BlogConfig)}


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

    blog_defaults = {k: v for k, v in defaults.items() if k in _BLOG_KEYS}
    unknown = set(defaults) - _SETTINGS_KEYS - _BLOG_KEYS
    if unknown:
        raise ConfigError(f"unknown keys in `defaults`: {sorted(unknown)}")

    blogs_raw = raw.get("blogs") or []
    if not isinstance(blogs_raw, list):
        raise ConfigError("`blogs` must be a list")
    seen: set[str] = set()
    for entry in blogs_raw:
        if not isinstance(entry, dict):
            raise ConfigError("each blog entry must be a mapping")
        unknown = set(entry) - _BLOG_KEYS
        if unknown:
            raise ConfigError(f"blog {entry.get('id')!r}: unknown keys {sorted(unknown)}")
        merged: dict[str, Any] = {**blog_defaults, **entry}
        for required in ("id", "url"):
            if not merged.get(required):
                raise ConfigError(f"blog entry {entry.get('id') or entry.get('url') or entry!r} is missing `{required}`")
        for key in ("since", "until"):
            if merged.get(key) is not None:
                merged[key] = str(merged[key])
        blog = BlogConfig(**merged)
        if blog.id in seen:
            raise ConfigError(f"duplicate blog id {blog.id!r}")
        seen.add(blog.id)
        settings.blogs.append(blog)
    return settings
