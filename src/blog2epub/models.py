from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class PostRef:
    """A post as seen in a listing (API page, feed, sitemap) before its body is fetched."""

    key: str
    url: str
    title: str = ""
    date: str | None = None      # ISO-8601 publication date, if the listing knows it
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
    source: str = ""
    fetched_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Post:
        known = {f for f in cls.__dataclass_fields__}
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


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        from dateutil import parser as dtparser

        d = dtparser.parse(value)
    except (ValueError, OverflowError, TypeError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d
