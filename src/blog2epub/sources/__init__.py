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


def _why(client: HttpClient) -> str:
    """What the site answered to the endpoints we tried, for a detection failure message.

    Without this a blocked blog reads only as "could not detect", which is indistinguishable
    from a site that genuinely has no feed. The digest's Substack source fails on every CI run
    and the log never said whether that was a 403, a timeout or a missing endpoint.

    Detection tries a dozen or so URLs, and listing every one buries the answer. A run of 404s
    is one fact, not twelve, so outcomes are grouped and each is shown with one example URL.
    """
    by_outcome: dict[str, list[str]] = {}
    for url, _, outcome in (p.partition(" -> ") for p in client.rejected_probes):
        by_outcome.setdefault(outcome, []).append(url)
    if not by_outcome:
        return "nothing was tried"
    parts = []
    for outcome, urls in by_outcome.items():
        more = f" (and {len(urls) - 1} more)" if len(urls) > 1 else ""
        parts.append(f"{urls[0]} -> {outcome}{more}")
    return "; ".join(parts)


def resolve_source(blog: BlogConfig, client: HttpClient, hint: str | None = None) -> Source:
    """Pick the source for a blog: the configured one, the cached one, or auto-detect."""
    wanted = blog.source if blog.source != "auto" else None
    if wanted:
        src = SOURCES[wanted].detect(blog, client)
        if src is None:
            raise SourceError(
                f"blog {blog.id!r}: configured source {wanted!r} is not available at "
                f"{blog.url} ({_why(client)})"
            )
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
    raise SourceError(
        f"blog {blog.id!r}: could not detect a WordPress API, feed or sitemap at {blog.url} ({_why(client)})"
    )


__all__ = ["SOURCES", "Source", "SourceError", "resolve_source"]
