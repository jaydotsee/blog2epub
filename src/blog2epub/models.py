from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from dateutil import parser as dtparser


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class PostRef:
    """A post as seen in a listing (API page, feed, sitemap) before its body is fetched."""

    key: str
    url: str
    title: str = ""
    date: str | None = None  # ISO-8601 publication date, if the listing knows it
    modified: str | None = None  # ISO-8601 last-modified, if the listing knows it
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Post:
    """A fully fetched post, stored in the per-blog cache."""

    key: str
    url: str
    title: str
    html: str
    date: str | None = None
    modified: str | None = None
    author: str | None = None
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    excerpt: str | None = None
    featured_image: str | None = None  # absolute URL of the post's lead/og image, if any
    source: str = ""
    blog_id: str = ""
    fetched_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Post:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def date_obj(self) -> datetime | None:
        return parse_date(self.date)

    @property
    def year(self) -> str:
        d = self.date_obj
        return str(d.year) if d else "Undated"

    @property
    def month(self) -> str:
        d = self.date_obj
        return d.strftime("%Y-%m") if d else "Undated"


_RELATIVE_RE = re.compile(r"^\s*(\d+)\s*([dwmy])\s*$", re.I)
_UNIT_DAYS = {"d": 1, "w": 7, "m": 30, "y": 365}


def resolve_date(value: str | None, now: datetime | None = None) -> datetime | None:
    """Turn a config date into a datetime.

    Accepts absolute dates ("2025-01-01", "2025-01-01T12:00:00Z") and rolling windows relative
    to now: "7d", "2w", "3m", "1y" (days, weeks, months of 30 days, years of 365 days).
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    m = _RELATIVE_RE.match(text)
    if m:
        now = now or datetime.now(timezone.utc)
        return now - timedelta(days=int(m.group(1)) * _UNIT_DAYS[m.group(2).lower()])
    return parse_date(text)


def is_relative_date(value: str | None) -> bool:
    return bool(value) and _RELATIVE_RE.match(str(value)) is not None


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        d = dtparser.parse(value)
    except (ValueError, OverflowError, TypeError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d
