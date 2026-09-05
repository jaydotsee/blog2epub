import zipfile

from lxml import etree

from blog2epub.config import BlogConfig, BookConfig
from blog2epub.epub import build_book, build_epub, excerpt_of, select_entries
from blog2epub.store import BlogStore
from tests.conftest import PNG_1x1, make_post

NS = {
    "x": "http://www.w3.org/1999/xhtml",
    "opf": "http://www.idpf.org/2007/opf",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
}
IMG = "https://example.com/img/one.png"


def _posts(store):
    store.put_image(IMG, PNG_1x1, "png", "image/png")
    posts = [
        make_post(
            "wp-1", "2023-05-01T10:00:00+00:00", html=f'<h2>Intro</h2><p>one <img src="{IMG}" alt="pic"></p>'
        ),
        make_post(
            "wp-2",
            "2023-06-01T10:00:00+00:00",
            html='<p>see <a href="https://example.com/blog/post-1/">the first</a> and <img src="https://example.com/missing.png" alt="m"></p>',
            excerpt="Second post excerpt […]",
        ),
        make_post(
            "wp-3",
            "2024-01-15T10:00:00+00:00",
            title="Third & <last>",
            categories=["Cat"],
            html='<p id="here">x</p><a href="https://example.com/blog/post-3/#here">self</a>'
            '<a href="https://example.com/blog/post-1/#nowhere">gone</a><a href="#here">local</a>',
        ),
    ]
    for p in posts:
        p.blog_id = "demo"
        store.put_post(p)
    store.save()
    return posts


def _entries(blog, store):
    return select_entries(blog.as_book(), {blog.id: (blog, store)})


def test_build_epub_structure(tmp_path, blog, store):
    _posts(store)
    book = blog.as_book()
    entries = _entries(blog, store)
    out = tmp_path / "demo.epub"
    result = build_epub(book, entries, out)
    assert result.posts == 3 and result.images == 1 and result.missing_images == 1

    z = zipfile.ZipFile(out)
    names = z.namelist()
    assert names[0] == "mimetype"
    info = z.getinfo("mimetype")
    assert info.compress_type == zipfile.ZIP_STORED and z.read("mimetype") == b"application/epub+zip"

    container = etree.fromstring(z.read("META-INF/container.xml"))
    assert container.find(".//c:rootfile", NS).get("full-path") == "OEBPS/content.opf"

    for n in names:
        if n.endswith((".xhtml", ".opf", ".ncx", ".svg")):
            etree.fromstring(z.read(n))  # every XML file is well-formed

    opf = etree.fromstring(z.read("OEBPS/content.opf"))
    hrefs = {i.get("href") for i in opf.findall(".//opf:item", NS)}
    for href in hrefs:
        assert f"OEBPS/{href}" in names, href
    assert opf.find(".//opf:item[@properties='nav']", NS).get("href") == "nav.xhtml"
    assert opf.find(".//opf:item[@properties='cover-image']", NS) is not None
    idrefs = [r.get("idref") for r in opf.findall(".//opf:itemref", NS)]
    assert idrefs[:3] == ["cover", "title", "nav"]
    assert (
        idrefs.index("part-2023")
        < idrefs.index("ch-0001")
        < idrefs.index("part-2024")
        < idrefs.index("ch-0003")
    )
    ids = {i.get("id") for i in opf.findall(".//opf:item", NS)}
    assert set(idrefs) <= ids

    nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
    top = nav.find(".//x:nav[@id='toc']/x:ol", NS)
    assert [li.find("x:a", NS).text for li in top.findall("x:li", NS)] == ["Title page", "2023", "2024"]
    nested = top.findall("x:li", NS)[1].find("x:ol", NS)
    assert [a.text for a in nested.findall(".//x:a", NS)] == ["Post wp-1", "Post wp-2"]

    ncx = etree.fromstring(z.read("OEBPS/toc.ncx"))
    assert [t.text for t in ncx.findall(".//ncx:navMap/ncx:navPoint/ncx:navLabel/ncx:text", NS)] == [
        "Title page",
        "2023",
        "2024",
    ]
    assert ncx.find(".//ncx:meta[@name='dtb:depth']", NS).get("content") == "2"

    ch1 = z.read("OEBPS/Text/ch-0001.xhtml").decode()
    assert "<h2>Intro</h2>" in ch1 and 'src="../Images/' in ch1
    ch2 = z.read("OEBPS/Text/ch-0002.xhtml").decode()
    assert 'href="ch-0001.xhtml"' in ch2 and "[image: m]" in ch2
    ch3 = z.read("OEBPS/Text/ch-0003.xhtml").decode()
    assert "Third &amp; &lt;last&gt;" in ch3 and "Cat" in ch3 and "By Someone" in ch3
    assert ch3.count('href="ch-0003.xhtml#here"') == 2
    assert 'href="ch-0001.xhtml"' in ch3 and "#nowhere" not in ch3

    part = z.read("OEBPS/Text/part-2023.xhtml").decode()
    assert '<p class="excerpt">Second post excerpt</p>' in part  # trailing […] stripped
    assert '<p class="excerpt">Intro one</p>' in part  # generated from the body text


def test_select_entries_order_range_and_max(blog, store):
    _posts(store)
    book = blog.as_book()
    book.order = "desc"
    assert [e.post.key for e in select_entries(book, {blog.id: (blog, store)})] == ["wp-3", "wp-2", "wp-1"]
    book.order, book.max_posts = "asc", 2
    assert [e.post.key for e in select_entries(book, {blog.id: (blog, store)})] == ["wp-2", "wp-3"]
    book.max_posts, book.since, book.until = None, "2023-05-15", "2023-12-31"
    assert [e.post.key for e in select_entries(book, {blog.id: (blog, store)})] == ["wp-2"]


def test_build_book_split_by_year_and_custom_cover(tmp_path, blog, store):
    _posts(store)
    book = blog.as_book()
    book.split = "year"
    cover = tmp_path / "cover.png"
    cover.write_bytes(PNG_1x1)
    results = build_book(book, {blog.id: (blog, store)}, tmp_path / "out", cover_path=cover)
    assert sorted(r.path.name for r in results) == ["demo-2023.epub", "demo-2024.epub"]
    z = zipfile.ZipFile(results[0].path)
    assert "OEBPS/Images/cover.png" in z.namelist()
    assert 'src="../Images/cover.png"' in z.read("OEBPS/Text/cover.xhtml").decode()
    assert results[0].title == "Demo Blog 2023"


def test_group_by_none_flat_nav(tmp_path, blog, store):
    _posts(store)
    book = blog.as_book()
    book.group_by = "none"
    build_epub(book, _entries(blog, store), tmp_path / "flat.epub")
    z = zipfile.ZipFile(tmp_path / "flat.epub")
    nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
    top = nav.find(".//x:nav[@id='toc']/x:ol", NS)
    assert [li.find("x:a", NS).text for li in top.findall("x:li", NS)] == [
        "Title page",
        "Post wp-1",
        "Post wp-2",
        "Third & <last>",
    ]
    assert not [n for n in z.namelist() if "part-" in n]


def test_multi_blog_book_grouped_by_blog(tmp_path, blog, store):
    _posts(store)
    other = BlogConfig(id="other", url="https://other.example/", title="Other Blog")
    other_store = BlogStore(tmp_path / "cache", other.id)
    p = make_post("feed-9", "2023-07-01T00:00:00+00:00", title="From other", html="<p>other body</p>")
    p.url, p.blog_id = "https://other.example/nine/", "other"
    other_store.put_post(p)
    other_store.save()
    book = BookConfig(
        id="digest", title="Digest", blogs=["other", "demo"], group_by="blog", order="desc", max_posts=3
    )
    sources = {"demo": (blog, store), "other": (other, other_store)}
    entries = select_entries(book, sources)
    assert [e.post.key for e in entries] == ["wp-3", "feed-9", "wp-2"]  # newest 3 across both blogs
    results = build_book(book, sources, tmp_path / "out")
    z = zipfile.ZipFile(results[0].path)
    nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
    top = nav.find(".//x:nav[@id='toc']/x:ol", NS)
    assert [li.find("x:a", NS).text for li in top.findall("x:li", NS)] == [
        "Title page",
        "Demo Blog",
        "Other Blog",
    ]
    ch = z.read("OEBPS/Text/ch-0002.xhtml").decode()
    assert "From other" in ch and "Other Blog" in ch  # blog name in the byline
    title = z.read("OEBPS/Text/title.xhtml").decode()
    assert "https://other.example/" in title and "https://example.com/blog" in title
    opf = z.read("OEBPS/content.opf").decode()
    assert opf.count("<dc:source>") == 2


def test_featured_image_leads_chapter_unless_already_inline(tmp_path, blog, store):
    _posts(store)
    lead_url = "https://example.com/img/lead-1024x536.png"
    store.put_image(lead_url, PNG_1x1, "png", "image/png")
    store.put_image("https://example.com/img/lead.png", PNG_1x1, "png", "image/png")
    a = make_post("wp-7", "2024-02-01T00:00:00+00:00", html="<p>text</p>", featured_image=lead_url)
    b = make_post(
        "wp-8", "2024-02-02T00:00:00+00:00", html=f'<p><img src="{IMG}" alt=""></p>', featured_image=IMG
    )
    c = make_post(
        "wp-9",
        "2024-02-03T00:00:00+00:00",
        html='<p><img src="https://example.com/img/lead.png" alt=""></p>',
        featured_image=lead_url,
    )
    for p in (a, b, c):
        store.put_post(p)
    store.save()
    book = blog.as_book()
    build_epub(book, _entries(blog, store), tmp_path / "lead.epub")
    z = zipfile.ZipFile(tmp_path / "lead.epub")
    chapters = {n: z.read(n).decode() for n in z.namelist() if "/ch-" in n}
    by_title = {v.split("<h1>")[1].split("</h1>")[0]: v for v in chapters.values()}
    assert 'class="lead"' in by_title["Post wp-7"]
    assert 'class="lead"' not in by_title["Post wp-8"]  # same image already in the body
    assert 'class="lead"' not in by_title["Post wp-9"]  # same image, different WP size suffix
    book.featured_images = False
    build_epub(book, _entries(blog, store), tmp_path / "nolead.epub")
    assert (
        'class="lead"'
        not in zipfile.ZipFile(tmp_path / "nolead.epub").read("OEBPS/Text/ch-0004.xhtml").decode()
    )


def test_images_false_gives_text_only_book(tmp_path, blog, store):
    _posts(store)
    book = blog.as_book()
    book.images = False
    r = build_epub(book, _entries(blog, store), tmp_path / "text.epub")
    assert r.images == 0
    assert not [
        n for n in zipfile.ZipFile(tmp_path / "text.epub").namelist() if "/Images/" in n and "cover" not in n
    ]


def test_excerpt_of():
    p = make_post("x", None, excerpt="  Short one ...")
    assert excerpt_of(p, "") == "Short one"
    p = make_post("x", None)
    p.excerpt = None
    long_body = "<p>" + "word " * 100 + "</p>"
    e = excerpt_of(p, long_body)
    assert e.endswith("…") and len(e) <= 222


def test_year_month_grouping_newest_first(tmp_path, blog, store):
    _posts(store)
    store.put_post(make_post("wp-4", "2023-06-20T10:00:00+00:00"))
    store.save()
    book = blog.as_book()
    book.order, book.group_by = "desc", "year-month"
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "ym.epub")
    z = zipfile.ZipFile(tmp_path / "ym.epub")
    nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
    top = nav.find(".//x:nav[@id='toc']/x:ol", NS)
    years = top.findall("x:li", NS)
    assert [li.find("x:a", NS).text for li in years] == ["Title page", "2024", "2023"]
    months_2023 = years[2].find("x:ol", NS).findall("x:li", NS)
    assert [li.find("x:a", NS).text for li in months_2023] == ["June 2023", "May 2023"]
    assert months_2023[0].find("x:a", NS).get("href") == "Text/sec-2023-06.xhtml"
    june_posts = [a.text for a in months_2023[0].find("x:ol", NS).findall("x:li/x:a", NS)]
    assert june_posts == ["Post wp-4", "Post wp-2"]  # newest first inside the month
    ncx = etree.fromstring(z.read("OEBPS/toc.ncx"))
    assert ncx.find(".//ncx:meta[@name='dtb:depth']", NS).get("content") == "3"
    part = z.read("OEBPS/Text/part-2023.xhtml").decode()
    assert '<section id="m-2023-06" class="month">' in part and "June 2023</a></h2>" in part
    assert part.index("June 2023") < part.index("May 2023")
    opf = etree.fromstring(z.read("OEBPS/content.opf"))
    idrefs = [r.get("idref") for r in opf.findall(".//opf:itemref", NS)]
    assert idrefs[3:] == [
        "part-2024",
        "sec-2024-01",
        "ch-0001",
        "part-2023",
        "sec-2023-06",
        "ch-0002",
        "ch-0003",
        "sec-2023-05",
        "ch-0004",
    ]
    sec = z.read("OEBPS/Text/sec-2023-06.xhtml").decode()
    assert "<h1>June 2023</h1>" in sec and 'class="kicker">2023</p>' in sec
    title = z.read("OEBPS/Text/title.xhtml").decode()
    assert '<p class="issue">Issue 20' in title
