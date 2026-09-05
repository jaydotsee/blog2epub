from __future__ import annotations

import logging

from ..config import BlogConfig
from ..http import HttpClient
from .base import Source, SourceError
from .feed import FeedSource
from .sitemap import SitemapSource
from .wordpress import WordPressSource

log = logging.getLogger(__name__)

SOURCES: dict[str, type[Source]] = {
    "wordpress": WordPressSource,
    "feed": FeedSource,
    "sitemap": SitemapSource,
}
DETECT_ORDER = ("wordpress", "feed", "sitemap")


def resolve_source(blog: BlogConfig, client: HttpClient, hint: str | None = None) -> Source:
    """Pick the source for a blog: the configured one, the cached one, or auto-detect."""
    wanted = blog.source if blog.source != "auto" else None
    if wanted:
        src = SOURCES[wanted].detect(blog, client)
        if src is None:
            raise SourceError(f"blog {blog.id!r}: configured source {wanted!r} is not available at {blog.url}")
        return src
    order = list(DETECT_ORDER)
    if hint in order:
        order.remove(hint)
        order.insert(0, hint)
    for name in order:
        src = SOURCES[name].detect(blog, client)
        if src is not None:
            log.info("blog %s: using %s source", blog.id, name)
            return src
    raise SourceError(f"blog {blog.id!r}: could not detect a WordPress API, feed or sitemap at {blog.url}")


__all__ = ["Source", "SourceError", "resolve_source", "SOURCES"]
