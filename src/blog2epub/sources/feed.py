"""RSS / Atom feed source, with optional full-page fetch for truncated feeds."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import feedparser
import requests

from ..clean import text_of
from ..config import BlogConfig
from ..extract import extract_article
from ..http import HttpClient
from ..models import Post, PostRef, utcnow_iso
from .base import Source

log = logging.getLogger(__name__)

FEED_PATHS = ("feed/", "feed", "rss.xml", "atom.xml", "feed.xml", "index.xml", "rss/", "rss")
MIN_FULL_BODY_CHARS = 1500


def _struct_to_iso(value: time.struct_time | None) -> str | None:
    if not value:
        return None
    return datetime(*value[:6], tzinfo=timezone.utc).isoformat()


class FeedSource(Source):
    name = "feed"

    def __init__(self, blog: BlogConfig, client: HttpClient, feed_url: str) -> None:
        super().__init__(blog, client)
        self.feed_url = feed_url
        self._entries: dict[str, Any] = {}

    def describe(self) -> str:
        return f"feed ({self.feed_url})"

    @classmethod
    def detect(cls, blog: BlogConfig, client: HttpClient) -> FeedSource | None:
        candidates: list[str] = []
        if blog.feed.get("url"):
            candidates.append(blog.feed["url"])
        else:
            page = client.try_get(blog.url)
            if page is not None:
                for m in re.finditer(r"<link[^>]+>", page.text, flags=re.I):
                    tag = m.group(0)
                    if re.search(r'type="application/(rss|atom)\+xml"', tag, re.I):
                        href = re.search(r'href="([^"]+)"', tag)
                        if href:
                            candidates.append(urljoin(blog.url, href.group(1)))
            base = blog.url if blog.url.endswith("/") else blog.url + "/"
            origin = cls(blog, client, "").origin + "/"
            for root in (base, origin):
                candidates.extend(urljoin(root, p) for p in FEED_PATHS)
        seen: set[str] = set()
        for url in candidates:
            if url in seen:
                continue
            seen.add(url)
            resp = client.try_get(url)
            if resp is None:
                continue
            parsed = feedparser.parse(resp.content)
            if parsed.entries:
                return cls(blog, client, url)
        return None

    def discover(self) -> list[PostRef]:
        parsed = feedparser.parse(self.client.get(self.feed_url).content)
        refs: list[PostRef] = []
        for entry in parsed.entries:
            url = entry.get("link")
            if not url:
                continue
            key = "feed-" + hashlib.sha1((entry.get("id") or url).encode("utf-8")).hexdigest()[:16]
            keys = set(entry.keys())  # feedparser warns on .get() of a missing *_parsed key
            ref = PostRef(
                key=key,
                url=url,
                title=entry.get("title", ""),
                date=_struct_to_iso(entry["published_parsed"]) if "published_parsed" in keys else None,
                modified=_struct_to_iso(entry["updated_parsed"]) if "updated_parsed" in keys else None,
            )
            if self.accepts(ref):
                self._entries[key] = entry
                refs.append(ref)
        return refs

    def fetch(self, refs: list[PostRef]) -> Iterator[Post]:
        if not self._entries:
            self.discover()
        for ref in refs:
            entry = self._entries.get(ref.key)
            body = ""
            if entry is not None:
                for c in entry.get("content") or []:
                    if c.get("value"):
                        body = c["value"]
                        break
                if not body:
                    body = entry.get("summary", "")
            author = entry.get("author") if entry is not None else None
            tags = [t.get("term") for t in (entry.get("tags") or []) if t.get("term")] if entry else []
            title, date, modified, excerpt, featured = ref.title, ref.date, ref.modified, None, None
            if entry is not None and body and entry.get("summary") and entry["summary"] != body:
                summary = text_of(entry["summary"])
                if 0 < len(summary) < 600:
                    excerpt = summary

            if self.blog.fetch_full and len(text_of(body)) < MIN_FULL_BODY_CHARS:
                try:
                    page = self.client.get_text(ref.url)
                    art = extract_article(page, ref.url)
                    if len(text_of(art["html"])) > len(text_of(body)):
                        body = art["html"]
                    title = title or art["title"]
                    date = date or art["date"]
                    modified = modified or art["modified"]
                    author = author or art["author"]
                    excerpt = excerpt or art["excerpt"]
                    featured = art["featured_image"]
                except requests.RequestException as exc:
                    log.warning("could not fetch %s, keeping feed body: %s", ref.url, exc)
            yield Post(
                key=ref.key,
                url=ref.url,
                title=title or ref.url,
                html=body,
                date=date,
                modified=modified,
                author=author,
                categories=[],
                tags=tags,
                excerpt=excerpt,
                featured_image=featured,
                source=self.name,
                fetched_at=utcnow_iso(),
            )
