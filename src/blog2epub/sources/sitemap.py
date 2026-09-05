"""Sitemap source: crawl sitemap.xml, keep URLs that match the blog, extract with readability."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterator
from urllib.parse import urljoin

import requests
from lxml import etree

from ..config import BlogConfig
from ..extract import extract_article
from ..http import HttpClient
from ..models import Post, PostRef, utcnow_iso
from .base import Source

log = logging.getLogger(__name__)

NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
MAX_SITEMAPS = 200  # raise with `sitemap: { max: N }` for date-partitioned indexes


class SitemapSource(Source):
    name = "sitemap"

    def __init__(self, blog: BlogConfig, client: HttpClient, sitemap_url: str) -> None:
        super().__init__(blog, client)
        self.sitemap_url = sitemap_url
        # Big sites partition their sitemap index by date and language (Google Cloud's blog has
        # 1058 fortnightly files across a dozen languages). `include` picks the partitions worth
        # walking; `max` raises the safety cap.
        self.max_sitemaps = int(blog.sitemap.get("max", MAX_SITEMAPS))
        self.sitemap_include = [re.compile(p) for p in blog.sitemap.get("include", [])]

    def describe(self) -> str:
        return f"sitemap ({self.sitemap_url})"

    @classmethod
    def detect(cls, blog: BlogConfig, client: HttpClient) -> SitemapSource | None:
        origin = cls(blog, client, "").origin
        candidates: list[str] = []
        if blog.sitemap.get("url"):
            candidates.append(blog.sitemap["url"])
        else:
            robots = client.try_get(f"{origin}/robots.txt")
            if robots is not None:
                candidates += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots.text)
            base = blog.url if blog.url.endswith("/") else blog.url + "/"
            candidates += [
                urljoin(base, "sitemap.xml"),
                f"{origin}/sitemap.xml",
                f"{origin}/sitemap_index.xml",
                f"{origin}/sitemap-index.xml",
            ]
        for url in dict.fromkeys(candidates):
            resp = client.try_get(url)
            if resp is None:
                continue
            try:
                root = etree.fromstring(resp.content)
            except etree.XMLSyntaxError:
                continue
            if root.tag in (f"{NS}urlset", f"{NS}sitemapindex"):
                return cls(blog, client, url)
        return None

    def _walk(self, url: str, seen: set[str], out: list[tuple[str, str | None]]) -> None:
        if url in seen or len(seen) >= self.max_sitemaps:
            return
        seen.add(url)
        try:
            root = etree.fromstring(self.client.get(url).content)
        except (requests.RequestException, etree.XMLSyntaxError) as exc:
            log.warning("sitemap %s unreadable: %s", url, exc)
            return
        if root.tag == f"{NS}sitemapindex":
            for sm in root.iter(f"{NS}sitemap"):
                loc = sm.findtext(f"{NS}loc")
                if loc and self._wanted_sitemap(loc.strip()):
                    # skip sitemaps that obviously belong to other content types when we can tell
                    self._walk(loc.strip(), seen, out)
        elif root.tag == f"{NS}urlset":
            for u in root.iter(f"{NS}url"):
                loc = u.findtext(f"{NS}loc")
                if loc:
                    out.append((loc.strip(), (u.findtext(f"{NS}lastmod") or "").strip() or None))

    def _wanted_sitemap(self, loc: str) -> bool:
        return not self.sitemap_include or any(p.search(loc) for p in self.sitemap_include)

    def discover(self) -> list[PostRef]:
        found: list[tuple[str, str | None]] = []
        self._walk(self.sitemap_url, set(), found)
        blog_prefix = self.blog.url.rstrip("/") + "/"
        refs: list[PostRef] = []
        for url, lastmod in found:
            # Without include patterns, only URLs *below* the blog root count as posts.
            if not self.blog.include and not url.startswith(blog_prefix):
                continue
            if url.rstrip("/") == self.blog.url.rstrip("/"):
                continue
            ref = PostRef(key="sm-" + hashlib.sha1(url.encode()).hexdigest()[:16], url=url, modified=lastmod)
            if self.accepts(ref):
                refs.append(ref)
        return refs

    def fetch(self, refs: list[PostRef]) -> Iterator[Post]:
        for ref in refs:
            try:
                page, url = self.client.get_text_tolerant(ref.url)
            except requests.RequestException as exc:
                log.warning("skipping %s: %s", ref.url, exc)
                continue
            ref.url = url  # remember the form the server actually serves
            art = extract_article(page, ref.url, keep=self.blog.keep, remove=self.blog.remove)
            if not art["html"]:
                log.warning("no article body found at %s, skipping", ref.url)
                continue
            post = Post(
                key=ref.key,
                url=ref.url,
                title=art["title"] or ref.url,
                html=art["html"],
                date=art["date"],
                modified=art["modified"] or ref.modified,
                author=art["author"],
                excerpt=art["excerpt"],
                featured_image=art["featured_image"],
                source=self.name,
                fetched_at=utcnow_iso(),
            )
            # the listing had no dates, so apply since/until now that we know them
            if self.accepts(PostRef(key=post.key, url=post.url, date=post.date)):
                yield post
