import zipfile

from lxml import etree

from blog2epub.epub import build_blog, build_epub, sort_posts
from tests.conftest import PNG_1x1, make_post

NS = {"x": "http://www.w3.org/1999/xhtml", "opf": "http://www.idpf.org/2007/opf",
      "ncx": "http://www.daisy.org/z3986/2005/ncx/", "c": "urn:oasis:names:tc:opendocument:xmlns:container"}


def _posts(store):
    img = "https://example.com/img/one.png"
    store.put_image(img, PNG_1x1, "png", "image/png")
    posts = [
        make_post("wp-1", "2023-05-01T10:00:00+00:00", html=f'<h2>Intro</h2><p>one <img src="{img}" alt="pic"></p>'),
        make_post("wp-2", "2023-06-01T10:00:00+00:00",
                  html='<p>see <a href="https://example.com/blog/post-1/">the first</a> and <img src="https://example.com/missing.png" alt="m"></p>'),
        make_post("wp-3", "2024-01-15T10:00:00+00:00", title="Third & <last>", categories=["Cat"],
                  html='<p id="here">x</p><a href="https://example.com/blog/post-3/#here">self</a>'
                       '<a href="https://example.com/blog/post-1/#nowhere">gone</a><a href="#here">local</a>'),
    ]
    for p in posts:
        store.put_post(p)
    store.save()
    return posts


def test_build_epub_structure(tmp_path, blog, store):
    posts = sort_posts(blog, _posts(store))
    out = tmp_path / "demo.epub"
    result = build_epub(blog, posts, store, out)
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
    assert "part-2023" in idrefs and "part-2024" in idrefs
    assert idrefs.index("part-2023") < idrefs.index("ch-0001") < idrefs.index("part-2024") < idrefs.index("ch-0003")
    ids = {i.get("id") for i in opf.findall(".//opf:item", NS)}
    assert set(idrefs) <= ids

    nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
    toc = nav.find(".//x:nav[@id='toc']", NS)
    top = toc.find("x:ol", NS)
    labels = [li.find("x:a", NS).text for li in top.findall("x:li", NS)]
    assert labels == ["Title page", "2023", "2024"]
    nested = top.findall("x:li", NS)[1].find("x:ol", NS)
    assert [a.text for a in nested.findall(".//x:a", NS)] == ["Post wp-1", "Post wp-2"]

    ncx = etree.fromstring(z.read("OEBPS/toc.ncx"))
    assert [t.text for t in ncx.findall(".//ncx:navMap/ncx:navPoint/ncx:navLabel/ncx:text", NS)] == ["Title page", "2023", "2024"]
    assert ncx.find(".//ncx:meta[@name='dtb:depth']", NS).get("content") == "2"

    ch1 = z.read("OEBPS/Text/ch-0001.xhtml").decode()
    assert "<h2>Intro</h2>" in ch1                   # no h1 in the body, so headings stay put
    assert 'src="../Images/' in ch1
    ch2 = z.read("OEBPS/Text/ch-0002.xhtml").decode()
    assert 'href="ch-0001.xhtml"' in ch2             # internal link rewritten
    assert "[image: m]" in ch2
    ch3 = z.read("OEBPS/Text/ch-0003.xhtml").decode()
    assert "Third &amp; &lt;last&gt;" in ch3 and "Cat" in ch3 and "By Someone" in ch3
    assert ch3.count('href="ch-0003.xhtml#here"') == 2      # existing fragments kept (absolute and local form)
    assert 'href="ch-0001.xhtml"' in ch3 and "#nowhere" not in ch3  # unknown fragment dropped


def test_sort_order_and_max_posts(blog, store):
    posts = _posts(store)
    blog.order = "desc"
    assert [p.key for p in sort_posts(blog, posts)] == ["wp-3", "wp-2", "wp-1"]
    blog.order = "asc"
    blog.max_posts = 2
    assert [p.key for p in sort_posts(blog, posts)] == ["wp-2", "wp-3"]


def test_build_blog_split_by_year_and_custom_cover(tmp_path, blog, store):
    _posts(store)
    blog.split = "year"
    cover = tmp_path / "cover.png"
    cover.write_bytes(PNG_1x1)
    results = build_blog(blog, store, tmp_path / "out", cover_path=cover)
    assert sorted(r.path.name for r in results) == ["demo-2023.epub", "demo-2024.epub"]
    z = zipfile.ZipFile(results[0].path)
    assert "OEBPS/Images/cover.png" in z.namelist()
    assert results[0].title == "Demo Blog 2023"


def test_group_by_none_flat_nav(tmp_path, blog, store):
    posts = sort_posts(blog, _posts(store))
    blog.group_by = "none"
    build_epub(blog, posts, store, tmp_path / "flat.epub")
    z = zipfile.ZipFile(tmp_path / "flat.epub")
    nav = etree.fromstring(z.read("OEBPS/nav.xhtml"))
    top = nav.find(".//x:nav[@id='toc']/x:ol", NS)
    assert [li.find("x:a", NS).text for li in top.findall("x:li", NS)] == ["Title page", "Post wp-1", "Post wp-2", "Third & <last>"]
    assert not [n for n in z.namelist() if "part-" in n]
