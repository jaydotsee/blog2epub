"""Write an EPUB 3 file (with an EPUB 2 toc.ncx for older readers) from cached posts."""
from __future__ import annotations

import logging
import re
import textwrap
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .clean import clean_html, normalize_url
from .config import BlogConfig
from .images import MEDIA_TYPES
from .models import Post
from .store import BlogStore

log = logging.getLogger(__name__)

XHTML_HEAD = ('<?xml version="1.0" encoding="utf-8"?>\n'
              '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"'
              ' lang={lang} xml:lang={lang}>\n<head>\n<meta charset="utf-8"/>\n<title>{title}</title>\n'
              '<link rel="stylesheet" type="text/css" href="../Styles/styles.css"/>\n</head>\n<body>\n')
XHTML_TAIL = "\n</body>\n</html>\n"


@dataclass
class Chapter:
    index: int
    post: Post
    filename: str      # relative to OEBPS, e.g. Text/ch-0001.xhtml
    item_id: str
    xhtml: str = ""
    images: list[str] = field(default_factory=list)


@dataclass
class Part:
    label: str
    slug: str
    chapters: list[Chapter]

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


def _esc(text: str | None) -> str:
    return escape(text or "")


def _attr(text: str | None) -> str:
    return quoteattr(text or "")


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "x"


def _fmt_date(post: Post) -> str:
    d = post.date_obj
    return f"{d.day} {d:%B %Y}" if d else ""


def sort_posts(blog: BlogConfig, posts: list[Post]) -> list[Post]:
    def key(p: Post):
        d = p.date_obj
        return (d.timestamp() if d else float("-inf"), p.title.lower())

    posts = sorted(posts, key=key, reverse=(blog.order == "desc"))
    if blog.max_posts:
        posts = posts[-blog.max_posts:] if blog.order == "asc" else posts[:blog.max_posts]
    return posts


def group_posts(blog: BlogConfig, chapters: list[Chapter]) -> list[Part]:
    if blog.group_by == "none":
        return [Part(label="", slug="all", chapters=chapters)]
    parts: dict[str, Part] = {}
    for ch in chapters:
        if blog.group_by == "year":
            label = ch.post.year
        else:
            d = ch.post.date_obj
            label = d.strftime("%B %Y") if d else "Undated"
        parts.setdefault(label, Part(label=label, slug=_slug(label), chapters=[])).chapters.append(ch)
    return list(parts.values())


# ---- page renderers ------------------------------------------------------------
def render_chapter(blog: BlogConfig, ch: Chapter, body_xhtml: str) -> str:
    p = ch.post
    bits = []
    if p.author:
        bits.append(f"By {_esc(p.author)}")
    if _fmt_date(p):
        bits.append(_esc(_fmt_date(p)))
    if p.categories:
        bits.append(_esc(", ".join(p.categories)))
    byline = " &#183; ".join(bits)
    return (XHTML_HEAD.format(lang=_attr(blog.language), title=_esc(p.title))
            + f'<section epub:type="chapter" id={_attr(ch.item_id)}>\n'
            + '<header class="post-header">\n'
            + f"<h1>{_esc(p.title)}</h1>\n"
            + (f'<p class="byline">{byline}</p>\n' if byline else "")
            + f'<p class="source">Originally published at <a href={_attr(p.url)}>{_esc(p.url)}</a></p>\n'
            + "</header>\n"
            + body_xhtml
            + "\n</section>" + XHTML_TAIL)


def render_part(blog: BlogConfig, part: Part) -> str:
    items = "\n".join(
        f'<li><a href={_attr(ch.filename.split("/")[-1])}>{_esc(ch.post.title)}</a>'
        + (f' <span class="date">({_esc(_fmt_date(ch.post))})</span>' if _fmt_date(ch.post) else "")
        + "</li>"
        for ch in part.chapters)
    n = len(part.chapters)
    return (XHTML_HEAD.format(lang=_attr(blog.language), title=_esc(part.label))
            + f'<section epub:type="part" class="part" id={_attr(part.item_id)}>\n'
            + f"<h1>{_esc(part.label)}</h1>\n"
            + f'<p class="count">{n} post{"s" if n != 1 else ""}</p>\n'
            + f'<ol class="part-list">\n{items}\n</ol>\n</section>' + XHTML_TAIL)


def render_title_page(blog: BlogConfig, title: str, subtitle: str, chapters: list[Chapter],
                      generated: datetime) -> str:
    dated = [c.post.date_obj for c in chapters if c.post.date_obj]
    span = ""
    if dated:
        lo, hi = min(dated), max(dated)
        span = f"{lo:%B %Y} &#8211; {hi:%B %Y}" if lo.strftime("%Y-%m") != hi.strftime("%Y-%m") else f"{lo:%B %Y}"
    lines = [f"<p>{len(chapters)} posts" + (f", {span}" if span else "") + "</p>"]
    if blog.description:
        lines.append(f"<p>{_esc(blog.description)}</p>")
    lines.append(f"<p>Collected from <a href={_attr(blog.url)}>{_esc(blog.url)}</a></p>")
    lines.append(f"<p>Generated {generated:%d %B %Y} by blog2epub. All content remains the property "
                 f"of its original authors.</p>")
    return (XHTML_HEAD.format(lang=_attr(blog.language), title=_esc(title))
            + '<section epub:type="titlepage" class="titlepage">\n'
            + f"<h1>{_esc(title)}</h1>\n"
            + (f'<p class="subtitle">{_esc(subtitle)}</p>\n' if subtitle else "")
            + (f'<p class="subtitle">{_esc(blog.author)}</p>\n' if blog.author else "")
            + '<div class="meta">\n' + "\n".join(lines) + "\n</div>\n</section>" + XHTML_TAIL)


def render_cover_page(blog: BlogConfig, title: str, cover_file: str) -> str:
    return (XHTML_HEAD.format(lang=_attr(blog.language), title=_esc(title))
            + f'<section epub:type="cover" class="cover">\n<img src={_attr("../" + cover_file)} alt={_attr(title)}/>\n</section>'
            + XHTML_TAIL)


def render_nav(blog: BlogConfig, title: str, parts: list[Part], has_cover: bool) -> str:
    def li(href: str, label: str, children: str = "") -> str:
        return f"<li><a href={_attr(href)}>{_esc(label)}</a>{children}</li>"

    entries = [li("Text/title.xhtml", "Title page")]
    for part in parts:
        chapter_items = "\n".join(li(ch.filename, ch.post.title) for ch in part.chapters)
        if part.label:
            entries.append(li(part.filename, part.label, f"\n<ol>\n{chapter_items}\n</ol>\n"))
        else:
            entries.append(chapter_items)
    first_body = parts[0].filename if parts and parts[0].label else (parts[0].chapters[0].filename if parts and parts[0].chapters else "Text/title.xhtml")
    landmarks = (['<li><a epub:type="cover" href="Text/cover.xhtml">Cover</a></li>'] if has_cover else []) + [
        '<li><a epub:type="toc" href="nav.xhtml">Table of contents</a></li>',
        f'<li><a epub:type="bodymatter" href={_attr(first_body)}>Start of content</a></li>',
    ]
    head = XHTML_HEAD.format(lang=_attr(blog.language), title=_esc(title)).replace("../Styles/", "Styles/")
    return (head
            + '<nav epub:type="toc" id="toc">\n<h1>Contents</h1>\n<ol>\n' + "\n".join(entries) + "\n</ol>\n</nav>\n"
            + '<nav epub:type="landmarks" hidden="">\n<h2>Landmarks</h2>\n<ol>\n' + "\n".join(landmarks) + "\n</ol>\n</nav>"
            + XHTML_TAIL)


def render_ncx(blog: BlogConfig, title: str, uid: str, parts: list[Part]) -> str:
    counter = 0
    out: list[str] = []

    def point(href: str, label: str, depth: int, children: list[str] | None = None) -> str:
        nonlocal counter
        counter += 1
        pad = "  " * depth
        inner = "\n".join(children) if children else ""
        return (f'{pad}<navPoint id="np-{counter}" playOrder="{counter}">\n'
                f"{pad}  <navLabel><text>{_esc(label)}</text></navLabel>\n"
                f"{pad}  <content src={_attr(href)}/>\n{inner}\n{pad}</navPoint>")

    out.append(point("Text/title.xhtml", "Title page", 1))
    for part in parts:
        if part.label:
            kids: list[str] = []
            for ch in part.chapters:
                kids.append(point(ch.filename, ch.post.title, 2))
            out.append(point(part.filename, part.label, 1, kids))
        else:
            for ch in part.chapters:
                out.append(point(ch.filename, ch.post.title, 1))
    depth = 2 if any(p.label for p in parts) else 1
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang=' + _attr(blog.language) + '>\n'
            "<head>\n"
            f'  <meta name="dtb:uid" content={_attr(uid)}/>\n'
            f'  <meta name="dtb:depth" content="{depth}"/>\n'
            '  <meta name="dtb:totalPageCount" content="0"/>\n'
            '  <meta name="dtb:maxPageNumber" content="0"/>\n'
            "</head>\n"
            f"<docTitle><text>{_esc(title)}</text></docTitle>\n"
            "<navMap>\n" + "\n".join(out) + "\n</navMap>\n</ncx>\n")


def render_opf(blog: BlogConfig, title: str, uid: str, modified: datetime, manifest: list[tuple[str, str, str, str]],
               spine: list[str], has_ncx: bool) -> str:
    items = "\n".join(
        f"    <item id={_attr(i)} href={_attr(h)} media-type={_attr(m)}" + (f" properties={_attr(p)}" if p else "") + "/>"
        for i, h, m, p in manifest)
    refs = "\n".join(f"    <itemref idref={_attr(i)}/>" for i in spine)
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" xml:lang=' + _attr(blog.language) + ' prefix="rendition: http://www.idpf.org/vocab/rendition/#">\n'
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'    <dc:identifier id="pub-id">{_esc(uid)}</dc:identifier>\n'
            f"    <dc:title>{_esc(title)}</dc:title>\n"
            f"    <dc:language>{_esc(blog.language)}</dc:language>\n"
            + (f'    <dc:creator id="creator">{_esc(blog.author)}</dc:creator>\n' if blog.author else "")
            + (f"    <dc:publisher>{_esc(blog.publisher)}</dc:publisher>\n" if blog.publisher else "")
            + (f"    <dc:description>{_esc(blog.description)}</dc:description>\n" if blog.description else "")
            + f"    <dc:source>{_esc(blog.url)}</dc:source>\n"
            + f"    <dc:date>{modified:%Y-%m-%d}</dc:date>\n"
            + f'    <meta property="dcterms:modified">{modified:%Y-%m-%dT%H:%M:%SZ}</meta>\n'
            + ('    <meta name="cover" content="cover-image"/>\n' if any(i == "cover-image" for i, _, _, _ in manifest) else "")
            + "  </metadata>\n  <manifest>\n" + items + "\n  </manifest>\n"
            + f'  <spine{" toc=" + chr(34) + "ncx" + chr(34) if has_ncx else ""}>\n' + refs + "\n  </spine>\n</package>\n")


def generate_cover_svg(title: str, subtitle: str, author: str) -> bytes:
    lines = textwrap.wrap(title, width=18)[:5]
    y = 520 - (len(lines) - 1) * 55
    title_svg = "".join(
        f'<text x="600" y="{y + i * 110}" text-anchor="middle" font-size="96" font-weight="bold" fill="#ffffff" '
        f'font-family="Helvetica, Arial, sans-serif">{_esc(line)}</text>' for i, line in enumerate(lines))
    sub_y = y + len(lines) * 110 + 30
    subtitle_svg = "".join(
        f'<text x="600" y="{sub_y + i * 60}" text-anchor="middle" font-size="48" fill="#dbe4ff" '
        f'font-family="Helvetica, Arial, sans-serif">{_esc(line)}</text>'
        for i, line in enumerate(textwrap.wrap(subtitle, width=32)[:3]))
    author_svg = (f'<text x="600" y="1500" text-anchor="middle" font-size="52" fill="#ffffff" '
                  f'font-family="Georgia, serif">{_esc(author)}</text>') if author else ""
    svg = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1600" viewBox="0 0 1200 1600">\n'
           '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
           '<stop offset="0" stop-color="#1f2a44"/><stop offset="1" stop-color="#0b1020"/></linearGradient></defs>\n'
           '<rect width="1200" height="1600" fill="url(#g)"/>\n'
           '<rect x="80" y="80" width="1040" height="1440" fill="none" stroke="#5b6fa8" stroke-width="6"/>\n'
           f"{title_svg}\n{subtitle_svg}\n{author_svg}\n</svg>\n")
    return svg.encode("utf-8")


_ID_RE = re.compile(r'\sid="([^"]+)"')
_CHAPTER_LINK_RE = re.compile(r'href="(ch-\d{4}\.xhtml)#([^"]*)"')


def _fix_fragments(chapters: list[Chapter]) -> None:
    """Links to another chapter keep their #fragment only when that id exists there (epubcheck RSC-012)."""
    ids = {ch.filename.split("/")[-1]: set(_ID_RE.findall(ch.xhtml)) for ch in chapters}

    def fix(m: re.Match[str]) -> str:
        file, frag = m.group(1), m.group(2)
        return m.group(0) if frag in ids.get(file, set()) else f'href="{file}"'

    for ch in chapters:
        ch.xhtml = _CHAPTER_LINK_RE.sub(fix, ch.xhtml)


# ---- the builder -----------------------------------------------------------------
def build_epub(blog: BlogConfig, posts: list[Post], store: BlogStore, out_path: Path, *,
               title: str | None = None, subtitle: str = "", cover_path: Path | None = None,
               now: datetime | None = None) -> BuildResult:
    if not posts:
        raise ValueError("no posts to build")
    now = now or datetime.now(timezone.utc)
    title = title or blog.title
    uid = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"{blog.url}#{title}"))
    css = resources.files("blog2epub").joinpath("assets/styles.css").read_bytes()

    chapters = [Chapter(index=i, post=p, filename=f"Text/ch-{i:04d}.xhtml", item_id=f"ch-{i:04d}")
                for i, p in enumerate(posts, start=1)]
    by_url = {normalize_url(c.post.url): c for c in chapters}

    image_files: dict[str, tuple[str, Path, str]] = {}   # url -> (href, path, media_type)
    missing = 0

    def link_resolver(href: str) -> str | None:
        base, _, frag = href.partition("#")
        target = by_url.get(normalize_url(base))
        if target is None:
            return None
        return target.filename.split("/")[-1] + (f"#{frag}" if frag else "")

    def make_image_resolver():
        def resolve(url: str) -> str | None:
            nonlocal missing
            if not blog.images:
                return None
            if url in image_files:
                return "../" + image_files[url][0]
            path = store.image_path(url)
            if path is None:
                missing += 1
                return None
            media_type = store.image_media_type(url) or MEDIA_TYPES.get(path.suffix.lstrip("."), "image/jpeg")
            href = f"Images/{path.name}"
            image_files[url] = (href, path, media_type)
            return "../" + href
        return resolve

    for ch in chapters:
        body, imgs = clean_html(ch.post.html, ch.post.url, image_resolver=make_image_resolver(),
                                link_resolver=link_resolver, max_image_width=blog.max_image_width,
                                demote_headings=blog.demote_headings)
        ch.images = imgs
        ch.xhtml = render_chapter(blog, ch, body)

    _fix_fragments(chapters)
    parts = group_posts(blog, chapters)

    # cover
    cover_bytes: bytes | None = None
    cover_href = ""
    cover_type = ""
    if cover_path and cover_path.exists():
        ext = cover_path.suffix.lower().lstrip(".")
        if ext in MEDIA_TYPES and ext != "svg":
            cover_bytes, cover_href, cover_type = cover_path.read_bytes(), f"Images/cover.{ext}", MEDIA_TYPES[ext]
    if cover_bytes is None:
        cover_bytes, cover_href, cover_type = generate_cover_svg(title, subtitle, blog.author), "Images/cover.svg", "image/svg+xml"

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
        "nav.xhtml": render_nav(blog, title, parts, has_cover=True).encode("utf-8"),
        "toc.ncx": render_ncx(blog, title, uid, parts).encode("utf-8"),
        "Styles/styles.css": css,
        cover_href: cover_bytes,
        "Text/cover.xhtml": render_cover_page(blog, title, cover_href).encode("utf-8"),
        "Text/title.xhtml": render_title_page(blog, title, subtitle, chapters, now).encode("utf-8"),
    }
    for part in parts:
        if part.label:
            manifest.append((part.item_id, part.filename, "application/xhtml+xml", ""))
            spine.append(part.item_id)
            files[part.filename] = render_part(blog, part).encode("utf-8")
        for ch in part.chapters:
            manifest.append((ch.item_id, ch.filename, "application/xhtml+xml", ""))
            spine.append(ch.item_id)
            files[ch.filename] = ch.xhtml.encode("utf-8")
    for n, (href, path, media_type) in enumerate(image_files.values(), start=1):
        manifest.append((f"img-{n}", href, media_type, ""))
        files[href] = path.read_bytes()

    files["content.opf"] = render_opf(blog, title, uid, now, manifest, spine, has_ncx=True).encode("utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".epub.tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml",
                    '<?xml version="1.0" encoding="utf-8"?>\n'
                    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                    '  <rootfiles>\n    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
                    "  </rootfiles>\n</container>\n", compress_type=zipfile.ZIP_DEFLATED)
        for name, data in files.items():
            zf.writestr(f"OEBPS/{name}", data, compress_type=zipfile.ZIP_DEFLATED)
    tmp.replace(out_path)
    log.info("wrote %s (%d posts, %d images, %.1f MB)", out_path, len(chapters), len(image_files),
             out_path.stat().st_size / 1e6)
    return BuildResult(path=out_path, title=title, posts=len(chapters), images=len(image_files),
                       missing_images=missing, size=out_path.stat().st_size)


def build_blog(blog: BlogConfig, store: BlogStore, output_dir: Path, cover_path: Path | None = None) -> list[BuildResult]:
    """Build one EPUB for the blog, or one per year when `split: year`."""
    posts = sort_posts(blog, list(store.iter_posts()))
    if not posts:
        raise ValueError(f"blog {blog.id!r}: nothing cached yet, run `sync` first")
    results: list[BuildResult] = []
    if blog.split == "year":
        years: dict[str, list[Post]] = {}
        for p in posts:
            years.setdefault(p.year, []).append(p)
        for year, group in years.items():
            results.append(build_epub(blog, group, store, output_dir / f"{blog.id}-{year}.epub",
                                      title=f"{blog.title} {year}",
                                      cover_path=cover_path))
    else:
        results.append(build_epub(blog, posts, store, output_dir / f"{blog.id}.epub", cover_path=cover_path))
    return results
