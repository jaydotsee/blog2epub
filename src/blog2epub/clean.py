"""Turn arbitrary blog HTML into a well-formed XHTML fragment that e-readers accept."""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

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
    "abbr": set(),
    "time": {"datetime"},
}
_KEEP_CLASS_ON = {"pre", "code", "figure", "figcaption", "blockquote", "table", "div", "p", "span"}
_UNWRAP_TAGS = {
    "font",
    "center",
    "noscript",
    "picture",
    "section",
    "article",
    "main",
    "header",
    "footer",
    "nav",
    "aside",
    "details",
    "summary",
    "span",
}
_DROP_TAGS = {
    "source",
    "track",
    "svg",
    "canvas",
    "map",
    "area",
    "template",
    "dialog",
    "button",
    "input",
    "select",
    "textarea",
    "label",
    "form",
    "object",
    "embed",
    "applet",
    "param",
    "link",
    "meta",
    "style",
    "script",
    "head",
    "title",
    "base",
}
_MEDIA_TAGS = {"iframe", "video", "audio"}
_KNOWN_TAGS = {
    "a",
    "abbr",
    "address",
    "b",
    "bdi",
    "bdo",
    "blockquote",
    "br",
    "caption",
    "cite",
    "code",
    "col",
    "colgroup",
    "dd",
    "del",
    "dfn",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "ins",
    "kbd",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "q",
    "rp",
    "rt",
    "ruby",
    "s",
    "samp",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "time",
    "tr",
    "u",
    "ul",
    "var",
    "wbr",
}
_EMPTY_OK = {"img", "br", "hr", "td", "th", "col"}

_cleaner = Cleaner(
    scripts=True,
    javascript=True,
    comments=True,
    style=True,
    inline_style=True,
    links=True,
    meta=True,
    page_structure=False,
    processing_instructions=True,
    embedded=False,
    frames=False,
    forms=True,
    annoying_tags=True,
    remove_unknown_tags=False,
    safe_attrs_only=False,
    kill_tags=["script", "style", "noembed", "object", "applet"],
)

LinkResolver = Callable[[str], str | None]
ImageResolver = Callable[[str], str | None]


def normalize_url(url: str) -> str:
    """Canonical form used to match links between posts: no scheme/fragment/tracking/trailing slash."""
    parts = urlsplit(url.strip())
    query = "&".join(
        q
        for q in parts.query.split("&")
        if q and not q.lower().startswith(("utm_", "fbclid", "gclid", "ref="))
    )
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
        # a span is valid both inside a <p> and on its own (CSS makes it display as a block)
        placeholder = html.Element("span")
        placeholder.set("class", "embed")
        label = {"iframe": "Embedded content", "video": "Video", "audio": "Audio"}[el.tag]
        if src and not src.startswith(("about:", "javascript:", "data:")) and _valid_href(src):
            a = etree.SubElement(placeholder, "a", href=_valid_href(src))
            a.text = f"{label}: {src}"
        else:
            placeholder.text = f"[{label} omitted]"
        placeholder.tail = el.tail
        el.getparent().replace(el, placeholder)


_BLOCK_TAGS = {
    "p",
    "div",
    "ul",
    "ol",
    "table",
    "pre",
    "blockquote",
    "figure",
    "hr",
    "dl",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "address",
}
_INLINE_TAGS = {
    "a",
    "b",
    "i",
    "em",
    "strong",
    "span",
    "code",
    "small",
    "u",
    "s",
    "sub",
    "sup",
    "mark",
    "q",
    "cite",
    "abbr",
    "kbd",
    "del",
    "ins",
    "label",
}
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-_~:\[\]@]+$")


def _valid_host(netloc: str) -> bool:
    if not _HOST_RE.match(netloc):
        return False
    host = netloc.rsplit("@", 1)[-1].split(":", maxsplit=1)[0]
    for label in host.split("."):
        if label.lower().startswith("xn--"):
            try:
                label.encode("ascii").decode("idna")
            except (UnicodeError, ValueError):
                return False
    return True


def _valid_href(href: str) -> str | None:
    """Return a cleaned href, or None when no reader would accept it (epubcheck RSC-020).

    Real posts carry a stray bracket left by a broken markdown link, and placeholders such as
    `http://managerhost:port/info`. Both are invalid URLs rather than merely ugly ones, so the
    path and query are percent-encoded and a non-numeric port is rejected outright.
    """
    href = href.strip()
    if not href or href.startswith(("javascript:", "data:", "vbscript:")):
        return None
    try:
        parts = urlsplit(href)
        _ = parts.port  # raises ValueError when the port is not a number
    except ValueError:
        return None
    if parts.scheme in ("http", "https") and not _valid_host(parts.netloc or ""):
        return None
    if parts.scheme and parts.scheme not in ("http", "https", "mailto", "tel", "ftp"):
        return None
    if parts.scheme in ("mailto", "tel"):
        return href
    safe = "/%:@!$&'()*+,;=~-._"
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            quote(parts.path, safe=safe),
            quote(parts.query, safe=safe + "?&"),
            parts.fragment,
        )
    )


def _unwrap_inline_around_blocks(root: html.HtmlElement) -> None:
    """<b><p>..</p></b> and friends are invalid XHTML; drop the inline wrapper, keep its content."""
    for el in list(root.iter(*_INLINE_TAGS)):
        if el.getparent() is None:
            continue
        if any(isinstance(d.tag, str) and d.tag in _BLOCK_TAGS for d in el.iterdescendants()):
            el.drop_tag()


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


def _looks_broken(url: str | None) -> bool:
    return not url or url.startswith("data:") or any(c in url for c in ("'", "<", "%3C", " "))


def _lazy_aware(img: html.HtmlElement) -> tuple[str | None, str | None]:
    """Lazy-load plugins park the real image in data-* attributes and a placeholder in src.

    When a lazy attribute is present it wins; a placeholder src (data: URI, inline SVG,
    anything with quotes or spaces in it) is never fetched.
    """
    src = img.get("src")
    srcset = img.get("srcset")
    for attr in _LAZY_SRC:
        value = img.get(attr)
        if value and not _looks_broken(value):
            src = value
            break
    for attr in _LAZY_SRCSET:
        value = img.get(attr)
        if value and "data:" not in value:
            srcset = value
            break
    if _looks_broken(src):
        src = None
    return src, srcset


def _fix_lists(root: html.HtmlElement) -> None:
    """Make list markup valid: `ul`/`ol` may hold only `li`, and `li` needs a list parent.

    Hand-written and CMS-exported posts routinely nest a list directly inside another list, or
    leave paragraphs and text loose between items. Browsers cope; epubcheck does not.
    """
    for lst in list(root.iter("ul", "ol")):
        item: html.HtmlElement | None = None
        for child in list(lst):
            if not isinstance(child.tag, str):
                continue
            if child.tag == "li":
                item = child
                continue
            if item is None:  # stray content before any item: give it one
                item = html.Element("li")
                child.addprevious(item)
            item.append(child)  # a nested list belongs inside the item it hangs off
        if (lst.text or "").strip():
            first = lst.find("li")
            if first is None:
                first = html.Element("li")
                lst.insert(0, first)
            first.text = (lst.text or "") + (first.text or "")
        lst.text = None
    for li in list(root.iter("li")):
        parent = li.getparent()
        if parent is not None and parent.tag not in ("ul", "ol"):
            li.tag = "div"  # an item with no list around it is just a block


def _unnest_links(root: html.HtmlElement) -> None:
    """An `a` inside an `a` is invalid; keep the outer link and unwrap the inner one."""
    nested = [a for a in root.iter("a") if any(anc.tag == "a" for anc in a.iterancestors())]
    for a in nested:
        if a.getparent() is not None:
            a.drop_tag()


def _is_effectively_empty(el: html.HtmlElement) -> bool:
    if el.tag in _EMPTY_OK:
        return False
    if len(el):
        return False
    return not (el.text or "").strip()


def apply_rules(root: html.HtmlElement, keep: list[str] | None, remove: list[str] | None) -> html.HtmlElement:
    """Site rules in the spirit of Calibre recipes.

    `keep`: CSS selectors naming the article container(s). When any match, only the matched
    elements survive (in document order). `remove`: selectors for clutter to drop.
    """
    if keep:
        matched: list[html.HtmlElement] = []
        for sel in keep:
            matched.extend(e for e in root.cssselect(sel) if e is not root)
        if matched:
            # keep outermost matches only, in document order (selectors may match out of order)
            position = {e: i for i, e in enumerate(root.iter())}
            outer = sorted(
                {e for e in matched if not any(a in matched for a in e.iterancestors())},
                key=lambda e: position.get(e, 0),
            )
            container = html.Element("div")
            for e in outer:
                container.append(e)
            root = container
    for sel in remove or []:
        for e in root.cssselect(sel):
            if e is not root and e.getparent() is not None:
                e.drop_tree()
    return root


def clean_html(
    raw_html: str,
    base_url: str,
    *,
    image_resolver: ImageResolver,
    link_resolver: LinkResolver | None = None,
    max_image_width: int = 1200,
    demote_headings: bool = True,
    keep: list[str] | None = None,
    remove: list[str] | None = None,
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
    root = apply_rules(root, keep, remove)
    _replace_media(root)
    root = _cleaner.clean_html(root)

    # Drop namespaced junk from Word/Google Docs pastes (o:p, w:sdt, ...) and disallowed tags.
    for el in list(root.iter()):
        if el is root or el.getparent() is None:
            continue
        if not isinstance(el.tag, str) or ":" in el.tag or el.tag in _DROP_TAGS:  # comments, PIs
            el.drop_tree()
    for el in list(root.iter()):
        if not isinstance(el.tag, str) or el is root or el.getparent() is None:
            continue
        if el.tag in _UNWRAP_TAGS or el.tag not in _KNOWN_TAGS:
            if el.get("class") == "embed":  # our own media placeholder
                continue
            el.drop_tag()

    _unwrap_inline_around_blocks(root)
    _fix_lists(root)
    _unnest_links(root)

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
        if local is None or chosen is None:
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
        valid = _valid_href(href)
        if valid:
            a.set("href", valid)
        else:
            del a.attrib["href"]

    seen_ids: set[str] = set()
    for el in root.iter():
        if isinstance(el.tag, str):
            _strip_attrs(el)
            el_id = el.get("id")
            if el_id is not None:
                if not el_id or el_id in seen_ids or not re.match(r"^[A-Za-z_][\w.-]*$", el_id):
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


def extract_image_urls(
    raw_html: str,
    base_url: str,
    max_image_width: int = 1200,
    keep: list[str] | None = None,
    remove: list[str] | None = None,
) -> list[str]:
    """Image URLs a post would want, so sync can prefetch them (same choice logic as clean_html)."""
    urls: list[str] = []

    def collect(url: str) -> str | None:
        urls.append(url)
        return "x"

    if raw_html and raw_html.strip():
        clean_html(
            raw_html,
            base_url,
            image_resolver=collect,
            max_image_width=max_image_width,
            keep=keep,
            remove=remove,
        )
    return list(dict.fromkeys(urls))


def text_of(fragment: str) -> str:
    """Plain text of an HTML fragment, with a space wherever elements meet."""
    try:
        return " ".join(" ".join(html.fromstring(fragment).itertext()).split())
    except (etree.ParserError, ValueError):
        return ""
