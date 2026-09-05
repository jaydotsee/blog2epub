"""SVG handling: rasterise (default), keep, drop; fallback cover rasterised."""

from __future__ import annotations

import zipfile

import pytest

from blog2epub.config import BookConfig, ConfigError
from blog2epub.epub import build_epub, select_entries
from tests.conftest import make_post

cairosvg = pytest.importorskip("cairosvg")

SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="#3366cc"/></svg>'
URL = "https://example.com/img/diagram.svg"


def _book_with_svg(blog, store, mode):
    store.put_image(URL, SVG, "svg", "image/svg+xml")
    store.put_post(
        make_post("wp-1", "2024-01-01T00:00:00+00:00", html=f'<p>see <img src="{URL}" alt="diagram"></p>')
    )
    store.save()
    book = blog.as_book()
    book.svg_images = mode
    return book


def _names_and_chapter(path):
    z = zipfile.ZipFile(path)
    return z.namelist(), z.read("OEBPS/Text/ch-0001.xhtml").decode(), z


def test_svg_rasterised_by_default(tmp_path, blog, store):
    book = _book_with_svg(blog, store, "raster")
    r = build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "r.epub")
    names, ch, z = _names_and_chapter(tmp_path / "r.epub")
    assert r.images == 1
    assert not [n for n in names if n.endswith(".svg")]
    png = [n for n in names if n.endswith(".svg.png")]
    assert len(png) == 1 and z.read(png[0]).startswith(b"\x89PNG")
    assert 'src="../Images/' in ch and ".svg.png" in ch
    opf = z.read("OEBPS/content.opf").decode()
    assert 'media-type="image/png"' in opf and "image/svg+xml" not in opf


def test_svg_kept_when_asked(tmp_path, blog, store):
    book = _book_with_svg(blog, store, "keep")
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "k.epub")
    names, ch, _ = _names_and_chapter(tmp_path / "k.epub")
    assert [n for n in names if n.endswith(".svg")] and ".svg.png" not in ch


def test_svg_dropped_when_asked(tmp_path, blog, store):
    book = _book_with_svg(blog, store, "drop")
    r = build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "d.epub")
    names, ch, _ = _names_and_chapter(tmp_path / "d.epub")
    assert r.images == 0 and not [n for n in names if "diagram" in n or n.endswith(".svg")]
    assert "[image: diagram]" in ch


def test_generated_cover_is_png_unless_keep(tmp_path, blog, store):
    store.put_post(make_post("wp-1", "2024-01-01T00:00:00+00:00"))
    store.save()
    book = blog.as_book()
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "c.epub")
    z = zipfile.ZipFile(tmp_path / "c.epub")
    assert "OEBPS/Images/cover.png" in z.namelist() and z.read("OEBPS/Images/cover.png").startswith(
        b"\x89PNG"
    )
    assert (
        'href="Images/cover.png" media-type="image/png" properties="cover-image"'
        in z.read("OEBPS/content.opf").decode()
    )
    book.svg_images = "keep"
    build_epub(book, select_entries(book, {blog.id: (blog, store)}), tmp_path / "s.epub")
    assert "OEBPS/Images/cover.svg" in zipfile.ZipFile(tmp_path / "s.epub").namelist()


def test_config_validates_svg_images():
    with pytest.raises(ConfigError):
        BookConfig(id="b", blogs=["x"], svg_images="vectorise")
