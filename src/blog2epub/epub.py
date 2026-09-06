"""Write an EPUB 3 file (with an EPUB 2 toc.ncx for older readers) from cached posts."""

from __future__ import annotations

import logging
import re
import textwrap
import uuid
import zipfile
import zlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .clean import clean_html, normalize_url, text_of
from .config import BlogConfig, BookConfig
from .covers import cover_values, is_template, playwright_available, render_cover_template, static_fallback
from .extract import readability_pass
from .images import MEDIA_TYPES, cairosvg_available, optimize_image, rasterize_svg, rasterize_svg_bytes
from .models import Post, resolve_date
from .store import BlogStore

log = logging.getLogger(__name__)

XHTML_HEAD = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"'
    ' lang={lang} xml:lang={lang}>\n<head>\n<meta charset="utf-8"/>\n<title>{title}</title>\n'
    '<link rel="stylesheet" type="text/css" href="../Styles/styles.css"/>\n</head>\n<body>\n'
)
XHTML_TAIL = "\n</body>\n</html>\n"
EXCERPT_CHARS = 220


@dataclass
class Entry:
    blog: BlogConfig
    store: BlogStore
    post: Post


@dataclass
class Chapter:
    index: int
    entry: Entry
    filename: str  # relative to OEBPS, e.g. Text/ch-0001.xhtml
    item_id: str
    xhtml: str = ""
    images: list[str] = field(default_factory=list)  # embedded image URLs, lead image included
    text_bytes: int = 0  # the XHTML as it will sit in the zip (deflated)
    missing: int = 0  # image references that had no cached file

    @property
    def post(self) -> Post:
        return self.entry.post


@dataclass
class Section:
    """A sub-heading inside a part page (e.g. a month inside a year)."""

    label: str
    slug: str
    chapters: list[Chapter]

    @property
    def filename(self) -> str:
        return f"Text/sec-{self.slug}.xhtml"

    @property
    def item_id(self) -> str:
        return f"sec-{self.slug}"


@dataclass
class Part:
    label: str
    slug: str
    chapters: list[Chapter]
    sections: list[Section] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"Text/part-{self.slug}.xhtml"

    @property
    def item_id(self) -> str:
        return f"part-{self.slug}"


@dataclass
class BuildResult:
    path: Path
    title: str
    posts: int
    images: int
    missing_images: int
    size: int
    image_bytes: int = 0  # bytes of images actually embedded
    image_bytes_before: int = 0  # what they weighed as the blogs serve them
    issue: str = ""  # YYYYMMDD
    volume: int = 1
    volumes: int = 1
    label: str = ""  # "Vol. 2 of 3", "2024", "March 2024"; empty for a single unsplit volume
    first_date: str = ""  # YYYY-MM-DD of the oldest post in this volume
    last_date: str = ""
    cover: Path | None = None

    @property
    def issue_number(self) -> str:
        return f"{self.issue}.{self.volume}"


def _esc(text: str | None) -> str:
    return escape(text or "")


def _attr(text: str | None) -> str:
    return quoteattr(text or "")


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "x"


def _fmt_date(post: Post) -> str:
    d = post.date_obj
    return f"{d.day} {d:%B %Y}" if d else ""


# ---- selecting and ordering --------------------------------------------------------
def _strip_title(title: str, patterns: list[re.Pattern[str]]) -> str:
    """Apply the blog's `title_strip` rules to a post title. Build-time, so editing a rule
    and rebuilding is enough; nothing has to be fetched again."""
    for pattern in patterns:
        title = pattern.sub("", title).strip()
    return title


def select_entries(book: BookConfig, sources: dict[str, tuple[BlogConfig, BlogStore]]) -> list[Entry]:
    """Every cached post of the book's blogs within since/until, sorted, trimmed to max_posts."""
    since, until = resolve_date(book.since), resolve_date(book.until)
    entries: list[Entry] = []
    for blog_id in book.blogs:
        blog, store = sources[blog_id]
        strip = [re.compile(p) for p in blog.title_strip]
        for post in store.iter_posts():
            d = post.date_obj
            if d is not None and ((since and d < since) or (until and d > until)):
                continue
            if strip:
                post.title = _strip_title(post.title, strip)
            entries.append(Entry(blog=blog, store=store, post=post))

    def key(e: Entry):
        d = e.post.date_obj
        return (d.timestamp() if d else float("-inf"), e.post.title.lower())

    entries.sort(key=key, reverse=(book.order == "desc"))
    if book.max_posts:
        entries = entries[-book.max_posts :] if book.order == "asc" else entries[: book.max_posts]
    return entries


def _month_label(ch: Chapter) -> tuple[str, str]:
    d = ch.post.date_obj
    label = d.strftime("%B %Y") if d else "Undated"
    return label, (d.strftime("%Y-%m") if d else "undated")


def group_chapters(book: BookConfig, chapters: list[Chapter]) -> list[Part]:
    """Split chapters into parts (and, for year-month, month sections inside each year).

    Chapters arrive already sorted (asc or desc), and parts/sections keep that order, so a
    newest-first book gets its years, months and posts all newest-first.
    """
    if book.group_by == "none":
        return [Part(label="", slug="all", chapters=chapters)]
    parts: dict[str, Part] = {}
    for ch in chapters:
        if book.group_by == "blog":
            label, slug = ch.entry.blog.title, ch.entry.blog.id
        elif book.group_by in ("year", "year-month"):
            label, slug = ch.post.year, _slug(ch.post.year)
        else:
            label, slug = _month_label(ch)
        parts.setdefault(slug, Part(label=label, slug=slug, chapters=[])).chapters.append(ch)
    if book.group_by == "year-month":
        for part in parts.values():
            sections: dict[str, Section] = {}
            for ch in part.chapters:
                label, slug = _month_label(ch)
                sections.setdefault(slug, Section(label=label, slug=slug, chapters=[])).chapters.append(ch)
            part.sections = list(sections.values())
    return list(parts.values())


def excerpt_of(post: Post, body_xhtml: str) -> str:
    text = (post.excerpt or "").strip()
    text = re.sub(r"\s*(\[…\]|\[\.\.\.\]|…|\.\.\.)\s*$", "", text)
    if not text:
        text = text_of(body_xhtml)
    if len(text) > EXCERPT_CHARS:
        cut = text[:EXCERPT_CHARS].rsplit(" ", 1)[0]
        text = cut + "…"
    return text


# ---- page renderers ------------------------------------------------------------
def _byline(book: BookConfig, ch: Chapter) -> str:
    p = ch.post
    bits = []
    if p.author:
        bits.append(f"By {_esc(p.author)}")
    if _fmt_date(p):
        bits.append(_esc(_fmt_date(p)))
    if len(book.blogs) > 1:
        bits.append(_esc(ch.entry.blog.title))
    if p.categories:
        bits.append(_esc(", ".join(p.categories)))
    return " &#183; ".join(bits)


def render_chapter(book: BookConfig, ch: Chapter, body_xhtml: str, lead_image: str | None) -> str:
    p = ch.post
    byline = _byline(book, ch)
    lead = f'<figure class="lead"><img src={_attr(lead_image)} alt=""/></figure>\n' if lead_image else ""
    return (
        XHTML_HEAD.format(lang=_attr(book.language), title=_esc(p.title))
        + f'<section epub:type="chapter" class={_attr("blog-" + ch.entry.blog.id)} id={_attr(ch.item_id)}>\n'
        + '<header class="post-header">\n'
        + f"<h1>{_esc(p.title)}</h1>\n"
        + (f'<p class="byline">{byline}</p>\n' if byline else "")
        + f'<p class="source">Originally published at <a href={_attr(p.url)}>{_esc(p.url)}</a></p>\n'
        + "</header>\n"
        + lead
        + body_xhtml
        + "\n</section>"
        + XHTML_TAIL
    )


def _part_items(book: BookConfig, chapters: list[Chapter], excerpts: dict[str, str]) -> str:
    items = []
    for ch in chapters:
        meta = [
            m
            for m in (
                _fmt_date(ch.post),
                ch.post.author,
                ch.entry.blog.title if len(book.blogs) > 1 and book.group_by != "blog" else "",
            )
            if m
        ]
        line = f"<li><a href={_attr(ch.filename.split('/')[-1])}>{_esc(ch.post.title)}</a>" + (
            f' <span class="date">{_esc(" · ".join(meta))}</span>' if meta else ""
        )
        if book.excerpts and excerpts.get(ch.item_id):
            line += f'\n<p class="excerpt">{_esc(excerpts[ch.item_id])}</p>'
        items.append(line + "</li>")
    return '<ol class="part-list">\n' + "\n".join(items) + "\n</ol>"


def render_part(book: BookConfig, part: Part, excerpts: dict[str, str]) -> str:
    n = len(part.chapters)
    if part.sections:
        body = "\n".join(
            f'<section id={_attr("m-" + sec.slug)} class="month">\n<h2><a href={_attr(sec.filename.split("/")[-1])}>{_esc(sec.label)}</a></h2>\n'
            + _part_items(book, sec.chapters, excerpts)
            + "\n</section>"
            for sec in part.sections
        )
    else:
        body = _part_items(book, part.chapters, excerpts)
    return (
        XHTML_HEAD.format(lang=_attr(book.language), title=_esc(part.label))
        + f'<section epub:type="part" class="part" id={_attr(part.item_id)}>\n'
        + f"<h1>{_esc(part.label)}</h1>\n"
        + f'<p class="count">{n} post{"s" if n != 1 else ""}</p>\n'
        + body
        + "\n</section>"
        + XHTML_TAIL
    )


def render_section(book: BookConfig, part: Part, sec: Section, excerpts: dict[str, str]) -> str:
    n = len(sec.chapters)
    return (
        XHTML_HEAD.format(lang=_attr(book.language), title=_esc(sec.label))
        + f'<section epub:type="part" class="part section" id={_attr(sec.item_id)}>\n'
        + f'<p class="kicker">{_esc(part.label)}</p>\n'
        + f"<h1>{_esc(sec.label)}</h1>\n"
        + f'<p class="count">{n} post{"s" if n != 1 else ""}</p>\n'
        + _part_items(book, sec.chapters, excerpts)
        + "\n</section>"
        + XHTML_TAIL
    )


def render_title_page(
    book: BookConfig,
    title: str,
    subtitle: str,
    chapters: list[Chapter],
    blogs: list[BlogConfig],
    generated: datetime,
    issue_number: str = "",
    volume_of: str = "",
) -> str:
    dated = [c.post.date_obj for c in chapters if c.post.date_obj]
    span = ""
    if dated:
        lo, hi = min(dated), max(dated)
        span = (
            f"{lo:%B %Y} &#8211; {hi:%B %Y}"
            if lo.strftime("%Y-%m") != hi.strftime("%Y-%m")
            else f"{lo:%B %Y}"
        )
    lines = [f"<p>{len(chapters)} posts" + (f", {span}" if span else "") + "</p>"]
    if book.description:
        lines.append(f"<p>{_esc(book.description)}</p>")
    if len(blogs) == 1:
        lines.append(f"<p>Collected from <a href={_attr(blogs[0].url)}>{_esc(blogs[0].url)}</a></p>")
    else:
        lines.append(
            "<p>Collected from:</p>\n<ul>\n"
            + "\n".join(
                f"<li>{_esc(b.title)} &#8212; <a href={_attr(b.url)}>{_esc(b.url)}</a></li>" for b in blogs
            )
            + "\n</ul>"
        )
    lines.append(
        f'<p class="issue">Issue {_esc(issue_number or f"{generated:%Y%m%d}.1")}'
        + (f" &#183; {_esc(volume_of)}" if volume_of else "")
        + "</p>\n"
        f"<p>Generated {generated:%d %B %Y} by blog2epub. All content remains the property "
        f"of its original authors.</p>"
    )
    return (
        XHTML_HEAD.format(lang=_attr(book.language), title=_esc(title))
        + '<section epub:type="titlepage" class="titlepage">\n'
        + f"<h1>{_esc(title)}</h1>\n"
        + (f'<p class="subtitle">{_esc(subtitle)}</p>\n' if subtitle else "")
        + (f'<p class="subtitle">{_esc(book.author)}</p>\n' if book.author else "")
        + '<div class="meta">\n'
        + "\n".join(lines)
        + "\n</div>\n</section>"
        + XHTML_TAIL
    )


def render_cover_page(book: BookConfig, title: str, cover_file: str) -> str:
    return (
        XHTML_HEAD.format(lang=_attr(book.language), title=_esc(title))
        + f'<section epub:type="cover" class="cover">\n<img src={_attr("../" + cover_file)} alt={_attr(title)}/>\n</section>'
        + XHTML_TAIL
    )


def render_nav(book: BookConfig, title: str, parts: list[Part]) -> str:
    def li(href: str, label: str, children: str = "") -> str:
        return f"<li><a href={_attr(href)}>{_esc(label)}</a>{children}</li>"

    entries = [li("Text/title.xhtml", "Title page")]
    for part in parts:
        if part.sections:
            month_items = "\n".join(
                li(
                    sec.filename,
                    sec.label,
                    "\n<ol>\n"
                    + "\n".join(li(ch.filename, ch.post.title) for ch in sec.chapters)
                    + "\n</ol>\n",
                )
                for sec in part.sections
            )
            entries.append(li(part.filename, part.label, f"\n<ol>\n{month_items}\n</ol>\n"))
            continue
        chapter_items = "\n".join(li(ch.filename, ch.post.title) for ch in part.chapters)
        if part.label:
            entries.append(li(part.filename, part.label, f"\n<ol>\n{chapter_items}\n</ol>\n"))
        else:
            entries.append(chapter_items)
    if parts and parts[0].label:
        first_body = parts[0].filename
    elif parts and parts[0].chapters:
        first_body = parts[0].chapters[0].filename
    else:
        first_body = "Text/title.xhtml"
    landmarks = [
        '<li><a epub:type="cover" href="Text/cover.xhtml">Cover</a></li>',
        '<li><a epub:type="toc" href="nav.xhtml">Table of contents</a></li>',
        f'<li><a epub:type="bodymatter" href={_attr(first_body)}>Start of content</a></li>',
    ]
    head = XHTML_HEAD.format(lang=_attr(book.language), title=_esc(title)).replace("../Styles/", "Styles/")
    return (
        head
        + '<nav epub:type="toc" id="toc">\n<h1>Contents</h1>\n<ol>\n'
        + "\n".join(entries)
        + "\n</ol>\n</nav>\n"
        + '<nav epub:type="landmarks" hidden="">\n<h2>Landmarks</h2>\n<ol>\n'
        + "\n".join(landmarks)
        + "\n</ol>\n</nav>"
        + XHTML_TAIL
    )


def render_ncx(book: BookConfig, title: str, uid: str, parts: list[Part]) -> str:
    counter = 0
    out: list[str] = []

    def point(href: str, label: str, depth: int, children: list[str] | None = None) -> str:
        nonlocal counter
        counter += 1
        pad = "  " * depth
        inner = "\n".join(children) if children else ""
        return (
            f'{pad}<navPoint id="np-{counter}" playOrder="{counter}">\n'
            f"{pad}  <navLabel><text>{_esc(label)}</text></navLabel>\n"
            f"{pad}  <content src={_attr(href)}/>\n{inner}\n{pad}</navPoint>"
        )

    out.append(point("Text/title.xhtml", "Title page", 1))
    for part in parts:
        if part.sections:
            kids = [
                point(
                    sec.filename,
                    sec.label,
                    2,
                    [point(ch.filename, ch.post.title, 3) for ch in sec.chapters],
                )
                for sec in part.sections
            ]
            out.append(point(part.filename, part.label, 1, kids))
        elif part.label:
            kids = [point(ch.filename, ch.post.title, 2) for ch in part.chapters]
            out.append(point(part.filename, part.label, 1, kids))
        else:
            out.extend(point(ch.filename, ch.post.title, 1) for ch in part.chapters)
    if any(p.sections for p in parts):
        depth = 3
    elif any(p.label for p in parts):
        depth = 2
    else:
        depth = 1
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang='
        + _attr(book.language)
        + ">\n"
        "<head>\n"
        f'  <meta name="dtb:uid" content={_attr(uid)}/>\n'
        f'  <meta name="dtb:depth" content="{depth}"/>\n'
        '  <meta name="dtb:totalPageCount" content="0"/>\n'
        '  <meta name="dtb:maxPageNumber" content="0"/>\n'
        "</head>\n"
        f"<docTitle><text>{_esc(title)}</text></docTitle>\n"
        "<navMap>\n" + "\n".join(out) + "\n</navMap>\n</ncx>\n"
    )


def render_opf(
    book: BookConfig,
    title: str,
    uid: str,
    modified: datetime,
    blogs: list[BlogConfig],
    manifest: list[tuple[str, str, str, str]],
    spine: list[str],
) -> str:
    items = "\n".join(
        f"    <item id={_attr(i)} href={_attr(h)} media-type={_attr(m)}"
        + (f" properties={_attr(p)}" if p else "")
        + "/>"
        for i, h, m, p in manifest
    )
    refs = "\n".join(f"    <itemref idref={_attr(i)}/>" for i in spine)
    sources = "".join(f"    <dc:source>{_esc(b.url)}</dc:source>\n" for b in blogs)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" xml:lang='
        + _attr(book.language)
        + ">\n"
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="pub-id">{_esc(uid)}</dc:identifier>\n'
        f"    <dc:title>{_esc(title)}</dc:title>\n"
        f"    <dc:language>{_esc(book.language)}</dc:language>\n"
        + (f'    <dc:creator id="creator">{_esc(book.author)}</dc:creator>\n' if book.author else "")
        + (f"    <dc:publisher>{_esc(book.publisher)}</dc:publisher>\n" if book.publisher else "")
        + (f"    <dc:description>{_esc(book.description)}</dc:description>\n" if book.description else "")
        + sources
        + f"    <dc:date>{modified:%Y-%m-%d}</dc:date>\n"
        + f'    <meta property="dcterms:modified">{modified:%Y-%m-%dT%H:%M:%SZ}</meta>\n'
        + '    <meta name="cover" content="cover-image"/>\n'
        + "  </metadata>\n  <manifest>\n"
        + items
        + "\n  </manifest>\n"
        + '  <spine toc="ncx">\n'
        + refs
        + "\n  </spine>\n</package>\n"
    )


def generate_cover_svg(title: str, subtitle: str, author: str) -> bytes:
    lines = textwrap.wrap(title, width=18)[:5]
    y = 520 - (len(lines) - 1) * 55
    title_svg = "".join(
        f'<text x="600" y="{y + i * 110}" text-anchor="middle" font-size="96" font-weight="bold" fill="#ffffff" '
        f'font-family="Helvetica, Arial, sans-serif">{_esc(line)}</text>'
        for i, line in enumerate(lines)
    )
    sub_y = y + len(lines) * 110 + 30
    subtitle_svg = "".join(
        f'<text x="600" y="{sub_y + i * 60}" text-anchor="middle" font-size="48" fill="#dbe4ff" '
        f'font-family="Helvetica, Arial, sans-serif">{_esc(line)}</text>'
        for i, line in enumerate(textwrap.wrap(subtitle, width=32)[:3])
    )
    author_svg = (
        (
            f'<text x="600" y="1500" text-anchor="middle" font-size="52" fill="#ffffff" '
            f'font-family="Georgia, serif">{_esc(author)}</text>'
        )
        if author
        else ""
    )
    svg = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1600" viewBox="0 0 1200 1600">\n'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#1f2a44"/><stop offset="1" stop-color="#0b1020"/></linearGradient></defs>\n'
        '<rect width="1200" height="1600" fill="url(#g)"/>\n'
        '<rect x="80" y="80" width="1040" height="1440" fill="none" stroke="#5b6fa8" stroke-width="6"/>\n'
        f"{title_svg}\n{subtitle_svg}\n{author_svg}\n</svg>\n"
    )
    return svg.encode("utf-8")


_ID_RE = re.compile(r'\sid="([^"]+)"')
_CHAPTER_LINK_RE = re.compile(r'href="(ch-\d{4}\.xhtml)#([^"]*)"')
_WP_SIZE_RE = re.compile(r"-\d+x\d+(?=\.[a-z]+$)", re.I)


def _fix_fragments(chapters: list[Chapter]) -> None:
    """Links to another chapter keep their #fragment only when that id exists there (epubcheck RSC-012)."""
    ids = {ch.filename.split("/")[-1]: set(_ID_RE.findall(ch.xhtml)) for ch in chapters}

    def fix(m: re.Match[str]) -> str:
        file, frag = m.group(1), m.group(2)
        return m.group(0) if frag in ids.get(file, set()) else f'href="{file}"'

    for ch in chapters:
        ch.xhtml = _CHAPTER_LINK_RE.sub(fix, ch.xhtml)


def _same_image(a: str, b: str) -> bool:
    return _WP_SIZE_RE.sub("", a.split("?", maxsplit=1)[0]) == _WP_SIZE_RE.sub(
        "", b.split("?", maxsplit=1)[0]
    )


def _wants_readability(book: BookConfig, post: Post) -> bool:
    if book.readability == "never":
        return False
    if book.readability == "always":
        return True
    # auto: feed bodies were never run through readability; API content already is the article
    # body, and sitemap pages went through readability when they were fetched.
    return post.source == "feed"


# ---- the builder -----------------------------------------------------------------
# ---- building ---------------------------------------------------------------------
# Planning to 97% of the budget leaves room for what the estimate cannot see: the cover image
# and the navigation files. Text is measured deflated, exactly as the zip will store it; images
# barely compress, so their file size is an upper bound.
SIZE_MARGIN = 0.97
VOLUME_OVERHEAD = 1_500_000
# <book>-<issue>[-<slug>].epub, and the <book>-<issue>.<n>.epub that the first issues used.
OUTPUT_RE = re.compile(r"^(?P<book>.+)-(?P<issue>\d{8})(?:[.-][^.]+)?\.epub$")
_CHAPTER_HREF_RE = re.compile(r'href="(ch-\d{4}\.xhtml)(#[^"]*)?"')


@dataclass
class Prepared:
    """Everything that is computed once for a book's posts, before they are cut into volumes."""

    chapters: list[Chapter]
    image_files: dict[str, tuple[str, Path, str]]  # url -> (href, path, media_type)
    excerpts: dict[str, str]
    missing: set[str]
    svg_kept: set[str]
    original_bytes: dict[str, int]
    css: str
    blogs: list[BlogConfig]

    def image_size(self, url: str) -> int:
        return self.image_files[url][1].stat().st_size


def book_outputs(output_dir: Path, book_id: str) -> list[Path]:
    """The EPUBs a book has written: <id>-<YYYYMMDD>.<n>.epub, plus the older <id>.epub and
    <id>-<year>.epub names. Exact on the id, so `api` never claims `api-management`'s files."""
    if not output_dir.exists():
        return []
    found = []
    for path in output_dir.iterdir():
        name = path.name
        if (
            name == f"{book_id}.epub"
            or re.fullmatch(rf"{re.escape(book_id)}-\d{{4}}\.epub", name)
            or ((m := OUTPUT_RE.match(name)) and m.group("book") == book_id)
        ):
            found.append(path)
    return sorted(found)


def prepare(book: BookConfig, entries: list[Entry]) -> Prepared:
    """Clean every post, resolve its images and links, and measure what each will weigh."""
    if not entries:
        raise ValueError("no posts to build")
    blogs = list({e.blog.id: e.blog for e in entries}.values())
    css = resources.files("blog2epub").joinpath("assets/styles.css").read_text(encoding="utf-8")
    for extra in [b.extra_css for b in blogs if b.extra_css] + ([book.extra_css] if book.extra_css else []):
        css += "\n" + extra.strip() + "\n"

    chapters = [
        Chapter(index=i, entry=e, filename=f"Text/ch-{i:04d}.xhtml", item_id=f"ch-{i:04d}")
        for i, e in enumerate(entries, start=1)
    ]
    by_url = {normalize_url(c.post.url): c for c in chapters}

    image_files: dict[str, tuple[str, Path, str]] = {}
    missing: set[str] = set()
    svg_kept: set[str] = set()  # SVGs we wanted to rasterise but could not
    original_bytes: dict[str, int] = {}  # url -> size as served, for the optimisation report
    widths = {e.blog.id: e.blog.max_image_width for e in entries}

    def store_width(store: BlogStore) -> int:
        return widths.get(store.root.name, 1200)

    def link_resolver(href: str) -> str | None:
        base, _, frag = href.partition("#")
        target = by_url.get(normalize_url(base))
        if target is None:
            return None
        return target.filename.split("/")[-1] + (f"#{frag}" if frag else "")

    def make_image_resolver(store: BlogStore):
        def resolve(url: str) -> str | None:
            if not book.images:
                return None
            if url in image_files:
                return "../" + image_files[url][0]
            path = store.image_path(url)
            if path is None:
                missing.add(url)
                return None
            media_type = store.image_media_type(url) or MEDIA_TYPES.get(path.suffix.lstrip("."), "image/jpeg")
            original_bytes[url] = path.stat().st_size
            if media_type != "image/svg+xml" and book.optimize_images:
                slimmed = optimize_image(path, store_width(store), book.image_quality)
                if slimmed:
                    path, media_type = slimmed
            if media_type == "image/svg+xml" and book.svg_images != "keep":
                if book.svg_images == "drop":
                    return None
                png = path.with_suffix(".svg.png")
                if not rasterize_svg(path, png, max(store_width(store), 600)):
                    svg_kept.add(url)
                else:
                    path, media_type = png, "image/png"
            href = f"Images/{path.name}"
            image_files[url] = (href, path, media_type)
            return "../" + href

        return resolve

    excerpts: dict[str, str] = {}
    for ch in chapters:
        post, blog, store = ch.post, ch.entry.blog, ch.entry.store
        raw = readability_pass(post.html, post.url) if _wants_readability(book, post) else post.html
        resolver = make_image_resolver(store)
        missing_before = len(missing)
        body, imgs = clean_html(
            raw,
            post.url,
            image_resolver=resolver,
            link_resolver=link_resolver,
            max_image_width=blog.max_image_width,
            demote_headings=book.demote_headings,
            keep=blog.keep,
            remove=blog.remove,
        )
        ch.images = [u for u in imgs if u in image_files]
        lead = None
        if (
            book.featured_images
            and book.images
            and post.featured_image
            and not any(_same_image(post.featured_image, u) for u in imgs)
        ):
            lead = resolver(post.featured_image)
            if lead and post.featured_image in image_files:
                ch.images.append(post.featured_image)
        ch.xhtml = render_chapter(book, ch, body, lead)
        ch.missing = len(missing) - missing_before
        excerpts[ch.item_id] = excerpt_of(post, body)

    _fix_fragments(chapters)
    for ch in chapters:
        ch.text_bytes = len(zlib.compress(ch.xhtml.encode("utf-8"), 6))

    if svg_kept:
        why = (
            "cairosvg is not installed (pip install 'blog2epub[svg]')"
            if not cairosvg_available()
            else "cairosvg could not parse them; see the warnings above"
        )
        log.warning(
            "%d SVG image(s) kept as SVG because %s; Kindle may treat the book as fixed layout",
            len(svg_kept),
            why,
        )
    return Prepared(chapters, image_files, excerpts, missing, svg_kept, original_bytes, css, blogs)


def _weight(ch: Chapter, prepared: Prepared, seen: set[str]) -> tuple[int, list[str]]:
    """Bytes the chapter adds to a volume: its text plus the images no earlier chapter carries."""
    new = [u for u in dict.fromkeys(ch.images) if u not in seen]
    return ch.text_bytes + sum(prepared.image_size(u) for u in new), new


@dataclass
class VolumePlan:
    chapters: list[Chapter]
    title: str  # "Tyk Blog 2024", "Axway Blog, Vol. 2", "Tyk Blog 2018, part 1 of 2"
    label: str  # "2024", "Vol. 2 of 3", "2018, part 1 of 2"; empty for a single unsplit volume
    slug: str = ""  # what the filename calls this volume: "2024", "2018-part1", "vol2", "2024-03"


def _pack(book: BookConfig, prepared: Prepared, chapters: list[Chapter]) -> list[list[Chapter]]:
    """Greedily fill volumes under max_book_bytes, in order, never reordering a post."""
    budget = int(book.max_book_bytes * SIZE_MARGIN) - VOLUME_OVERHEAD
    volumes: list[list[Chapter]] = []
    current: list[Chapter] = []
    used = 0
    seen: set[str] = set()
    for ch in chapters:
        weight, new = _weight(ch, prepared, seen)
        if current and used + weight > budget:
            volumes.append(current)
            current, used, seen = [], 0, set()
            weight, new = _weight(ch, prepared, seen)
        if weight > budget:
            log.warning(
                "%s: post %r alone weighs %.1f MB, more than max_book_bytes allows; it gets a volume of its own",
                book.id,
                ch.post.title[:60],
                weight / 1e6,
            )
        current.append(ch)
        used += weight
        seen.update(new)
    if current:
        volumes.append(current)
    return volumes


def plan_volumes(book: BookConfig, prepared: Prepared) -> list[VolumePlan]:
    """Cut the chapters, in reading order, into the volumes the book's `split` asks for.

    `year` and `month` cut on the calendar, `size` only where the budget says, `none` never.
    Whatever the split, no volume exceeds max_book_bytes except with `none`: a year that outgrew
    the budget is cut by size inside the year and its parts numbered.
    """
    chapters = prepared.chapters
    if book.split == "none":
        label = "Collector's Edition" if book.id.endswith("-collectors") else ""
        return [VolumePlan(chapters, book.title, label)]
    groups: list[tuple[str, str, list[Chapter]]]
    if book.split == "size":
        groups = [("", "", chapters)]
    else:
        keyed: dict[str, tuple[str, str, list[Chapter]]] = {}
        for ch in chapters:
            label, key = (ch.post.year, ch.post.year) if book.split == "year" else _month_label(ch)
            keyed.setdefault(key, (label, key, []))[2].append(ch)
        groups = list(keyed.values())

    plans: list[VolumePlan] = []
    sep = " " if book.split == "year" else ", "
    for label, key, group in groups:
        parts = _pack(book, prepared, group)
        for i, part in enumerate(parts, start=1):
            if book.split == "size":
                plans.append(VolumePlan(part, book.title, ""))  # numbered below, once the count is known
            elif len(parts) == 1:
                plans.append(VolumePlan(part, f"{book.title}{sep}{label}", label, key))
            else:
                sub = f"{label}, part {i} of {len(parts)}"
                plans.append(VolumePlan(part, f"{book.title}{sep}{sub}", sub, f"{key}-part{i}"))
    if book.split == "size" and len(plans) > 1:
        for n, plan in enumerate(plans, start=1):
            plan.title = f"{book.title}, Vol. {n}"
            plan.label, plan.slug = f"Vol. {n} of {len(plans)}", f"vol{n}"
    return plans


def _relink_outside(xhtml: str, outside: dict[str, str]) -> str:
    """Links to chapters that landed in another volume go back to the post's own URL."""
    if not outside:
        return xhtml

    def swap(m: re.Match[str]) -> str:
        url = outside.get(m.group(1))
        if url is None:
            return m.group(0)
        return f'href="{escape(url, {chr(34): "&quot;"})}{m.group(2) or ""}"'

    return _CHAPTER_HREF_RE.sub(swap, xhtml)


def package(
    book: BookConfig,
    prepared: Prepared,
    chapters: list[Chapter],
    out_path: Path,
    *,
    title: str,
    subtitle: str = "",
    cover_path: Path | None = None,
    now: datetime,
    issue: str,
    volume: int = 1,
    volumes: int = 1,
    label: str = "",
) -> BuildResult:
    """Write one EPUB holding `chapters` (a subset of the prepared ones, in order)."""
    uid = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"blog2epub:{book.id}:{title}"))
    inside = {ch.filename.split("/")[-1] for ch in chapters}
    outside = {
        ch.filename.split("/")[-1]: ch.post.url
        for ch in prepared.chapters
        if ch.filename.split("/")[-1] not in inside
    }
    parts = group_chapters(book, chapters)
    issue_number = f"{issue}.{volume}"
    volume_of = f"Volume {volume} of {volumes}" if volumes > 1 else ""

    cover_bytes: bytes | None = None
    cover_href = cover_type = ""
    if cover_path and cover_path.exists():
        ext = cover_path.suffix.lower().lstrip(".")
        if ext in MEDIA_TYPES and ext != "svg":
            cover_bytes, cover_href, cover_type = (
                cover_path.read_bytes(),
                f"Images/cover.{ext}",
                MEDIA_TYPES[ext],
            )
    if cover_bytes is None:
        cover_bytes = generate_cover_svg(title, subtitle or book.description, book.author)
        cover_href, cover_type = "Images/cover.svg", "image/svg+xml"
        if book.svg_images != "keep":
            png = rasterize_svg_bytes(cover_bytes, 1200)
            if png:
                cover_bytes, cover_href, cover_type = png, "Images/cover.png", "image/png"

    manifest: list[tuple[str, str, str, str]] = [
        ("nav", "nav.xhtml", "application/xhtml+xml", "nav"),
        ("ncx", "toc.ncx", "application/x-dtbncx+xml", ""),
        ("css", "Styles/styles.css", "text/css", ""),
        ("cover-image", cover_href, cover_type, "cover-image"),
        ("cover", "Text/cover.xhtml", "application/xhtml+xml", ""),
        ("title", "Text/title.xhtml", "application/xhtml+xml", ""),
    ]
    spine = ["cover", "title", "nav"]
    files: dict[str, bytes] = {
        "nav.xhtml": render_nav(book, title, parts).encode("utf-8"),
        "toc.ncx": render_ncx(book, title, uid, parts).encode("utf-8"),
        "Styles/styles.css": prepared.css.encode("utf-8"),
        cover_href: cover_bytes,
        "Text/cover.xhtml": render_cover_page(book, title, cover_href).encode("utf-8"),
        "Text/title.xhtml": render_title_page(
            book, title, subtitle, chapters, prepared.blogs, now, issue_number, volume_of
        ).encode("utf-8"),
    }

    def add_chapter(ch: Chapter) -> None:
        manifest.append((ch.item_id, ch.filename, "application/xhtml+xml", ""))
        spine.append(ch.item_id)
        files[ch.filename] = _relink_outside(ch.xhtml, outside).encode("utf-8")

    for part in parts:
        if part.label:
            manifest.append((part.item_id, part.filename, "application/xhtml+xml", ""))
            spine.append(part.item_id)
            files[part.filename] = render_part(book, part, prepared.excerpts).encode("utf-8")
        if part.sections:
            # month page, then its posts, so the TOC follows reading order (epubcheck NAV-011)
            for sec in part.sections:
                manifest.append((sec.item_id, sec.filename, "application/xhtml+xml", ""))
                spine.append(sec.item_id)
                files[sec.filename] = render_section(book, part, sec, prepared.excerpts).encode("utf-8")
                for ch in sec.chapters:
                    add_chapter(ch)
        else:
            for ch in part.chapters:
                add_chapter(ch)

    wanted = list(dict.fromkeys(u for ch in chapters for u in ch.images))
    embedded_bytes = 0
    for n, url in enumerate(wanted, start=1):
        href, path, media_type = prepared.image_files[url]
        manifest.append((f"img-{n}", href, media_type, ""))
        data = path.read_bytes()
        embedded_bytes += len(data)
        files[href] = data
    files["content.opf"] = render_opf(book, title, uid, now, prepared.blogs, manifest, spine).encode("utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".epub.tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            '  <rootfiles>\n    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
            "  </rootfiles>\n</container>\n",
            compress_type=zipfile.ZIP_DEFLATED,
        )
        for name, data in files.items():
            zf.writestr(f"OEBPS/{name}", data, compress_type=zipfile.ZIP_DEFLATED)
    tmp.replace(out_path)
    size = out_path.stat().st_size
    if book.split == "size" and size > book.max_book_bytes:
        log.warning(
            "%s: %s is %.1f MB, over max_book_bytes (%.1f MB); the size estimate was short",
            book.id,
            out_path.name,
            size / 1e6,
            book.max_book_bytes / 1e6,
        )
    dated = sorted(c.post.date_obj for c in chapters if c.post.date_obj)
    log.info("wrote %s (%d posts, %d images, %.1f MB)", out_path, len(chapters), len(wanted), size / 1e6)
    return BuildResult(
        path=out_path,
        title=title,
        posts=len(chapters),
        images=len(wanted),
        missing_images=sum(ch.missing for ch in chapters),
        size=size,
        image_bytes=embedded_bytes,
        image_bytes_before=sum(prepared.original_bytes.get(u, 0) for u in wanted),
        issue=issue,
        volume=volume,
        volumes=volumes,
        label=label,
        first_date=dated[0].strftime("%Y-%m-%d") if dated else "",
        last_date=dated[-1].strftime("%Y-%m-%d") if dated else "",
        cover=cover_path if cover_bytes is not None and cover_path and cover_path.exists() else None,
    )


def build_epub(
    book: BookConfig,
    entries: list[Entry],
    out_path: Path,
    *,
    title: str | None = None,
    subtitle: str = "",
    cover_path: Path | None = None,
    now: datetime | None = None,
    issue: str | None = None,
) -> BuildResult:
    """Write `entries` as one EPUB, whatever the book's `split` says. `build_book` is the
    normal entry point; this is for tests and for callers that do their own cutting."""
    now = now or datetime.now(timezone.utc)
    prepared = prepare(book, entries)
    return package(
        book,
        prepared,
        prepared.chapters,
        out_path,
        title=title or book.title,
        subtitle=subtitle,
        cover_path=cover_path,
        now=now,
        issue=issue or f"{now:%Y%m%d}",
    )


def _render_volume_cover(
    book: BookConfig,
    template: Path,
    chapters: list[Chapter],
    out: Path,
    *,
    now: datetime,
    issue: str,
    volume: int,
    volumes: int,
    label: str,
) -> Path | None:
    values = cover_values(
        book, [c.entry for c in chapters], now=now, issue=issue, volume=volume, volumes=volumes, label=label
    )
    try:
        failed_fonts = render_cover_template(template, out, values)
    except Exception as exc:  # Chromium can fail in many ways; the book must still build
        log.warning(
            "%s: could not render cover for volume %d from %s: %s", book.id, volume, template.name, exc
        )
        return None
    if failed_fonts:
        log.warning("%s: fonts not loaded on the volume %d cover: %s", book.id, volume, failed_fonts)
    return out


def build_book(
    book: BookConfig,
    sources: dict[str, tuple[BlogConfig, BlogStore]],
    output_dir: Path,
    cover_path: Path | None = None,
    *,
    now: datetime | None = None,
    issue: str | None = None,
    collectors: bool = False,
) -> list[BuildResult]:
    """Build the book as one or more volumes, <id>-<issue>-<volume>.epub, each with its own cover.

    `cover_path` may be an image, used as is on every volume, or an HTML template, rendered once
    per volume with that volume's post count, year span, issue number and cover lines. Files from
    the book's previous builds are removed once the new ones are written.

    `collectors` builds the whole archive as one file instead — the collector's edition. It is
    the same book under its own name, `<id>-collectors`, so its files, covers and cleanup never
    collide with the split edition's, and the size ceiling does not apply.
    """
    now = now or datetime.now(timezone.utc)
    if collectors:
        book = replace(
            book, id=f"{book.id}-collectors", title=f"{book.title} — Collector's Edition", split="none"
        )
    issue = issue or f"{now:%Y%m%d}"
    if not re.fullmatch(r"\d{8}", issue):
        raise ValueError(f"issue must be YYYYMMDD, not {issue!r}")
    entries = select_entries(book, sources)
    if not entries:
        raise ValueError(
            f"book {book.id!r}: no posts in the cache match, run `sync` first or widen since/until"
        )
    previous = book_outputs(output_dir, book.id)
    prepared = prepare(book, entries)
    volumes = plan_volumes(book, prepared)
    if len(volumes) > 1:
        log.info(
            "%s: %d posts go into %d volumes (split: %s)", book.id, len(entries), len(volumes), book.split
        )

    template: Path | None = None
    static_cover = cover_path
    if is_template(cover_path):
        assert cover_path is not None
        if playwright_available():
            template = cover_path
        else:
            static_cover = static_fallback(cover_path)
            log.warning(
                "%s: Playwright is not installed (pip install 'blog2epub[covers]'), so every volume gets %s",
                book.id,
                static_cover.name if static_cover else "a generated cover",
            )

    results: list[BuildResult] = []
    for n, plan in enumerate(volumes, start=1):
        chapters, title, label = plan.chapters, plan.title, plan.label
        # The name says which volume this is, not just its number: a bare ordinal sorts wrongly
        # (.1 .10 .11 .2) and means nothing once the file is out of the release page's context.
        stem = f"{book.id}-{issue}" + (f"-{plan.slug}" if plan.slug else "")
        out_path = output_dir / f"{stem}.epub"
        cover = static_cover
        if template is not None:
            cover_out = output_dir / "covers" / f"{stem}.jpg"
            cover = _render_volume_cover(
                book,
                template,
                chapters,
                cover_out,
                now=now,
                issue=issue,
                volume=n,
                volumes=len(volumes),
                label=label,
            ) or static_fallback(template)
        results.append(
            package(
                book,
                prepared,
                chapters,
                out_path,
                title=title,
                cover_path=cover,
                now=now,
                issue=issue,
                volume=n,
                volumes=len(volumes),
                label=label,
            )
        )
    written = {r.path for r in results}
    for stale in previous:
        if stale not in written:
            stale.unlink(missing_ok=True)
            log.info("removed %s from an earlier build", stale)
    return results
