"""Turn arbitrary blog HTML into a well-formed XHTML fragment that e-readers accept."""
from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree, html
from lxml_html_clean import Cleaner

from .images import pick_srcset_candidate

# Attributes that survive cleaning, per tag (plus the global ones below).
_GLOBAL_ATTRS = {"id", "lang", "title", "dir"}
_TAG_ATTRS = {
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "ol": {"start"},
    "blockquote": {"cite"},
    "q": {"cite"},
    "abbr": {},
    "time": {"datetime"},
}
_KEEP_CLASS_ON = {"pre", "code", "figure", "figcaption", "blockquote", "table", "div", "p", "span"}
_UNWRAP_TAGS = {"font", "center", "noscript", "picture", "section", "article", "main",
                "header", "footer", "nav", "aside", "details", "summary", "span"}
_DROP_TAGS = {"source", "track", "svg", "canvas", "map", "area", "template", "dialog",
              "button", "input", "select", "textarea", "label", "form", "object", "embed",
              "applet", "param", "link", "meta", "style", "script", "head", "title", "base"}
_MEDIA_TAGS = {"iframe", "video", "audio"}
_EMPTY_OK = {"img", "br", "hr", "td", "th", "col"}

_cleaner = Cleaner(
    scripts=True, javascript=True, comments=True, style=True, inline_style=True,
    links=True, meta=True, page_structure=False, processing_instructions=True,
    embedded=False, frames=False, forms=True, annoying_tags=True, remove_unknown_tags=False,
    safe_attrs_only=False, kill_tags=["script", "style", "noembed", "object", "applet"],
)

LinkResolver = Callable[[str], str | None]
ImageResolver = Callable[[str], str | None]


def normalize_url(url: str) -> str:
    """Canonical form used to match links between posts: no scheme/fragment/tracking/trailing slash."""
    parts = urlsplit(url.strip())
    query = "&".join(q for q in parts.query.split("&")
                     if q and not q.lower().startswith(("utm_", "fbclid", "gclid", "ref=")))
    path = parts.path.rstrip("/") or "/"
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunsplit(("", host, path, query, ""))


def _replace_media(root: html.HtmlElement) -> None:
    for el in list(root.iter(*_MEDIA_TAGS)):
        src = el.get("src")
        if not src:
            src_el = el.find("source")
            src = src_el.get("src") if src_el is not None else None
        p = html.Element("p")
        p.set("class", "embed")
        label = {"iframe": "Embedded content", "video": "Video", "audio": "Audio"}[el.tag]
        if src and not src.startswith(("about:", "javascript:", "data:")):
            a = etree.SubElement(p, "a", href=src)
            a.text = f"{label}: {src}"
        else:
            p.text = f"[{label} omitted]"
        p.tail = el.tail
        el.getparent().replace(el, p)


def _shift_headings(root: html.HtmlElement) -> None:
    if root.find(".//h1") is None:
        return
    for level in range(5, 0, -1):  # h5->h6 first so we never shift twice
        for el in root.iter(f"h{level}"):
            el.tag = f"h{level + 1}"


def _strip_attrs(el: html.HtmlElement) -> None:
    allowed = _GLOBAL_ATTRS | _TAG_ATTRS.get(el.tag, set())
    if el.tag in _KEEP_CLASS_ON:
        allowed = allowed | {"class"}
    for name in list(el.attrib):
        if name not in allowed or name.startswith("on"):
            del el.attrib[name]


_LAZY_SRC = ("data-src", "data-lazy-src", "data-original", "data-orig-file", "data-large-file")
_LAZY_SRCSET = ("data-srcset", "data-lazy-srcset")


def _lazy_aware(img: html.HtmlElement) -> tuple[str | None, str | None]:
    """Lazy-load plugins park the real image in data-* attributes and a placeholder in src."""
    src = img.get("src")
    srcset = img.get("srcset")
    if not src or src.startswith("data:") or "placeholder" in src or "lazy" in src.lower():
        for attr in _LAZY_SRC:
            if img.get(attr) and not img.get(attr).startswith("data:"):
                src = img.get(attr)
                break
    if not srcset or srcset.startswith("data:"):
        for attr in _LAZY_SRCSET:
            if img.get(attr):
                srcset = img.get(attr)
                break
    return src, srcset


def _is_effectively_empty(el: html.HtmlElement) -> bool:
    if el.tag in _EMPTY_OK:
        return False
    if len(el):
        return False
    return not (el.text or "").strip()


def clean_html(
    raw_html: str,
    base_url: str,
    *,
    image_resolver: ImageResolver,
    link_resolver: LinkResolver | None = None,
    max_image_width: int = 1200,
    demote_headings: bool = True,
) -> tuple[str, list[str]]:
    """Return (xhtml_fragment, image_urls_wanted).

    `image_resolver(url)` maps an absolute image URL to the relative path inside the
    book, or None to drop the image. `link_resolver(url)` maps a link to a chapter file
    when the target post is part of the same book.
    """
    if not raw_html or not raw_html.strip():
        return '<div class="post-body"></div>', []

    root = html.fragment_fromstring(raw_html, create_parent="div")
    root.make_links_absolute(base_url, resolve_base_href=True)
    _replace_media(root)
    root = _cleaner.clean_html(root)

    # Drop namespaced junk from Word/Google Docs pastes (o:p, w:sdt, ...) and disallowed tags.
    for el in list(root.iter()):
        if el is root or el.getparent() is None:
            continue
        if not isinstance(el.tag, str):  # comments, PIs
            el.drop_tree()
        elif ":" in el.tag or el.tag in _DROP_TAGS:
            el.drop_tree()
    for el in list(root.iter()):
        if isinstance(el.tag, str) and el.tag in _UNWRAP_TAGS and el is not root and el.getparent() is not None:
            el.drop_tag()

    if demote_headings:
        _shift_headings(root)

    wanted_images: list[str] = []
    for img in list(root.iter("img")):
        src, srcset = _lazy_aware(img)
        chosen = pick_srcset_candidate(src, srcset, max_image_width)
        if chosen:
            chosen = urljoin(base_url, chosen)
        if chosen and chosen.startswith("data:"):
            chosen = None
        local = image_resolver(chosen) if chosen else None
        if local is None:
            alt = (img.get("alt") or "").strip()
            if alt:
                span = html.Element("span")
                span.set("class", "missing-image")
                span.text = f"[image: {alt}]"
                span.tail = img.tail
                img.getparent().replace(img, span)
            else:
                img.drop_tree()
            continue
        wanted_images.append(chosen)
        img.set("src", local)
        if not img.get("alt"):
            img.set("alt", "")
        # width/height from srcset originals would distort the chosen candidate
        for attr in ("width", "height"):
            img.attrib.pop(attr, None)

    for a in root.iter("a"):
        href = a.get("href")
        if not href:
            continue
        if link_resolver:
            target = link_resolver(href)
            if target:
                a.set("href", target)
                continue
        if href.startswith(("javascript:", "data:")):
            a.attrib.pop("href", None)

    seen_ids: set[str] = set()
    for el in root.iter():
        if isinstance(el.tag, str):
            _strip_attrs(el)
            el_id = el.get("id")
            if el_id:
                if el_id in seen_ids or not re.match(r"^[A-Za-z_][\w.-]*$", el_id):
                    del el.attrib["id"]
                else:
                    seen_ids.add(el_id)

    # Remove empty paragraphs/divs left behind by the cleanup (WordPress loves them).
    changed = True
    while changed:
        changed = False
        for el in list(root.iter("p", "div", "span", "figure", "ul", "ol", "li", "em", "strong")):
            if el is not root and _is_effectively_empty(el):
                el.drop_tree()
                changed = True

    root.tag = "div"
    root.attrib.clear()
    root.set("class", "post-body")
    xhtml = etree.tostring(root, method="xml", encoding="unicode")
    # lxml emits <br/> etc. already; only remove any stray XML declarations.
    xhtml = re.sub(r"^<\?xml[^>]*\?>\s*", "", xhtml)
    return xhtml, wanted_images


def extract_image_urls(raw_html: str, base_url: str, max_image_width: int = 1200) -> list[str]:
    """Image URLs a post would want, so sync can prefetch them (same choice logic as clean_html)."""
    urls: list[str] = []

    def collect(url: str) -> str | None:
        urls.append(url)
        return "x"

    if raw_html and raw_html.strip():
        clean_html(raw_html, base_url, image_resolver=collect, max_image_width=max_image_width)
    return list(dict.fromkeys(urls))


def text_of(fragment: str) -> str:
    try:
        return " ".join(html.fromstring(fragment).text_content().split())
    except (etree.ParserError, ValueError):
        return ""
