"""WordPress REST API source (wp-json/wp/v2/posts)."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from html import unescape
from typing import Any

import requests
from lxml import html as lxml_html

from ..config import BlogConfig
from ..http import HttpClient
from ..models import Post, PostRef, is_relative_date, resolve_date, utcnow_iso
from .base import Source, SourceError

log = logging.getLogger(__name__)

PER_PAGE = 100
LIST_FIELDS = "id,date_gmt,modified_gmt,slug,link,title"
FETCH_FIELDS = (
    "id,date_gmt,modified_gmt,slug,link,title,content,excerpt,author,categories,tags,_links,_embedded"
)


def _strip_tags(text: str) -> str:
    if not text:
        return ""
    try:
        return " ".join(lxml_html.fromstring(text).text_content().split())
    except Exception:
        return unescape(re.sub(r"<[^>]+>", "", text)).strip()


class WordPressSource(Source):
    name = "wordpress"

    def __init__(self, blog: BlogConfig, client: HttpClient, api_base: str) -> None:
        super().__init__(blog, client)
        self.api_base = api_base.rstrip("/")
        self.post_type = blog.wordpress.get("post_type", "posts")

    def describe(self) -> str:
        return f"wordpress ({self.api_base}/{self.post_type})"

    # ---- detection -----------------------------------------------------------
    @classmethod
    def detect(cls, blog: BlogConfig, client: HttpClient) -> WordPressSource | None:
        candidates: list[str] = []
        if blog.wordpress.get("api"):
            candidates.append(blog.wordpress["api"])
        else:
            page = client.try_get(blog.url)
            if page is not None:
                m = re.search(r'<link[^>]+rel="https://api\.w\.org/"[^>]+href="([^"]+)"', page.text)
                if m:
                    candidates.append(m.group(1).rstrip("/") + "/wp/v2")
            origin = cls(blog, client, "").origin
            candidates.append(f"{origin}/wp-json/wp/v2")
            candidates.append(f"{origin}/?rest_route=/wp/v2")
        seen: set[str] = set()
        for candidate in candidates:
            api = candidate.rstrip("/")
            if api in seen:
                continue
            seen.add(api)
            post_type = blog.wordpress.get("post_type", "posts")
            resp = client.try_get(_join(api, post_type), params={"per_page": 1, "_fields": "id"})
            if resp is None:
                continue
            try:
                data = resp.json()
            except ValueError:
                continue
            if isinstance(data, list):
                return cls(blog, client, api)
        return None

    # ---- listing -------------------------------------------------------------
    def _params(self, **extra: Any) -> dict[str, Any]:
        params: dict[str, Any] = {
            "per_page": PER_PAGE,
            "orderby": "date",
            "order": "desc",
            "status": "publish",
        }
        if self.blog.since:
            params["after"] = _iso_day(self.blog.since, end=False)
        if self.blog.until:
            params["before"] = _iso_day(self.blog.until, end=True)
        cats = self.blog.wordpress.get("categories")
        if cats:
            params["categories"] = ",".join(str(c) for c in cats)
        params.update(self.blog.wordpress.get("params", {}))
        params.update(extra)
        return params

    def discover(self) -> list[PostRef]:
        refs: list[PostRef] = []
        page = 1
        total_pages = 1
        while page <= total_pages:
            try:
                resp = self.client.get(
                    _join(self.api_base, self.post_type), params=self._params(page=page, _fields=LIST_FIELDS)
                )
            except requests.RequestException as exc:
                # WordPress answers 400 (rest_post_invalid_page_number) when we page past the end
                resp_ = getattr(exc, "response", None)
                if resp_ is not None and resp_.status_code == 400 and page > 1:
                    break
                raise SourceError(f"listing posts failed: {exc}") from exc
            total_pages = int(resp.headers.get("X-WP-TotalPages", total_pages) or 1)
            items = resp.json()
            if not items:
                break
            for item in items:
                ref = PostRef(
                    key=f"wp-{item['id']}",
                    url=item.get("link", ""),
                    title=_strip_tags((item.get("title") or {}).get("rendered", "")),
                    date=_gmt(item.get("date_gmt")),
                    modified=_gmt(item.get("modified_gmt")),
                    extra={"id": item["id"], "slug": item.get("slug")},
                )
                if self.accepts(ref):
                    refs.append(ref)
            page += 1
        return refs

    # ---- fetching ------------------------------------------------------------
    def fetch(self, refs: list[PostRef]) -> Iterator[Post]:
        ids = [r.extra["id"] for r in refs]
        for start in range(0, len(ids), PER_PAGE):
            batch = ids[start : start + PER_PAGE]
            params = self._params(
                include=",".join(map(str, batch)),
                _fields=FETCH_FIELDS,
                _embed="author,wp:term,wp:featuredmedia",
            )
            # `include` must not be combined with date filters, or WP silently drops posts.
            params.pop("after", None)
            params.pop("before", None)
            params.pop("categories", None)
            try:
                items = self.client.get_json(_join(self.api_base, self.post_type), params=params)
            except requests.RequestException as exc:
                # A long archive is many batches; losing one to a hiccup should not cost the
                # rest. The posts stay uncached and the next sync picks them up.
                log.warning("batch of %d posts starting %s failed, skipping: %s", len(batch), batch[0], exc)
                continue
            for item in items:
                yield self._to_post(item)

    def _to_post(self, item: dict[str, Any]) -> Post:
        embedded = item.get("_embedded") or {}
        author = None
        for a in embedded.get("author") or []:
            if isinstance(a, dict) and a.get("name"):
                author = a["name"]
                break
        categories: list[str] = []
        tags: list[str] = []
        for group in embedded.get("wp:term") or []:
            for term in group or []:
                if not isinstance(term, dict):
                    continue
                name = unescape(term.get("name", ""))
                if term.get("taxonomy") == "category" and name and name.lower() != "uncategorized":
                    categories.append(name)
                elif term.get("taxonomy") == "post_tag" and name:
                    tags.append(name)
        featured = None
        for media in embedded.get("wp:featuredmedia") or []:
            if not isinstance(media, dict):
                continue
            sizes = (media.get("media_details") or {}).get("sizes") or {}
            for size in ("large", "medium_large", "full"):
                if sizes.get(size, {}).get("source_url"):
                    featured = sizes[size]["source_url"]
                    break
            featured = featured or media.get("source_url")
            if featured:
                break
        return Post(
            key=f"wp-{item['id']}",
            featured_image=featured,
            url=item.get("link", ""),
            title=_strip_tags((item.get("title") or {}).get("rendered", "")) or item.get("slug", ""),
            html=(item.get("content") or {}).get("rendered", ""),
            date=_gmt(item.get("date_gmt")),
            modified=_gmt(item.get("modified_gmt")),
            author=author,
            categories=categories,
            tags=tags,
            excerpt=_strip_tags((item.get("excerpt") or {}).get("rendered", "")) or None,
            source=self.name,
            fetched_at=utcnow_iso(),
        )


def _join(api: str, path: str) -> str:
    # works for both `/wp-json/wp/v2` and `/?rest_route=/wp/v2` style bases
    return f"{api}/{path}"


def _gmt(value: str | None) -> str | None:
    if not value:
        return None
    return value if value.endswith(("Z", "+00:00")) else value + "+00:00"


def _iso_day(value: str, end: bool) -> str:
    """WordPress wants ISO-8601; config values may be dates or rolling windows like 7d."""
    if is_relative_date(value):
        d = resolve_date(value)
        assert d is not None
        return d.strftime("%Y-%m-%dT%H:%M:%S")
    value = value.strip()
    if "T" in value:
        return value
    return f"{value}T23:59:59" if end else f"{value}T00:00:00"
