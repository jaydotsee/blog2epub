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


def extract_article(
    page_html: str, url: str, keep: list[str] | None = None, remove: list[str] | None = None
) -> dict[str, Any]:
    """Return {title, html, date, modified, author, excerpt, featured_image} for a blog post page."""
    doc = html.fromstring(page_html)
    ld = _jsonld(doc)

    title = ld.get("headline") or _meta(doc, "og:title", "twitter:title") or ""
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
    featured = _meta(doc, "og:image", "twitter:image")

    body_html = ""
    if keep:
        kept = _keep_container(doc, keep)
        if kept:
            body_html = kept
    if not body_html:
        try:
            readable = Document(page_html, url=url)
            body_html = readable.summary(html_partial=True)
        except Exception as exc:  # readability raises a variety of lxml errors on odd pages
            log.warning("readability failed for %s: %s", url, exc)
    if body_html and remove:
        body_html = _drop(body_html, remove)
    return {
        "title": title,
        "html": body_html,
        "date": date,
        "modified": modified,
        "author": author,
        "excerpt": excerpt,
        "featured_image": featured,
    }


MIN_KEEP_RATIO = 0.6


def readability_pass(body_html: str, url: str) -> str:
    """Run readability over an already-extracted body (API/feed content) to trim boilerplate.

    Readability is tuned for whole pages and can be over-eager on short bodies, so the
    original is kept whenever the pass would drop more than 40% of the text.
    """
    if not body_html or not body_html.strip():
        return body_html
    try:
        before = len(" ".join(html.fromstring(body_html).text_content().split()))
        page = f"<html><head><title>x</title></head><body><article>{body_html}</article></body></html>"
        out = _unwrap(Document(page, url=url).summary(html_partial=True))
        after = len(" ".join(html.fromstring(out).text_content().split())) if out.strip() else 0
    except Exception as exc:  # lxml / readability errors on odd markup
        log.debug("readability pass skipped for %s: %s", url, exc)
        return body_html
    if not after or (before and after / before < MIN_KEEP_RATIO):
        log.debug(
            "readability pass would drop %d%% of %s, keeping original",
            100 - int(100 * after / before) if before else 100,
            url,
        )
        return body_html
    return out


def _unwrap(fragment: str) -> str:
    """Strip the <body id="readabilityBody"><article> wrappers readability adds around a partial."""
    if not fragment.strip():
        return ""
    root = html.fragment_fromstring(fragment, create_parent="div")
    while (
        len(root) == 1
        and not (root.text or "").strip()
        and root[0].tag in ("body", "article", "div")
        and not (root[0].tail or "").strip()
    ):
        root = root[0]
    inner = (root.text or "") + "".join(html.tostring(child, encoding="unicode") for child in root)
    return inner


def _keep_container(doc: html.HtmlElement, keep: list[str]) -> str:
    """Serialise the elements matched by `keep` selectors, outermost first, document order."""
    matched: list[html.HtmlElement] = []
    for sel in keep:
        matched.extend(doc.cssselect(sel))
    position = {e: i for i, e in enumerate(doc.iter())}
    outer = sorted(
        {e for e in matched if not any(a in matched for a in e.iterancestors())},
        key=lambda e: position.get(e, 0),
    )
    if not outer:
        return ""
    return "".join(html.tostring(e, encoding="unicode") for e in outer)


def _drop(fragment: str, remove: list[str]) -> str:
    root = html.fragment_fromstring(fragment, create_parent="div")
    for sel in remove:
        for e in root.cssselect(sel):
            if e is not root and e.getparent() is not None:
                e.drop_tree()
    return (root.text or "") + "".join(html.tostring(c, encoding="unicode") for c in root)
