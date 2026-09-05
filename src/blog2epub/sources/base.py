from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from urllib.parse import urlsplit

from ..config import BlogConfig
from ..http import HttpClient
from ..models import Post, PostRef, parse_date


class SourceError(Exception):
    pass


class Source(ABC):
    name: str = ""

    def __init__(self, blog: BlogConfig, client: HttpClient) -> None:
        self.blog = blog
        self.client = client

    @classmethod
    @abstractmethod
    def detect(cls, blog: BlogConfig, client: HttpClient) -> Source | None:
        """Return an instance if this source works for the blog, else None."""

    @abstractmethod
    def discover(self) -> list[PostRef]:
        """List every post the source knows about (already filtered by the blog config)."""

    @abstractmethod
    def fetch(self, refs: list[PostRef]) -> Iterator[Post]:
        """Fetch the full body for the given refs."""

    def describe(self) -> str:
        return self.name

    # ---- helpers shared by implementations ---------------------------------
    def accepts(self, ref: PostRef) -> bool:
        if not self.blog.accepts_url(ref.url):
            return False
        d = parse_date(ref.date)
        if d is not None:
            since = parse_date(self.blog.since)
            until = parse_date(self.blog.until)
            if since and d < since:
                return False
            if until and d > until:
                return False
        return True

    @property
    def origin(self) -> str:
        parts = urlsplit(self.blog.url)
        return f"{parts.scheme}://{parts.netloc}"
