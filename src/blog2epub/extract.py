"""Pull an article body and its metadata out of a full HTML page (for non-API sources)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lxml import html
from readability import Document

log = logging.getLogger(__name__)


def _meta(doc: html.HtmlElement, *names: str) -> str | None:
    for name in names:
        for attr in ("property", "name", "itemprop"):
            el = doc.find(f".//meta[@{attr}='{name}']")
            if el is not None and el.get("content"):
                return el.get("content").strip()
    return None


def _jsonld(doc: html.HtmlElement) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for script in doc.iter("script"):
        if (script.get("type") or "").lower() != "application/ld+json" or not script.text:
            continue
        try:
            data = json.loads(script.text)
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item:
                    stack.extend(item["@graph"])
                types = item.get("@type")
                types = types if isinstance(types, list) else [types]
                if any(t in ("Article", "BlogPosting", "NewsArticle", "TechArticle") for t in types):
                    out.setdefault("datePublished", item.get("datePublished"))
                    out.setdefault("dateModified", item.get("dateModified"))
                    out.setdefault("headline", item.get("headline"))
                    author = item.get("author")
                    if isinstance(author, list) and author:
                        author = author[0]
                    if isinstance(author, dict):
                        out.setdefault("author", author.get("name"))
                    elif isinstance(author, str):
                        out.setdefault("author", author)
    return {k: v for k, v in out.items() if v}


def extract_article(page_html: str, url: str) -> dict[str, Any]:
    """Return {title, html, date, modified, author, excerpt} for a blog post page."""
    doc = html.fromstring(page_html)
    ld = _jsonld(doc)

    title = (ld.get("headline") or _meta(doc, "og:title", "twitter:title") or "")
    if not title:
        h1 = doc.find(".//h1")
        title = h1.text_content().strip() if h1 is not None else ""
    if not title and doc.find(".//title") is not None:
        title = doc.findtext(".//title", "").strip()
    title = re.sub(r"\s+", " ", title)

    date = ld.get("datePublished") or _meta(doc, "article:published_time", "datePublished", "date")
    if not date:
        t = doc.find(".//time[@datetime]")
        date = t.get("datetime") if t is not None else None
    modified = ld.get("dateModified") or _meta(doc, "article:modified_time", "dateModified")
    author = ld.get("author") or _meta(doc, "author", "article:author")
    excerpt = _meta(doc, "description", "og:description")

    body_html = ""
    try:
        readable = Document(page_html, url=url)
        body_html = readable.summary(html_partial=True)
    except Exception as exc:  # readability raises a variety of lxml errors on odd pages
        log.warning("readability failed for %s: %s", url, exc)
    return {"title": title, "html": body_html, "date": date, "modified": modified,
            "author": author, "excerpt": excerpt}
